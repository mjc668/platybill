"""GET /bills next-due fields: earliest unpaid instance per template."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from tests.conftest import auth, register_and_login, sync_payments

_BILL = {
    "name": "Internet",
    "category": "utilities",
    "frequency": "monthly",
    "amount": "120.00",
    "currency": "PLN",
    "due_day": 15,
    "notes": None,
    "is_paused": False,
}


def _create_bill(client: TestClient, token: str, overrides: dict | None = None) -> dict:
    r = client.post("/bills", json={**_BILL, **(overrides or {})}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def test_next_due_points_at_earliest_unpaid_instance(client_db):
    client, db = client_db
    token = register_and_login(client, "nextdue1@test.com")
    _create_bill(client, token)
    sync_payments(client, token)

    bills = client.get("/bills", headers=auth(token)).json()
    bill = bills[0]
    today = date.today()
    assert bill["next_due_date"] is not None
    due = date.fromisoformat(bill["next_due_date"])
    assert due == date(today.year, today.month, 15)
    assert bill["next_due_amount"] == "120.00"
    assert bill["next_due_status"] in {"upcoming", "overdue"}


def test_next_due_advances_after_payment(client_db):
    client, db = client_db
    token = register_and_login(client, "nextdue2@test.com")
    _create_bill(client, token)
    sync_payments(client, token)
    bills = client.get("/bills", headers=auth(token)).json()
    due = date.fromisoformat(bills[0]["next_due_date"])

    instance_id = (
        db.query(PaymentInstance.id).filter(PaymentInstance.due_date == due).scalar()
    )
    r = client.post(f"/bills/payments/{instance_id}/pay", json={}, headers=auth(token))
    assert r.status_code == 200, r.text

    bills = client.get("/bills", headers=auth(token)).json()
    next_due = date.fromisoformat(bills[0]["next_due_date"])
    assert next_due > due
    assert bills[0]["next_due_status"] == "upcoming"


def test_next_due_none_when_all_paid(client_db):
    client, db = client_db
    token = register_and_login(client, "nextdue3@test.com")
    bill = _create_bill(client, token, {"frequency": "one_off", "due_day": 15})
    sync_payments(client, token)

    bills = client.get("/bills", headers=auth(token)).json()
    assert bills[0]["next_due_date"] is not None

    instance_id = db.query(PaymentInstance.id).scalar()
    client.post(f"/bills/payments/{instance_id}/pay", json={}, headers=auth(token))

    bills = client.get("/bills", headers=auth(token)).json()
    assert bills[0]["next_due_date"] is None
    assert bills[0]["next_due_amount"] is None


def test_next_due_uses_estimate_for_variable_bills(client_db):
    client, db = client_db
    token = register_and_login(client, "nextdue4@test.com")
    _create_bill(client, token, {"amount_varies": True})
    sync_payments(client, token)

    bills = client.get("/bills", headers=auth(token)).json()
    assert bills[0]["next_due_amount"] == "120.00"
