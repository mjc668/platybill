"""Tests for Passkey (WebAuthn) authentication, endpoints, and session persistence."""

from types import SimpleNamespace
from unittest.mock import patch
import pytest

from app.models.passkey import Passkey
from app.models.user import User
from app.services.passkeys import (
    ChallengeCache,
    resolve_rp_id,
    resolve_expected_origins,
)
from tests.conftest import auth, register_and_login

_PASSWORD = "pw123456"


def test_challenge_cache_ttl_and_expiry():
    cache = ChallengeCache(default_ttl=1)
    key = cache.save(b"challenge-data", user_id=42)
    entry = cache.pop(key)
    assert entry is not None
    assert entry.challenge == b"challenge-data"
    assert entry.user_id == 42
    # Pop should remove it
    assert cache.pop(key) is None

    # Expired entry
    cache._default_ttl = -1
    expired_key = cache.save(b"expired-challenge", user_id=42)
    assert cache.pop(expired_key) is None


def test_resolve_rp_id_and_origins():
    req = SimpleNamespace(
        headers={
            "host": "my-platybill.domain.local:3010",
            "origin": "https://my-platybill.domain.local:3010",
        },
        base_url="http://my-platybill.domain.local:3010/",
        url=SimpleNamespace(
            scheme="http", hostname="my-platybill.domain.local", port=3010
        ),
    )
    rp_id = resolve_rp_id(req)  # type: ignore
    assert rp_id == "my-platybill.domain.local"

    origins = resolve_expected_origins(req)  # type: ignore
    assert "https://my-platybill.domain.local:3010" in origins
    assert "http://my-platybill.domain.local:3010" in origins


def test_passkey_routes_unauthenticated_return_401(client):
    assert client.get("/auth/passkeys").status_code == 401
    assert client.post("/auth/passkeys/register/options").status_code == 401
    assert client.post("/auth/passkeys/register/verify", json={}).status_code == 401
    assert client.delete("/auth/passkeys/1").status_code == 401


def test_register_options_returns_valid_webauthn_options(client):
    token = register_and_login(client, "passkey-reg@test.com", _PASSWORD)
    r = client.post("/auth/passkeys/register/options", headers=auth(token))
    assert r.status_code == 200
    data = r.json()
    assert "options" in data
    opts = data["options"]
    assert "challenge" in opts
    assert "rp" in opts
    assert opts["rp"]["name"] == "Platybill"
    assert "user" in opts
    assert opts["user"]["name"] == "passkey-reg@test.com"
    assert "pubKeyCredParams" in opts


