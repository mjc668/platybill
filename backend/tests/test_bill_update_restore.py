"""Tests for GET /bills/{id}/has-deleted-future and PATCH recreate_deleted_future."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.models.bill import PaymentInstance, PaymentStatus
from app.services.recurrence import _due_date_for_period
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


def _instance_exists(db, instance_id: int) -> bool:
    """Query-based existence check: Session.get on a deleted identity-mapped
    row raises ObjectDeletedError in the test session."""
    return (
        db.query(PaymentInstance).filter(PaymentInstance.id == instance_id).count() > 0
    )


def _insert_instance(
    db,
    bill_id: int,
    period: str,
    due_date: date,
    status=PaymentStatus.upcoming,
    is_deleted: bool = False,
    amount="120.00",
) -> PaymentInstance:
    inst = PaymentInstance(
        bill_id=bill_id,
        period=period,
        due_date=due_date,
        amount=amount,
        status=status,
        is_deleted=is_deleted,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _current_period() -> str:
    return date.today().strftime("%Y-%m")


def _future_period() -> str:
    """One month ahead of today."""
    today = date.today()
    month = today.month % 12 + 1
    year = today.year + (1 if today.month == 12 else 0)
    return f"{year}-{month:02d}"


def _past_period() -> str:
    """One month before today."""
    today = date.today()
    month = today.month - 1 or 12
    year = today.year - (1 if today.month == 1 else 0)
    return f"{year}-{month:02d}"


# ---------------------------------------------------------------------------
# GET /bills/{id}/has-deleted-future
# ---------------------------------------------------------------------------


def test_has_deleted_future_no_instances(client_db):
    """Bill with no instances at all returns false."""
    client, db = client_db
    token = register_and_login(client, "u1@test.com")
    bill_id = _create_bill(client, token)

    r = client.get(f"/bills/{bill_id}/has-deleted-future", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == {"has_deleted_future": False}


def test_has_deleted_future_with_current_period_tombstone(client_db):
    """Tombstone in current period returns true."""
    client, db = client_db
    token = register_and_login(client, "u2@test.com")
    bill_id = _create_bill(client, token)
    period = _current_period()
    _insert_instance(db, bill_id, period, date.today(), is_deleted=True)

    r = client.get(f"/bills/{bill_id}/has-deleted-future", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == {"has_deleted_future": True}


def test_has_deleted_future_only_past_tombstone_returns_false(client_db):
    """Tombstone in a past period does not count — returns false."""
    client, db = client_db
    token = register_and_login(client, "u3@test.com")
    bill_id = _create_bill(client, token)
    past = _past_period()
    year, month = map(int, past.split("-"))
    _insert_instance(db, bill_id, past, date(year, month, 15), is_deleted=True)

    r = client.get(f"/bills/{bill_id}/has-deleted-future", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == {"has_deleted_future": False}


def test_has_deleted_future_cross_user_returns_404(client_db):
    """Another user cannot probe a bill they don't own."""
    client, db = client_db
    tok_a = register_and_login(client, "a1@test.com")
    tok_b = register_and_login(client, "b1@test.com")
    bill_id = _create_bill(client, tok_a)

    r = client.get(f"/bills/{bill_id}/has-deleted-future", headers=auth(tok_b))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /bills/{id} with recreate_deleted_future=true
# ---------------------------------------------------------------------------


def test_patch_restore_flips_tombstone_to_active(client_db):
    """recreate_deleted_future=true restores is_deleted=False and status=upcoming."""
    client, db = client_db
    token = register_and_login(client, "u4@test.com")
    bill_id = _create_bill(client, token)
    period = _current_period()
    inst = _insert_instance(db, bill_id, period, date.today(), is_deleted=True)

    r = client.patch(
        f"/bills/{bill_id}",
        json={"recreate_deleted_future": True},
        headers=auth(token),
    )
    assert r.status_code == 200

    db.expire_all()
    refreshed = db.get(PaymentInstance, inst.id)
    assert refreshed.is_deleted is False
    assert refreshed.status == PaymentStatus.upcoming


