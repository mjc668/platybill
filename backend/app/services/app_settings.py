"""Install-level settings resolution: DB override → environment → default.

Only the bill-import folder/poller knobs are exposed for now; anything not
stored in `app_settings` falls back to the env-backed Settings object.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import socket
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.services.ollama import OllamaConfig

IMPORT_ENABLED_KEY = "import.enabled"
IMPORT_DIR_KEY = "import.dir"
IMPORT_POLL_MINUTES_KEY = "import.poll_minutes"
OLLAMA_BASE_URL_KEY = "ollama.base_url"
OLLAMA_MODEL_KEY = "ollama.model"

MIN_POLL_MINUTES = 1
MAX_POLL_MINUTES = 1440


def get_value(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row is not None else None


def set_value(db: Session, key: str, value: str | None) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def import_enabled(db: Session) -> bool:
    override = get_value(db, IMPORT_ENABLED_KEY)
    if override is None:
        return settings.import_enabled
    return override == "1"


def import_dir(db: Session) -> str:
    return get_value(db, IMPORT_DIR_KEY) or settings.import_dir


def import_poll_minutes(db: Session) -> int:
    override = get_value(db, IMPORT_POLL_MINUTES_KEY)
    if override is not None:
        try:
            minutes = int(override)
        except ValueError:
            minutes = settings.import_poll_minutes
        if MIN_POLL_MINUTES <= minutes <= MAX_POLL_MINUTES:
            return minutes
    return settings.import_poll_minutes


def path_is_allowed(path: str) -> bool:
    """Only directories inside the data volume may be polled.

    The poller moves/deletes processed files, so pointing it at an arbitrary
    host path could destroy data; confine it to DATA_DIR.
    """
    data_dir = Path(settings.data_dir).resolve()
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    return resolved == data_dir or data_dir in resolved.parents


def validate_import_dir(path: str) -> str | None:
    """Return an error message when the directory is unusable, else None."""
    if not path or not path.startswith("/"):
        return "Directory must be an absolute path"
    if not path_is_allowed(path):
        return f"Directory must live inside {settings.data_dir}"
    if os.path.exists(path) and not os.path.isdir(path):
        return "Path exists but is not a directory"
    return None


def ollama_base_url(db: Session) -> str | None:
    return get_value(db, OLLAMA_BASE_URL_KEY) or settings.ollama_base_url


def ollama_model(db: Session) -> str:
    return get_value(db, OLLAMA_MODEL_KEY) or settings.ollama_model


def ollama_config(db: Session) -> OllamaConfig | None:
    """Effective Ollama connection settings, or None when unconfigured."""
    base_url = ollama_base_url(db)
    if not base_url:
        return None
    return OllamaConfig(
        base_url=base_url,
        model=ollama_model(db),
        ocr_model=settings.ollama_ocr_model,
        text_model=settings.ollama_text_model,
        timeout=settings.ollama_timeout_seconds,
    )


def validate_ollama_url(url: str) -> str | None:
    if not url.startswith(("http://", "https://")):
        return "URL must start with http:// or https://"
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return "URL must include a host"
    if parsed.username or parsed.password:
        return "URL must not include credentials"
    lowered = host.lower()
    if lowered in {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "169.254.169.254",
        "metadata.google.internal",
    }:
        return "URL host is not allowed"
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return "URL host is not allowed"
    except ValueError:
        pass
    # Best-effort DNS check: block hostnames that resolve to private ranges.
    # Unresolvable hosts are allowed (e.g. docker service names in tests).
    try:
        for info in socket.getaddrinfo(host, None):
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return "URL host is not allowed"
    except socket.gaierror:
        pass
    return None
