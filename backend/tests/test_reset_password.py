"""Integration tests for forgot-password / reset-password / smtp-status endpoints."""

import hashlib
import smtplib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.reset_token import PasswordResetToken
from tests.conftest import auth, register_and_login


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# smtp-status
# ---------------------------------------------------------------------------


def test_smtp_status_unconfigured(client_db):
    client, _ = client_db
    with (
        patch("app.services.app_settings.get_value", return_value=None),
        patch("app.routers.auth.settings") as mock_settings,
    ):
        mock_settings.smtp_host = None
        r = client.get("/auth/smtp-status")
    assert r.status_code == 200
    assert r.json() == {"configured": False}


def test_smtp_status_configured(client_db):
    client, _ = client_db
    with patch(
        "app.services.app_settings.get_value",
        side_effect=lambda db, key: "smtp.example.com" if key == "smtp.host" else None,
    ):
        r = client.get("/auth/smtp-status")
    assert r.status_code == 200
    assert r.json() == {"configured": True}


# ---------------------------------------------------------------------------
# forgot-password
# ---------------------------------------------------------------------------


def test_forgot_password_unknown_email_returns_200(client_db):
    client, _ = client_db
    r = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200
    assert "reset link" in r.json()["message"]


def test_forgot_password_creates_token_row(client_db):
    client, db = client_db
    register_and_login(client, "user@example.com")

    with patch("app.routers.auth.send_password_reset_email"):
        r = client.post("/auth/forgot-password", json={"email": "user@example.com"})

    assert r.status_code == 200
    rows = db.query(PasswordResetToken).all()
    assert len(rows) == 1


def test_forgot_password_replaces_old_token(client_db):
    client, db = client_db
    register_and_login(client, "user2@example.com")

    with patch("app.routers.auth.send_password_reset_email"):
        client.post("/auth/forgot-password", json={"email": "user2@example.com"})
        first_hash = db.query(PasswordResetToken).one().token_hash

        client.post("/auth/forgot-password", json={"email": "user2@example.com"})

    rows = db.query(PasswordResetToken).all()
    assert len(rows) == 1
    assert rows[0].token_hash != first_hash


def test_forgot_password_reset_link_uses_url_fragment(client_db):
    """The raw token travels in the fragment, never the query string."""
    client, db = client_db
    register_and_login(client, "fragment@example.com")

    with (
        patch("app.routers.auth.settings") as mock_settings,
        patch("app.routers.auth.send_password_reset_email") as mock_send,
        patch("app.services.app_settings.smtp_configured", return_value=True),
        patch(
            "app.services.app_settings.smtp_kwargs",
            return_value={
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": None,
                "smtp_password": None,
                "smtp_use_tls": True,
                "from_addr": "",
            },
        ),
    ):
        mock_settings.app_base_url = "http://localhost:3010"
        mock_settings.password_reset_token_expire_minutes = 60

        r = client.post("/auth/forgot-password", json={"email": "fragment@example.com"})

    assert r.status_code == 200
    reset_url = mock_send.call_args.kwargs["reset_url"]
    assert reset_url.startswith("http://localhost:3010/reset-password#token=")
    assert "?token=" not in reset_url

    # The fragment token is the same one stored (hashed) for the reset call.
    raw_token = reset_url.split("#token=", 1)[1]
    assert db.query(PasswordResetToken).one().token_hash == _token_hash(raw_token)


# ---------------------------------------------------------------------------
# reset-password
# ---------------------------------------------------------------------------


def test_reset_password_success(client_db):
    client, db = client_db
    register_and_login(client, "reset@example.com")

    with patch("app.routers.auth.send_password_reset_email"):
        client.post("/auth/forgot-password", json={"email": "reset@example.com"})

    row = db.query(PasswordResetToken).one()
    # Reconstruct a valid raw token by brute-forcing is not possible; instead
    # insert a known token directly and call reset with it.
    known_raw = "known-raw-token-for-testing-12345"
    row.token_hash = _token_hash(known_raw)
    db.commit()

    r = client.post(
        "/auth/reset-password",
        json={"token": known_raw, "new_password": "newpassword1"},
    )
    assert r.status_code == 200

    # Token row is deleted after use.
    db.expire_all()
    assert db.query(PasswordResetToken).count() == 0

    # Login with new password succeeds.
    login_r = client.post(
        "/auth/login", json={"email": "reset@example.com", "password": "newpassword1"}
    )
    assert login_r.status_code == 200


