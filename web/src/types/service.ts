export interface ServiceLibraryItem {
  id: string
  ownerId: string
  serviceId: string
  label?: string
  description?: string
  createdAt?: string
  updatedAt?: string
  projectCount?: number
  knowledgeCount?: number
  dbConfig?: { type: string; uri?: string; db?: string; collection?: string; has_uri?: boolean } | null
  globallyRegistered?: boolean
}

export interface ServiceRegistryEntry {
  service_id: string
}

export interface ServiceUsage {
  projectId: string
  name: string
}

export interface ServiceKnowledgeLite {
  refId: string
  knowledgeLibraryId: string
  name: string
  folder: string
  ownerId: string
}

export interface ProjectServiceRef {
  id: string
  projectId: string
  libraryServiceId: string
  serviceId: string
  label?: string
  description?: string
  ownerId?: string // FE-8.1: kelola knowledge hanya oleh pemilik service
  addedBy: string
  addedAt?: string
  /** FE-8.2: knowledge ter-link ditampilkan langsung di settings */
  knowledge?: ServiceKnowledgeLite[]
}

export interface ServiceKnowledgeLink {
  id: string
  serviceLibraryId: string
  knowledgeLibraryId: string
  name: string
  folder: string
  ownerId?: string // FE-8.1: edit hanya utk pemilik dokumen
  addedBy: string
  addedAt?: string
}

/** FE-8.1: service refs seluruh project dalam satu workspace (grouped). */
export interface WorkspaceServiceGroup {
  projectId: string
  projectName: string
  services: ProjectServiceRef[]
}
