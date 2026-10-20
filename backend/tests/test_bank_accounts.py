"""Integration tests for /bank-accounts and bill preferred_account wiring."""

from tests.conftest import auth, register_and_login

_BILL = {
    "name": "Electricity",
    "category": "utilities",
    "frequency": "monthly",
    "amount": "100.00",
    "currency": "PLN",
    "due_day": 15,
    "is_paused": False,
}


def _accounts(client, token, query: str = "") -> list[dict]:
    r = client.get(f"/bank-accounts{query}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _create(client, token, **body) -> dict:
    r = client.post("/bank-accounts", json=body, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _bill(client, token, **overrides) -> dict:
    body = {**_BILL, **overrides}
    r = client.post("/bills", json=body, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def test_crud_and_archived_filtering(client):
    token = register_and_login(client, "bank_crud@test.com")
    assert _accounts(client, token) == []

    acc = _create(client, token, name="Checking", iban="DE89 1234", note="main")
    assert acc["name"] == "Checking"
    assert acc["iban"] == "DE89 1234"
    assert acc["is_archived"] is False

    # Duplicate names rejected case-insensitively.
    r = client.post("/bank-accounts", json={"name": "  checking "}, headers=auth(token))
    assert r.status_code == 409, r.text

    r = client.patch(
        f"/bank-accounts/{acc['id']}",
        json={"name": "Everyday", "is_archived": True},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Everyday"

    assert _accounts(client, token) == []
    archived = _accounts(client, token, "?include_archived=true")
    assert [a["id"] for a in archived] == [acc["id"]]


def test_scoped_per_user(client):
    t1 = register_and_login(client, "bank_user1@test.com")
    t2 = register_and_login(client, "bank_user2@test.com")
    acc = _create(client, t1, name="Mine")

    r = client.get(f"/bank-accounts/{acc['id']}", headers=auth(t2))
    assert r.status_code in (404, 405)
    r = client.patch(
        f"/bank-accounts/{acc['id']}", json={"name": "Theirs"}, headers=auth(t2)
    )
    assert r.status_code == 404, r.text
    r = client.delete(f"/bank-accounts/{acc['id']}", headers=auth(t2))
    assert r.status_code == 404, r.text


def test_bill_preferred_account_flows_to_payments(client):
    token = register_and_login(client, "bank_bill@test.com")
    acc = _create(client, token, name="Checking")

    bill = _bill(client, token, preferred_account_id=acc["id"])
    assert bill["preferred_account"]["id"] == acc["id"]
    assert bill["preferred_account"]["name"] == "Checking"

    # Foreign account rejected; archived account rejected on create.
    other = register_and_login(client, "bank_other@test.com")
    other_acc = _create(client, other, name="Theirs")
    r = client.post(
        "/bills",
        json={**_BILL, "preferred_account_id": other_acc["id"]},
        headers=auth(token),
    )
    assert r.status_code == 404, r.text

    r = client.patch(
        f"/bank-accounts/{acc['id']}",
        json={"is_archived": True},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/bills",
        json={**_BILL, "preferred_account_id": acc["id"]},
        headers=auth(token),
    )
    assert r.status_code == 422, r.text

    # Existing bill keeps working: rename relabels it live; update can clear.
    fresh = register_and_login(client, "bank_live@test.com")
    live = _create(client, fresh, name="Old Name")
    b = _bill(client, fresh, preferred_account_id=live["id"])
    r = client.patch(
        f"/bank-accounts/{live['id']}",
        json={"name": "New Name"},
        headers=auth(fresh),
    )
    assert r.json()["name"] == "New Name"
    r = client.patch(
        f"/bills/{b['id']}",
        json={"preferred_account_id": None},
        headers=auth(fresh),
    )
    assert r.status_code == 200, r.text
    assert r.json()["preferred_account"] is None


def test_delete_refused_while_in_use(client):
    token = register_and_login(client, "bank_inuse@test.com")
    acc = _create(client, token, name="Checking")
    _bill(client, token, preferred_account_id=acc["id"])

    r = client.delete(f"/bank-accounts/{acc['id']}", headers=auth(token))
    assert r.status_code == 400, r.text

    r = client.patch(
        f"/bank-accounts/{acc['id']}",
        json={"is_archived": True},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text


def test_backup_round_trip_preserves_account(client):
    token = register_and_login(client, "bank_backup@test.com")
    acc = _create(client, token, name="Checking")
    _bill(client, token, preferred_account_id=acc["id"])

    r = client.get("/export/json", headers=auth(token))
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["bill_templates"][0]["bank_account"] == "Checking"

    r = client.post(
        "/export/restore",
        files={"file": ("backup.json", r.content, "application/json")},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    bills = client.get("/bills", headers=auth(token)).json()
    assert bills[0]["preferred_account"]["name"] == "Checking"