def test_reset_password_invalid_token_returns_400(client_db):
    client, _ = client_db
    r = client.post(
        "/auth/reset-password",
        json={"token": "completely-bogus-token", "new_password": "newpassword1"},
    )
    assert r.status_code == 400


def test_reset_password_expired_token_returns_400(client_db):
    client, db = client_db
    register_and_login(client, "expired@example.com")

    with patch("app.routers.auth.send_password_reset_email"):
        client.post("/auth/forgot-password", json={"email": "expired@example.com"})

    known_raw = "expired-raw-token-for-testing-99"
    row = db.query(PasswordResetToken).one()
    row.token_hash = _token_hash(known_raw)
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()

    r = client.post(
        "/auth/reset-password",
        json={"token": known_raw, "new_password": "newpassword1"},
    )
    assert r.status_code == 400
    assert "expired" in r.json()["detail"].lower()


def test_reset_password_too_short_returns_400(client_db):
    client, db = client_db
    register_and_login(client, "short@example.com")

    known_raw = "short-password-test-token-99999"
    db.add(
        PasswordResetToken(
            user_id=db.execute(
                __import__("sqlalchemy").text(
                    "SELECT id FROM users WHERE email='short@example.com'"
                )
            ).scalar(),
            token_hash=_token_hash(known_raw),
            expires_at=None,
        )
    )
    db.commit()

    r = client.post(
        "/auth/reset-password",
        json={"token": known_raw, "new_password": "short"},
    )
    assert r.status_code == 400
    assert "8" in r.json()["detail"]


def test_reset_password_over_72_bytes_returns_422(client_db):
    client, _ = client_db
    r = client.post(
        "/auth/reset-password",
        json={"token": "any-token", "new_password": "a" * 73},
    )
    assert r.status_code == 422


def test_reset_password_replay_after_consumption_returns_400_not_500(client_db):
    """A consumed token (e.g. lost race) is rejected cleanly, never a 500."""
    client, db = client_db
    register_and_login(client, "replay@example.com")

    known_raw = "replay-raw-token-for-testing-123456"
    db.add(
        PasswordResetToken(
            user_id=db.execute(
                __import__("sqlalchemy").text(
                    "SELECT id FROM users WHERE email='replay@example.com'"
                )
            ).scalar(),
            token_hash=_token_hash(known_raw),
            expires_at=None,
        )
    )
    db.commit()

    first = client.post(
        "/auth/reset-password",
        json={"token": known_raw, "new_password": "newpassword1"},
    )
    assert first.status_code == 200

    replay = client.post(
        "/auth/reset-password",
        json={"token": known_raw, "new_password": "anotherpassword1"},
    )
    assert replay.status_code == 400
    assert "invalid" in replay.json()["detail"].lower()


def test_reset_password_token_is_single_use(client_db):
    client, db = client_db
    register_and_login(client, "singleuse@example.com")

    with patch("app.routers.auth.send_password_reset_email"):
        client.post("/auth/forgot-password", json={"email": "singleuse@example.com"})

    known_raw = "single-use-raw-token-for-testing"
    row = db.query(PasswordResetToken).one()
    row.token_hash = _token_hash(known_raw)
    db.commit()

    first = client.post(
        "/auth/reset-password",
        json={"token": known_raw, "new_password": "newpassword1"},
    )
    assert first.status_code == 200

    second = client.post(
        "/auth/reset-password",
        json={"token": known_raw, "new_password": "anotherpassword1"},
    )
    assert second.status_code == 400


def test_forgot_password_smtp_failure_still_returns_200(
    client_db: tuple[TestClient, Session],
) -> None:
    """SMTP exception must not propagate — enumeration guarantee must hold."""
    client, db = client_db
    register_and_login(client, "smtpfail@example.com", "pw-smtp-fail-1")

    with (
        patch("app.routers.auth.settings") as mock_settings,
        patch(
            "app.routers.auth.send_password_reset_email",
            side_effect=smtplib.SMTPException("connection refused"),
        ),
    ):
        mock_settings.smtp_host = "smtp.example.com"
        mock_settings.smtp_port = 587
        mock_settings.smtp_user = None
        mock_settings.smtp_password = None
        mock_settings.smtp_use_tls = True
        mock_settings.reminder_from = ""
        mock_settings.app_base_url = "http://localhost:3010"
        mock_settings.password_reset_token_expire_minutes = 60

        resp = client.post(
            "/auth/forgot-password", json={"email": "smtpfail@example.com"}
        )

    assert resp.status_code == 200
    assert "reset link" in resp.json()["message"].lower()
