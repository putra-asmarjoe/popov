"""
Observability Watchdog — SCALE_ESCALATION_PLAN Layer 1 (B1)

WatchdogScheduler: dedicated scheduler yang bisa berjalan sebagai proses terpisah
(watchdog_worker.py) ATAU in-process legacy. Multi-target ready:
- Target dari collection `observability_targets` (Fase C / MULTI_OBS)
- Fallback backward-compatible: tanpa row → 1 target sintetis dari .env global

Kapasitas:
- Master tick 30s; per-target poll_interval_seconds (default 300s)
- Semaphore dinamis min(10, max(3, n//10))
- Circuit breaker per stack (3 fail → open dengan backoff eksponensial, maks 15m)
- Fingerprint anti-spam PER TARGET (bukan global) — composite workspace+observ_id

Constraint operasional: watchdog WAJIB tepat 1 instance (replicas:1 di K8s).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from config.settings import settings
from services.observability_client import (
    aggregate_observability,
    build_content_fingerprint,
    build_fingerprint,
)
from services.request_log import create_watchdog_alert
# Fix #40: pengiriman alert kini via broadcast() multi-channel (telegram_client)

logger = logging.getLogger(__name__)

MASTER_TICK_SECONDS = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CircuitBreakerState:
    """Per-stack breaker: N fail berturut-turut → open dengan backoff eksponensial."""

    def __init__(
        self,
        failure_threshold: int = 3,
        backoff_base_s: int = 120,
        max_backoff_s: int = 900,
    ):
        self.failure_threshold = failure_threshold
        self.backoff_base_s = backoff_base_s
        self.max_backoff_s = max_backoff_s
        self.consecutive_failures = 0
        self.open_until: datetime | None = None

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.open_until = None

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            backoff = min(
                self.backoff_base_s * (2 ** (self.consecutive_failures - self.failure_threshold)),
                self.max_backoff_s,
            )
            self.open_until = _utcnow() + timedelta(seconds=backoff)
            logger.warning(
                f"[Scheduler] breaker OPEN ({self.consecutive_failures} fails) → "
                f"backoff {backoff}s until {self.open_until.isoformat()}"
            )

    def is_open(self, now: datetime | None = None) -> bool:
        if self.open_until is None:
            return False
        now = now or _utcnow()
        if now >= self.open_until:
            # half-open — izinkan satu percobaan lagi
            self.open_until = None
            return False
        return True


class WatchdogScheduler:
    def __init__(self):
        self._last_checked: dict[str, datetime] = {}       # target_key → waktu cek terakhir
        self._fingerprints: dict[str, str] = {}             # target_key → fingerprint terakhir
        self._breakers: dict[str, CircuitBreakerState] = {}

    # ── Target loading ───────────────────────────────────────────────────────

    @staticmethod
    def target_key(target: dict) -> str:
        ws = target.get("workspace_id") or "global"
        return f"{ws}:{target.get('observ_id', 'default')}"

    async def load_active_targets(self) -> list[dict]:
        """Load targets aktif dari DB observability_targets. DB kosong → [] (idle)."""
        try:
            from services.mongodb_client import get_db
            db = get_db()
            rows = await db["observability_targets"].find({"enabled": {"$ne": False}}).to_list(500)
            if rows:
                for r in rows:
                    r["_id"] = str(r["_id"])
                return rows
        except Exception as e:
            logger.warning(f"[Scheduler] load observability_targets failed: {e}")
        return []

    def _breaker_for(self, key: str) -> CircuitBreakerState:
        if key not in self._breakers:
            self._breakers[key] = CircuitBreakerState()
        return self._breakers[key]

    def _load_due_targets(self, targets: list[dict]) -> list[dict]:
        now = _utcnow()
        due = []
        for t in targets:
            key = self.target_key(t)
            interval = max(int(t.get("poll_interval_seconds") or 300), MASTER_TICK_SECONDS)
            last = self._last_checked.get(key)
            if last is not None and (now - last).total_seconds() < interval:
                continue
            if self._breaker_for(key).is_open(now):
                continue
            due.append(t)
        return due

    # ── Main loop ────────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Main loop — tidak pernah berhenti kecuali task di-cancel."""
        logger.info(f"[Scheduler] WatchdogScheduler started (master tick={MASTER_TICK_SECONDS}s).")
        while True:
            tick_start = _utcnow()
            try:
                await self.tick()
            except asyncio.CancelledError:
                logger.info("[Scheduler] stopped (cancelled).")
                raise
            except Exception as e:
                logger.error(f"[Scheduler] master tick error: {e}")

            elapsed = (_utcnow() - tick_start).total_seconds()
            try:
                await asyncio.sleep(max(MASTER_TICK_SECONDS - elapsed, 1.0))
            except asyncio.CancelledError:
                logger.info("[Scheduler] stopped (cancelled during sleep).")
                raise

    async def tick(self) -> None:
        targets = await self.load_active_targets()
        due = self._load_due_targets(targets)
        if not due:
            return

        # Semaphore dinamis (L1-6): 10 target → 3, 50 → 5, 100 → 10
        concurrency = min(10, max(3, len(due) // 10))
        semaphore = asyncio.Semaphore(concurrency)

        async def bound_check(target: dict):
            key = self.target_key(target)
            async with semaphore:
                await self._check_single_target(target)

        results = await asyncio.gather(
            *(bound_check(t) for t in due),
            return_exceptions=True,   # KRITIS: satu gagal tidak blokir lain
        )
        for t, r in zip(due, results):
            if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
                logger.error(f"[Scheduler] unhandled exception stack {self.target_key(t)}: {r}")

    # ── Per-target check ─────────────────────────────────────────────────────

    async def _check_single_target(self, target: dict) -> None:
        key = self.target_key(target)
        logger.info(f"[Scheduler] checking stack '{key}' (webhook_mode={bool(target.get('webhook_mode'))})")
        try:
            if target.get("webhook_mode"):
                await self._health_check_only(target)
            else:
                await self._full_check(target)
            self._breaker_for(key).record_success()
        except Exception as e:
            self._breaker_for(key).record_failure()
            raise
        finally:
            self._last_checked[key] = _utcnow()

    async def _health_check_only(self, target: dict) -> None:
        """
        Stack webhook_mode=true: alert datang via push → JANGAN polling alert.
        Cukup health check ringan endpoint agar status stack tetap terpantau.
        """
        import httpx
        checks = {}
        for name, url_field in (("alertmanager", "alertmanager_url"), ("prometheus", "prometheus_url"), ("tempo", "tempo_url")):
            base = (target.get(url_field) or "").rstrip("/")
            if not base:
                continue
            probe = f"{base}/-/ready" if name == "prometheus" else base
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.get(probe)
                checks[name] = "ok" if resp.status_code < 500 else f"http_{resp.status_code}"
            except Exception as e:
                checks[name] = f"error:{type(e).__name__}"

        bad = [k for k, v in checks.items() if v != "ok"]
        if bad:
            logger.warning(f"[Scheduler] health check {self.target_key(target)} degraded: {checks}")
            try:
                from services.observability_store import record_health_status
                await record_health_status(target["observ_id"], f"degraded:{','.join(bad)}")
            except Exception:
                pass
            raise ConnectionError(f"health check failed for {bad}: {checks}")

        logger.info(f"[Scheduler] health check {self.target_key(target)} ok: {checks}")
        try:
            from services.observability_store import record_health_status
            await record_health_status(target["observ_id"], "ok")
        except Exception:
            pass

    async def _full_check(self, target: dict) -> None:
        """Polling alert lengkap (mode pull default) untuk satu target."""
        aggregate = await aggregate_observability(
            alertmanager_url=target.get("alertmanager_url"),
            prometheus_url=target.get("prometheus_url"),
            tempo_url=target.get("tempo_url"),
        )

        services = aggregate.get("services", {})
        if not services:
            logger.info(f"[Scheduler] {self.target_key(target)}: tidak ada temuan (sumber sehat).")
            return

        fingerprint = build_fingerprint(aggregate)
        if self._fingerprints.get(self.target_key(target)) == fingerprint:
            logger.info(f"[Scheduler] {self.target_key(target)}: temuan sama (anti-spam skip).")
            return

        sent_count = 0
        for service, alerts in services.items():
            sent_count += await process_service_alerts(
                service=service,
                alerts=alerts,
                workspace_id=target.get("workspace_id"),
                observ_id=target.get("observ_id"),
            )
        if sent_count > 0:
            self._fingerprints[self.target_key(target)] = fingerprint
            logger.info(
                f"[Scheduler] {self.target_key(target)}: {len(services)} service alert, "
                f"{sent_count} pesan terkirim."
            )
        else:
            logger.warning(f"[Scheduler] {self.target_key(target)}: temuan baru tapi tidak ada pesan terkirim.")


# Reusable processing (dipakai Scheduler DAN webhook Layer 2) ─────────────

DEDUP_WINDOW_MINUTES = 30


async def _recent_content_duplicate(content_fp: str, minutes: int = DEDUP_WINDOW_MINUTES) -> bool:
    """Fix #84: True bila konten alert (content_fp) sudah di-broadcast dalam window.
    Dedup LINTAS-target — target berbeda yang mendeteksi alert sama hanya sekali per window.
    """
    if not content_fp:
        return False
    from datetime import datetime, timedelta, timezone
    from services.mongodb_client import get_db
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    doc = await get_db()["watchdog_alerts"].find_one(
        {"content_fp": content_fp, "sent_at": {"$gte": since.isoformat()}},
        {"alert_id": 1},
    )
    return doc is not None


def _extract_trace_ids(alerts: list) -> list:
    """Kumpulkan trace_id (unik) dari alert bersumber Tempo untuk service yang sama."""
    seen = set()
    trace_ids = []
    for alert in alerts:
        if alert.get("source") != "tempo":
            continue
        tid = alert.get("trace_id")
        if tid and tid not in seen:
            seen.add(tid)
            trace_ids.append(str(tid))
    return trace_ids


def _format_service_message(service: str, alerts: list) -> str:
    lines = [f"🚨 *Observability Alert — {service}*", ""]
    for alert in alerts:
        source = alert.get("source", "unknown")

        # Trace Tempo 5xx punya struktur berbeda dari alert (trace_id/duration_ms/span_count)
        if source == "tempo":
            trace_id = alert.get("trace_id") or "N/A"
            duration_ms = alert.get("duration_ms") or "N/A"
            span_count = alert.get("span_count")
            span_count_str = span_count if span_count is not None else "N/A"
            root_trace = alert.get("root_trace_name") or ""
            services_involved = alert.get("services_involved") or []
            error_spans = alert.get("error_spans") or []

            lines.append(f"• Trace 5xx (durasi {duration_ms} ms, {span_count_str} span)")
            lines.append(f"   Sumber: tempo · TraceID: `{trace_id}`")
            if root_trace:
                lines.append(f"   Operasi: {root_trace}")
            if services_involved:
                lines.append(f"   Service terlibat: {', '.join(services_involved[:5])}")
            if error_spans:
                lines.append(f"   ⚠️ Span error ({len(error_spans)}):")
                for es in error_spans[:5]:
                    lines.append(f"      • {es.get('name')} ({es.get('service', 'unknown')})")
            lines.append("")
            continue

        name = alert.get("name", "UnknownAlert")
        severity = alert.get("severity", "warning").upper()
        active_at = alert.get("active_at") or "—"
        desc = alert.get("description") or ""
        lines.append(f"• [{severity}] {name}")
        lines.append(f"   Sumber: {source} · Aktif sejak: {active_at}")
        if desc:
            lines.append(f"   {desc[:300]}")
        lines.append("")
    return "\n".join(lines).rstrip()


async def run_triage_silent(
    service: str,
    alerts: list,
    workspace_id: str | None = None,
    project_id: str | None = None,
    observ_id: str | None = None,
) -> dict | None:
    """Triage silent (<30s) reusable — dipakai scheduler & webhook. Return triage dict atau None."""
    try:
        from agents.triage_agent import triage_agent
        fake_intent = f"error pada {service}"
        triage = await triage_agent({
            "service_name": service,
            "intent": fake_intent,
            "preset_service_name": service,
            "preset_trace_ids": _extract_trace_ids(alerts),
            "workspace_id": workspace_id,
            "project_id": project_id,
            "observ_id": observ_id,
        })
        tr = triage.get("triage_result") if isinstance(triage, dict) else None
        if tr:
            logger.info(
                f"[Triage] {service} → {tr.get('hypothesis')} conf={tr.get('confidence')} "
                f"deploy={tr.get('deploy_detected')} severity={tr.get('severity')}"
            )
        return tr
    except Exception as e:
        logger.warning(f"[Triage] failed for {service}: {e} — fallback tanpa triage")
        return None


async def process_service_alerts(
    service: str,
    alerts: list,
    workspace_id: str | None = None,
    observ_id: str | None = None,
    fingerprint: str | None = None,
) -> int:
    """
    Proses satu grup alert (satu service): triage silent → format → simpan alert →
    auto-ticket → kirim Telegram interaktif.
    Return jumlah pesan terkirim. Dipakai WatchdogScheduler DAN api/webhook (Layer 2).
    """
    # Triage silent sebelum kirim
    triage = await run_triage_silent(
        service,
        alerts,
        workspace_id=workspace_id,
        observ_id=observ_id,
    )
    tr = (triage or {}).get("triage_result")
    if tr and not tr.get("proceed_to_stage2", True):
        logger.info(f"[Triage] skip {service} severity low")
        return 0

    # Fix #84: dedup broadcast LINTAS-target — alert sama dari stack lain → skip seluruhnya
    content_fp = build_content_fingerprint(service, alerts)
    if await _recent_content_duplicate(content_fp):
        logger.info(f"[Dedup] {service}: konten sama sudah di-broadcast <{DEDUP_WINDOW_MINUTES}m — skip")
        return 0

    text = _format_service_message(service, alerts)
    if tr:
        hyp = tr.get("hypothesis")
        dep = tr.get("deploy_detected")
        if hyp:
            text += f"\n\n🧠 *Triage:* `{hyp}`" + (f" · deploy `{dep}`" if dep else "")

    trace_ids = _extract_trace_ids(alerts)
    try:
        alert_id = await create_watchdog_alert(
            service_name=service,
            message=text,
            trace_id=trace_ids[0] if trace_ids else None,
            trace_ids=trace_ids,
            workspace_id=workspace_id,
            observ_id=observ_id,
            fingerprint=fingerprint,
            content_fp=content_fp,
        )
    except Exception as e:
        logger.error(f"Gagal simpan alert untuk '{service}': {e}")
        alert_id = None

    # FE-4 auto-ticket (Fix #40): SATU alert → tiket di SEMUA project yang memakai
    # service ini (incident_router), masing-masing dengan fingerprint ber-suffix project.
    try:
        from services.auto_ticket import maybe_create_watchdog_ticket
        tickets = await maybe_create_watchdog_ticket(
            service,
            alerts,
            alert_id,
            workspace_id=workspace_id,
            observ_id=observ_id,
        )
        if len(tickets) > 1:
            logger.info(f"Auto-ticket: {len(tickets)} tiket dibuat untuk '{service}' (multi-project)")
    except Exception as e:
        logger.warning(f"Auto-ticket hook failed untuk '{service}': {e}")

    # Notifikasi broadcast (Fix #40): union channel project-linked ∪ workspace-wide.
    # Tanpa env fallback — 0 channel = tidak terkirim (warning).
    sent = 0
    try:
        from services.notification_store import resolve_channels, list_channels_internal
        from services.observability_store import get_target
        from services.incident_router import resolve_projects_for_incident
        from services.telegram_client import broadcast, build_alert_buttons

        observ_target = None
        if observ_id:
            try:
                observ_target = await get_target(observ_id)
            except Exception:
                observ_target = None

        projects = await resolve_projects_for_incident(
            workspace_id=workspace_id,
            service_name=service,
            observ_target=observ_target,
        )
        # Union channel atas semua project match + channel workspace-wide, dedup notif_id
        channels: dict = {}
        pids = [str(p["_id"]) for p in projects]
        for pid in pids:
            for ch in await resolve_channels(workspace_id, pid):
                channels[ch.get("notif_id")] = ch
        if not channels and workspace_id:
            for ch in await resolve_channels(workspace_id, None):
                channels.setdefault(ch.get("notif_id"), ch)
        if not channels and not pids:
            # konteks legacy global (tanpa ws/project) — pakai semua channel telegram enabled
            for ch in await list_channels_internal(channel="telegram", enabled_only=True):
                channels.setdefault(ch.get("notif_id"), ch)

        if channels:
            markup = build_alert_buttons(service, callback_ref=alert_id)
            sent = await broadcast(list(channels.values()), text, reply_markup=markup)
            logger.info(
                f"[Notification] alert '{service}' dikirim ke {sent}/{len(channels)} channel "
                f"(project match: {len(pids)})"
            )
        else:
            logger.warning(
                f"[Notification] tidak ada channel notifikasi match untuk '{service}' — "
                f"alert tidak terkirim ke Telegram (murni DB)"
            )
    except Exception as e:
        logger.error(f"[Notification] broadcast gagal utk '{service}': {e}")
    return sent


# ── Legacy entry point (backward compat — masih bisa dipanggil in-process) ──

_scheduler_instance: WatchdogScheduler | None = None


def get_scheduler() -> WatchdogScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = WatchdogScheduler()
    return _scheduler_instance


async def start_watchdog() -> None:
    """
    LEGACY in-process entry (sebelumnya dipanggil main.py lifespan).
    Sekarang jalur utama = watchdog_worker.py (Layer 1). Fungsi ini tetap ada
    agar deployment lama/opsional tetap bisa jalan in-process.
    """
    await get_scheduler().run_forever()
