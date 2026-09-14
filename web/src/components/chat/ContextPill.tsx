import { useTranslation } from "react-i18next"
import { Link2 } from "lucide-react"
import type { ContextPillData } from "@/lib/chat-meta"

/**
 * ContextPill — konteks aktif / resolusi anaphora di ATAS reply (CHAT3 §4A.1/§4A.5).
 * Data dari metadata pesan (`context_pill`, CHAT3 §4A.5) — persist server, refresh-safe.
 * Hidden bila payload kosong. Nilai payload (service, ticket_id) identifier
 * locale-neutral — tidak diterjemahkan (K9); prefix dari i18n keys pill.*.
 */
export function ContextPill({ pill }: { pill?: ContextPillData | null }) {
  const { t } = useTranslation("common")
  if (!pill || typeof pill !== "object") return null

  // Anaphora (Phase 2): resolved_ref {original, resolved} menang di atas context biasa
  const ref = pill.resolved_ref
  if (ref && typeof ref === "object" && ref.original && ref.resolved) {
    return (
      <div className="inline-flex max-w-full items-center gap-1 rounded-full border border-border/60 bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground">
        <Link2 className="size-3 shrink-0" aria-hidden />
        <span className="truncate">
          {t("pill.resolved", { term: ref.original, value: ref.resolved })}
        </span>
      </div>
    )
  }

  const parts = [pill.service, pill.ticket_id].filter(
    (v): v is string => typeof v === "string" && v.length > 0,
  )
  if (parts.length === 0) return null

  return (
    <div className="inline-flex max-w-full items-center gap-1 rounded-full border border-border/60 bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground">
      <Link2 className="size-3 shrink-0" aria-hidden />
      <span className="truncate">
        {t("pill.context")} {parts.join(" · ")}
      </span>
    </div>
  )
}
