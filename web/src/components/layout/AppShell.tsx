import { Outlet } from "react-router-dom"
import { Sidebar } from "@/components/layout/Sidebar"
import { Topbar } from "@/components/layout/Topbar"

/**
 * AppShell — kerangka aplikasi: Sidebar kiri + Topbar atas + konten (Outlet).
 * Referensi desain: Linear.app (popov-frontend-plan.md).
 */
export function AppShell() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar className="hidden md:flex" />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="flex-1 overflow-y-auto overflow-x-hidden bg-background">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
