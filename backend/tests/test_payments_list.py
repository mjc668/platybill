"""Tests for GET /bills/payments scoping, including the include_overdue flag."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

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


def _previous_period(period: str) -> str:
    year, month = map(int, period.split("-"))
    month -= 1
    if month < 1:
        month = 12
        year -= 1
    return f"{year:04d}-{month:02d}"


def _create_bill(client, token: str, overrides: dict | None = None) -> int:
    r = client.post("/bills", json={**_BILL, **(overrides or {})}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _insert_instance(
    db: Session,
    bill_id: int,
    *,
    period: str,
    due_date: date,
    amount: str = "100.00",
    status: str = "upcoming",
    paid_amount: str | None = None,
    is_deleted: bool = False,
) -> int:
    from app.models.bill import PaymentInstance, PaymentStatus

    instance = PaymentInstance(
        bill_id=bill_id,
        period=period,
        due_date=due_date,
        amount=Decimal(amount),
        status=PaymentStatus(status),
        paid_amount=Decimal(paid_amount) if paid_amount is not None else None,
        is_deleted=is_deleted,
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance.id


def _list(client, token: str, month: str, include_overdue: bool = False) -> list[dict]:
    query = f"?month={month}"
    if include_overdue:
        query += "&include_overdue=true"
    r = client.get(f"/bills/payments{query}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_include_overdue_adds_earlier_unpaid_periods(client_db):
    client, db = client_db
    token = register_and_login(client, "list_overdue@test.com")
    today = date.today()
    current = today.strftime("%Y-%m")
    previous = _previous_period(current)

    bill_id = _create_bill(client, token)
    earlier = _insert_instance(
        db,
        bill_id,
        period=previous,
        due_date=today - timedelta(days=20),
        amount="30.00",
    )
    current_inst = _insert_instance(
        db,
        bill_id,
        period=current,
        due_date=today + timedelta(days=5),
        amount="40.00",
    )

    # Default: the selected month only
    assert [p["id"] for p in _list(client, token, current)] == [current_inst]

    # include_overdue: earlier overdue first (sorted by due date)
    data = _list(client, token, current, include_overdue=True)
    assert [p["id"] for p in data] == [earlier, current_inst]
    assert data[0]["status"] == "overdue"
    assert data[0]["period"] == previous


def test_include_overdue_skips_paid_deleted_and_future_rows(client_db):
    client, db = client_db
    token = register_and_login(client, "list_overdue_skip@test.com")
    today = date.today()
    current = today.strftime("%Y-%m")
    previous = _previous_period(current)

    bill_id = _create_bill(client, token)
    _insert_instance(
        db,
        bill_id,
        period=previous,
        due_date=today - timedelta(days=10),
        status="paid",
        paid_amount="100.00",
    )
    _insert_instance(
        db,
        bill_id,
        period=previous,
        due_date=today - timedelta(days=11),
        is_deleted=True,
    )
    # A future-dated row in an earlier period is not overdue
    _insert_instance(
        db,
        bill_id,
        period=previous,
        due_date=today + timedelta(days=3),
    )
    # A paid or future row in the selected month is still returned by the month scope
    current_paid = _insert_instance(
        db,
        bill_id,
        period=current,
        due_date=today,
        status="paid",
        paid_amount="100.00",
    )

    data = _list(client, token, current, include_overdue=True)
    assert [p["id"] for p in data] == [current_paid]


def test_include_overdue_excludes_other_users(client_db):
    client, db = client_db
    alice = register_and_login(client, "list_overdue_a@test.com")
    bob = register_and_login(client, "list_overdue_b@test.com")
    today = date.today()
    current = today.strftime("%Y-%m")
    previous = _previous_period(current)

    alice_bill = _create_bill(client, alice)
    _insert_instance(
        db,
        alice_bill,
        period=previous,
        due_date=today - timedelta(days=10),
    )

    assert _list(client, bob, current, include_overdue=True) == []


def test_window_days_returns_overdue_and_rolling_window(client_db):
    """The rolling view: all unpaid overdue + everything within +/- 30 days."""
    from datetime import date, timedelta
    from decimal import Decimal

    from app.models.bill import PaymentInstance, PaymentStatus

    client, db = client_db
    token = register_and_login(client, "window@test.com")
    bill_id = _create_bill(client, token)

    today = date.today()

    def add(period: str, due: date, status=PaymentStatus.upcoming, paid=None):
        inst = PaymentInstance(
            bill_id=bill_id,
            period=period,
            due_date=due,
            amount=Decimal("10.00"),
            status=status,
            paid_amount=paid,
        )
        db.add(inst)
        db.commit()
        return inst

    add("2025-01", today - timedelta(days=200))  # long overdue: included
    add("2026-01", today - timedelta(days=10))  # recent overdue: included
    add("2026-02", today + timedelta(days=5))  # due soon: included
    add("2026-03", today + timedelta(days=90))  # far future: excluded
    add("2025-06", today - timedelta(days=120), PaymentStatus.paid, Decimal("10.00"))
    add("2026-04", today - timedelta(days=3), PaymentStatus.paid, Decimal("10.00"))

    rows = client.get("/bills/payments?window_days=30", headers=auth(token)).json()
    due_dates = {row["due_date"] for row in rows}
    assert str(today - timedelta(days=200)) in due_dates
    assert str(today - timedelta(days=10)) in due_dates
    assert str(today + timedelta(days=5)) in due_dates
    assert str(today - timedelta(days=3)) in due_dates  # recently paid
    assert str(today + timedelta(days=90)) not in due_dates
    assert str(today - timedelta(days=120)) not in due_dates
