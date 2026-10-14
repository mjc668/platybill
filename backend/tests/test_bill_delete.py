"""Tests for DELETE /bills/{id} — soft delete of archived bills.

Covers the contract: only archived bills can be deleted, the row (and its
history) stays in the database and in JSON backups, and every frontend-facing
surface hides it — bills lists, payments, review queue, generation/sync.
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from tests.conftest import auth, register_and_login

_BILL = {
    "name": "Electricity",
    "category": "utilities",
    "frequency": "monthly",
    "amount": "120.00",
    "currency": "PLN",
    "due_day": 15,
    "notes": None,
    "is_paused": False,
}


def _create_bill(client: TestClient, token: str, overrides: dict | None = None) -> int:
    payload = {**_BILL, **(overrides or {})}
    r = client.post("/bills", json=payload, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _archive(client: TestClient, token: str, bill_id: int) -> None:
    r = client.post(f"/bills/{bill_id}/archive", headers=auth(token))
    assert r.status_code == 204, r.text


def _delete(client: TestClient, token: str, bill_id: int):
    return client.delete(f"/bills/{bill_id}", headers=auth(token))


def _insert_instance(
    db,
    bill_id: int,
    period: str,
    due_date: date,
    status=PaymentStatus.upcoming,
    amount_estimated: bool = False,
) -> PaymentInstance:
    inst = PaymentInstance(
        bill_id=bill_id,
        period=period,
        due_date=due_date,
        amount="120.00",
        amount_estimated=amount_estimated,
        status=status,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def test_delete_archived_bill_hides_it_from_both_lists(client_db):
    """After delete the bill is gone from active and archived listings."""
    client, db = client_db
    token = register_and_login(client, "del_hide@test.com")
    bill_id = _create_bill(client, token)
    _archive(client, token, bill_id)

    r = _delete(client, token, bill_id)
    assert r.status_code == 204, r.text

    active = client.get("/bills", headers=auth(token)).json()
    archived = client.get("/bills?include_archived=true", headers=auth(token)).json()
    assert all(b["id"] != bill_id for b in active)
    assert all(b["id"] != bill_id for b in archived)

    # The row itself stays in the database, in deleted status.
    row = db.get(BillTemplate, bill_id)
    assert row is not None
    assert row.is_deleted is True
    assert row.is_archived is True


def test_delete_active_bill_requires_archiving_first(client_db):
    """A non-archived bill returns 400 and stays visible."""
    client, _ = client_db
    token = register_and_login(client, "del_active@test.com")
    bill_id = _create_bill(client, token)

    r = _delete(client, token, bill_id)
    assert r.status_code == 400
    assert "Archive" in r.json()["detail"]

    active = client.get("/bills", headers=auth(token)).json()
    assert any(b["id"] == bill_id for b in active)


def test_delete_is_scoped_and_unknown_ids_404(client_db):
    """Unknown bills, foreign bills and repeat deletes all 404."""
    client, _ = client_db
    tok_a = register_and_login(client, "del_a@test.com")
    tok_b = register_and_login(client, "del_b@test.com")
    bill_id = _create_bill(client, tok_a)
    _archive(client, tok_a, bill_id)

    assert _delete(client, tok_b, bill_id).status_code == 404
    assert _delete(client, tok_a, 99999).status_code == 404

    assert _delete(client, tok_a, bill_id).status_code == 204
    # Already deleted: hidden, so it 404s on a repeat delete.
    assert _delete(client, tok_a, bill_id).status_code == 404


def test_deleted_bill_payments_and_review_stay_hidden(client_db):
    """Payments list, review queue and sync generation all ignore deleted bills."""
    client, db = client_db
    token = register_and_login(client, "del_payments@test.com")
    today = date.today()
    month = today.strftime("%Y-%m")
    bill_id = _create_bill(client, token, {"due_day": today.day})

    _insert_instance(db, bill_id, month, today)
    yesterday = today - timedelta(days=1)
    _insert_instance(
        db,
        bill_id,
        yesterday.strftime("%Y-%m"),
        yesterday,
        amount_estimated=True,
    )
    _archive(client, token, bill_id)
    assert _delete(client, token, bill_id).status_code == 204

    payments = client.get(f"/bills/payments?month={month}", headers=auth(token)).json()
    assert all(p["bill_id"] != bill_id for p in payments)

    review = client.get(
        "/bills/payments/needs-confirmation", headers=auth(token)
    ).json()
    assert all(p["bill_id"] != bill_id for p in review)

    # Sync must not re-seed instances for a deleted bill.
    r = client.post(f"/bills/sync-instances?month={month}", headers=auth(token))
    assert r.status_code == 204
    payments = client.get(f"/bills/payments?month={month}", headers=auth(token)).json()
    assert all(p["bill_id"] != bill_id for p in payments)


def test_deleted_bill_visible_in_export_and_stays_hidden_after_restore(client_db):
    """Backups keep the row (with the flag); restoring preserves the hidden state."""
    client, db = client_db
    token = register_and_login(client, "del_backup@test.com")
    bill_id = _create_bill(client, token)
    _archive(client, token, bill_id)
    assert _delete(client, token, bill_id).status_code == 204

    export = client.get("/export/json", headers=auth(token))
    assert export.status_code == 200
    backup = export.json()
    templates = [t for t in backup["bill_templates"] if t["id"] == bill_id]
    assert len(templates) == 1
    assert templates[0]["is_deleted"] is True
    assert templates[0]["is_archived"] is True

    r = client.post(
        "/export/restore",
        files={
            "file": (
                "backup.json",
                export.content,
                "application/json",
            )
        },
        headers=auth(token),
    )
    assert r.status_code == 200, r.text

    active = client.get("/bills", headers=auth(token)).json()
    archived = client.get("/bills?include_archived=true", headers=auth(token)).json()
    assert all(b["id"] != bill_id for b in active)
    assert all(b["id"] != bill_id for b in archived)
    assert (
        db.query(BillTemplate)
        .filter(BillTemplate.is_deleted.is_(True), BillTemplate.name == "Electricity")
        .count()
        == 1
    )
