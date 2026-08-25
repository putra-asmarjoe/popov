import type { UserRole } from "./auth"

export type WorkspaceRole = "admin" | "member"

export interface Workspace {
  id: string
  name: string
  slug: string
  ownerId: string
  memberCount?: number
  createdAt: string
}

export interface WorkspaceMember {
  userId: string
  name: string
  email: string
  globalRole: UserRole
  wsRole: WorkspaceRole
  joinedAt: string
}

export interface WorkspaceDetail extends Workspace {
  members: WorkspaceMember[]
  isOwner: boolean
}

export interface Project {
  id: string
  workspaceId: string
  name: string
  slug: string
  key: string
  createdBy: string
  createdAt: string
}
