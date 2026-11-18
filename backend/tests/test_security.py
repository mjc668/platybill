"""Security-hardening tests: rate limits, password policy, token revocation,
JWT claims, and secure cookies."""

import hashlib
from unittest.mock import patch

from app.core.config import settings
from app.core.ratelimit import reset_rate_limits
from app.core.security import decode_token
from app.models.reset_token import PasswordResetToken
from tests.conftest import auth, register_and_login


def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_login_rate_limited_returns_429(client):
    original = settings.login_rate_limit
    try:
        settings.login_rate_limit = 3
        reset_rate_limits("login")
        for _ in range(3):
            r = client.post(
                "/auth/login",
                json={"email": "nobody@test.com", "password": "wrong"},
            )
            assert r.status_code == 401
        r = client.post(
            "/auth/login",
            json={"email": "nobody@test.com", "password": "wrong"},
        )
        assert r.status_code == 429
    finally:
        settings.login_rate_limit = original
        reset_rate_limits()


def test_register_rate_limited_returns_429(client):
    original = settings.register_rate_limit
    try:
        settings.register_rate_limit = 1
        reset_rate_limits("register")
        r = client.post(
            "/auth/register",
            json={"email": "rl1@test.com", "password": "pw123456"},
        )
        assert r.status_code == 201
        r = client.post(
            "/auth/register",
            json={"email": "rl2@test.com", "password": "pw123456"},
        )
        assert r.status_code == 429
    finally:
        settings.register_rate_limit = original
        reset_rate_limits("register")