def test_has_deleted_future_past_due_current_month_returns_false(client_db):
    """A tombstone whose due date already passed is not "future"."""
    client, db = client_db
    token = register_and_login(client, "u3b@test.com")
    bill_id = _create_bill(client, token)
    due = date.today() - timedelta(days=1)
    _insert_instance(db, bill_id, due.strftime("%Y-%m"), due, is_deleted=True)

    r = client.get(f"/bills/{bill_id}/has-deleted-future", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == {"has_deleted_future": False}


def test_patch_restore_skips_past_due_tombstone(client_db):
    """recreate_deleted_future never resurrects a due date that already passed.

    Regression: the old period-based filter restored a current-month tombstone
    even when its due date was in the past (e.g. cancelled inside an archived
    span), resurrecting a phantom overdue.
    """
    client, db = client_db
    token = register_and_login(client, "u4b@test.com")
    bill_id = _create_bill(client, token)
    due = date.today() - timedelta(days=1)
    inst = _insert_instance(db, bill_id, due.strftime("%Y-%m"), due, is_deleted=True)

    r = client.patch(
        f"/bills/{bill_id}",
        json={"recreate_deleted_future": True},
        headers=auth(token),
    )
    assert r.status_code == 200

    db.expire_all()
    refreshed = db.get(PaymentInstance, inst.id)
    assert refreshed.is_deleted is True


def test_patch_restore_updates_amount(client_db):
    """Restored instances pick up the template's updated amount."""
    client, db = client_db
    token = register_and_login(client, "u5@test.com")
    bill_id = _create_bill(client, token)
    period = _current_period()
    inst = _insert_instance(
        db, bill_id, period, date.today(), is_deleted=True, amount="120.00"
    )

    r = client.patch(
        f"/bills/{bill_id}",
        json={"amount": "250.00", "recreate_deleted_future": True},
        headers=auth(token),
    )
    assert r.status_code == 200

    db.expire_all()
    refreshed = db.get(PaymentInstance, inst.id)
    assert float(refreshed.amount) == pytest.approx(250.00)


def test_patch_restore_recalculates_due_date(client_db):
    """Restored instances get due_date recalculated from the updated due_day."""
    client, db = client_db
    token = register_and_login(client, "u6@test.com")
    bill_id = _create_bill(client, token)  # due_day=15
    period = _current_period()
    year, month = map(int, period.split("-"))
    inst = _insert_instance(db, bill_id, period, date(year, month, 28), is_deleted=True)

    r = client.patch(
        f"/bills/{bill_id}",
        json={"due_day": 20, "recreate_deleted_future": True},
        headers=auth(token),
    )
    assert r.status_code == 200

    db.expire_all()
    refreshed = db.get(PaymentInstance, inst.id)
    assert refreshed.due_date == _due_date_for_period(period, 20)


def test_patch_without_restore_flag_leaves_tombstone_intact(client_db):
    """Default PATCH (recreate_deleted_future omitted) does not touch tombstones."""
    client, db = client_db
    token = register_and_login(client, "u7@test.com")
    bill_id = _create_bill(client, token)
    period = _current_period()
    inst = _insert_instance(db, bill_id, period, date.today(), is_deleted=True)

    r = client.patch(
        f"/bills/{bill_id}",
        json={"amount": "200.00"},
        headers=auth(token),
    )
    assert r.status_code == 200

    db.expire_all()
    assert db.get(PaymentInstance, inst.id).is_deleted is True


def test_patch_restore_no_tombstones_is_noop(client_db):
    """recreate_deleted_future=true with no tombstones: 200, template updated, no error."""
    client, db = client_db
    token = register_and_login(client, "u8@test.com")
    bill_id = _create_bill(client, token)
    # active instance (not deleted)
    period = _current_period()
    _insert_instance(db, bill_id, period, date.today(), is_deleted=False)

    r = client.patch(
        f"/bills/{bill_id}",
        json={"amount": "300.00", "recreate_deleted_future": True},
        headers=auth(token),
    )
    assert r.status_code == 200
    assert float(r.json()["amount"]) == pytest.approx(300.00)


def test_patch_restore_does_not_restore_past_tombstones(client_db):
    """Past-period tombstones are ignored; only current/future ones are restored."""
    client, db = client_db
    token = register_and_login(client, "u9@test.com")
    bill_id = _create_bill(client, token)

    past = _past_period()
    past_year, past_month = map(int, past.split("-"))
    past_inst = _insert_instance(
        db, bill_id, past, date(past_year, past_month, 15), is_deleted=True
    )

    future = _future_period()
    future_year, future_month = map(int, future.split("-"))
    future_inst = _insert_instance(
        db, bill_id, future, date(future_year, future_month, 15), is_deleted=True
    )

    r = client.patch(
        f"/bills/{bill_id}",
        json={"recreate_deleted_future": True},
        headers=auth(token),
    )
    assert r.status_code == 200

    db.expire_all()
    assert db.get(PaymentInstance, past_inst.id).is_deleted is True  # untouched
    assert db.get(PaymentInstance, future_inst.id).is_deleted is False  # restored


def test_patch_restore_cross_user_returns_404(client_db):
    """Cross-user PATCH with restore flag is blocked."""
    client, db = client_db
    tok_a = register_and_login(client, "a2@test.com")
    tok_b = register_and_login(client, "b2@test.com")
    bill_id = _create_bill(client, tok_a)

    r = client.patch(
        f"/bills/{bill_id}",
        json={"recreate_deleted_future": True},
        headers=auth(tok_b),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /bills/{id} — weekly schedule changes and interval validation
# ---------------------------------------------------------------------------


def test_patch_weekly_schedule_change_respaces_future_unpaid(client_db):
    """Changing a weekly interval re-spaces future unpaid instances from the
    first occurrence on/after today. Paid and soft-deleted rows are untouched."""
    client, db = client_db
    token = register_and_login(client, "weekly_patch@test.com")
    today = date.today()
    # Future anchor so create does not backfill the current month.
    start = today + timedelta(days=30)
    bill_id = _create_bill(
        client,
        token,
        {
            "frequency": "weekly",
            "start_date": start.isoformat(),
            "interval_count": 1,
            "due_day": None,
        },
    )

    first = _insert_instance(
        db,
        bill_id,
        (today + timedelta(days=40)).strftime("%Y-%m"),
        today + timedelta(days=40),
    )
    second = _insert_instance(
        db,
        bill_id,
        (today + timedelta(days=50)).strftime("%Y-%m"),
        today + timedelta(days=50),
    )
    third = _insert_instance(
        db,
        bill_id,
        (today + timedelta(days=60)).strftime("%Y-%m"),
        today + timedelta(days=60),
    )
    paid = _insert_instance(
        db,
        bill_id,
        (today + timedelta(days=45)).strftime("%Y-%m"),
        today + timedelta(days=45),
        status=PaymentStatus.paid,
    )
    deleted = _insert_instance(
        db,
        bill_id,
        (today + timedelta(days=55)).strftime("%Y-%m"),
        today + timedelta(days=55),
        is_deleted=True,
    )

    r = client.patch(
        f"/bills/{bill_id}", json={"interval_count": 2}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["interval_count"] == 2

    db.expire_all()
    assert db.get(PaymentInstance, first.id).due_date == start
    assert db.get(PaymentInstance, second.id).due_date == start + timedelta(days=14)
    assert db.get(PaymentInstance, third.id).due_date == start + timedelta(days=28)
    assert db.get(PaymentInstance, first.id).period == start.strftime("%Y-%m")
    # Paid and soft-deleted rows keep their old dates.
    assert db.get(PaymentInstance, paid.id).due_date == today + timedelta(days=45)
    assert db.get(PaymentInstance, deleted.id).due_date == today + timedelta(days=55)


def test_patch_weekly_to_monthly_clears_start_date_and_due_day(client_db):
    client, db = client_db
    token = register_and_login(client, "weekly_to_monthly@test.com")
    start = date.today() + timedelta(days=10)
    bill_id = _create_bill(
        client,
        token,
        {
            "frequency": "weekly",
            "start_date": start.isoformat(),
            "due_day": None,
        },
    )

    r = client.patch(
        f"/bills/{bill_id}",
        json={"frequency": "monthly", "due_day": 10},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["frequency"] == "monthly"
    assert data["start_date"] is None
    assert data["due_day"] == 10
    assert data["interval_count"] == 1


def test_patch_weekly_to_monthly_collapses_duplicate_occurrences(client_db):
    """Several weekly rows in one period must not collapse onto one date."""
    client, db = client_db
    token = register_and_login(client, "weekly_collapse@test.com")
    today = date.today()
    start = date(today.year, today.month, 1)
    bill_id = _create_bill(
        client,
        token,
        {"frequency": "weekly", "start_date": start.isoformat(), "due_day": None},
    )

    r = client.patch(
        f"/bills/{bill_id}",
        json={"frequency": "monthly", "due_day": 10},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text

    rows = db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill_id).all()
    assert len(rows) == 1
    assert rows[0].due_date == date(today.year, today.month, 10)


def test_patch_monthly_to_weekly_requires_start_date(client_db):
    client, db = client_db
    token = register_and_login(client, "monthly_to_weekly@test.com")
    bill_id = _create_bill(client, token)  # monthly, no start_date

    r = client.patch(
        f"/bills/{bill_id}", json={"frequency": "weekly"}, headers=auth(token)
    )
    assert r.status_code == 422


def test_patch_interval_out_of_bounds_returns_422(client_db):
    client, db = client_db
    token = register_and_login(client, "patch_interval_bounds@test.com")
    bill_id = _create_bill(client, token)  # monthly → max 12

    r = client.patch(
        f"/bills/{bill_id}", json={"interval_count": 13}, headers=auth(token)
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /bills/{id} — max_occurrences
# ---------------------------------------------------------------------------


def _shift_period(period: str, delta: int) -> str:
    year, month = map(int, period.split("-"))
    total = year * 12 + month - 1 + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _day15(period: str) -> date:
    year, month = map(int, period.split("-"))
    return date(year, month, 15)


def test_patch_lowering_cap_prunes_future_unpaid(client_db):
    """Lowering the cap removes future, unpaid, non-deleted, event-free rows."""
    client, db = client_db
    token = register_and_login(client, "cap_prune@test.com")
    bill_id = _create_bill(client, token)  # monthly anchored in the current month
    current = _current_period()

    plus1 = _insert_instance(
        db, bill_id, _shift_period(current, 1), _day15(_shift_period(current, 1))
    )
    plus2 = _insert_instance(
        db, bill_id, _shift_period(current, 2), _day15(_shift_period(current, 2))
    )
    plus3 = _insert_instance(
        db, bill_id, _shift_period(current, 3), _day15(_shift_period(current, 3))
    )
    # Capture PKs before the PATCH: the request deletes rows in another
    # session, and touching an expired instance afterwards raises.
    plus1_id, plus2_id, plus3_id = plus1.id, plus2.id, plus3.id

    # Cap 2 allows indices 0 (current month) and 1 (+1 month).
    r = client.patch(
        f"/bills/{bill_id}", json={"max_occurrences": 2}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_occurrences"] == 2

    assert _instance_exists(db, plus1_id)
    assert not _instance_exists(db, plus2_id)
    assert not _instance_exists(db, plus3_id)


def test_patch_lowering_cap_keeps_paid_partial_and_tombstones(client_db):
    client, db = client_db
    token = register_and_login(client, "cap_keep@test.com")
    bill_id = _create_bill(client, token)
    current = _current_period()

    paid = _insert_instance(
        db,
        bill_id,
        _shift_period(current, 2),
        _day15(_shift_period(current, 2)),
        status=PaymentStatus.paid,
    )
    partial = _insert_instance(
        db, bill_id, _shift_period(current, 3), _day15(_shift_period(current, 3))
    )
    tombstone = _insert_instance(
        db,
        bill_id,
        _shift_period(current, 4),
        _day15(_shift_period(current, 4)),
        is_deleted=True,
    )
    plain = _insert_instance(
        db, bill_id, _shift_period(current, 5), _day15(_shift_period(current, 5))
    )
    paid_id, partial_id, tombstone_id, plain_id = (
        paid.id,
        partial.id,
        tombstone.id,
        plain.id,
    )

    r = client.post(
        f"/bills/payments/{partial.id}/payments",
        json={"amount": "10.00"},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text  # partial → stays unpaid but has an event

    r = client.patch(
        f"/bills/{bill_id}", json={"max_occurrences": 1}, headers=auth(token)
    )
    assert r.status_code == 200, r.text

    assert _instance_exists(db, paid_id)
    assert _instance_exists(db, partial_id)
    assert _instance_exists(db, tombstone_id)
    assert not _instance_exists(db, plain_id)


def test_patch_raising_cap_does_not_prune(client_db):
    client, db = client_db
    token = register_and_login(client, "cap_raise@test.com")
    bill_id = _create_bill(client, token, {"max_occurrences": 1})
    current = _current_period()
    beyond = _insert_instance(
        db, bill_id, _shift_period(current, 2), _day15(_shift_period(current, 2))
    )
    beyond_id = beyond.id

    r = client.patch(
        f"/bills/{bill_id}", json={"max_occurrences": 5}, headers=auth(token)
    )
    assert r.status_code == 200, r.text

    assert _instance_exists(db, beyond_id)


def test_patch_clearing_cap_does_not_prune(client_db):
    client, db = client_db
    token = register_and_login(client, "cap_clear@test.com")
    bill_id = _create_bill(client, token, {"max_occurrences": 1})
    current = _current_period()
    beyond = _insert_instance(
        db, bill_id, _shift_period(current, 2), _day15(_shift_period(current, 2))
    )
    beyond_id = beyond.id

    r = client.patch(
        f"/bills/{bill_id}", json={"max_occurrences": None}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_occurrences"] is None

    assert _instance_exists(db, beyond_id)


def test_patch_one_off_forces_max_occurrences_null(client_db):
    client, db = client_db
    token = register_and_login(client, "cap_oneoff_patch@test.com")
    bill_id = _create_bill(client, token, {"max_occurrences": 4})

    r = client.patch(
        f"/bills/{bill_id}",
        json={"frequency": "one_off", "max_occurrences": 5},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["frequency"] == "one_off"
    assert r.json()["max_occurrences"] is None


def test_patch_frequency_to_one_off_clears_existing_cap(client_db):
    client, db = client_db
    token = register_and_login(client, "cap_oneoff_clear@test.com")
    bill_id = _create_bill(client, token, {"max_occurrences": 4})

    r = client.patch(
        f"/bills/{bill_id}", json={"frequency": "one_off"}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_occurrences"] is None


@pytest.mark.parametrize("value", [0, 1000, -3])
def test_patch_max_occurrences_out_of_bounds_returns_422(client_db, value):
    client, db = client_db
    token = register_and_login(client, f"cap_bounds_{value}@test.com")
    bill_id = _create_bill(client, token)

    r = client.patch(
        f"/bills/{bill_id}", json={"max_occurrences": value}, headers=auth(token)
    )
    assert r.status_code == 422


@pytest.mark.parametrize("value", [1, 999])
def test_patch_max_occurrences_at_bounds_accepted(client_db, value):
    client, db = client_db
    token = register_and_login(client, f"cap_ok_{value}@test.com")
    bill_id = _create_bill(client, token)

    r = client.patch(
        f"/bills/{bill_id}", json={"max_occurrences": value}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["max_occurrences"] == value


def test_patch_amount_propagates_to_live_instances(client_db):
    """A price change follows unpaid event-free instances; history stays frozen."""
    from app.models.payment import Payment

    client, db = client_db
    token = register_and_login(client, "amt_live@test.com")
    bill_id = _create_bill(client, token)  # 120.00
    period = _current_period()
    today = date.today()

    live = _insert_instance(db, bill_id, period, today, amount="120.00")
    paid = _insert_instance(
        db,
        bill_id,
        period,
        today - timedelta(days=1),
        status=PaymentStatus.paid,
        amount="120.00",
    )
    db.add(Payment(instance_id=paid.id, amount="120.00", paid_on=today))
    db.commit()

    r = client.patch(
        f"/bills/{bill_id}", json={"amount": "150.00"}, headers=auth(token)
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    assert float(db.get(PaymentInstance, live.id).amount) == pytest.approx(150.00)
    assert float(db.get(PaymentInstance, paid.id).amount) == pytest.approx(120.00)


def test_patch_amount_skips_instances_with_partial_events(client_db):
    """Partially-paid rows keep their amount: the ledger already references it."""
    from app.models.payment import Payment

    client, db = client_db
    token = register_and_login(client, "amt_partial@test.com")
    bill_id = _create_bill(client, token)
    period = _current_period()
    today = date.today()

    partial = _insert_instance(db, bill_id, period, today, amount="120.00")
    db.add(Payment(instance_id=partial.id, amount="50.00", paid_on=today))
    db.commit()

    r = client.patch(
        f"/bills/{bill_id}", json={"amount": "150.00"}, headers=auth(token)
    )
    assert r.status_code == 200, r.text

    db.expire_all()
    assert float(db.get(PaymentInstance, partial.id).amount) == pytest.approx(120.00)
