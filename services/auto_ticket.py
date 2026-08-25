"""
Auto-ticket watchdog — FE-4.
Mengubah alert observability watchdog menjadi tiket (source=watchdog, badge 🤖 Auto)
dengan dedup per fingerprint MD5. Murni side-effect: kegagalan TIDAK boleh
mengganggu siklus watchdog, dan laporan Telegram tetap 1 (tidak berubah).

Fix #40: routing service→project via incident_router — SATU alert bisa menghasilkan
tiket di SEMUA project yang memakai service tsb (fingerprint diberi suffix project_id
agar dedup antar-project tetap jalan). Setiap tiket membawa field serviceName.
"""
import hashlib
import logging
from typing import Any, Dict, List, Optional

from config.settings import settings
from services.ticket_alert_store import record_ticket_alert
from services.ticket_store import create_ticket, find_linkable_ticket_by_fingerprint

logger = logging.getLogger(__name__)

# Watchdog "user" sintetis — createdBy bukan user sungguhan
WATCHDOG_ACTOR = {"_id": "watchdog", "name": "Popov Watchdog", "email": "watchdog@popov.internal"}

# alert severity → ticket severity (plan FE-4)
_SEVERITY_MAP = {"critical": "critical", "warning": "high", "info": "low"}


async def _notify_workspace_members(
    workspace_id: Optional[str],
    title: str,
    payload: Dict[str, Any],
) -> None:
    """Bell notifikasi ke SEMUA member workspace (keputusan user, Fix #89-lanjutan)
    agar alert yang muncul di Telegram juga muncul di web bell + /notifications.
    Fire-and-forget & non-fatal — kegagalan tidak boleh mengganggu watchdog."""
    try:
        if not workspace_id:
            return  # konteks legacy global — tidak ada penerima yang jelas
        from services.notification_store import create_notification
        from services.workspace_store import find_workspace_by_id

        ws = await find_workspace_by_id(str(workspace_id))
        if not ws:
            return
        for m in ws.get("members", []):
            uid = m.get("userId")
            if uid:
                await create_notification(uid, "alert:new", title, payload)
    except Exception as e:
        logger.warning(f"Notifikasi alert web gagal (non-fatal): {e}")


def _ticket_severity(alerts: List[Dict[str, Any]]) -> str:
    ranked = {"critical": 3, "warning": 2, "info": 1}
    best = 0
    for a in alerts:
        sev = str(a.get("severity", "warning")).lower()
        if sev in ranked:
            best = max(best, ranked[sev])
        if a.get("source") == "tempo":  # trace 5xx dianggap minimal high
            best = max(best, 2)
    if best >= 3:
        return "critical"
    if best == 2:
        return "high"
    return "low"