def test_rate_limit_uses_forwarded_for_when_trusting_proxy(client):
    original_limit = settings.login_rate_limit
    original_account_limit = settings.login_account_rate_limit
    original_proxy = settings.trust_proxy
    try:
        settings.trust_proxy = True
        settings.login_rate_limit = 1
        settings.login_account_rate_limit = 100000
        reset_rate_limits("login")
        r = client.post(
            "/auth/login",
            json={"email": "nobody@test.com", "password": "wrong"},
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert r.status_code == 401
        # Same rightmost entry (the one the trusted proxy appended) → same
        # bucket, even though the attacker-controlled leftmost value differs.
        r = client.post(
            "/auth/login",
            json={"email": "nobody2@test.com", "password": "wrong"},
            headers={"X-Forwarded-For": "9.9.9.9, 1.2.3.4"},
        )
        assert r.status_code == 429
        # A different rightmost entry → its own bucket → not limited yet.
        r = client.post(
            "/auth/login",
            json={"email": "nobody3@test.com", "password": "wrong"},
            headers={"X-Forwarded-For": "1.2.3.4, 5.6.7.8"},
        )
        assert r.status_code == 401
    finally:
        settings.trust_proxy = original_proxy
        settings.login_rate_limit = original_limit
        settings.login_account_rate_limit = original_account_limit
        reset_rate_limits("login")


def test_login_limited_per_account_across_ips(client):
    original_account_limit = settings.login_account_rate_limit
    try:
        settings.login_account_rate_limit = 3
        reset_rate_limits("login")
        for ip in ("1.2.3.4", "5.6.7.8", "9.9.9.9"):
            r = client.post(
                "/auth/login",
                json={"email": "victim@test.com", "password": "wrong"},
                headers={"X-Forwarded-For": ip},
            )
            assert r.status_code == 401
        # Fourth attempt, new IP, same account → 429.
        r = client.post(
            "/auth/login",
            json={"email": "victim@test.com", "password": "wrong"},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert r.status_code == 429
    finally:
        settings.login_account_rate_limit = original_account_limit
        reset_rate_limits("login")


def test_login_account_limit_is_case_insensitive(client):
    original_account_limit = settings.login_account_rate_limit
    try:
        settings.login_account_rate_limit = 1
        reset_rate_limits("login")
        r = client.post(
            "/auth/login",
            json={"email": "Mixed@test.com", "password": "wrong"},
        )
        assert r.status_code == 401
        r = client.post(
            "/auth/login",
            json={"email": "mixed@TEST.com", "password": "wrong"},
        )
        assert r.status_code == 429
    finally:
        settings.login_account_rate_limit = original_account_limit
        reset_rate_limits("login")


def test_send_now_rate_limited_by_user_returns_429(client):
    token = register_and_login(client, "sendnowrl@test.com")
    original = settings.send_now_rate_limit
    try:
        settings.send_now_rate_limit = 1
        reset_rate_limits("send_now")
        # SMTP not configured → 400, but the dependency already counted the request.
        r = client.post("/auth/send-notification-now", headers=auth(token))
        assert r.status_code == 400
        r = client.post("/auth/send-notification-now", headers=auth(token))
        assert r.status_code == 429
    finally:
        settings.send_now_rate_limit = original
        reset_rate_limits("send_now")


# ---------------------------------------------------------------------------
# Cache-Control
# ---------------------------------------------------------------------------


def test_responses_set_no_store_cache_control(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"

    r = client.post(
        "/auth/login",
        json={"email": "nobody@test.com", "password": "wrong"},
    )
    assert r.status_code == 401
    assert r.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------


def test_password_policy_rejects_common_password(client):
    r = client.post(
        "/auth/register",
        json={"email": "common@test.com", "password": "password"},
    )
    assert r.status_code == 422


def test_password_policy_rejects_short_password(client):
    r = client.post(
        "/auth/register",
        json={"email": "short@test.com", "password": "short"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Token versioning / revocation
# ---------------------------------------------------------------------------


def test_change_password_revokes_old_token(client):
    token = register_and_login(client, "chpwr@test.com")
    r = client.get("/auth/me", headers=auth(token))
    assert r.status_code == 200

    r = client.patch(
        "/auth/change-password",
        json={"current_password": "pw123456", "new_password": "newpassword1"},
        headers=auth(token),
    )
    assert r.status_code == 200

    r = client.get("/auth/me", headers=auth(token))
    assert r.status_code == 401

    login_r = client.post(
        "/auth/login",
        json={"email": "chpwr@test.com", "password": "newpassword1"},
    )
    assert login_r.status_code == 200


def test_logout_revokes_token(client):
    token = register_and_login(client, "logoutrev@test.com")
    r = client.post("/auth/logout", headers=auth(token))
    assert r.status_code == 204

    r = client.get("/auth/me", headers=auth(token))
    assert r.status_code == 401


def test_logout_with_invalid_token_clears_cookies(client):
    """Logout must succeed even when the token is dead (backward-compat with
    pre-v1.0.9 cookies that fail the issuer/audience checks), so the client
    can always clear the stale HttpOnly cookie and break the redirect loop."""
    r = client.post(
        "/auth/logout", headers=auth("eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjF9.garbage")
    )
    assert r.status_code == 204
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "access_token=" in set_cookie
    assert "auth_logged_in=" in set_cookie
    assert "max-age=0" in set_cookie or "expires=thu, 01 jan 1970" in set_cookie


def test_reset_password_revokes_old_token(client_db):
    client, db = client_db
    token = register_and_login(client, "resetrev@example.com")

    with patch("app.routers.auth.send_password_reset_email"):
        client.post("/auth/forgot-password", json={"email": "resetrev@example.com"})

    known_raw = "known-raw-token-for-testing-12345"
    row = db.query(PasswordResetToken).one()
    row.token_hash = _token_hash(known_raw)
    db.commit()

    r = client.post(
        "/auth/reset-password",
        json={"token": known_raw, "new_password": "newpassword1"},
    )
    assert r.status_code == 200


def test_rate_limit_ignores_x_real_ip_when_trust_proxy_false(client):
    from types import SimpleNamespace
    from app.core.ratelimit import client_ip

    original_proxy = settings.trust_proxy
    try:
        settings.trust_proxy = False
        req = SimpleNamespace(
            headers={"x-real-ip": "9.9.9.9", "x-forwarded-for": "8.8.8.8"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        assert client_ip(req) == "127.0.0.1"  # type: ignore[arg-type]
    finally:
        settings.trust_proxy = original_proxy


def test_registration_disabled_blocks_register_and_reports_status(client):
    original = settings.registration_enabled
    try:
        settings.registration_enabled = False
        status_r = client.get("/auth/registration-status")
        assert status_r.status_code == 200
        assert status_r.json() == {"enabled": False}

        reg_r = client.post(
            "/auth/register",
            json={"email": "blocked@test.com", "password": "pw123456"},
        )
        assert reg_r.status_code == 403
    finally:
        settings.registration_enabled = original
        r_enabled = client.get("/auth/registration-status")
        assert r_enabled.status_code == 200
        assert r_enabled.json() == {"enabled": True}

    r = client.get("/auth/me", headers=auth(token))
    assert r.status_code == 401

    login_r = client.post(
        "/auth/login",
        json={"email": "resetrev@example.com", "password": "newpassword1"},
    )
    assert login_r.status_code == 200


# ---------------------------------------------------------------------------
# JWT claims & cookies
# ---------------------------------------------------------------------------


def test_jwt_contains_security_claims(client):
    r = client.post(
        "/auth/register",
        json={"email": "claims@test.com", "password": "pw123456"},
    )
    assert r.status_code == 201
    assert "access_token" not in r.json()
    payload = decode_token(r.cookies["access_token"])
    assert payload["iss"] == "platybill-backend"
    assert payload["aud"] == "platybill"
    assert payload["iat"]
    assert payload["exp"]
    assert payload["jti"]
    assert payload["tv"] == 0


def test_secure_cookie_set_when_enabled(client):
    original = settings.cookie_secure
    try:
        settings.cookie_secure = True
        r = client.post(
            "/auth/register",
            json={"email": "secure@test.com", "password": "pw123456"},
        )
        assert r.status_code == 201
        assert "secure" in r.headers.get("set-cookie", "").lower()
    finally:
        settings.cookie_secure = original


def test_register_does_not_return_token_in_body(client):
    r = client.post(
        "/auth/register",
        json={"email": "notoken@test.com", "password": "pw123456"},
    )
    assert r.status_code == 201
    assert r.json() == {"message": "Account created."}
    assert "access_token" in r.cookies


def test_login_does_not_return_token_in_body(client):
    register_and_login(client, "notokenlogin@test.com")
    r = client.post(
        "/auth/login",
        json={"email": "notokenlogin@test.com", "password": "pw123456"},
    )
    assert r.status_code == 200
    assert r.json() == {"message": "Logged in."}
    assert "access_token" in r.cookies


# ---------------------------------------------------------------------------
# bcrypt 72-byte limit
# ---------------------------------------------------------------------------


def test_register_password_over_72_bytes_returns_422(client):
    r = client.post(
        "/auth/register",
        json={"email": "longpw@test.com", "password": "a" * 73},
    )
    assert r.status_code == 422


def test_change_password_over_72_bytes_returns_422(client):
    token = register_and_login(client, "longpwchange@test.com")
    r = client.patch(
        "/auth/change-password",
        json={"current_password": "pw123456", "new_password": "a" * 73},
        headers=auth(token),
    )
    assert r.status_code == 422


def test_login_with_over_72_byte_password_returns_401(client):
    register_and_login(client, "longpwlogin@test.com")
    r = client.post(
        "/auth/login",
        json={"email": "longpwlogin@test.com", "password": "a" * 73},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Reset-token lifecycle
# ---------------------------------------------------------------------------


def test_change_password_deletes_outstanding_reset_tokens(client_db):
    client, db = client_db
    token = register_and_login(client, "pwresetkill@test.com")

    with patch("app.routers.auth.send_password_reset_email"):
        client.post("/auth/forgot-password", json={"email": "pwresetkill@test.com"})
    assert db.query(PasswordResetToken).count() == 1

    r = client.patch(
        "/auth/change-password",
        json={"current_password": "pw123456", "new_password": "newpassword1"},
        headers=auth(token),
    )
    assert r.status_code == 200

    db.expire_all()
    assert db.query(PasswordResetToken).count() == 0


def test_change_email_deletes_outstanding_reset_tokens(client_db):
    client, db = client_db
    token = register_and_login(client, "emailresetkill@test.com")

    with patch("app.routers.auth.send_password_reset_email"):
        client.post("/auth/forgot-password", json={"email": "emailresetkill@test.com"})
    assert db.query(PasswordResetToken).count() == 1

    r = client.patch(
        "/auth/change-email",
        json={
            "new_email": "emailresetkill2@test.com",
            "current_password": "pw123456",
        },
        headers=auth(token),
    )
    assert r.status_code == 200

    db.expire_all()
    assert db.query(PasswordResetToken).count() == 0


def test_reset_token_stolen_and_still_usable_after_failed_change(client_db):
    """A reset link stays valid after a failed change-password attempt."""
    client, db = client_db
    token = register_and_login(client, "pwresetstay@example.com")

    with patch("app.routers.auth.send_password_reset_email"):
        client.post("/auth/forgot-password", json={"email": "pwresetstay@example.com"})

    known_raw = "reset-token-lifecycle-1234567890"
    row = db.query(PasswordResetToken).one()
    row.token_hash = _token_hash(known_raw)
    db.commit()

    # Wrong current password → 401; the reset token must survive.
    r = client.patch(
        "/auth/change-password",
        json={"current_password": "wrong", "new_password": "newpassword1"},
        headers=auth(token),
    )
    assert r.status_code == 401
    db.expire_all()
    assert db.query(PasswordResetToken).count() == 1

    r = client.post(
        "/auth/reset-password",
        json={"token": known_raw, "new_password": "newpassword1"},
    )
    assert r.status_code == 200


def test_rate_limit_ignores_x_real_ip_when_trust_proxy_false(client):
    from types import SimpleNamespace
    from app.core.ratelimit import client_ip

    original_proxy = settings.trust_proxy
    try:
        settings.trust_proxy = False
        req = SimpleNamespace(
            headers={"x-real-ip": "9.9.9.9", "x-forwarded-for": "8.8.8.8"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        assert client_ip(req) == "127.0.0.1"  # type: ignore[arg-type]
    finally:
        settings.trust_proxy = original_proxy


def test_registration_disabled_blocks_register_and_reports_status(client):
    original = settings.registration_enabled
    try:
        settings.registration_enabled = False
        status_r = client.get("/auth/registration-status")
        assert status_r.status_code == 200
        assert status_r.json() == {"enabled": False}

        reg_r = client.post(
            "/auth/register",
            json={"email": "blocked@test.com", "password": "pw123456"},
        )
        assert reg_r.status_code == 403
    finally:
        settings.registration_enabled = original
        r_enabled = client.get("/auth/registration-status")
        assert r_enabled.status_code == 200
        assert r_enabled.json() == {"enabled": True}
