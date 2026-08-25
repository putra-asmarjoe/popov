import { create } from "zustand"
import type { Project, Workspace } from "@/types/workspace"

const LAST_WS_KEY = "popov.lastWorkspace"
const LAST_PROJ_KEY = "popov.lastProject"

function readLS(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function writeLS(key: string, value: string | null): void {
  try {
    if (value) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch {
    // ignore
  }
}

interface WorkspaceStore {
  activeWorkspace: Workspace | null
  activeProject: Project | null

  setActiveWorkspace: (ws: Workspace | null) => void
  setActiveProject: (project: Project | null) => void
  /** Slug workspace/project terakhir dari localStorage (untuk redirect awal). */
  lastSlugs: () => { workspaceSlug: string | null; projectSlug: string | null }
}

export const useWorkspaceStore = create<WorkspaceStore>((set) => ({
  activeWorkspace: null,
  activeProject: null,

  setActiveWorkspace(ws) {
    writeLS(LAST_WS_KEY, ws?.slug ?? null)
    set({ activeWorkspace: ws, activeProject: null })
    writeLS(LAST_PROJ_KEY, null)
  },

  setActiveProject(project) {
    writeLS(LAST_PROJ_KEY, project?.slug ?? null)
    set({ activeProject: project })
  },

  lastSlugs() {
    return { workspaceSlug: readLS(LAST_WS_KEY), projectSlug: readLS(LAST_PROJ_KEY) }
  },
}))
