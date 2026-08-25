export type KnowledgeFolder = "general" | "services" | "playbooks" | "schemas" | "connections" | "observability"

export interface KnowledgeItem {
  id: string
  ownerId: string
  name: string
  folder: KnowledgeFolder
  content?: string
  sizeBytes?: number
  createdAt?: string
  updatedAt?: string
  usageCount?: number
}

export interface KnowledgeUsage {
  workspaceId: string
  name: string
}

export interface WorkspaceKnowledgeRef {
  id: string
  workspaceId: string
  workspaceName?: string
  libraryId: string
  name: string
  folder: string
  updatedAt?: string | null
  addedBy: string
  addedAt?: string
  content?: string
}