async def maybe_create_watchdog_ticket(
    service: str,
    alerts: List[Dict[str, Any]],
    alert_id: Optional[str],
    workspace_id: Optional[str] = None,
    observ_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Buat tiket dari alert watchdog di SEMUA project match (Fix #40).

    Routing per project (incident_router):
      1. project yang memakai service ini (project_service_refs ⋈ service_library)
      2. observability target.project_ids (tervalidasi)
      3. fallback: project pertama workspace

    Dedup WINDOW (bukan permanen): bila ada tiket AKTIF (new/open/in_progress/
    needs_review) dengan konten sama (contentFp md5(service|alert_name)) dalam
    TICKET_ALERT_DEDUP_HOURS terakhir → alert disimpan sebagai dokumen
    ticket_alerts ter-link ke tiket itu (1 tiket : N alert), TANPA tiket baru.
    Di luar window / tiket resolved|closed → tiket baru + alert pertama.

    Returns: daftar tiket baru (kosong bila semua ter-link / gagal — selalu aman).
    """
    created: List[Dict[str, Any]] = []
    try:
        observ_target = None
        if observ_id:
            try:
                from services.observability_store import get_target

                observ_target = await get_target(observ_id)
            except Exception as e:
                logger.warning(f"Auto-ticket: resolve target {observ_id} gagal: {e}")

        from services.incident_router import resolve_projects_for_incident

        projects = await resolve_projects_for_incident(
            workspace_id=workspace_id,
            service_name=service,
            observ_target=observ_target,
        )
        if not projects:
            logger.warning("Auto-ticket: tidak ada project tujuan — skip")
            return []

        first_alert = alerts[0] if alerts else {}
        alert_name = first_alert.get("name") or f"trace 5xx {first_alert.get('trace_id', '')[:12]}".strip()
        trace_id = first_alert.get("trace_id")
        # Fix #84: dedup lintas-stack — tanpa observ_id; base_fp pakai alert PRIMER
        fp_seed = f"{workspace_id or 'global'}"
        base_fp = hashlib.md5(f"{service}|{alert_name}".encode()).hexdigest()
        all_trace_ids = [str(a.get("trace_id")) for a in alerts if a.get("trace_id")]
        alert_severity = str(first_alert.get("severity", "warning")).lower()

        for project in projects:
            pid = str(project["_id"])
            fingerprint = f"{fp_seed}:{pid}:{base_fp}"

            # Dedup WINDOW (bukan permanen): tiket AKTIF dgn konten sama dalam
            # TICKET_ALERT_DEDUP_HOURS → alert di-link ke tiket itu, bukan tiket baru.
            linkable = await find_linkable_ticket_by_fingerprint(
                pid, base_fp, settings.ticket_alert_dedup_hours
            )
            if linkable is not None:
                await record_ticket_alert(
                    ticket=linkable,
                    service=service,
                    name=alert_name,
                    severity=alert_severity,
                    trace_ids=all_trace_ids,
                    content_fp=base_fp,
                    workspace_id=str(workspace_id) if workspace_id else None,
                    observ_id=observ_id,
                    note=(
                        f"🔔 Alert baru ter-link: {alert_name} ({alert_severity})"
                    ),
                )
                # Web bell: paritas dgn Telegram — semua member workspace (Fix #89)
                link_no = f"{project.get('key', '?')}-{linkable.get('ticketNumber', '?')}"
                await _notify_workspace_members(
                    workspace_id or linkable.get("workspaceId"),
                    f"🔔 {service}: {alert_name} — alert baru di tiket {link_no}",
                    {
                        "projectId": pid,
                        "ticketNumber": linkable.get("ticketNumber"),
                        "projectKey": project.get("key"),
                        "severity": alert_severity,
                        "serviceName": service,
                    },
                )
                logger.info(
                    f"Auto-ticket: alert '{alert_name}' ter-link ke tiket aktif "
                    f"#{linkable.get('ticketNumber')} di project '{project.get('name')}' "
                    f"(window {settings.ticket_alert_dedup_hours}h)"
                )
                continue

            try:
                ticket = await create_ticket(
                    project,
                    WATCHDOG_ACTOR,
                    title=f"[ALERT] {service}: {alert_name}",
                    description=(
                        f"Tiket dibuat otomatis oleh Popov Watchdog untuk service '{service}'.\n\n"
                        f"Jumlah alert: {len(alerts)}. Sumber: observability (Prometheus/Tempo/Alertmanager).\n"
                        f"Alert pertama: {alert_name} (severity {alert_severity}).\n"
                        "Gunakan tombol Cek Detail di laporan Telegram untuk investigasi penuh."
                    ),
                    kind="infrastructure",
                    severity=_ticket_severity(alerts),
                    environment="production",
                    trace_id=str(trace_id) if trace_id else None,
                    tags=["watchdog", service],
                    source="watchdog",
                    fingerprint=fingerprint,
                    content_fp=base_fp,
                    initial_note=f"Tiket dibuat otomatis oleh watchdog (alert {alert_id or '-'})",
                    service_name=service,
                )
                # Alert pertama → dokumen alert ter-link ke tiket baru
                await record_ticket_alert(
                    ticket=ticket,
                    service=service,
                    name=alert_name,
                    severity=alert_severity,
                    trace_ids=all_trace_ids,
                    content_fp=base_fp,
                    workspace_id=str(workspace_id) if workspace_id else None,
                    observ_id=observ_id,
                )
                # Web bell: paritas dgn Telegram — semua member workspace (Fix #89)
                new_no = f"{project.get('key', '?')}-{ticket['ticketNumber']}"
                await _notify_workspace_members(
                    workspace_id or ticket.get("workspaceId"),
                    f"🚨 {service}: {alert_name} — tiket baru {new_no}",
                    {
                        "projectId": pid,
                        "ticketNumber": ticket["ticketNumber"],
                        "projectKey": project.get("key"),
                        "severity": _ticket_severity(alerts),
                        "serviceName": service,
                    },
                )
                created.append(ticket)
                logger.info(
                    f"Auto-ticket created #{ticket['ticketNumber']} untuk service {service} "
                    f"di project '{project.get('name')}'"
                )
            except ValueError as e:
                # race nomor tiket / constraint — bukan error fatal
                logger.info(f"Auto-ticket skipped di project '{project.get('name')}': {e}")
    except Exception as e:
        logger.error(f"Auto-ticket failed (watchdog tetap jalan): {e}")
    return created
