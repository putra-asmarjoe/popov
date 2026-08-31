/** Mode tampilan halaman utama project — disimpan di session browser (per tab). */

export type ProjectView = "classic" | "warroom"

const STORAGE_KEY = "popov:project:view"

/** Baca preferensi mode. Belum diset / tab baru → default "warroom". */
export function getProjectView(): ProjectView {
  try {
    const v = window.sessionStorage.getItem(STORAGE_KEY)
    if (v === "classic" || v === "warroom") return v
  } catch {
    // sessionStorage tidak tersedia (privacy mode) — fallback default
  }
  return "warroom"
}

export function setProjectView(view: ProjectView): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, view)
  } catch {
    // abaikan — mode tidak persist, tetap default
  }
}