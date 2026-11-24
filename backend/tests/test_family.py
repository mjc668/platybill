"""Tests for family membership, invites, shared workspace scoping, and permissions."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.core.config import settings
from app.models.family import FamilyInvite
from tests.conftest import auth, register_and_login


def _create_bill(client, token: str, name: str = "Internet") -> int:
    r = client.post(
        "/bills",
        json={
            "name": name,
            "category": "utilities",
            "frequency": "monthly",
            "amount": "80.00",
            "currency": "AUD",
            "due_day": 15,
        },
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_add_new_member_even_when_registration_disabled_and_enforce_scopes(client):
    owner_token = register_and_login(client, "fam-owner@test.com")
    bill_id = _create_bill(client, owner_token, "Family Power")

    # Sync current month so a payment instance exists
    assert (
        client.post("/bills/sync-instances", headers=auth(owner_token)).status_code
        == 204
    )
    payments = client.get("/bills/payments", headers=auth(owner_token)).json()
    assert len(payments) == 1
    inst_id = payments[0]["id"]

    # Even with REGISTRATION_ENABLED=false, owner can add a new family member
    with patch.object(settings, "registration_enabled", False):
        r = client.post(
            "/family/members",
            json={
                "email": "fam-viewer@test.com",
                "initial_password": "memberpass123",  # pragma: allowlist secret
                "scopes": ["bills:read"],
            },
            headers=auth(owner_token),
        )
        assert r.status_code == 201, r.text
        fam = r.json()
        assert fam["is_owner"] is True
        assert len(fam["members"]) == 1
        member_id = fam["members"][0]["id"]

    # Member logs in and can see owner's bills, payments, and stats
    login_r = client.post(
        "/auth/login",
        json={
            "email": "fam-viewer@test.com",
            "password": "memberpass123",  # pragma: allowlist secret
        },
    )
    assert login_r.status_code == 200
    member_token = login_r.cookies["access_token"]

    bills_r = client.get("/bills", headers=auth(member_token))
    assert bills_r.status_code == 200
    assert any(b["id"] == bill_id for b in bills_r.json())

    stats_r = client.get("/stats/overview", headers=auth(member_token))
    assert stats_r.status_code == 200

    # Viewer cannot create bills or mark payments paid
    assert (
        client.post(
            "/bills",
            json={
                "name": "Nope",
                "category": "utilities",
                "frequency": "monthly",
                "amount": "10.00",
                "currency": "AUD",
                "due_day": 1,
            },
            headers=auth(member_token),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/bills/payments/{inst_id}/pay",
            json={},
            headers=auth(member_token),
        ).status_code
        == 403
    )

    # Non-owner cannot add or edit family members
    assert (
        client.post(
            "/family/members",
            json={
                "email": "other@test.com",
                "initial_password": "memberpass123",  # pragma: allowlist secret
                "scopes": ["bills:read"],
            },
            headers=auth(member_token),
        ).status_code
        == 403
    )

    # Owner upgrades member to include payments:write -> now paying succeeds
    upd = client.patch(
        f"/family/members/{member_id}",
        json={"scopes": ["bills:read", "payments:write"]},
        headers=auth(owner_token),
    )
    assert upd.status_code == 200
    pay_r = client.post(
        f"/bills/payments/{inst_id}/pay",
        json={},
        headers=auth(member_token),
    )
    assert pay_r.status_code == 200
    assert pay_r.json()["status"] == "paid"

    # Removing member revokes access to owner's bills
    del_r = client.delete(f"/family/members/{member_id}", headers=auth(owner_token))
    assert del_r.status_code == 204
    after_bills = client.get("/bills", headers=auth(member_token)).json()
    assert after_bills == []


def test_existing_user_invite_flow_and_bill_owner_guard(client_db):
    client, db = client_db
    owner_token = register_and_login(client, "inv-owner@test.com")
    _create_bill(client, owner_token, "Shared Water")

    # Existing user with no bills can be invited and accept
    existing_token = register_and_login(client, "inv-member@test.com")
    r = client.post(
        "/family/members",
        json={"email": "inv-member@test.com", "scopes": ["bills:read"]},
        headers=auth(owner_token),
    )
    assert r.status_code == 201
    assert len(r.json()["outgoing_invites"]) == 1
    invite_id = r.json()["outgoing_invites"][0]["id"]

    # Recipient sees incoming invite
    rec_fam = client.get("/family", headers=auth(existing_token)).json()
    assert len(rec_fam["incoming_invites"]) == 1

    # Accepting grants access
    acc = client.post(
        f"/family/invites/{invite_id}/accept", headers=auth(existing_token)
    )
    assert acc.status_code == 200
    assert len(client.get("/bills", headers=auth(existing_token)).json()) == 1

    # User who already owns bills cannot be invited
    busy_token = register_and_login(client, "busy-owner@test.com")
    _create_bill(client, busy_token, "Own Bill")
    reject_r = client.post(
        "/family/members",
        json={"email": "busy-owner@test.com", "scopes": ["bills:read"]},
        headers=auth(owner_token),
    )
    assert reject_r.status_code == 409

    # Expired invite cannot be accepted
    expired_token = register_and_login(client, "exp-member@test.com")
    inv_r = client.post(
        "/family/members",
        json={"email": "exp-member@test.com", "scopes": ["bills:read"]},
        headers=auth(owner_token),
    )
    exp_id = inv_r.json()["outgoing_invites"][0]["id"]
    inv_row = db.get(FamilyInvite, exp_id)
    assert inv_row is not None
    inv_row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    assert (
        client.post(
            f"/family/invites/{exp_id}/accept", headers=auth(expired_token)
        ).status_code
        == 404
    )
