"""Tests for scoped API keys, intersection with family scopes, and security boundaries."""

from datetime import datetime, timedelta, timezone

from app.models.api_key import ApiKey
from tests.conftest import auth, register_and_login


def _create_bill(client, token: str, name: str = "Agent Bill") -> int:
    r = client.post(
        "/bills",
        json={
            "name": name,
            "category": "utilities",
            "frequency": "monthly",
            "amount": "45.00",
            "currency": "AUD",
            "due_day": 10,
        },
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_api_key_lifecycle_headers_and_scope_enforcement(client_db):
    client, db = client_db
    token = register_and_login(client, "agent-owner@test.com")
    _create_bill(client, token, "Electricity")

    # Mint read-only API key
    r = client.post(
        "/auth/api-keys",
        json={"name": "Read Agent", "scopes": ["bills:read"], "expires_in_days": 30},
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    created = r.json()
    raw_key = created["key"]
    assert raw_key.startswith("pb_live_")
    key_id = created["id"]

    # Listing keys never leaks the raw secret or hash
    list_r = client.get("/auth/api-keys", headers=auth(token))
    assert list_r.status_code == 200
    assert len(list_r.json()) == 1
    assert "key" not in list_r.json()[0]
    assert "key_hash" not in list_r.json()[0]
    assert list_r.json()[0]["key_prefix"] == raw_key[:16]

    # Works via Authorization: Bearer and X-API-Key
    assert client.get("/bills", headers=auth(raw_key)).status_code == 200
    assert client.get("/bills", headers={"X-API-Key": raw_key}).status_code == 200
    assert client.get("/stats/overview", headers=auth(raw_key)).status_code == 200

    # Read-only key cannot write bills
    assert (
        client.post(
            "/bills",
            json={
                "name": "Blocked",
                "category": "utilities",
                "frequency": "monthly",
                "amount": "10.00",
                "currency": "AUD",
                "due_day": 1,
            },
            headers=auth(raw_key),
        ).status_code
        == 403
    )

    # API key cannot access sensitive account/security/family/key/global-settings routes
    for method, path in (
        ("GET", "/auth/api-keys"),
        ("POST", "/auth/api-keys"),
        ("GET", "/family"),
        ("PATCH", "/auth/change-password"),
        ("PATCH", "/auth/change-email"),
        ("DELETE", "/auth/users/me"),
        ("GET", "/auth/passkeys"),
        ("GET", "/notifications/settings"),
        ("GET", "/import/status"),
    ):
        resp = client.request(method, path, headers=auth(raw_key), json={})
        assert resp.status_code == 403, f"{method} {path} returned {resp.status_code}"

    # Expired key returns 401
    key_row = db.get(ApiKey, key_id)
    assert key_row is not None
    key_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert client.get("/bills", headers=auth(raw_key)).status_code == 401

    # Revoking/deleting removes key
    assert (
        client.delete(f"/auth/api-keys/{key_id}", headers=auth(token)).status_code
        == 204
    )
    assert client.get("/bills", headers=auth(raw_key)).status_code == 401


def test_family_member_api_key_intersects_with_family_scopes(client):
    owner_token = register_and_login(client, "fam-key-owner@test.com")
    _create_bill(client, owner_token, "Shared Gas")

    fam_r = client.post(
        "/family/members",
        json={
            "email": "fam-key-member@test.com",
            "initial_password": "memberpass123",  # pragma: allowlist secret
            "scopes": ["bills:read", "bills:write"],
        },
        headers=auth(owner_token),
    )
    assert fam_r.status_code == 201
    member_id = fam_r.json()["members"][0]["id"]

    member_login = client.post(
        "/auth/login",
        json={
            "email": "fam-key-member@test.com",
            "password": "memberpass123",  # pragma: allowlist secret
        },
    )
    member_token = member_login.cookies["access_token"]

    # Member cannot mint an API key with payments:write (which they don't hold)
    bad_key = client.post(
        "/auth/api-keys",
        json={"name": "Too Broad", "scopes": ["bills:read", "payments:write"]},
        headers=auth(member_token),
    )
    assert bad_key.status_code == 403

    # Member mints a bills:read + bills:write key
    good_key_r = client.post(
        "/auth/api-keys",
        json={"name": "Member Agent", "scopes": ["bills:read", "bills:write"]},
        headers=auth(member_token),
    )
    assert good_key_r.status_code == 201
    member_key = good_key_r.json()["key"]

    # Owner narrows member's family scopes to bills:read only
    assert (
        client.patch(
            f"/family/members/{member_id}",
            json={"scopes": ["bills:read"]},
            headers=auth(owner_token),
        ).status_code
        == 200
    )

    # Member's existing API key can still read, but is now blocked from writing
    assert client.get("/bills", headers=auth(member_key)).status_code == 200
    assert (
        client.post(
            "/bills",
            json={
                "name": "Now Blocked",
                "category": "utilities",
                "frequency": "monthly",
                "amount": "20.00",
                "currency": "AUD",
                "due_day": 5,
            },
            headers=auth(member_key),
        ).status_code
        == 403
    )
