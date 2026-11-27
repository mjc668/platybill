"""Tests for two-tier BNPL instalment deduplication (Tier 1 skip vs Tier 2 flag)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.core.config import settings
from app.models.bill import PaymentInstance
from app.models.import_draft import ImportDraft, ImportSource, ImportStatus
from app.models.user import User
from app.services.bill_import import import_document_drafts
from tests.conftest import auth, register_and_login, sync_payments

REF_DATE = date(2026, 11, 24)


def _png_bytes(tag: str) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + tag.encode("utf-8")


def _upload(client, token: str, data: bytes, name: str = "orders.png"):
    return client.post(
        "/import/upload",
        files={"file": (name, data, "image/png")},
        headers=auth(token),
    )


def _bnpl_payload(*rows: tuple[str, float, str, str]) -> dict:
    """Build a vision JSON payload from (merchant, amount, due_date, label) tuples."""
    return {
        "provider": None,
        "amount": None,
        "currency": "AUD",
        "due_date": None,
        "period": None,
        "confidence": 0.95,
        "installments": [
            {
                "merchant": merchant,
                "amount": amount,
                "due_date": due_date,
                "installment_label": label,
            }
            for merchant, amount, due_date, label in rows
        ],
    }


def test_tier1_same_row_imported_twice_skips_duplicate(client_db):
    """Same merchant/amount/date/instalment imported twice -> 1 draft, skipped_duplicates == 1."""
    client, db = client_db
    register_and_login(client, "bnpl_tier1@test.com")
    user = db.query(User).filter(User.email == "bnpl_tier1@test.com").one()

    payload = _bnpl_payload(("Target", 28.50, "Sun, 6 Dec", "2 of 4"))

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.user_today", return_value=REF_DATE),
        patch("app.services.bill_extract.generate_json", return_value=payload),
    ):
        first = import_document_drafts(
            db,
            user_id=user.id,
            data=_png_bytes("shot-a"),
            filename="shot-a.png",
            content_type="image/png",
            source=ImportSource.upload,
        )
        second = import_document_drafts(
            db,
            user_id=user.id,
            data=_png_bytes("shot-b"),
            filename="shot-b.png",
            content_type="image/png",
            source=ImportSource.upload,
        )

    assert len(first.drafts) == 1
    assert first.skipped_duplicates == 0
    assert not (first.drafts[0].meta or {}).get("possible_duplicate")
    assert not (first.drafts[0].meta or {}).get("warnings")

    assert second.drafts == []
    assert second.skipped_duplicates == 1
    assert db.query(ImportDraft).count() == 1


def test_tier2_different_instalment_number_creates_flagged_draft(client_db):
    """Same merchant/amount/date with a different instalment number -> draft created & flagged."""
    client, db = client_db
    token = register_and_login(client, "bnpl_tier2_inst@test.com")

    payload_first = _bnpl_payload(("Target", 28.50, "Sun, 6 Dec", "2 of 4"))
    payload_second = _bnpl_payload(("Target", 28.50, "Sun, 6 Dec", "3 of 4"))

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.user_today", return_value=REF_DATE),
    ):
        with patch(
            "app.services.bill_extract.generate_json", return_value=payload_first
        ):
            r1 = _upload(client, token, _png_bytes("plan-1"), name="plan1.png")
        assert r1.status_code == 201, r1.text
        first_draft = r1.json()["drafts"][0]

        with patch(
            "app.services.bill_extract.generate_json", return_value=payload_second
        ):
            r2 = _upload(client, token, _png_bytes("plan-2"), name="plan2.png")

    assert r2.status_code == 201, r2.text
    body = r2.json()
    assert body["skipped_duplicates"] == 0
    assert len(body["drafts"]) == 1

    flagged = body["drafts"][0]
    meta = flagged["meta"]
    assert meta["type"] == "afterpay"
    assert meta["installment_number"] == 3
    assert meta["total_installments"] == 4
    assert meta["installment_label"] == "3 of 4"
    assert meta["possible_duplicate"] is True

    warnings = meta["warnings"]
    assert len(warnings) == 1
    assert f"draft #{first_draft['id']}" in warnings[0]
    assert "Afterpay: Target" in warnings[0]
    assert "$28.50" in warnings[0]
    assert "6 Dec" in warnings[0]

    assert db.query(ImportDraft).count() == 2


def test_tier2_existing_payment_instance_creates_flagged_draft_without_extra_instance(
    client_db,
):
    """Existing template PaymentInstance at same amount+date -> draft created & flagged,
    skipped_duplicates == 0, and no extra PaymentInstance generated."""
    client, db = client_db
    token = register_and_login(client, "bnpl_tier2_inst_pi@test.com")

    r_bill = client.post(
        "/bills",
        json={
            "name": "Afterpay: Target",
            "category": "other",
            "frequency": "weekly",
            "interval_count": 2,
            "max_occurrences": 4,
            "start_date": "2026-11-22",
            "amount": "28.50",
            "currency": "AUD",
        },
        headers=auth(token),
    )
    assert r_bill.status_code == 201, r_bill.text
    bill_id = r_bill.json()["id"]
    sync_payments(client, token, "2026-12")

    existing_instances = (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == bill_id)
        .order_by(PaymentInstance.due_date)
        .all()
    )
    dec6_inst = next(i for i in existing_instances if i.due_date == date(2026, 12, 6))
    instances_before = len(existing_instances)

    payload = _bnpl_payload(("Target", 28.50, "Sun, 6 Dec", "2 of 4"))
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.user_today", return_value=REF_DATE),
        patch("app.services.bill_extract.generate_json", return_value=payload),
    ):
        resp = _upload(client, token, _png_bytes("target-dec6"), name="target.png")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["skipped_duplicates"] == 0
    assert len(body["drafts"]) == 1

    draft = body["drafts"][0]
    meta = draft["meta"]
    assert meta["type"] == "afterpay"
    assert meta["merchant"] == "Target"
    assert meta["installment_number"] == 2
    assert meta["total_installments"] == 4
    assert meta["possible_duplicate"] is True
    assert meta["warnings"] == [
        f"Possible duplicate: Afterpay: Target already has $28.50 due 6 Dec "
        f"(payment instance #{dec6_inst.id})."
    ]

    # No extra payment instance generated for the template.
    instances_after = (
        db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill_id).count()
    )
    assert instances_after == instances_before


def test_unrelated_merchant_row_drafts_normally_without_flag_or_warning(client_db):
    """Regression: a row with a different merchant drafts cleanly with no flag or warning."""
    client, db = client_db
    token = register_and_login(client, "bnpl_unrelated@test.com")

    # Seed both a Target payment instance and a Target draft on 6 Dec for $28.50.
    r_bill = client.post(
        "/bills",
        json={
            "name": "Afterpay: Target",
            "category": "other",
            "frequency": "weekly",
            "interval_count": 2,
            "max_occurrences": 4,
            "start_date": "2026-11-22",
            "amount": "28.50",
            "currency": "AUD",
        },
        headers=auth(token),
    )
    assert r_bill.status_code == 201
    sync_payments(client, token, "2026-12")

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.user_today", return_value=REF_DATE),
    ):
        with patch(
            "app.services.bill_extract.generate_json",
            return_value=_bnpl_payload(("Target", 28.50, "Sun, 6 Dec", "2 of 4")),
        ):
            r_target = _upload(client, token, _png_bytes("t1"), name="t1.png")
        assert r_target.status_code == 201

        with patch(
            "app.services.bill_extract.generate_json",
            return_value=_bnpl_payload(("eBay", 28.50, "Sun, 6 Dec", "2 of 4")),
        ):
            r_ebay = _upload(client, token, _png_bytes("ebay1"), name="ebay.png")

    assert r_ebay.status_code == 201, r_ebay.text
    body = r_ebay.json()
    assert body["skipped_duplicates"] == 0
    assert len(body["drafts"]) == 1

    draft = body["drafts"][0]
    assert draft["provider"] == "Afterpay: eBay"
    assert "possible_duplicate" not in draft["meta"]
    assert "warnings" not in draft["meta"]


def test_tier2_non_bnpl_draft_appends_warning_without_overwriting_row_warnings(
    client_db,
):
    """Matching a draft without BNPL meta triggers Tier 2 and appends to existing row warnings."""
    client, db = client_db
    token = register_and_login(client, "bnpl_non_meta_draft@test.com")
    user = db.query(User).filter(User.email == "bnpl_non_meta_draft@test.com").one()

    # Seed a plain (non-BNPL) draft at the same merchant, amount, and date.
    plain_draft = ImportDraft(
        user_id=user.id,
        source=ImportSource.upload,
        source_ref="upload:plain-target-seed",
        filename="receipt.pdf",
        provider="Afterpay: Target",
        amount=Decimal("28.50"),
        currency="AUD",
        due_date=date(2026, 12, 6),
        period="2026-12",
        status=ImportStatus.pending,
        meta=None,
    )
    db.add(plain_draft)
    db.commit()
    db.refresh(plain_draft)

    # 6 Dec 2026 is a Sunday, so "Tue, 6 Dec 2026" produces an existing weekday warning
    # on BnplInstallmentRow.to_meta().
    payload = _bnpl_payload(("Target", 28.50, "Tue, 6 Dec 2026", "2 of 4"))
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.user_today", return_value=REF_DATE),
        patch("app.services.bill_extract.generate_json", return_value=payload),
    ):
        resp = _upload(client, token, _png_bytes("warn-merge"), name="warn.png")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["skipped_duplicates"] == 0
    assert len(body["drafts"]) == 1

    meta = body["drafts"][0]["meta"]
    assert meta["possible_duplicate"] is True
    assert meta["installment_number"] == 2
    assert meta["total_installments"] == 4
    assert len(meta["warnings"]) == 2
    assert "Tue" in meta["warnings"][0]
    assert f"draft #{plain_draft.id}" in meta["warnings"][1]


def test_tier1_exact_match_wins_even_when_earlier_tier2_draft_exists(client_db):
    """If draft #1 has a different instalment and draft #2 matches exactly, Tier 1 still skips."""
    client, db = client_db
    register_and_login(client, "bnpl_tier1_wins@test.com")
    user = db.query(User).filter(User.email == "bnpl_tier1_wins@test.com").one()

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.user_today", return_value=REF_DATE),
    ):
        with patch(
            "app.services.bill_extract.generate_json",
            return_value=_bnpl_payload(("Target", 28.50, "Sun, 6 Dec", "1 of 4")),
        ):
            r1 = import_document_drafts(
                db,
                user_id=user.id,
                data=_png_bytes("first-1of4"),
                filename="s1.png",
                content_type="image/png",
                source=ImportSource.upload,
            )
        assert len(r1.drafts) == 1

        with patch(
            "app.services.bill_extract.generate_json",
            return_value=_bnpl_payload(("Target", 28.50, "Sun, 6 Dec", "2 of 4")),
        ):
            r2 = import_document_drafts(
                db,
                user_id=user.id,
                data=_png_bytes("second-2of4"),
                filename="s2.png",
                content_type="image/png",
                source=ImportSource.upload,
            )
        assert len(r2.drafts) == 1
        assert r2.drafts[0].meta["possible_duplicate"] is True

        # Re-importing 2 of 4 must hit Tier 1 against draft #2 and skip.
        with patch(
            "app.services.bill_extract.generate_json",
            return_value=_bnpl_payload(("Target", 28.50, "Sun, 6 Dec", "2 of 4")),
        ):
            r3 = import_document_drafts(
                db,
                user_id=user.id,
                data=_png_bytes("third-2of4-repeat"),
                filename="s3.png",
                content_type="image/png",
                source=ImportSource.upload,
            )

    assert r3.drafts == []
    assert r3.skipped_duplicates == 1
    assert db.query(ImportDraft).count() == 2
