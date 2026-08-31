"""
Shared bilingual message catalog for API responses.
All user-facing messages (errors, success, notes) centralized here.

Usage:
    from api.messages import msg, M
    locale = await get_user_locale(user_id)
    raise HTTPException(404, msg(locale, M.WORKSPACE_NOT_FOUND))
"""


class M:
    """Message keys — grouped by module."""

    # ── auth ──────────────────────────────────────────────────────────────
    EMAIL_ALREADY_REGISTERED = "email_already_registered"
    FAILED_CREATE_USER = "failed_create_user"
    INVALID_CREDENTIALS = "invalid_credentials"
    USER_NOT_FOUND = "user_not_found"
    INVALID_LOCALE = "invalid_locale"

    # ── workspace ─────────────────────────────────────────────────────────
    NOT_WORKSPACE_MEMBER = "not_workspace_member"
    ADMIN_ONLY_ACTION = "admin_only_action"
    WORKSPACE_NOT_FOUND = "workspace_not_found"
    FAILED_CREATE_WORKSPACE = "failed_create_workspace"
    DELETED_LABEL = "deleted_label"
    ROLE_MUST_BE_ADMIN_OR_MEMBER = "role_must_be_admin_or_member"
    USER_NOT_REGISTERED = "user_not_registered"
    OWNER_ALREADY_ADMIN = "owner_already_admin"
    OWNER_CANNOT_BE_REMOVED = "owner_cannot_be_removed"
    FAILED_CREATE_PROJECT = "failed_create_project"
    PROJECT_NOT_FOUND = "project_not_found"
    ARCHIVE_NOTE = "archive_note"

    # ── notification channels ─────────────────────────────────────────────
    CHANNEL_NOT_FOUND = "channel_not_found"
    OWNER_WORKSPACE_NOT_FOUND = "owner_workspace_not_found"
    ADMIN_ONLY_CHANNEL = "admin_only_channel"
    ADMIN_ONLY_CREATE_CHANNEL = "admin_only_create_channel"
    UNSUPPORTED_CHANNEL = "unsupported_channel"
    BOT_TOKEN_CHAT_ID_REQUIRED = "bot_token_chat_id_required"
    INVALID_BOT_TOKEN = "invalid_bot_token"
    SMTP_FIELDS_REQUIRED = "smtp_fields_required"
    INVALID_SMTP = "invalid_smtp"
    CHANNEL_STILL_LINKED = "channel_still_linked"
    BOT_TOKEN_NOT_SET = "bot_token_not_set"
    TELEGRAM_TEST_FAILED = "telegram_test_failed"
    SMTP_HOST_NOT_SET = "smtp_host_not_set"
    EMAIL_TEST_FAILED = "email_test_failed"
    SMTP_SEND_FAILED = "smtp_send_failed"
    TO_ADDRS_EMPTY = "to_addrs_empty"
    BOT_TOKEN_REQUIRED = "bot_token_required"
    SMTP_HOST_REQUIRED = "smtp_host_required"
    ADMIN_ONLY_DELIVERY_LOGS = "admin_only_delivery_logs"
    CHANNEL_BELONGS_TO_OTHER = "channel_belongs_to_other"
    WORKSPACE_PROJECT_NOT_FOUND = "workspace_project_not_found"
    ADMIN_ONLY_LINK_CHANNEL = "admin_only_link_channel"

    # ── chat ──────────────────────────────────────────────────────────────
    SESSION_NOT_FOUND = "session_not_found"
    NOT_YOUR_SESSION = "not_your_session"
    PIPELINE_STARTED = "pipeline_started"
    PIPELINE_ERROR = "pipeline_error"
    NO_ANSWER = "no_answer"
    INTERNAL_ERROR = "internal_error"
    TICKET_SESSION_LOCKED = "ticket_session_locked"
    MESSAGE_TOO_SHORT = "message_too_short"
    INVALID_MODE = "invalid_mode"
    WAIT_FOR_RESPONSE = "wait_for_response"
    INVALID_TOKEN = "invalid_token"
    STREAM_IN_USE = "stream_in_use"
    CANNOT_DELETE_RUNNING = "cannot_delete_running"
    TIMEOUT_ANALYSIS = "timeout_analysis"
    TIMEOUT_GENERIC = "timeout_generic"
    ANALYSIS_LOOP_STATUS = "analysis_loop_status"
    FETCHING_DATA = "fetching_data"

    # ── tickets ───────────────────────────────────────────────────────────
    TICKET_NOT_FOUND = "ticket_not_found"
    TICKET_EDIT_FORBIDDEN = "ticket_edit_forbidden"
    TITLE_TOO_SHORT = "title_too_short"
    DESCRIPTION_TOO_SHORT = "description_too_short"
    ASSIGNEE_NOT_MEMBER = "assignee_not_member"
    ASSIGNMENT_NOTIFICATION = "assignment_notification"
    TICKET_REOPEN_FORBIDDEN = "ticket_reopen_forbidden"
    NOTE_TOO_SHORT = "note_too_short"

    # ── knowledge ─────────────────────────────────────────────────────────
    KNOWLEDGE_DOC_NOT_FOUND = "knowledge_doc_not_found"
    KNOWLEDGE_NOT_FOUND = "knowledge_not_FOUND"
    KNOWLEDGE_IN_USE = "knowledge_in_use"
    ADMIN_ONLY_ADD_KNOWLEDGE = "admin_only_add_knowledge"
    ADMIN_ONLY_CONNECT_GROUNDING = "admin_only_connect_grounding"
    GROUNDING_DOC_NOT_FOUND = "grounding_doc_not_found"
    ADMIN_ONLY_UNLINK_GROUNDING = "admin_only_unlink_grounding"
    GROUNDING_REF_NOT_FOUND = "grounding_ref_not_found"
    KNOWLEDGE_REF_NOT_FOUND = "knowledge_ref_not_found"
    ADMIN_ONLY_UNLINK_KNOWLEDGE = "admin_only_unlink_knowledge"
    ONLY_MANAGEMENT_DOCS = "only_management_docs"

    # ── services ──────────────────────────────────────────────────────────
    SERVICE_NOT_FOUND = "service_not_found"
    ADMIN_ONLY_PROJECT_SERVICES = "admin_only_project_services"
    DB_CONNECTION_ADMIN_ONLY = "db_connection_admin_only"
    DB_CONNECTION_CHANGE_ADMIN_ONLY = "db_connection_change_admin_only"
    SERVICE_IN_USE = "service_in_use"
    KNOWLEDGE_DOC_NOT_YOURS = "knowledge_doc_not_yours"
    LINK_KNOWLEDGE_NOT_FOUND = "link_knowledge_not_found"
    SERVICE_REF_NOT_FOUND = "service_ref_not_found"

    # ── config ────────────────────────────────────────────────────────────
    INVALID_SERVICE_ID = "invalid_service_id"
    INVALID_COLLECTION_NAME = "invalid_collection_name"
    SERVICE_NOT_REGISTERED = "service_not_registered"
    INVALID_URL = "invalid_url"
    INVALID_PROVIDER = "invalid_provider"
    INVALID_MODEL_NAME = "invalid_model_name"
    UNKNOWN_PROVIDER = "unknown_provider"
    INVALID_KEY = "invalid_key"
    KEY_TOO_SHORT = "key_too_short"
    INVALID_EMBEDDING_MODE = "invalid_embedding_mode"
    EMBEDDING_MODEL_REQUIRED = "embedding_model_required"
    NO_CHANGES = "no_changes"
    MODEL_REQUIRED = "model_required"
    WATCHDOG_INTERVAL_INVALID = "watchdog_interval_invalid"
    TARGET_NOT_FOUND = "target_not_found"
    INVALID_PROBE_KIND = "invalid_probe_kind"
    URL_REQUIRED = "url_required"
    NOTIFICATION_NOT_FOUND = "notification_not_found"
    STACK_NOT_FOUND = "stack_not_found"
    REGISTRY_NOT_FOUND = "registry_not_found"
    DESCRIBPTION_TEMPLATE = "description_template"

    # ── routes (notify) ───────────────────────────────────────────────────
    NOTIFY_CHANNEL_NOT_FOUND = "notify_channel_not_found"
    NO_ENABLED_CHANNEL = "no_enabled_channel"
    NOTIFY_ID_OR_WORKSPACE_REQUIRED = "notify_id_or_workspace_required"
    NOTIFY_SENT = "notify_sent"
    NOTIFY_ALL_FAILED = "notify_all_failed"
    NOTIFY_SEND_FAILED = "notify_send_failed"
    SERVICE_DOC_NOT_FOUND = "service_doc_not_found"
    DOC_RELOADED = "doc_reloaded"
    REQUEST_NOT_FOUND = "request_not_found"
    EPISODE_NOT_FOUND = "episode_not_found"
    PATTERNS_NOT_FOUND = "patterns_not_found"
    PROMPT_NOT_FOUND = "prompt_not_found"
    PROMPT_CACHE_RELOADED = "prompt_cache_reloaded"


