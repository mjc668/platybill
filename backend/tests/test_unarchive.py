"""Tests for POST /bills/{id}/unarchive — resume seeding and span cancellation.

Covers the unarchive contract: flags are cleared, occurrences whose due date
fell inside the archived span are cancelled, and the schedule resumes at the
first occurrence on/after today — a past-due occurrence is never materialized.
Also covers idempotency (including tombstones), cap re-anchoring, and
cross-user 404.
"""

from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from app.models.payment import Payment
from app.services.recurrence import (
    _due_date_for_period,
    _weekly_occurrences_in_period,
    seed_resumed_occurrences,
)
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


def _insert_instance(
    db,
    bill_id: int,
    period: str,
    due_date: date,
    status=PaymentStatus.upcoming,
    is_deleted: bool = False,
) -> PaymentInstance:
    inst = PaymentInstance(
        bill_id=bill_id,
        period=period,
        due_date=due_date,
        amount="120.00",
        status=status,
        is_deleted=is_deleted,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def _rows(db, bill_id: int) -> list[PaymentInstance]:
    db.expire_all()
    return (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == bill_id)
        .order_by(PaymentInstance.due_date, PaymentInstance.id)
        .all()
    )


def _shift_period(period: str, delta: int) -> str:
    year, month = map(int, period.split("-"))
    total = year * 12 + (month - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _archive(client: TestClient, token: str, bill_id: int) -> None:
    r = client.post(f"/bills/{bill_id}/archive", headers=auth(token))
    assert r.status_code == 204, r.text


# ---------------------------------------------------------------------------
# Resume semantics — current period, no gap backfill
# ---------------------------------------------------------------------------


def test_unarchive_monthly_resumes_at_next_occurrence_without_gap(client_db):
    """A resumed monthly bill resumes at its next due date.

    The current month's occurrence is not materialized when its due date
    already passed while the bill was archived.
    """
    client, db = client_db
    token = register_and_login(client, "monthly_resume@test.com")
    today = date.today()
    current = today.strftime("%Y-%m")

    overrides: dict = {"is_paused": True, "due_day": 1}
    if today.month > 2:
        overrides["due_month"] = today.month - 2  # past due_month
    bill_id = _create_bill(client, token, overrides)

    # Creation backfills nothing while paused; backdate the anchor so the bill
    # looks like a long-archived schedule with no live history.
    db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill_id).delete()
    bill = db.get(BillTemplate, bill_id)
    bill.start_period = _shift_period(current, -3)
    db.commit()

    _archive(client, token, bill_id)
    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_archived"] is False
    assert data["is_paused"] is False

    # Expected resume: the 1st of this month when it is today or later,
    # otherwise next month's occurrence. Never a past-due row.
    expected_period = current
    if _due_date_for_period(current, 1) < today:
        expected_period = _shift_period(current, 1)

    rows = _rows(db, bill_id)
    assert len(rows) == 1  # no gap rows
    assert rows[0].period == expected_period
    assert rows[0].due_date == _due_date_for_period(expected_period, 1)
    assert rows[0].due_date >= today


def test_unarchive_weekly_seeds_only_remaining_occurrences(client_db):
    """Weekly resume seeds only occurrences on/after today."""
    client, db = client_db
    token = register_and_login(client, "weekly_resume@test.com")
    today = date.today()
    current = today.strftime("%Y-%m")
    start = today - timedelta(days=21)

    bill_id = _create_bill(
        client,
        token,
        {
            "frequency": "weekly",
            "start_date": start.isoformat(),
            "due_day": None,
            "is_paused": True,
        },
    )
    db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill_id).delete()
    db.commit()

    _archive(client, token, bill_id)
    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text

    bill = db.get(BillTemplate, bill_id)
    expected = [d for d in _weekly_occurrences_in_period(bill, current) if d >= today]
    rows = _rows(db, bill_id)
    assert [row.due_date for row in rows] == expected
    assert all(row.due_date >= today for row in rows)
    assert all(row.period == current for row in rows)


def test_unarchive_one_off_past_due_creates_nothing(client_db):
    """A one-off whose date passed while archived is never materialized."""
    client, db = client_db
    token = register_and_login(client, "oneoff_resume@test.com")
    today = date.today()
    past_period = _shift_period(today.strftime("%Y-%m"), -1)

    bill_id = _create_bill(
        client, token, {"frequency": "one_off", "due_day": 5, "is_paused": True}
    )
    bill = db.get(BillTemplate, bill_id)
    bill.start_period = past_period
    db.commit()

    _archive(client, token, bill_id)
    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text
    assert _rows(db, bill_id) == []

    # Unarchiving again must not create the past occurrence either.
    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text
    assert _rows(db, bill_id) == []


