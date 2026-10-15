"""Per-user timezone: local-date helpers and profile validation."""

import os
from datetime import date, datetime, timezone

import pytest

from app.core.timezones import user_now, user_today, validate_timezone
from tests.conftest import auth, register_and_login

# 23:30 UTC is already the 16th in Sydney (+11) but still the 15th in LA.
_FIXED_UTC = datetime(2026, 10, 15, 23, 30, tzinfo=timezone.utc)


def test_user_today_follows_the_users_timezone():
    assert user_today("Australia/Sydney", now_utc=_FIXED_UTC) == date(2026, 10, 16)
    assert user_today("America/Los_Angeles", now_utc=_FIXED_UTC) == date(2026, 10, 15)


def test_user_today_without_timezone_follows_server_local_time():
    # The suite pins TZ=UTC (conftest), so server-local == UTC here.
    assert os.environ["TZ"] == "UTC"
    assert user_today(None, now_utc=_FIXED_UTC) == date(2026, 10, 15)
    # An unparsable stored value degrades to server-local instead of crashing.
    assert user_today("Mars/Olympus", now_utc=_FIXED_UTC) == date(2026, 10, 15)


def test_user_now_converts_aware_input():
    local = user_now("Australia/Sydney", now_utc=_FIXED_UTC)
    assert local.utcoffset() is not None
    assert local.hour == 10  # 23:30 UTC + 11 on 2026-10-16


def test_validate_timezone_normalises_and_rejects():
    assert validate_timezone(None) is None
    assert validate_timezone("") is None
    assert validate_timezone(" Australia/Sydney ") == "Australia/Sydney"
    with pytest.raises(ValueError):
        validate_timezone("Not/AZone")


def test_profile_timezone_round_trip_and_validation(client_db):
    client, _ = client_db
    token = register_and_login(client, "tz@test.com")

    r = client.patch(
        "/auth/me", json={"timezone": "Australia/Sydney"}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == "Australia/Sydney"

    r = client.get("/auth/me", headers=auth(token))
    assert r.json()["timezone"] == "Australia/Sydney"

    # Null clears back to the UTC fallback.
    r = client.patch("/auth/me", json={"timezone": None}, headers=auth(token))
    assert r.status_code == 200
    assert r.json()["timezone"] is None

    r = client.patch("/auth/me", json={"timezone": "Not/AZone"}, headers=auth(token))
    assert r.status_code == 422
