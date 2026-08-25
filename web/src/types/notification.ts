export interface NotificationItem {
  id: string
  type: string
  title: string
  payload: {
    ticketId?: string
    ticketNumber?: number
    projectId?: string
    projectKey?: string
  }
  readAt: string | null
  createdAt: string
}

export interface NotificationsResponse {
  notifications: NotificationItem[]
  unread: number
}