def test_unarchive_one_off_future_due_seeds_occurrence(client_db):
    """A one-off anchored in a future month seeds its single occurrence."""
    client, db = client_db
    token = register_and_login(client, "oneoff_future@test.com")
    today = date.today()
    future_period = _shift_period(today.strftime("%Y-%m"), 1)

    bill_id = _create_bill(
        client, token, {"frequency": "one_off", "due_day": 5, "is_paused": True}
    )
    bill = db.get(BillTemplate, bill_id)
    bill.start_period = future_period
    db.commit()

    _archive(client, token, bill_id)
    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text

    rows = _rows(db, bill_id)
    assert len(rows) == 1
    assert rows[0].due_date == _due_date_for_period(future_period, 5)
    assert rows[0].period == future_period


# ---------------------------------------------------------------------------
# Archived-span cancellation
# ---------------------------------------------------------------------------


def test_archive_stamps_archived_at_and_unarchive_clears_it(client_db):
    """Archive records when it happened; unarchive clears the stamp."""
    client, db = client_db
    token = register_and_login(client, "stamp@test.com")
    bill_id = _create_bill(client, token, {"is_paused": True})

    _archive(client, token, bill_id)
    bill = db.get(BillTemplate, bill_id)
    assert bill.archived_at is not None

    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text
    db.expire_all()
    bill = db.get(BillTemplate, bill_id)
    assert bill.archived_at is None


def test_unarchive_cancels_occurrences_due_inside_archived_span(client_db):
    """Span occurrences are cancelled/tombstoned; paid and event rows survive."""
    client, db = client_db
    token = register_and_login(client, "span_cancel@test.com")
    today = date.today()
    current = today.strftime("%Y-%m")

    bill_id = _create_bill(client, token, {"due_day": 1})
    bill = db.get(BillTemplate, bill_id)
    bill.start_period = _shift_period(current, -3)
    db.commit()

    due3 = _due_date_for_period(_shift_period(current, -3), 1)
    due2 = _due_date_for_period(_shift_period(current, -2), 1)
    due1 = _due_date_for_period(_shift_period(current, -1), 1)
    due0 = _due_date_for_period(current, 1)

    # due3: no row at all — the cancel pass must create a tombstone for it.
    # due2: paid inside the span — must be untouched.
    _insert_instance(
        db, bill_id, _shift_period(current, -2), due2, status=PaymentStatus.paid
    )
    # due1: unpaid but carries a payment event — must be untouched.
    event_row = _insert_instance(db, bill_id, _shift_period(current, -1), due1)
    db.add(Payment(instance_id=event_row.id, amount="50.00", paid_on=today))
    # due0: live unpaid row; cancelled only when its due date already passed.
    _insert_instance(db, bill_id, current, due0)
    db.commit()

    # Pretend the bill was archived the day before due3's month-start cycle.
    bill = db.get(BillTemplate, bill_id)
    bill.is_archived = True
    bill.archived_at = datetime.combine(due3, datetime.min.time()) - timedelta(days=1)
    db.commit()

    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text

    by_date = {row.due_date: row for row in _rows(db, bill_id)}

    # Missing span occurrence got a blocking tombstone.
    assert by_date[due3].is_deleted is True
    # Paid span occurrence untouched.
    assert by_date[due2].status == PaymentStatus.paid
    assert by_date[due2].is_deleted is False
    # Event-bearing span occurrence untouched.
    assert by_date[due1].is_deleted is False
    # Current-month occurrence: cancelled iff its due date already passed.
    assert by_date[due0].is_deleted is (due0 < today)

    # The schedule resumed at the first occurrence on/after today.
    expected_period = current if due0 >= today else _shift_period(current, 1)
    expected_due = _due_date_for_period(expected_period, 1)
    assert by_date[expected_due].is_deleted is False


def test_unarchive_weekly_seeds_next_occurrence_when_month_empty(client_db):
    """Weekly resume falls back to the next occurrence when none remain."""
    client, db = client_db
    token = register_and_login(client, "weekly_fallback@test.com")
    today = date.today()
    next_month = _shift_period(today.strftime("%Y-%m"), 1)
    start = _due_date_for_period(next_month, 3)

    bill_id = _create_bill(
        client,
        token,
        {
            "frequency": "weekly",
            "start_date": start.isoformat(),
            "due_day": None,
            "is_paused": True,
        },
    )
    db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill_id).delete()
    db.commit()

    _archive(client, token, bill_id)
    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text

    rows = _rows(db, bill_id)
    assert len(rows) == 1
    assert rows[0].due_date == start


# ---------------------------------------------------------------------------
# Idempotency + tombstones
# ---------------------------------------------------------------------------


def test_unarchive_twice_creates_one_row(client_db):
    """Two consecutive unarchives are idempotent on (bill_id, due_date)."""
    client, db = client_db
    token = register_and_login(client, "double_resume@test.com")
    today = date.today()
    bill_id = _create_bill(client, token, {"is_paused": True, "due_day": today.day})
    _archive(client, token, bill_id)

    first = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert first.status_code == 200, first.text
    second = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert second.status_code == 200, second.text

    rows = _rows(db, bill_id)
    assert len(rows) == 1
    assert rows[0].due_date == today