# ── Catalog ────────────────────────────────────────────────────────────────────
# Key: message key from M class
# Value: (indonesian, english)
_CATALOG: dict[str, tuple[str, str]] = {
    # auth
    M.EMAIL_ALREADY_REGISTERED: ("Email sudah terdaftar", "Email already registered"),
    M.FAILED_CREATE_USER: ("Gagal membuat user", "Failed to create user"),
    M.INVALID_CREDENTIALS: ("Email atau password salah", "Invalid email or password"),
    M.USER_NOT_FOUND: ("User tidak ditemukan", "User not found"),
    M.INVALID_LOCALE: ("Invalid locale", "Invalid locale"),

    # workspace
    M.NOT_WORKSPACE_MEMBER: ("Kamu bukan member workspace ini", "You are not a member of this workspace"),
    M.ADMIN_ONLY_ACTION: ("Hanya workspace admin yang boleh melakukan aksi ini", "Only workspace admin can perform this action"),
    M.WORKSPACE_NOT_FOUND: ("Workspace tidak ditemukan", "Workspace not found"),
    M.FAILED_CREATE_WORKSPACE: ("Gagal membuat workspace", "Failed to create workspace"),
    M.DELETED_LABEL: ("(terhapus)", "(deleted)"),
    M.ROLE_MUST_BE_ADMIN_OR_MEMBER: ("Role harus admin atau member", "Role must be admin or member"),
    M.USER_NOT_REGISTERED: ("User dengan email {email} belum terdaftar", "User with email {email} is not registered"),
    M.OWNER_ALREADY_ADMIN: ("Owner sudah admin workspace", "Owner is already workspace admin"),
    M.OWNER_CANNOT_BE_REMOVED: ("Owner tidak bisa dikeluarkan", "Owner cannot be removed"),
    M.FAILED_CREATE_PROJECT: ("Gagal membuat project", "Failed to create project"),
    M.PROJECT_NOT_FOUND: ("Project tidak ditemukan", "Project not found"),
    M.ARCHIVE_NOTE: ("Tiket & chat ikut terarsip (data utuh di DB). Pemulihan manual via DB.", "Tickets & chats archived (data intact in DB). Manual recovery via DB."),

    # notification channels
    M.CHANNEL_NOT_FOUND: ("Channel tidak ditemukan", "Channel not found"),
    M.OWNER_WORKSPACE_NOT_FOUND: ("Workspace pemilik channel tidak ditemukan", "Channel owner workspace not found"),
    M.ADMIN_ONLY_CHANNEL: ("Hanya admin workspace yang bisa mengelola notification channel", "Only workspace admin can manage notification channels"),
    M.ADMIN_ONLY_CREATE_CHANNEL: ("Hanya admin workspace yang bisa menambah notification channel", "Only workspace admin can add notification channels"),
    M.UNSUPPORTED_CHANNEL: ("channel '{channel}' belum didukung (opsi: {supported})", "channel '{channel}' not supported (options: {supported})"),
    M.BOT_TOKEN_CHAT_ID_REQUIRED: ("bot_token dan chat_id wajib diisi", "bot_token and chat_id are required"),
    M.INVALID_BOT_TOKEN: ("bot_token tidak valid: {error}", "Invalid bot_token: {error}"),
    M.SMTP_FIELDS_REQUIRED: ("smtp_host, from_addr, dan to_addrs wajib diisi", "smtp_host, from_addr, and to_addrs are required"),
    M.INVALID_SMTP: ("SMTP tidak valid: {error}", "Invalid SMTP: {error}"),
    M.CHANNEL_STILL_LINKED: ("Channel masih ter-link ke project. Kirim confirm=true untuk hapus paksa (link ikut terputus).", "Channel is still linked to projects. Send confirm=true to force delete (links will be removed)."),
    M.BOT_TOKEN_NOT_SET: ("bot_token belum diset", "bot_token not set"),
    M.TELEGRAM_TEST_FAILED: ("Telegram menolak pesan tes (cek chat_id / bot harus join chat)", "Telegram rejected test message (check chat_id / bot must join chat)"),
    M.SMTP_HOST_NOT_SET: ("smtp_host belum diset", "smtp_host not set"),
    M.EMAIL_TEST_FAILED: ("gagal kirim", "failed to send"),
    M.SMTP_SEND_FAILED: ("gagal kirim", "failed to send"),
    M.TO_ADDRS_EMPTY: ("to_addrs kosong", "to_addrs is empty"),
    M.BOT_TOKEN_REQUIRED: ("bot_token wajib", "bot_token is required"),
    M.SMTP_HOST_REQUIRED: ("smtp_host wajib", "smtp_host is required"),
    M.ADMIN_ONLY_DELIVERY_LOGS: ("Hanya admin workspace yang bisa melihat delivery logs", "Only workspace admin can view delivery logs"),
    M.CHANNEL_BELONGS_TO_OTHER: ("Channel milik workspace lain", "Channel belongs to another workspace"),
    M.WORKSPACE_PROJECT_NOT_FOUND: ("Workspace project tidak ditemukan", "Workspace project not found"),
    M.ADMIN_ONLY_LINK_CHANNEL: ("Hanya admin workspace yang bisa mengatur link channel project", "Only workspace admin can manage channel-project links"),

    # chat
    M.SESSION_NOT_FOUND: ("Session tidak ditemukan", "Session not found"),
    M.NOT_YOUR_SESSION: ("Bukan session milikmu", "Not your session"),
    M.PIPELINE_STARTED: ("Pipeline dimulai", "Pipeline started"),
    M.PIPELINE_ERROR: ("⚠️ Pipeline selesai dengan error: {error}", "⚠️ Pipeline finished with an error: {error}"),
    M.NO_ANSWER: ("⚠️ Agent tidak menghasilkan jawaban. Coba ulangi pertanyaanmu.", "⚠️ The agent did not produce an answer. Try asking again."),
    M.INTERNAL_ERROR: ("⚠️ Terjadi error internal saat analisis: {error}", "⚠️ An internal error occurred during analysis: {error}"),
    M.TICKET_SESSION_LOCKED: ("Sesi terikat tiket tidak bisa diubah dari sini", "Ticket-bound session cannot be modified from here"),
    M.MESSAGE_TOO_SHORT: ("Pesan minimal 2 karakter", "Message must be at least 2 characters"),
    M.INVALID_MODE: ("mode harus salah satu dari: low, medium, thinking", "mode must be one of: low, medium, thinking"),
    M.WAIT_FOR_RESPONSE: ("Tunggu respons selesai (atau stop stream)", "Wait for the response to finish (or stop the stream)"),
    M.INVALID_TOKEN: ("Token tidak valid", "Invalid token"),
    M.STREAM_IN_USE: ("Stream sedang dibaca klien lain", "Stream is being read by another client"),
    M.CANNOT_DELETE_RUNNING: ("Tidak bisa menghapus sesi yang sedang berjalan — tunggu/hentikan stream dulu", "Cannot delete a running session — wait for or stop the stream first"),
    M.TIMEOUT_ANALYSIS: ("⚠️ Analisis melebihi batas waktu (120 detik) karena respons LLM lambat/timeout. Ringkasan sebagian dikirim ke Telegram.", "⚠️ Analysis exceeded time limit (120s) due to slow LLM response/timeout. Partial summary sent to Telegram."),
    M.TIMEOUT_GENERIC: ("⚠️ Analisis melebihi batas waktu (120 detik). Coba pertanyaan yang lebih spesifik.", "⚠️ Analysis exceeded time limit (120s). Try a more specific question."),
    M.ANALYSIS_LOOP_STATUS: ("Analisis awal selesai (Confidence {pct}%). Memeriksa data tambahan secara otomatis...", "Initial analysis complete (Confidence {pct}%). Checking additional data automatically..."),
    M.FETCHING_DATA: ("Mengambil data dari {agent}...", "Fetching data from {agent}..."),

    # tickets
    M.TICKET_NOT_FOUND: ("Tiket tidak ditemukan", "Ticket not found"),
    M.TICKET_EDIT_FORBIDDEN: ("Hanya pembuat, assignee, atau admin workspace yang bisa mengedit", "Only creator, assignee, or workspace admin can edit"),
    M.TITLE_TOO_SHORT: ("Judul minimal 5 karakter", "Title must be at least 5 characters"),
    M.DESCRIPTION_TOO_SHORT: ("Deskripsi minimal 10 karakter", "Description must be at least 10 characters"),
    M.ASSIGNEE_NOT_MEMBER: ("Ada assignee yang bukan member workspace", "One or more assignees are not workspace members"),
    M.ASSIGNMENT_NOTIFICATION: ('Kamu di-assign ke {display} "{title}"', 'You have been assigned to {display} "{title}"'),
    M.TICKET_REOPEN_FORBIDDEN: ("Hanya tiket resolved/closed yang bisa dibuka kembali", "Only resolved/closed tickets can be reopened"),
    M.NOTE_TOO_SHORT: ("Catatan minimal 2 karakter", "Note must be at least 2 characters"),

    # knowledge
    M.KNOWLEDGE_DOC_NOT_FOUND: ("Dokumen knowledge tidak ditemukan", "Knowledge document not found"),
    M.KNOWLEDGE_NOT_FOUND: ("Knowledge tidak ditemukan", "Knowledge not found"),
    M.KNOWLEDGE_IN_USE: ("Knowledge masih dipakai {count} workspace", "Knowledge is still used by {count} workspaces"),
    M.ADMIN_ONLY_ADD_KNOWLEDGE: ("Hanya admin workspace yang bisa menambah knowledge", "Only workspace admin can add knowledge"),
    M.ADMIN_ONLY_CONNECT_GROUNDING: ("Hanya admin workspace yang bisa mengkoneksikan grounding doc", "Only workspace admin can connect grounding docs"),
    M.GROUNDING_DOC_NOT_FOUND: ("Grounding doc tidak ditemukan di Management", "Grounding doc not found in Management"),
    M.ADMIN_ONLY_UNLINK_GROUNDING: ("Hanya admin workspace yang bisa melepas koneksi grounding doc", "Only workspace admin can disconnect grounding docs"),
    M.GROUNDING_REF_NOT_FOUND: ("Referensi grounding doc tidak ditemukan", "Grounding doc reference not found"),
    M.KNOWLEDGE_REF_NOT_FOUND: ("Referensi knowledge tidak ditemukan", "Knowledge reference not found"),
    M.ADMIN_ONLY_UNLINK_KNOWLEDGE: ("Hanya admin workspace yang bisa melepas knowledge", "Only workspace admin can unlink knowledge"),
    M.ONLY_MANAGEMENT_DOCS: ("Hanya dokumen dari Management library yang bisa di-link ke workspace", "Only documents from the Management library can be linked to workspaces"),

    # services
    M.SERVICE_NOT_FOUND: ("Service tidak ditemukan", "Service not found"),
    M.ADMIN_ONLY_PROJECT_SERVICES: ("Hanya admin workspace yang bisa mengubah services project", "Only workspace admin can modify project services"),
    M.DB_CONNECTION_ADMIN_ONLY: ("Koneksi database hanya bisa didaftarkan admin global — simpan service tanpa DB config, lalu hubungi admin", "Database connections can only be registered by global admin — save the service without DB config, then contact admin"),
    M.DB_CONNECTION_CHANGE_ADMIN_ONLY: ("Koneksi database hanya bisa diubah admin global", "Database connections can only be modified by global admin"),
    M.SERVICE_IN_USE: ("Service masih dipakai {count} project", "Service is still used by {count} projects"),
    M.KNOWLEDGE_DOC_NOT_YOURS: ("Dokumen knowledge tidak ditemukan (bukan milikmu)", "Knowledge document not found (not yours)"),
    M.LINK_KNOWLEDGE_NOT_FOUND: ("Link knowledge tidak ditemukan", "Knowledge link not found"),
    M.SERVICE_REF_NOT_FOUND: ("Referensi service tidak ditemukan", "Service reference not found"),

    # config
    M.INVALID_SERVICE_ID: ("service_id: huruf kecil/angka/underscore, 2-64 karakter", "service_id: lowercase letters/numbers/underscore, 2-64 characters"),
    M.INVALID_COLLECTION_NAME: ("Nama collection tidak valid", "Invalid collection name"),
    M.SERVICE_NOT_REGISTERED: ("Service tidak terdaftar", "Service not registered"),
    M.INVALID_URL: ("{label} harus URL http(s)", "{label} must be an http(s) URL"),
    M.INVALID_PROVIDER: ("Provider harus salah satu dari {providers}", "Provider must be one of {providers}"),
    M.INVALID_MODEL_NAME: ("Nama model tidak valid", "Invalid model name"),
    M.UNKNOWN_PROVIDER: ("Provider model tidak dikenal: {provider}", "Unknown model provider: {provider}"),
    M.INVALID_KEY: ("API key {provider} terlalu pendek", "API key {provider} is too short"),
    M.KEY_TOO_SHORT: ("API key {provider} terlalu pendek", "API key {provider} is too short"),
    M.INVALID_EMBEDDING_MODE: ("embedding.mode harus local atau provider", "embedding.mode must be local or provider"),
    M.EMBEDDING_MODEL_REQUIRED: ("model embedding wajib diisi saat mode provider", "embedding model is required when mode is provider"),
    M.NO_CHANGES: ("Tidak ada perubahan", "No changes"),
    M.MODEL_REQUIRED: ("model wajib diisi", "model is required"),
    M.WATCHDOG_INTERVAL_INVALID: ("Interval watchdog 1-1440 menit", "Watchdog interval 1-1440 minutes"),
    M.TARGET_NOT_FOUND: ("target tidak ditemukan", "target not found"),
    M.INVALID_PROBE_KIND: ("kind harus salah satu dari {kinds}", "kind must be one of {kinds}"),
    M.URL_REQUIRED: ("URL wajib diisi", "URL is required"),
    M.NOTIFICATION_NOT_FOUND: ("notifikasi tidak ditemukan", "notification not found"),
    M.STACK_NOT_FOUND: ("stack tidak ditemukan", "stack not found"),
    M.REGISTRY_NOT_FOUND: ("registry tidak ditemukan", "registry not found"),
    M.DESCRIBPTION_TEMPLATE: ("## Deskripsi\n\nService {sid} — kelola grounding doc ini via UI/API.", "## Description\n\nService {sid} — manage this grounding doc via UI/API."),

    # routes (notify)
    M.NOTIFY_CHANNEL_NOT_FOUND: ("Channel tidak ditemukan / disabled", "Channel not found / disabled"),
    M.NO_ENABLED_CHANNEL: ("Tidak ada channel telegram enabled untuk konteks ini", "No enabled telegram channel for this context"),
    M.NOTIFY_ID_OR_WORKSPACE_REQUIRED: ("Wajib sertakan notif_id ATAU workspace_id", "notif_id or workspace_id is required"),
    M.NOTIFY_SENT: ("Terkirim ke {sent}/{total} channel telegram", "Sent to {sent}/{total} telegram channels"),
    M.NOTIFY_ALL_FAILED: ("semua channel gagal", "all channels failed"),
    M.NOTIFY_SEND_FAILED: ("Gagal mengirim pesan ke Telegram", "Failed to send message to Telegram"),
    M.SERVICE_DOC_NOT_FOUND: ("Dokumen service '{service_id}' tidak ditemukan.", "Service document '{service_id}' not found."),
    M.DOC_RELOADED: ("Dokumen berhasil di-reload", "Document reloaded successfully"),
    M.REQUEST_NOT_FOUND: ("Request {request_id} tidak ditemukan", "Request {request_id} not found"),
    M.EPISODE_NOT_FOUND: ("Episode tidak ditemukan", "Episode not found"),
    M.PATTERNS_NOT_FOUND: ("Patterns for {service} not found", "Patterns for {service} not found"),
    M.PROMPT_NOT_FOUND: ("Prompt '{name}' tidak ditemukan", "Prompt '{name}' not found"),
    M.PROMPT_CACHE_RELOADED: ("Prompt cache di-reload", "Prompt cache reloaded"),
}


def msg(locale: str, key: str, **kwargs) -> str:
    """Return localized message by key. Supports {placeholders} via str.format()."""
    pair = _CATALOG.get(key)
    if pair is None:
        return key  # fallback: return key itself
    text = pair[1] if locale == "en" else pair[0]
    if kwargs:
        text = text.format(**kwargs)
    return text
