"""One-off bills are single known charges: never usage-based or estimated."""

from datetime import datetime, timezone

from tests.conftest import auth, register_and_login, sync_payments

_BILL = {
    "name": "Registration",
    "category": "utilities",
    "frequency": "one_off",
    "amount": "42.00",
    "currency": "PLN",
    "due_day": 20,
    "notes": None,
    "is_paused": False,
}


def _today_utc():
    return datetime.now(timezone.utc).date()


def test_create_one_off_ignores_amount_varies(client_db):
    client, _ = client_db
    token = register_and_login(client, "oneoff1@test.com")

    r = client.post(
        "/bills", json={**_BILL, "amount_varies": True}, headers=auth(token)
    )
    assert r.status_code == 201, r.text
    assert r.json()["amount_varies"] is False


def test_update_one_off_forces_amount_varies_off(client_db):
    client, _ = client_db
    token = register_and_login(client, "oneoff2@test.com")
    bill_id = client.post("/bills", json=_BILL, headers=auth(token)).json()["id"]

    r = client.patch(
        f"/bills/{bill_id}", json={"amount_varies": True}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["amount_varies"] is False


def test_one_off_instance_is_visible_immediately(client_db):
    """A one-off one for the current month syncs a real, listed instance."""
    client, _ = client_db
    token = register_and_login(client, "oneoff3@test.com")
    today = _today_utc()

    r = client.post(
        "/bills",
        json={**_BILL, "due_day": today.day, "amount_varies": True},
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    bill_id = r.json()["id"]

    sync_payments(client, token)

    listed = client.get("/bills/payments", headers=auth(token)).json()
    mine = [i for i in listed if i["bill_id"] == bill_id]
    assert len(mine) == 1
    assert mine[0]["amount_estimated"] is False
    assert mine[0]["amount"] == "42.00"

    # It is a plain ledger row — never part of the confirmation queue.
    queue = client.get("/bills/payments/needs-confirmation", headers=auth(token)).json()
    assert queue == []
