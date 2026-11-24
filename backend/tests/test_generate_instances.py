"""Integration tests for POST /bills/generate-instances (series generator).

Covers the eligible-template filter, the current-month+1..+months range,
idempotency via (bill_id, due_date), ownership errors, and period selection
per frequency/interval.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.bill import PaymentInstance, PaymentStatus
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


def _create_bill(client, token: str, overrides: dict | None = None) -> int:
    payload = {**_BILL, **(overrides or {})}
    r = client.post("/bills", json=payload, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _shift(period: str, delta: int) -> str:
    year, month = map(int, period.split("-"))
    total = year * 12 + month - 1 + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _generate(client, token: str, **body):
    return client.post("/bills/generate-instances", json=body, headers=auth(token))


def _periods_in_db(db, bill_id: int) -> set[str]:
    return {
        row.period
        for row in db.query(PaymentInstance.period).filter(
            PaymentInstance.bill_id == bill_id
        )
    }


# ---------------------------------------------------------------------------
# Range and response shape
# ---------------------------------------------------------------------------


def test_generate_defaults_to_six_months(client):
    token = register_and_login(client, "gen_default@test.com")
    r = _generate(client, token)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 0, "bill_count": 0, "months": 6}


def test_monthly_generates_current_plus_one_through_plus_months(client_db):
    client, db = client_db
    token = register_and_login(client, "gen_monthly@test.com")
    bill_id = _create_bill(client, token)

    r = _generate(client, token, months=6)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 6, "bill_count": 1, "months": 6}

    current = _current_month()
    assert _periods_in_db(db, bill_id) == {
        _shift(current, offset) for offset in range(1, 7)
    }


def test_generate_is_idempotent(client_db):
    client, db = client_db
    token = register_and_login(client, "gen_idempotent@test.com")
    bill_id = _create_bill(client, token)
    current = _current_month()

    first = _generate(client, token, months=3)
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 3

    second = _generate(client, token, months=3)
    assert second.status_code == 200, second.text
    assert second.json() == {"created": 0, "bill_count": 1, "months": 3}
    assert _periods_in_db(db, bill_id) == {
        _shift(current, offset) for offset in (1, 2, 3)
    }


def test_generate_periods_per_frequency(client_db):
    client, db = client_db
    token = register_and_login(client, "gen_frequency@test.com")
    current = _current_month()

    monthly = _create_bill(client, token, {"name": "Monthly"})
    every2 = _create_bill(client, token, {"name": "Every 2", "interval_count": 2})
    quarterly = _create_bill(client, token, {"name": "Quarterly", "interval_count": 3})
    annual = _create_bill(client, token, {"name": "Annual", "frequency": "annual"})

    r = _generate(client, token, months=12)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["months"] == 12
    assert data["bill_count"] == 4

    assert _periods_in_db(db, monthly) == {
        _shift(current, offset) for offset in range(1, 13)
    }
    assert _periods_in_db(db, every2) == {
        _shift(current, offset) for offset in range(2, 13, 2)
    }
    assert _periods_in_db(db, quarterly) == {
        _shift(current, offset) for offset in range(3, 13, 3)
    }
    # Annual anchored at the current month → only +12 falls in range.
    assert _periods_in_db(db, annual) == {_shift(current, 12)}
    assert data["created"] == 12 + 6 + 4 + 1


def test_weekly_generates_all_occurrences(client_db):
    client, db = client_db
    token = register_and_login(client, "gen_weekly@test.com")
    current = _current_month()

    # Anchor on the first day of the current month so occurrences are dense.
    start = date(int(current[:4]), int(current[5:]), 1)
    bill_id = _create_bill(
        client,
        token,
        {
            "name": "Weekly",
            "frequency": "weekly",
            "start_date": start.isoformat(),
            "due_day": None,
        },
    )

    r = _generate(client, token, months=2)
    assert r.status_code == 200, r.text
    target_periods = {_shift(current, 1), _shift(current, 2)}

    # Independent oracle: step 7 days at a time from the anchor.
    expected: set[date] = set()
    cursor = start
    while cursor.strftime("%Y-%m") <= _shift(current, 2):
        if cursor.strftime("%Y-%m") in target_periods:
            expected.add(cursor)
        cursor += timedelta(days=7)

    assert r.json()["created"] == len(expected)
    due_dates = {
        row.due_date
        for row in db.query(PaymentInstance).filter(
            PaymentInstance.bill_id == bill_id,
            PaymentInstance.period.in_(target_periods),
        )
    }
    assert due_dates == expected


def test_weekly_soft_deleted_occurrence_blocks_only_that_date(client_db):
    client, db = client_db
    token = register_and_login(client, "gen_weekly_tombstone@test.com")
    current = _current_month()
    target_period = _shift(current, 1)
    start = date(int(current[:4]), int(current[5:]), 1)

    bill_id = _create_bill(
        client,
        token,
        {
            "name": "Weekly",
            "frequency": "weekly",
            "start_date": start.isoformat(),
            "due_day": None,
        },
    )

    # First weekly occurrence that falls in the target month.
    blocked_due_date = start
    while blocked_due_date.strftime("%Y-%m") != target_period:
        blocked_due_date += timedelta(days=7)

    db.add(
        PaymentInstance(
            bill_id=bill_id,
            period=target_period,
            due_date=blocked_due_date,
            amount=Decimal("120.00"),
            status=PaymentStatus.upcoming,
            is_deleted=True,
        )
    )
    db.commit()

    r = _generate(client, token, months=1)
    assert r.status_code == 200, r.text

    rows = (
        db.query(PaymentInstance)
        .filter(
            PaymentInstance.bill_id == bill_id,
            PaymentInstance.period == target_period,
        )
        .all()
    )
    by_due_date = {row.due_date: row for row in rows}
    # The tombstone is retained and blocks only its own due date.
    assert blocked_due_date in by_due_date
    assert by_due_date[blocked_due_date].is_deleted is True

    expected_active = {
        start + timedelta(days=7 * k)
        for k in range(0, 40)
        if (start + timedelta(days=7 * k)).strftime("%Y-%m") == target_period
        and start + timedelta(days=7 * k) != blocked_due_date
    }
    assert {row.due_date for row in rows if not row.is_deleted} == expected_active
    assert r.json()["created"] == len(expected_active)


def test_soft_deleted_instance_acts_as_tombstone(client_db):
    client, db = client_db
    token = register_and_login(client, "gen_tombstone@test.com")
    bill_id = _create_bill(client, token)
    target = _shift(_current_month(), 1)
    db.add(
        PaymentInstance(
            bill_id=bill_id,
            period=target,
            due_date=date(int(target[:4]), int(target[5:]), 15),
            amount=Decimal("120.00"),
            status=PaymentStatus.upcoming,
            is_deleted=True,
        )
    )
    db.commit()

    r = _generate(client, token, months=1)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 0
    assert _periods_in_db(db, bill_id) == {target}


# ---------------------------------------------------------------------------
# Eligibility and ownership
# ---------------------------------------------------------------------------


def test_paused_archived_and_one_off_are_skipped(client_db):
    client, db = client_db
    token = register_and_login(client, "gen_skipped@test.com")

    paused = _create_bill(client, token, {"name": "Paused", "is_paused": True})
    archived = _create_bill(client, token, {"name": "Archived"})
    r = client.post(f"/bills/{archived}/archive", headers=auth(token))
    assert r.status_code == 204, r.text
    one_off = _create_bill(client, token, {"name": "One-off", "frequency": "one_off"})

    r = _generate(client, token, months=6)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 0, "bill_count": 0, "months": 6}
    for bill_id in (paused, archived, one_off):
        assert _periods_in_db(db, bill_id) == set()


def test_bill_ids_limits_generation_to_selected_bills(client_db):
    client, db = client_db
    token = register_and_login(client, "gen_subset@test.com")

    selected = _create_bill(client, token, {"name": "Selected"})
    other = _create_bill(client, token, {"name": "Other"})

    r = _generate(client, token, months=2, bill_ids=[selected])
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 2, "bill_count": 1, "months": 2}

    current = _current_month()
    assert _periods_in_db(db, selected) == {
        _shift(current, 1),
        _shift(current, 2),
    }
    assert _periods_in_db(db, other) == set()


def test_foreign_or_unknown_bill_id_returns_404(client_db):
    client, db = client_db
    token_a = register_and_login(client, "gen_owner_a@test.com")
    token_b = register_and_login(client, "gen_owner_b@test.com")
    foreign = _create_bill(client, token_b, {"name": "B's bill"})

    r = _generate(client, token_a, bill_ids=[foreign])
    assert r.status_code == 404

    r = _generate(client, token_a, bill_ids=[999999])
    assert r.status_code == 404

    # A valid id mixed with a foreign one still fails before creating anything.
    own = _create_bill(client, token_a, {"name": "A's bill"})
    r = _generate(client, token_a, bill_ids=[own, foreign])
    assert r.status_code == 404
    assert _periods_in_db(db, own) == set()


# ---------------------------------------------------------------------------
# Validation and auth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("months", [0, 25, -1, "abc"])
def test_invalid_months_returns_422(client, months):
    token = register_and_login(client, "gen_bounds@test.com")
    r = _generate(client, token, months=months)
    assert r.status_code == 422, months


@pytest.mark.parametrize("months", [1, 24])
def test_boundary_months_are_valid(client, months):
    token = register_and_login(client, "gen_bounds_ok@test.com")
    r = _generate(client, token, months=months)
    assert r.status_code == 200, r.text
    assert r.json()["months"] == months


def test_requires_authentication(client):
    r = client.post("/bills/generate-instances", json={"months": 6})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# max_occurrences
# ---------------------------------------------------------------------------


def test_monthly_generation_stops_at_cap(client_db):
    """Cap 3 anchored this month → only +1 and +2 fall before the cap."""
    client, db = client_db
    token = register_and_login(client, "gen_cap_monthly@test.com")
    current = _current_month()
    bill_id = _create_bill(client, token, {"max_occurrences": 3})

    r = _generate(client, token, months=6)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 2, "bill_count": 1, "months": 6}
    assert _periods_in_db(db, bill_id) == {
        _shift(current, 1),
        _shift(current, 2),
    }


def test_weekly_generation_stops_at_cap(client_db):
    """A weekly cap counts individual occurrences, across month boundaries."""
    client, db = client_db
    token = register_and_login(client, "gen_cap_weekly@test.com")
    current = _current_month()
    start = date(int(current[:4]), int(current[5:]), 1)
    bill_id = _create_bill(
        client,
        token,
        {
            "name": "Weekly capped",
            "frequency": "weekly",
            "start_date": start.isoformat(),
            "due_day": None,
            "max_occurrences": 8,
        },
    )
    target_periods = {_shift(current, 1), _shift(current, 2)}

    r = _generate(client, token, months=2)
    assert r.status_code == 200, r.text

    # Independent oracle: the first eight 7-day steps from the anchor.
    expected = {
        start + timedelta(days=7 * k)
        for k in range(8)
        if (start + timedelta(days=7 * k)).strftime("%Y-%m") in target_periods
    }
    assert r.json()["created"] == len(expected)
    all_dues = {
        row.due_date
        for row in db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill_id)
    }
    # The create-time backfill already materialized the current-month steps,
    # so the table holds exactly the first eight 7-day occurrences.
    assert all_dues == {start + timedelta(days=7 * k) for k in range(8)}
    assert {
        due for due in all_dues if due.strftime("%Y-%m") in target_periods
    } == expected


# ---------------------------------------------------------------------------
# Month-anchored interval_count, derived anchor, one_off -> recurring, readability
# ---------------------------------------------------------------------------


def test_monthly_interval_3_anchored_at_sep_produces_dec_and_mar_only(client_db):
    """monthly x 3 anchored at 2026-09 yields 2026-12 and 2027-03, never Oct/Nov."""
    from app.models.bill import BillTemplate
    from app.services.recurrence import backfill_template_instances

    client, db = client_db
    token = register_and_login(client, "gen_q_sep@test.com")
    bill_id = _create_bill(
        client,
        token,
        {
            "name": "Water",
            "frequency": "monthly",
            "interval_count": 3,
            "due_day": 11,
            "amount": "574.13",
            "amount_varies": True,
        },
    )
    template = db.get(BillTemplate, bill_id)
    assert template is not None
    template.start_period = "2026-09"
    db.commit()

    created = backfill_template_instances(db, template, "2026-10", "2027-03")
    assert created == 2
    assert _periods_in_db(db, bill_id) == {"2026-12", "2027-03"}
    dues = {
        row.due_date
        for row in db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill_id)
    }
    assert dues == {date(2026, 12, 11), date(2027, 3, 11)}


def test_monthly_interval_3_without_start_period_derives_anchor_from_latest_instance(
    client_db,
):
    """When start_period is None, anchor derives from the most recent existing instance."""
    from app.models.bill import BillTemplate
    from app.services.recurrence import generate_future_instances

    client, db = client_db
    token = register_and_login(client, "gen_q_derived@test.com")
    bill_id = _create_bill(
        client,
        token,
        {
            "name": "Water",
            "frequency": "monthly",
            "interval_count": 3,
            "due_day": 11,
            "amount": "574.13",
            "amount_varies": True,
        },
    )
    template = db.get(BillTemplate, bill_id)
    assert template is not None
    # Simulate a template with no explicit start_period whose created_at is Nov 2026,
    # while its most recent existing instance was 11 Sep 2026.
    template.start_period = None
    template.created_at = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    db.add(
        PaymentInstance(
            bill_id=bill_id,
            period="2026-09",
            due_date=date(2026, 9, 11),
            amount=Decimal("574.13"),
            amount_estimated=False,
            status=PaymentStatus.paid,
        )
    )
    db.commit()

    created, count = generate_future_instances(
        db,
        template.user_id,
        months=4,
        bill_ids=[bill_id],
        today=date(2026, 11, 24),
    )
    assert count == 1
    assert created == 2
    assert _periods_in_db(db, bill_id) == {"2026-09", "2026-12", "2027-03"}


def test_patch_one_off_to_recurring_backfills_current_period(client_db):
    """Converting a one_off template to recurring backfills the current period."""
    client, db = client_db
    token = register_and_login(client, "gen_oneoff_conv@test.com")
    current = _current_month()
    bill_id = _create_bill(
        client,
        token,
        {
            "name": "Water",
            "frequency": "one_off",
            "due_day": 11,
            "amount": "574.13",
        },
    )
    assert _periods_in_db(db, bill_id) == set()

    r = client.patch(
        f"/bills/{bill_id}",
        json={"frequency": "monthly", "interval_count": 3},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    assert _periods_in_db(db, bill_id) == {current}


def test_variable_bill_generated_instances_are_readable_and_match_created_count(
    client_db,
):
    """Generated amount_varies instances are readable and count matches `created`."""
    from app.models.bill import BillTemplate

    client, db = client_db
    token = register_and_login(client, "gen_var_read@test.com")
    current = _current_month()
    anchor = _shift(current, -2)  # so +1 and +4 are active for monthly x 3
    bill_id = _create_bill(
        client,
        token,
        {
            "name": "Water",
            "frequency": "monthly",
            "interval_count": 3,
            "due_day": 11,
            "amount": "574.13",
            "amount_varies": True,
        },
    )
    # Re-anchor via PATCH start_period
    patch_r = client.patch(
        f"/bills/{bill_id}",
        json={"start_period": anchor},
        headers=auth(token),
    )
    assert patch_r.status_code == 200, patch_r.text
    assert patch_r.json()["start_period"] == anchor

    # Remove any instance created during POST/PATCH outside our target window
    db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill_id).delete()
    db.commit()

    r = _generate(client, token, months=4, bill_ids=[bill_id])
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert created == 2

    # Repeat call is idempotent
    r2 = _generate(client, token, months=4, bill_ids=[bill_id])
    assert r2.status_code == 200, r2.text
    assert r2.json()["created"] == 0

    # Re-read every generated month via GET /bills/payments?include_estimated=true
    readable: list[dict] = []
    for offset in range(1, 5):
        month = _shift(current, offset)
        resp = client.get(
            f"/bills/payments?month={month}&include_estimated=true",
            headers=auth(token),
        )
        assert resp.status_code == 200, resp.text
        readable.extend(row for row in resp.json() if row["bill_id"] == bill_id)

    assert len(readable) == created
    assert {row["period"] for row in readable} == {
        _shift(current, 1),
        _shift(current, 4),
    }
    assert all(row["amount_estimated"] is True for row in readable)

    # Also readable via needs-confirmation?include_future=true
    future_queue = client.get(
        "/bills/payments/needs-confirmation?include_future=true",
        headers=auth(token),
    )
    assert future_queue.status_code == 200, future_queue.text
    future_items = [row for row in future_queue.json() if row["bill_id"] == bill_id]
    assert len(future_items) == created
    assert {row["period"] for row in future_items} == {
        _shift(current, 1),
        _shift(current, 4),
    }

    # Default (no flag) preserves FR-018 behavior: unconfirmed estimates stay out
    default_list = client.get(
        f"/bills/payments?month={_shift(current, 1)}",
        headers=auth(token),
    ).json()
    assert [row for row in default_list if row["bill_id"] == bill_id] == []
    assert db.get(BillTemplate, bill_id) is not None
