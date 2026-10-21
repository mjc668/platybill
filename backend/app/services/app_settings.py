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

# LLM provider (DB override → env → default). Provider ids: "ollama",
# "openai", "anthropic", "google", "opencode" (OpenAI-compatible endpoint).
LLM_PROVIDER_KEY = "llm.provider"
LLM_MODEL_KEY = "llm.model"
LLM_BASE_URL_KEY = "llm.base_url"
LLM_API_KEY_KEY = "llm.api_key"
LLM_TIMEOUT_KEY = "llm.timeout_seconds"

# SMTP (DB override → env). Password stays masked in every API response.
SMTP_HOST_KEY = "smtp.host"
SMTP_PORT_KEY = "smtp.port"
SMTP_USER_KEY = "smtp.user"
SMTP_PASSWORD_KEY = "smtp.password"
SMTP_USE_TLS_KEY = "smtp.use_tls"
SMTP_FROM_KEY = "smtp.from"

# Apprise (DB override → env).
APPRISE_BASE_URL_KEY = "apprise.base_url"
APPRISE_URLS_KEY = "apprise.urls"
APPRISE_KEY_KEY = "apprise.key"
APPRISE_TIMEOUT_KEY = "apprise.timeout_seconds"

# IMAP mailbox (DB override → env).
IMAP_HOST_KEY = "imap.host"
IMAP_PORT_KEY = "imap.port"
IMAP_USER_KEY = "imap.user"
IMAP_PASSWORD_KEY = "imap.password"
IMAP_FOLDER_KEY = "imap.folder"
IMAP_TLS_KEY = "imap.tls"
IMAP_POLL_MINUTES_KEY = "imap.poll_minutes"
IMAP_MARK_READ_KEY = "imap.mark_read"
IMAP_ALLOWED_SENDERS_KEY = "imap.allowed_senders"
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


