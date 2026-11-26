"""Tests for BNPL ad-hoc confirmation, recurring-template guard, and single-instance guarantee."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.bill import BillTemplate, PaymentInstance
from app.models.import_draft import ImportDraft, ImportSource, ImportStatus
from app.models.user import User
from app.services.recurrence import (
    ensure_current_period_instances,
    generate_future_instances,
)
from tests.conftest import auth, register_and_login

_LIVE_BNPL_META = {
    "type": "afterpay",
    "source_kind": "bnpl_list",
    "merchant": "Bing Lee Electri...",
    "installment_number": 3,
    "total_installments": 4,
    "installment_label": "3 of 4",
    "remaining_installments": 1,
    "interval_count": 2,
    "max_occurrences": 4,
}


def _create_account(client, token: str, name: str) -> dict:
    r = client.post("/bank-accounts", json={"name": name}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _create_bill(client, token: str, **overrides) -> dict:
    body = {
        "name": "Test Bill",
        "category": "other",
        "frequency": "monthly",
        "amount": "71.50",
        "currency": "AUD",
        "due_day": 15,
        "is_paused": False,
        **overrides,
    }
    r = client.post("/bills", json=body, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _insert_draft(
    db,
    *,
    user_id: int,
    source_ref: str,
    provider: str | None = "Afterpay: Bing Lee Electri...",
    amount: Decimal = Decimal("71.50"),
    due_date: date = date(2026, 12, 6),
    matched_bill_id: int | None = None,
    meta: dict | None = None,
) -> ImportDraft:
    draft = ImportDraft(
        user_id=user_id,
        source=ImportSource.upload,
        source_ref=source_ref,
        provider=provider,
        amount=amount,
        currency="AUD",
        due_date=due_date,
        period=due_date.strftime("%Y-%m"),
        matched_bill_id=matched_bill_id,
        status=ImportStatus.pending,
        meta=dict(meta) if meta is not None else None,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def test_bnpl_draft_adhoc_confirm_creates_single_unlinked_instance(client_db):
    """BNPL draft + ad_hoc=true creates an unlinked instance using meta.merchant (or provider fallback)."""
    client, db = client_db
    token = register_and_login(client, "bnpl_adhoc@test.com")
    user = db.query(User).filter(User.email == "bnpl_adhoc@test.com").one()
    acc = _create_account(client, token, "ING Everyday")

    draft = _insert_draft(
        db,
        user_id=user.id,
        source_ref="upload:bnpl-adhoc-1",
        provider="Afterpay: Bing Lee Electri...",
        amount=Decimal("71.50"),
        due_date=date(2026, 12, 6),
        matched_bill_id=None,
        meta=_LIVE_BNPL_META,
    )

    r = client.post(
        f"/import/drafts/{draft.id}/confirm",
        json={"ad_hoc": True, "account_id": acc["id"]},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["draft_id"] == draft.id
    assert body["bill_id"] is None
    assert body["created_instance"] is True

    inst = db.get(PaymentInstance, body["instance_id"])
    assert inst is not None
    assert inst.bill_id is None
    assert inst.user_id == user.id
    assert inst.label == "Bing Lee Electri..."
    assert inst.amount == Decimal("71.50")
    assert inst.due_date == date(2026, 12, 6)
    assert inst.period == "2026-12"
    assert inst.account_id == acc["id"]
    assert inst.amount_estimated is False
    # No BillTemplate was invented.
    assert db.query(BillTemplate).filter(BillTemplate.user_id == user.id).count() == 0

    # Fallback: when meta has no merchant and account_id is omitted, falls back to provider + Unspecified.
    draft_fallback = _insert_draft(
        db,
        user_id=user.id,
        source_ref="upload:bnpl-adhoc-2",
        provider="Afterpay: Kmart",
        amount=Decimal("28.50"),
        due_date=date(2026, 12, 10),
        matched_bill_id=None,
        meta={"type": "afterpay", "interval_count": 2, "max_occurrences": 4},
    )
    r2 = client.post(
        f"/import/drafts/{draft_fallback.id}/confirm",
        json={"ad_hoc": True},
        headers=auth(token),
    )
    assert r2.status_code == 200, r2.text
    inst2 = db.get(PaymentInstance, r2.json()["instance_id"])
    assert inst2 is not None
    assert inst2.bill_id is None
    assert inst2.label == "Afterpay: Kmart"
    assert inst2.account_id is None
    assert inst2.amount_estimated is False


@pytest.mark.parametrize(
    "bill_overrides",
    [
        {
            "name": "Afterpay: Bing Lee Weekly",
            "frequency": "weekly",
            "interval_count": 2,
            "max_occurrences": 4,
            "start_date": "2026-11-08",
            "due_day": None,
        },
        {
            "name": "Afterpay: Bing Lee Monthly",
            "frequency": "monthly",
            "due_day": 6,
        },
        {
            "name": "Afterpay: Bing Lee Annual",
            "frequency": "annual",
            "due_day": 6,
            "due_month": 12,
        },
    ],
)
def test_bnpl_draft_confirm_against_recurring_template_returns_409_and_creates_nothing(
    client_db, bill_overrides
):
    """BNPL draft + ad_hoc=false against any recurring template returns 409 and creates no instances."""
    client, db = client_db
    email = f"bnpl_409_{bill_overrides['frequency']}@test.com"
    token = register_and_login(client, email)
    user = db.query(User).filter(User.email == email).one()

    bill = _create_bill(client, token, **bill_overrides)
    draft = _insert_draft(
        db,
        user_id=user.id,
        source_ref=f"upload:bnpl-409-{bill_overrides['frequency']}",
        matched_bill_id=bill["id"],
        meta=_LIVE_BNPL_META,
    )

    before_count = db.query(PaymentInstance).count()
    r = client.post(
        f"/import/drafts/{draft.id}/confirm",
        json={"bill_id": bill["id"], "ad_hoc": False},
        headers=auth(token),
    )
    assert r.status_code == 409, r.text
    assert (
        "BNPL instalments must be confirmed as one-off payments" in r.json()["detail"]
    )

    # No instances were created and the draft remains pending.
    assert db.query(PaymentInstance).count() == before_count
    db.refresh(draft)
    assert draft.status == ImportStatus.pending


def test_bnpl_draft_confirm_against_one_off_template_succeeds_single_instance(
    client_db,
):
    """BNPL draft + ad_hoc=false against a one_off template succeeds with a single instance."""
    client, db = client_db
    token = register_and_login(client, "bnpl_oneoff@test.com")
    user = db.query(User).filter(User.email == "bnpl_oneoff@test.com").one()
    acc = _create_account(client, token, "Everyday")

    one_off_bill = _create_bill(
        client,
        token,
        name="Afterpay: Bing Lee One-off",
        frequency="one_off",
        due_day=6,
        due_month=12,
    )
    draft = _insert_draft(
        db,
        user_id=user.id,
        source_ref="upload:bnpl-oneoff-1",
        amount=Decimal("71.50"),
        due_date=date(2026, 12, 6),
        matched_bill_id=one_off_bill["id"],
        meta=_LIVE_BNPL_META,
    )

    r = client.post(
        f"/import/drafts/{draft.id}/confirm",
        json={"bill_id": one_off_bill["id"], "ad_hoc": False, "account_id": acc["id"]},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bill_id"] == one_off_bill["id"]
    assert body["created_instance"] is True

    instances = (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == one_off_bill["id"])
        .all()
    )
    assert len(instances) == 1
    inst = instances[0]
    assert inst.id == body["instance_id"]
    assert inst.amount == Decimal("71.50")
    assert inst.due_date == date(2026, 12, 6)
    assert inst.account_id == acc["id"]
    assert inst.amount_estimated is False


def test_confirming_any_import_draft_creates_at_most_one_instance(client_db):
    """Confirming any import draft never invokes recurrence generation and creates exactly one instance."""
    client, db = client_db
    token = register_and_login(client, "single_inst@test.com")
    user = db.query(User).filter(User.email == "single_inst@test.com").one()

    monthly_bill = _create_bill(
        client, token, name="Electricity", frequency="monthly", due_day=15
    )
    weekly_bill = _create_bill(
        client,
        token,
        name="Gym",
        frequency="weekly",
        interval_count=2,
        max_occurrences=4,
        start_date="2026-12-01",
        due_day=None,
    )
    one_off_bill = _create_bill(
        client,
        token,
        name="Afterpay: Special",
        frequency="one_off",
        due_day=20,
        due_month=12,
    )

    draft_monthly = _insert_draft(
        db,
        user_id=user.id,
        source_ref="upload:single-monthly",
        provider="Electricity",
        amount=Decimal("120.00"),
        due_date=date(2026, 12, 15),
        matched_bill_id=monthly_bill["id"],
        meta=None,
    )
    draft_weekly = _insert_draft(
        db,
        user_id=user.id,
        source_ref="upload:single-weekly",
        provider="Gym",
        amount=Decimal("40.00"),
        due_date=date(2026, 12, 1),
        matched_bill_id=weekly_bill["id"],
        meta=None,
    )
    draft_bnpl_adhoc = _insert_draft(
        db,
        user_id=user.id,
        source_ref="upload:single-bnpl-adhoc",
        due_date=date(2026, 12, 6),
        meta=_LIVE_BNPL_META,
    )
    draft_bnpl_oneoff = _insert_draft(
        db,
        user_id=user.id,
        source_ref="upload:single-bnpl-oneoff",
        due_date=date(2026, 12, 20),
        matched_bill_id=one_off_bill["id"],
        meta=_LIVE_BNPL_META,
    )

    with (
        patch("app.services.recurrence.generate_future_instances") as mock_gen,
        patch("app.services.recurrence.ensure_current_period_instances") as mock_ensure,
    ):
        for draft, payload in [
            (draft_monthly, {"bill_id": monthly_bill["id"]}),
            (draft_weekly, {"bill_id": weekly_bill["id"]}),
            (draft_bnpl_adhoc, {"ad_hoc": True}),
            (draft_bnpl_oneoff, {"bill_id": one_off_bill["id"]}),
        ]:
            before = db.query(PaymentInstance).count()
            r = client.post(
                f"/import/drafts/{draft.id}/confirm",
                json=payload,
                headers=auth(token),
            )
            assert r.status_code == 200, r.text
            assert db.query(PaymentInstance).count() == before + 1

        mock_gen.assert_not_called()
        mock_ensure.assert_not_called()

    assert (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == monthly_bill["id"])
        .count()
        == 1
    )
    assert (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == weekly_bill["id"])
        .count()
        == 1
    )
    assert (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == one_off_bill["id"])
        .count()
        == 1
    )


def test_bnpl_cadence_metadata_preserved_and_inert(client_db):
    """Cadence metadata stays intact in draft.meta after confirm and never drives generation."""
    client, db = client_db
    token = register_and_login(client, "bnpl_meta@test.com")
    user = db.query(User).filter(User.email == "bnpl_meta@test.com").one()

    meta_with_warning = {
        **_LIVE_BNPL_META,
        "warnings": ["Date year adjusted from 2025 to 2026 to match Sunday"],
    }
    draft = _insert_draft(
        db,
        user_id=user.id,
        source_ref="upload:bnpl-meta-1",
        due_date=date(2026, 12, 6),
        meta=meta_with_warning,
    )

    r = client.post(
        f"/import/drafts/{draft.id}/confirm",
        json={"ad_hoc": True},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text

    # Cadence metadata is preserved in DB and API output.
    db.refresh(draft)
    assert draft.meta == meta_with_warning
    listed = client.get("/import/drafts?status=confirmed", headers=auth(token)).json()
    confirmed_row = next(d for d in listed if d["id"] == draft.id)
    assert confirmed_row["meta"]["interval_count"] == 2
    assert confirmed_row["meta"]["max_occurrences"] == 4
    assert confirmed_row["meta"]["installment_label"] == "3 of 4"
    assert confirmed_row["meta"]["remaining_installments"] == 1
    assert confirmed_row["meta"]["warnings"] == meta_with_warning["warnings"]

    # Running recurrence generation afterwards creates zero extra instances.
    ensure_current_period_instances(db, "2026-12", user.id)
    created, bill_count = generate_future_instances(
        db, user.id, months=3, today=date(2026, 12, 1)
    )
    assert created == 0
    assert bill_count == 0
    assert db.query(PaymentInstance).count() == 1
