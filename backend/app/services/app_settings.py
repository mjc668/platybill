"""Install-level settings resolution: DB override → environment → default.

Only the bill-import folder/poller knobs are exposed for now; anything not
stored in `app_settings` falls back to the env-backed Settings object.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.app_setting import AppSetting

IMPORT_ENABLED_KEY = "import.enabled"
IMPORT_DIR_KEY = "import.dir"
IMPORT_POLL_MINUTES_KEY = "import.poll_minutes"

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
