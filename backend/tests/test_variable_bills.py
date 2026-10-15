"""Variable-amount bills: estimated instances, confirmation queue, median suggestion."""

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from app.models.category import Category
from app.models.user import User
from app.services.recurrence import suggested_amount
from app.services.reminder_job import send_daily_reminders
from tests.conftest import auth, register_and_login, sync_payments

_BILL = {
    "name": "Water",
    "category": "utilities",
    "frequency": "monthly",
    "amount": "80.00",
    "amount_varies": True,
    "currency": "PLN",
    "due_day": 10,
    "notes": None,
    "is_paused": False,
}


def _create_bill(client, token, overrides=None) -> dict:
    r = client.post("/bills", json={**_BILL, **(overrides or {})}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _insert_instance(
    db,
    bill_id: int,
    period: str,
    due_date: date,
    amount: str,
    *,
    estimated: bool = False,
    status=PaymentStatus.upcoming,
) -> PaymentInstance:
    inst = PaymentInstance(
        bill_id=bill_id,
        period=period,
        due_date=due_date,
        amount=Decimal(amount),
        amount_estimated=estimated,
        status=status,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Queue + confirmation
# ---------------------------------------------------------------------------


def test_variable_instance_starts_estimated_and_queued(client_db):
    client, db = client_db
    token = register_and_login(client, "var1@test.com")
    _create_bill(client, token)
    sync_payments(client, token)

    # Not in the normal list while unconfirmed
    listed = client.get("/bills/payments", headers=auth(token)).json()
    assert listed == []

    queue = client.get("/bills/payments/needs-confirmation", headers=auth(token)).json()
    assert len(queue) == 1
    item = queue[0]
    assert item["amount"] == "80.00"  # no history: template amount
    assert item["amount_estimated"] is True
    assert item["basis_amounts"] == []


def test_confirm_amount_moves_instance_into_list(client_db):
    client, db = client_db
    token = register_and_login(client, "var2@test.com")
    _create_bill(client, token)
    sync_payments(client, token)
    instance_id = client.get(
        "/bills/payments/needs-confirmation", headers=auth(token)
    ).json()[0]["id"]

    r = client.patch(
        f"/bills/payments/{instance_id}/amount",
        json={"amount": "95.50"},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == "95.50"
    assert body["amount_estimated"] is False

    listed = client.get("/bills/payments", headers=auth(token)).json()
    assert [i["id"] for i in listed] == [instance_id]
    queue = client.get("/bills/payments/needs-confirmation", headers=auth(token)).json()
    assert queue == []


def test_cannot_change_paid_instance_amount(client_db):
    client, db = client_db
    token = register_and_login(client, "var3@test.com")
    _create_bill(client, token)
    sync_payments(client, token)
    instance_id = client.get(
        "/bills/payments/needs-confirmation", headers=auth(token)
    ).json()[0]["id"]
    client.post(f"/bills/payments/{instance_id}/pay", json={}, headers=auth(token))

    r = client.patch(
        f"/bills/payments/{instance_id}/amount",
        json={"amount": "10.00"},
        headers=auth(token),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------


def test_suggestion_is_median_of_last_three(client_db):
    client, db = client_db
    token = register_and_login(client, "var4@test.com")
    bill = _create_bill(client, token)
    template = db.get(BillTemplate, bill["id"])

    # No history yet -> template amount
    assert suggested_amount(db, template) == Decimal("80.00")

    today = _today_utc()
    _insert_instance(db, template.id, "2026-04", today - timedelta(days=200), "100.00")
    _insert_instance(db, template.id, "2026-05", today - timedelta(days=170), "80.00")
    _insert_instance(db, template.id, "2026-06", today - timedelta(days=140), "90.00")
    assert suggested_amount(db, template) == Decimal("90.00")

    # Even count averages the two middle values: [80, 100] -> 90
    for inst in (
        db.query(PaymentInstance).filter(PaymentInstance.bill_id == template.id).all()
    ):
        if inst.period == "2026-06":
            db.delete(inst)
    db.commit()
    assert suggested_amount(db, template) == Decimal("90.00")


def test_full_payment_auto_confirms_and_seeds_next_estimate(client_db):
    client, db = client_db
    token = register_and_login(client, "var5@test.com")
    bill = _create_bill(client, token)
    sync_payments(client, token)
    instance_id = client.get(
        "/bills/payments/needs-confirmation", headers=auth(token)
    ).json()[0]["id"]

    r = client.post(
        f"/bills/payments/{instance_id}/pay",
        json={"paid_amount": "87.30"},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    paid = r.json()
    assert paid["amount"] == "87.30"
    assert paid["amount_estimated"] is False

    # The next period was generated from the confirmed history (only one
    # confirmed amount so far -> that amount, flagged as an estimate). Its
    # period has not arrived, so it is not in the confirmation queue yet.
    next_inst = (
        db.query(PaymentInstance)
        .filter(
            PaymentInstance.bill_id == bill["id"],
            PaymentInstance.due_date > date.fromisoformat(paid["due_date"]),
        )
        .one()
    )
    assert next_inst.amount_estimated is True
    assert next_inst.amount == Decimal("87.30")
    queue = client.get("/bills/payments/needs-confirmation", headers=auth(token)).json()
    assert queue == []


# ---------------------------------------------------------------------------
# Reminders + stats exclusions
# ---------------------------------------------------------------------------


@contextmanager
def _smtp():
    with (
        patch.object(settings, "smtp_host", "smtp.test"),
        patch.object(settings, "smtp_port", 587),
        patch.object(settings, "smtp_user", None),
        patch.object(settings, "smtp_password", None),
        patch.object(settings, "smtp_use_tls", True),
        patch.object(settings, "reminder_from", "r@test.com"),
        patch.object(settings, "email_blocked_domains", []),
        patch.object(settings, "apprise_base_url", None),
    ):
        yield


def _make_user(db, email="rem@test.com") -> User:
    user = User(
        email=email,
        password_hash="x",
        is_active=True,
        email_reminders_enabled=True,
        notify_1_day_before=True,
        reminder_send_minute=480,
    )
    db.add(user)
    db.flush()
    return user


@patch("app.services.reminder_job.send_reminder_email")
def test_reminders_skip_estimated_instances(mock_send, db_session, db_sessionmaker):
    today = _today_utc()
    user = _make_user(db_session)
    category = Category(key="utilities", name="Utilities", user_id=user.id)
    db_session.add(category)
    db_session.flush()
    bill = BillTemplate(
        name="Water",
        category_id=category.id,
        frequency="monthly",
        interval_count=1,
        amount=Decimal("80.00"),
        amount_varies=True,
        currency="PLN",
        due_day=10,
        user_id=user.id,
        start_period=today.strftime("%Y-%m"),
    )
    db_session.add(bill)
    db_session.flush()
    _insert_instance(
        db_session,
        bill.id,
        today.strftime("%Y-%m"),
        today + timedelta(days=1),
        "80.00",
        estimated=True,
    )

    with _smtp():
        send_daily_reminders(db_sessionmaker, send_minute=480)
    mock_send.assert_not_called()


def test_stats_exclude_estimated_until_confirmed(client_db):
    client, db = client_db
    token = register_and_login(client, "var6@test.com")
    _create_bill(client, token)
    sync_payments(client, token)

    overview = client.get("/stats/overview", headers=auth(token)).json()
    assert overview["summary"]["total_count"] == 0

    instance_id = client.get(
        "/bills/payments/needs-confirmation", headers=auth(token)
    ).json()[0]["id"]
    client.patch(
        f"/bills/payments/{instance_id}/amount",
        json={"amount": "95.50"},
        headers=auth(token),
    )
    overview = client.get("/stats/overview", headers=auth(token)).json()
    assert overview["summary"]["total_count"] == 1


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------


def test_backup_round_trip_preserves_variable_flags(client_db):
    client, db = client_db
    token = register_and_login(client, "var7@test.com")
    _create_bill(client, token)
    sync_payments(client, token)

    payload = client.get("/export/json", headers=auth(token)).json()
    assert payload["schema_version"] == 8
    assert payload["bill_templates"][0]["amount_varies"] is True
    assert payload["payment_instances"][0]["amount_estimated"] is True

    import json

    r = client.post(
        "/export/restore",
        files={"file": ("backup.json", json.dumps(payload), "application/json")},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text

    queue = client.get("/bills/payments/needs-confirmation", headers=auth(token)).json()
    assert len(queue) == 1
    assert queue[0]["amount_estimated"] is True
    bills = client.get("/bills", headers=auth(token)).json()
    assert bills[0]["amount_varies"] is True


def test_old_backup_without_flags_restores_as_fixed(client_db):
    client, db = client_db
    token = register_and_login(client, "var8@test.com")
    payload = {
        "schema_version": 7,
        "bill_templates": [
            {
                "id": 1,
                "name": "Water",
                "category": "utilities",
                "frequency": "monthly",
                "interval_count": 1,
                "max_occurrences": None,
                "start_date": None,
                "amount": 80.0,
                "currency": "PLN",
                "due_day": 10,
                "notes": None,
                "is_archived": False,
                "is_paused": False,
                "start_period": "2026-01",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "payment_instances": [
            {
                "id": 1,
                "bill_id": 1,
                "period": "2026-01",
                "due_date": "2026-01-10",
                "amount": 80.0,
                "status": "upcoming",
                "paid_at": None,
                "paid_amount": None,
                "notes": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "payments": [],
    }

    import json

    r = client.post(
        "/export/restore",
        files={"file": ("backup.json", json.dumps(payload), "application/json")},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    bills = client.get("/bills", headers=auth(token)).json()
    assert bills[0]["amount_varies"] is False
    queue = client.get("/bills/payments/needs-confirmation", headers=auth(token)).json()
    assert queue == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_edit_amount_of_plain_instance(client_db):
    """Plain (non-estimated) unpaid instances can have their amount corrected."""
    client, db = client_db
    token = register_and_login(client, "var_edit@test.com")
    bill = _create_bill(client, token, {"amount_varies": False})
    today = _today_utc()
    inst = _insert_instance(
        db, bill["id"], today.strftime("%Y-%m"), today, "80.00", estimated=False
    )

    r = client.patch(
        f"/bills/payments/{inst.id}/amount",
        json={"amount": "84.25"},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == "84.25"
    assert body["amount_estimated"] is False

    listed = client.get("/bills/payments", headers=auth(token)).json()
    assert [(i["id"], i["amount"]) for i in listed] == [(inst.id, "84.25")]