def test_unarchive_existing_current_instance_not_duplicated(client_db):
    """An already-present current-period instance is not duplicated."""
    client, db = client_db
    token = register_and_login(client, "existing_current@test.com")
    today = date.today()
    bill_id = _create_bill(client, token, {"is_paused": True, "due_day": today.day})
    existing = _insert_instance(db, bill_id, today.strftime("%Y-%m"), today)
    _archive(client, token, bill_id)

    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text

    rows = _rows(db, bill_id)
    assert len(rows) == 1
    assert rows[0].id == existing.id


def test_unarchive_seeds_current_period_even_with_a_future_instance(client_db):
    """An existing next-month instance does not skip the current-period seed."""
    client, db = client_db
    token = register_and_login(client, "existing_future@test.com")
    today = date.today()
    current = today.strftime("%Y-%m")
    next_period = _shift_period(current, 1)
    bill_id = _create_bill(client, token, {"is_paused": True, "due_day": today.day})
    future = _insert_instance(
        db, bill_id, next_period, _due_date_for_period(next_period, today.day)
    )
    _archive(client, token, bill_id)

    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text

    rows = _rows(db, bill_id)
    assert [row.period for row in rows] == [current, next_period]
    assert future.id in [row.id for row in rows]
    assert rows[0].due_date == today


def test_unarchive_respects_tombstone_at_candidate_date(client_db):
    """A soft-deleted row on the target date is not resurrected."""
    client, db = client_db
    token = register_and_login(client, "tombstone_resume@test.com")
    today = date.today()
    bill_id = _create_bill(client, token, {"is_paused": True, "due_day": today.day})
    tombstone = _insert_instance(
        db, bill_id, today.strftime("%Y-%m"), today, is_deleted=True
    )
    _archive(client, token, bill_id)

    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text

    rows = _rows(db, bill_id)
    assert len(rows) == 1
    assert rows[0].id == tombstone.id
    assert rows[0].is_deleted is True


# ---------------------------------------------------------------------------
# Cap-aware re-anchoring
# ---------------------------------------------------------------------------


def test_unarchive_cap_reached_reanchors_then_is_capped_out(client_db):
    """Cap 1 created months ago resumes by re-anchoring to the next cycle."""
    client, db = client_db
    token = register_and_login(client, "cap_reanchor@test.com")
    today = date.today()
    current = today.strftime("%Y-%m")
    expected_period = current
    if _due_date_for_period(current, 1) < today:
        expected_period = _shift_period(current, 1)

    bill_id = _create_bill(
        client,
        token,
        {"is_paused": True, "max_occurrences": 1, "due_day": 1},
    )
    bill = db.get(BillTemplate, bill_id)
    bill.start_period = _shift_period(current, -3)
    db.commit()

    _archive(client, token, bill_id)
    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["max_occurrences"] == 1  # 1 - 0 existing rows
    assert data["start_period"] == expected_period  # re-anchored to the next cycle

    rows = _rows(db, bill_id)
    assert len(rows) == 1
    assert rows[0].due_date == _due_date_for_period(expected_period, 1)

    # A second archive/unarchive resumes the existing instance: capped out.
    _archive(client, token, bill_id)
    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(token))
    assert r.status_code == 200, r.text
    assert len(_rows(db, bill_id)) == 1


def test_unarchive_cap_exhausted_by_existing_rows_creates_nothing(client_db):
    """When rows already meet the cap, the target occurrence is not created."""
    client, db = client_db
    token = register_and_login(client, "cap_exhausted@test.com")
    today = date.today()
    past_period = _shift_period(today.strftime("%Y-%m"), -3)

    bill_id = _create_bill(
        client,
        token,
        {"is_paused": True, "max_occurrences": 1, "due_day": 1},
    )
    bill = db.get(BillTemplate, bill_id)
    bill.start_period = past_period
    _insert_instance(db, bill_id, past_period, _due_date_for_period(past_period, 1))
    db.commit()

    db.expire_all()
    bill = db.get(BillTemplate, bill_id)
    created = seed_resumed_occurrences(db, bill, today)
    db.commit()

    assert created == []
    assert bill.max_occurrences == 1  # cap not reduced further
    assert bill.start_period == past_period  # schedule not re-anchored
    assert len(_rows(db, bill_id)) == 1


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------


def test_unarchive_other_user_returns_404(client_db):
    client, _ = client_db
    tok_a = register_and_login(client, "owner@test.com")
    tok_b = register_and_login(client, "intruder@test.com")
    bill_id = _create_bill(client, tok_a)

    r = client.post(f"/bills/{bill_id}/unarchive", headers=auth(tok_b))
    assert r.status_code == 404


def test_unarchive_missing_bill_returns_404(client_db):
    client, _ = client_db
    token = register_and_login(client, "missing@test.com")

    r = client.post("/bills/99999/unarchive", headers=auth(token))
    assert r.status_code == 404