def test_list_passkeys_empty_by_default(client):
    token = register_and_login(client, "empty-pk@test.com", _PASSWORD)
    r = client.get("/auth/passkeys", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == []


def test_register_verify_and_list_passkeys(client):
    token = register_and_login(client, "verify-pk@test.com", _PASSWORD)

    with patch(
        "app.routers.passkeys.verify_registration_credential",
        return_value=(
            "cred-id-abc-123",
            b"pubkey-bytes",
            0,
            "00000000-0000-0000-0000-000000000000",
            "[]",
        ),
    ):
        r = client.post(
            "/auth/passkeys/register/verify",
            headers=auth(token),
            json={
                "name": "My Pixel Phone",
                "response": {
                    "id": "cred-id-abc-123",
                    "rawId": "cred-id-abc-123",
                    "response": {},
                    "type": "public-key",
                },
            },
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "My Pixel Phone"
        assert "id" in data
        pk_id = data["id"]

    # Listing should show the new passkey
    r = client.get("/auth/passkeys", headers=auth(token))
    assert r.status_code == 200
    passkeys = r.json()
    assert len(passkeys) == 1
    assert passkeys[0]["id"] == pk_id
    assert passkeys[0]["name"] == "My Pixel Phone"
    assert passkeys[0]["last_used_at"] is None

    # Registering the same credential again should return 409 Conflict
    with patch(
        "app.routers.passkeys.verify_registration_credential",
        return_value=(
            "cred-id-abc-123",
            b"pubkey-bytes",
            0,
            "00000000-0000-0000-0000-000000000000",
            "[]",
        ),
    ):
        dup_res = client.post(
            "/auth/passkeys/register/verify",
            headers=auth(token),
            json={
                "name": "Duplicate Key",
                "response": {"id": "cred-id-abc-123"},
            },
        )
        assert dup_res.status_code == 409


def test_delete_passkey(client):
    token = register_and_login(client, "del-pk@test.com", _PASSWORD)

    with patch(
        "app.routers.passkeys.verify_registration_credential",
        return_value=(
            "cred-to-delete",
            b"pubkey-bytes",
            0,
            "00000000-0000-0000-0000-000000000000",
            "[]",
        ),
    ):
        r = client.post(
            "/auth/passkeys/register/verify",
            headers=auth(token),
            json={
                "name": "Temp Key",
                "response": {"id": "cred-to-delete"},
            },
        )
        assert r.status_code == 201
        pk_id = r.json()["id"]

    # Delete
    del_res = client.delete(f"/auth/passkeys/{pk_id}", headers=auth(token))
    assert del_res.status_code == 200

    # Now empty
    r = client.get("/auth/passkeys", headers=auth(token))
    assert r.json() == []

    # Deleting again returns 404
    assert (
        client.delete(f"/auth/passkeys/{pk_id}", headers=auth(token)).status_code == 404
    )


def test_cannot_delete_another_users_passkey(client):
    token_a = register_and_login(client, "user-a-pk@test.com", _PASSWORD)
    token_b = register_and_login(client, "user-b-pk@test.com", _PASSWORD)

    with patch(
        "app.routers.passkeys.verify_registration_credential",
        return_value=(
            "cred-user-a",
            b"pubkey-bytes",
            0,
            "00000000-0000-0000-0000-000000000000",
            "[]",
        ),
    ):
        r = client.post(
            "/auth/passkeys/register/verify",
            headers=auth(token_a),
            json={
                "name": "A Key",
                "response": {"id": "cred-user-a"},
            },
        )
        assert r.status_code == 201
        pk_id = r.json()["id"]

    # User B attempts to delete User A's passkey
    del_res = client.delete(f"/auth/passkeys/{pk_id}", headers=auth(token_b))
    assert del_res.status_code == 404


def test_passkey_login_flow(client):
    token = register_and_login(client, "login-pk@test.com", _PASSWORD)

    with patch(
        "app.routers.passkeys.verify_registration_credential",
        return_value=(
            "login-cred-123",
            b"pubkey-bytes",
            0,
            "00000000-0000-0000-0000-000000000000",
            "[]",
        ),
    ):
        client.post(
            "/auth/passkeys/register/verify",
            headers=auth(token),
            json={
                "name": "Login Key",
                "response": {"id": "login-cred-123"},
            },
        )

    # 1. Fetch login options
    opt_res = client.post("/auth/passkeys/login/options")
    assert opt_res.status_code == 200
    assert "options" in opt_res.json()

    # 2. Verify login with unknown credential ID -> 401
    bad_res = client.post(
        "/auth/passkeys/login/verify",
        json={"remember_me": False, "response": {"id": "unknown-cred-id"}},
    )
    assert bad_res.status_code == 401

    # 3. Verify login successfully
    with patch("app.routers.passkeys.verify_login_credential", return_value=1):
        verify_res = client.post(
            "/auth/passkeys/login/verify",
            json={
                "remember_me": True,
                "response": {"id": "login-cred-123"},
            },
        )
        assert verify_res.status_code == 200
        assert verify_res.json()["message"] == "Signed in successfully with Passkey."
        assert "access_token" in verify_res.cookies
        assert "auth_logged_in" in verify_res.cookies


def test_login_remember_me_cookie_persistence(client):
    register_and_login(client, "remember@test.com", _PASSWORD)

    res_short = client.post(
        "/auth/login",
        json={
            "email": "remember@test.com",
            "password": _PASSWORD,
            "remember_me": False,
        },
    )
    assert res_short.status_code == 200

    res_long = client.post(
        "/auth/login",
        json={"email": "remember@test.com", "password": _PASSWORD, "remember_me": True},
    )
    assert res_long.status_code == 200
    cookie_header_long = res_long.headers.get("set-cookie", "")

    # 30 days is 2,592,000 seconds
    assert "Max-Age=2592000" in cookie_header_long
