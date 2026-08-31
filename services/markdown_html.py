"""
Markdown → HTML untuk body email (channel notifikasi email).

Watchdog `_format_service_message` menghasilkan teks Markdown; body email butuh
HTML + text/plain fallback. `markdown` lib standar (extensions: tables, fenced_code,
nl2br opsional). Jika lib tidak tersedia, fallback = escape + <pre> (tidak crash).
"""
from __future__ import annotations

import html
import logging

logger = logging.getLogger(__name__)


def markdown_to_html(text: str) -> str:
    """Render Markdown → HTML string. Fallback: escaped plain text di <pre>."""
    if not text:
        return ""
    try:
        import markdown as md

        return md.markdown(
            text,
            extensions=["tables", "fenced_code", "nl2br"],
            output_format="html5",
        )
    except Exception as e:
        logger.warning(f"[markdown_html] fallback plain (lib error: {e})")
        return f"<pre>{html.escape(text)}</pre>"