def _host_is_metadata(host: str) -> bool:
    """True for cloud metadata / link-local endpoints (the SSRF targets).

    Loopback, LAN, and Docker names are legitimate here: this is a
    self-hosted app and Ollama typically runs on localhost or the LAN.
    """
    lowered = host.lower().rstrip(".")
    if lowered in {"169.254.169.254", "metadata.google.internal"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_link_local


def _host_resolves_to_metadata(host: str) -> bool:
    """Best-effort DNS check for metadata endpoints behind a hostname.

    Unresolvable hosts are allowed (e.g. docker service names in tests).
    """
    lowered = host.lower().rstrip(".")
    if lowered in {"metadata.google.internal"}:
        return True
    try:
        ipaddress.ip_address(host)
        return False  # literal IPs handled by _host_is_metadata
    except ValueError:
        pass
    try:
        for info in socket.getaddrinfo(host, None):
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if ip.is_link_local or str(ip) == "169.254.169.254":
                return True
    except socket.gaierror:
        pass
    return False


def validate_server_url(url: str) -> str | None:
    """Validate a user-supplied server URL (Ollama, LLM, Apprise).

    Requires http(s), a host, and no embedded credentials; blocks cloud
    metadata endpoints. LAN/loopback hosts are allowed — self-hosted
    services live there.
    """
    if not url.startswith(("http://", "https://")):
        return "URL must start with http:// or https://"
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return "URL must include a host"
    if parsed.username or parsed.password:
        return "URL must not include credentials"
    if _host_is_metadata(host) or _host_resolves_to_metadata(host):
        return "URL host is not allowed"
    return None


def validate_ollama_url(url: str) -> str | None:
    """Legacy alias for validate_server_url (Ollama settings path)."""
    return validate_server_url(url)


def _bool_override(db: Session, key: str, default: bool) -> bool:
    override = get_value(db, key)
    if override is None:
        return default
    return override == "1"


def _int_override(
    db: Session, key: str, default: int, *, minimum: int, maximum: int
) -> int:
    override = get_value(db, key)
    if override is not None:
        try:
            value = int(override)
        except ValueError:
            value = default
        if minimum <= value <= maximum:
            return value
    return default


# --- SMTP ---------------------------------------------------------------


def smtp_host(db: Session) -> str | None:
    return get_value(db, SMTP_HOST_KEY) or settings.smtp_host


def smtp_port(db: Session) -> int:
    return _int_override(
        db, SMTP_PORT_KEY, settings.smtp_port, minimum=1, maximum=65535
    )


def smtp_user(db: Session) -> str | None:
    return get_value(db, SMTP_USER_KEY) or settings.smtp_user


def smtp_password(db: Session) -> str | None:
    override = get_value(db, SMTP_PASSWORD_KEY)
    if override is not None:
        return override or None
    return settings.smtp_password.get_secret_value() if settings.smtp_password else None


def smtp_use_tls(db: Session) -> bool:
    return _bool_override(db, SMTP_USE_TLS_KEY, settings.smtp_use_tls)


def smtp_from(db: Session) -> str | None:
    return get_value(db, SMTP_FROM_KEY) or settings.reminder_from


def smtp_configured(db: Session) -> bool:
    return bool(smtp_host(db))


# --- Apprise ------------------------------------------------------------


def apprise_base_url(db: Session) -> str | None:
    override = get_value(db, APPRISE_BASE_URL_KEY)
    if override is not None:
        return override or None
    return settings.apprise_base_url


def apprise_urls(db: Session) -> str | None:
    override = get_value(db, APPRISE_URLS_KEY)
    if override is not None:
        return override or None
    return settings.apprise_urls


def apprise_key(db: Session) -> str | None:
    override = get_value(db, APPRISE_KEY_KEY)
    if override is not None:
        return override or None
    return settings.apprise_key


def apprise_timeout(db: Session) -> float:
    override = get_value(db, APPRISE_TIMEOUT_KEY)
    if override is not None:
        try:
            return max(1.0, float(override))
        except ValueError:
            pass
    return settings.apprise_timeout_seconds


def apprise_configured(db: Session) -> bool:
    return bool(apprise_base_url(db))


# --- IMAP ---------------------------------------------------------------


def imap_host(db: Session) -> str | None:
    return get_value(db, IMAP_HOST_KEY) or settings.imap_host


def imap_port(db: Session) -> int:
    return _int_override(
        db, IMAP_PORT_KEY, settings.imap_port, minimum=1, maximum=65535
    )


def imap_user(db: Session) -> str | None:
    return get_value(db, IMAP_USER_KEY) or settings.imap_user


def imap_password(db: Session) -> str | None:
    override = get_value(db, IMAP_PASSWORD_KEY)
    if override is not None:
        return override or None
    return settings.imap_password.get_secret_value() if settings.imap_password else None


def imap_folder(db: Session) -> str:
    return get_value(db, IMAP_FOLDER_KEY) or settings.imap_folder


def imap_tls(db: Session) -> bool:
    return _bool_override(db, IMAP_TLS_KEY, settings.imap_tls)


def imap_poll_minutes(db: Session) -> int:
    override = get_value(db, IMAP_POLL_MINUTES_KEY)
    if override is not None:
        try:
            minutes = int(override)
        except ValueError:
            minutes = settings.imap_poll_minutes
        if MIN_POLL_MINUTES <= minutes <= MAX_POLL_MINUTES:
            return minutes
    return settings.imap_poll_minutes


def imap_mark_read(db: Session) -> bool:
    return _bool_override(db, IMAP_MARK_READ_KEY, settings.imap_mark_read)


def imap_allowed_senders(db: Session) -> list[str]:
    override = get_value(db, IMAP_ALLOWED_SENDERS_KEY)
    if override is not None:
        return [s.strip() for s in override.split(",") if s.strip()]
    return settings.imap_allowed_senders


def imap_configured(db: Session) -> bool:
    return bool(imap_host(db) and imap_user(db) and imap_password(db))


def smtp_kwargs(db: Session) -> dict:
    """Effective SMTP connection kwargs for email senders (DB override → env)."""
    host = smtp_host(db)
    if host is None:
        raise OSError("SMTP not configured")
    return {
        "smtp_host": host,
        "smtp_port": smtp_port(db),
        "smtp_user": smtp_user(db),
        "smtp_password": smtp_password(db),
        "smtp_use_tls": smtp_use_tls(db),
        "from_addr": smtp_from(db) or smtp_user(db) or "",
    }


# --- LLM provider -------------------------------------------------------


def llm_provider(db: Session) -> str:
    from app.services.llm import PROVIDERS

    override = get_value(db, LLM_PROVIDER_KEY) or settings.llm_provider
    if override in PROVIDERS:
        return override
    return "ollama"


def llm_model(db: Session) -> str:
    return get_value(db, LLM_MODEL_KEY) or settings.llm_model


def llm_base_url(db: Session) -> str | None:
    return get_value(db, LLM_BASE_URL_KEY) or settings.llm_base_url


def llm_api_key(db: Session) -> str | None:
    override = get_value(db, LLM_API_KEY_KEY)
    if override is not None:
        return override or None
    return settings.llm_api_key.get_secret_value() if settings.llm_api_key else None


def llm_timeout(db: Session) -> float:
    override = get_value(db, LLM_TIMEOUT_KEY)
    if override is not None:
        try:
            return max(1.0, float(override))
        except ValueError:
            pass
    return settings.llm_timeout_seconds


def llm_config(db: Session):
    """Effective LLM connection settings (DB override → env → default)."""
    from app.services.llm import LlmConfig

    provider = llm_provider(db)
    if provider == "ollama":
        # Legacy Ollama keys keep working: they win when the provider is
        # unset/ollama, so existing installs carry over untouched.
        base_url = ollama_base_url(db)
        model = get_value(db, LLM_MODEL_KEY) or ollama_model(db)
    else:
        base_url = llm_base_url(db)
        model = llm_model(db)
    if not base_url and provider in ("ollama", "opencode"):
        return None
    if provider not in ("ollama", "opencode") and not llm_api_key(db):
        return None
    return LlmConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=llm_api_key(db),
        timeout=llm_timeout(db),
    )


def llm_configured(db: Session) -> bool:
    return llm_config(db) is not None
