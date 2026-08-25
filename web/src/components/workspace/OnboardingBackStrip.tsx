import { useTranslation } from "react-i18next"
import { Link, useSearchParams } from "react-router-dom"
import { ListChecks } from "lucide-react"
import { readOnboardingProgress } from "@/lib/onboarding-storage"

/**
 * OnboardingBackStrip — jalan pulang utk user yang datang dari checklist
 * (URL mengandung ?from=onboarding). Tampil di halaman tujuan aksi
 * (Settings / Management) supaya user tahu cara kembali + progress terakhir.
 */
export function OnboardingBackStrip({ backTo }: { backTo: string }) {
  const { t } = useTranslation("onboarding")
  const [searchParams] = useSearchParams()

  if (searchParams.get("from") !== "onboarding") return null
  // Progress null = checklist sudah selesai/di-skip (dibersihkan) → strip hilang,
  // bahkan di tab lama yang URL-nya masih membawa from=onboarding.
  const progress = readOnboardingProgress()
  if (!progress) return null

  return (
    <Link
      to={backTo}
      className="mb-4 flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/[0.06] px-3 py-2 text-sm text-primary transition-colors hover:bg-primary/10"
    >
      <ListChecks className="size-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">
        {progress && progress.total > 0
          ? t("back_progress", { done: progress.done, total: progress.total })
          : t("back_plain")}
      </span>
    </Link>
  )
}
