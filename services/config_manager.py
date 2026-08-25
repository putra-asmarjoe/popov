"""
Config manager — FE-6 Management Panel.
Utilitas tulis-konfigurasi yang aman: atomic JSON (tmp + os.replace) dan patch .env
(timpa baris KEY=… atau append). Tidak pernah me-return nilai secret.
"""
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CONFIG_DIR = ROOT / "config"
ENV_PATH = ROOT / ".env"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Cannot load {path}: {e}")
        return default


def save_json_atomic(path: Path, data: Any) -> None:
    """Tulis JSON atomically (tmp + os.replace) — pola Pattern Miner Fix #30."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def patch_env(updates: Dict[str, str]) -> List[str]:
    """Patch .env: timpa baris KEY=… bila ada, append bila belum. Return daftar key yang diubah."""
    if not updates:
        return []
    lines: List[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    changed = []
    for key, value in updates.items():
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$")
        new_line = f"{key}={value}"
        for i, line in enumerate(lines):
            if pattern.match(line.strip()):
                if lines[i] != new_line:
                    lines[i] = new_line
                break
        else:
            lines.append(new_line)
        changed.append(key)
    # atomic write
    fd, tmp = tempfile.mkstemp(dir=str(ENV_PATH.parent), suffix=".env.tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, ENV_PATH)
    logger.info(f".env patched: {changed}")
    return changed


def mask_uri(uri: Optional[str]) -> Optional[str]:
    """Sembunyikan kredensial userinfo pada URI (scheme://***@host/...)."""
    if not uri:
        return None
    return re.sub(r"://[^@/]+@", "://***@", uri)
