/**
 * Persistensi dismissal onboarding checklist — pola theme-storage
 * (try/catch silent-fail agar private-mode tidak crash).
 *
 * Key tunggal berisi map per-user → per-workspace sehingga dismissal
 * benar-benar ter-scope: user lain di browser yang sama tidak terpengaruh.
 */
const KEY = "popov-agent-onboarding"

type DismissMap = Record<string, Record<string, true>>

function readMap(): DismissMap {
  try {
    const raw = window.localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as DismissMap) : {}
  } catch {
    return {}
  }
}

function writeMap(map: DismissMap) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(map))
  } catch {
    // private mode / quota — abaikan
  }
}

export function isOnboardingDismissed(userId: string, wsId: string): boolean {
  return readMap()[userId]?.[wsId] === true
}

export function dismissOnboarding(userId: string, wsId: string) {
  const map = readMap()
  map[userId] = { ...map[userId], [wsId]: true }
  writeMap(map)
}

// Progress terakhir yang diketahui — dipakai strip "kembali ke checklist" di
// halaman lain (settings/management) supaya user tetap melihat status tanpa
// mengulang semua query deteksi. Boleh sedikit stale; hanya kosmetik.
const PROGRESS_KEY = "popov-agent-onboarding-progress"

export function saveOnboardingProgress(done: number, total: number) {
  try {
    window.localStorage.setItem(PROGRESS_KEY, JSON.stringify({ done, total }))
  } catch {
    // private mode / quota — abaikan
  }
}

export function readOnboardingProgress(): { done: number; total: number } | null {
  try {
    const raw = window.localStorage.getItem(PROGRESS_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { done?: number; total?: number }
    if (typeof parsed.done === "number" && typeof parsed.total === "number") {
      return { done: parsed.done, total: parsed.total }
    }
  } catch {
    // korup / tidak ada — anggap belum ada data
  }
  return null
}

/** Checklist selesai / di-skip → strip "kembali" tidak boleh muncul lagi di mana pun. */
export function clearOnboardingProgress() {
  try {
    window.localStorage.removeItem(PROGRESS_KEY)
  } catch {
    // abaikan
  }
}
