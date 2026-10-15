"""User-local date/time helpers.

Every date-sensitive backend decision (overdue, due-soon, reminder windows,
resume dates, month checks) must use the *user's* current date, not the
server's. Users without a timezone follow the server's local time — the
deployment's TZ and the behaviour that predates per-user timezones — so
existing users are unaffected until they set one.
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_zone(timezone_name: str | None) -> ZoneInfo | None:
    """Return the ZoneInfo for an IANA name, or None when unset/invalid."""
    if not timezone_name:
        return None
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def user_now(timezone_name: str | None, *, now_utc: datetime | None = None) -> datetime:
    """Current time in the user's timezone (server-local when unset).

    `now_utc` exists for tests: pass a fixed aware UTC datetime to get a
    deterministic local time.
    """
    base = now_utc if now_utc is not None else datetime.now(timezone.utc)
    zone = resolve_zone(timezone_name)
    if zone is None:
        # No timezone: the server's local time (the deployment TZ) — the
        # pre-timezone behaviour of date.today().
        return base.astimezone()
    return base.astimezone(zone)


def user_today(timezone_name: str | None, *, now_utc: datetime | None = None) -> date:
    """The user's current date (server-local date when no timezone is set)."""
    return user_now(timezone_name, now_utc=now_utc).date()


def validate_timezone(value: str | None) -> str | None:
    """Normalise and validate an IANA timezone name for storage."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if resolve_zone(value) is None:
        raise ValueError("timezone must be a valid IANA name, e.g. Australia/Sydney")
    return value
