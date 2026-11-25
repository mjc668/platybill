"""Tests for image-based Afterpay / BNPL instalment screenshot importing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.bill import BillTemplate, PaymentInstance
from app.models.import_draft import ImportDraft, ImportStatus
from app.models.user import User
from app.services import app_settings
from app.services.afterpay_parser import (
    BnplInstallmentRow,
    parse_afterpay_installments_payload,
    parse_afterpay_orders_text,
    parse_bnpl_date,
)
from app.services.bill_extract import extract_document_items
from app.services.bill_import import _message_drafts, poll_directory
from app.services.llm import LlmConfig, LlmError
from tests.conftest import auth, register_and_login, sync_payments

REF_DATE = date(2026, 11, 24)

# ---------------------------------------------------------------------------
# Verbatim OCR transcripts & vision payloads for afterpay-1.png .. afterpay-6.png
# ---------------------------------------------------------------------------

SCREENSHOT_1_OCR = """
20:38
Your orders
4 of 4 • Sun, 27 Dec
M
MARULAN IGA PL... $17.76
4 of 4 • Sun, 27 Dec
Amazon.com.au $31.57
3 of 4 • Sun, 27 Dec
Target $28.50
4 of 4 • 3 Jan, 2027
ebay
eBay $64.58
4 of 4 • 3 Jan, 2027
A
AMCALPHARMA... $75.00
4 of 4 • 3 Jan, 2027
Logo
Smash Forth Pty L... $43.87
4 of 4 • 3 Jan, 2027
Amazon.com.au $31.56
4 of 4 • 10 Jan, 2027
Make multiple payments
"""

SCREENSHOT_2_OCR = """
20:38
Your orders
A
AMCALPHARMA... $75.00
3 of 4 • Sun, 20 Dec
Logo
Smash Forth Pty L... $43.87
3 of 4 • Sun, 20 Dec
U
UNITED BERRIMA $20.00
4 of 4 • Sun, 27 Dec
M
MARULAN IGA PL... $17.76
4 of 4 • Sun, 27 Dec
Amazon.com.au $31.57
3 of 4 • Sun, 27 Dec
Target $28.50
4 of 4 • 3 Jan, 2027
ebay
eBay $64.58
4 of 4 • 3 Jan, 2027
A
AMCALPHARMA... $75.00
4 of 4 • 3 Jan, 2027
Make multiple payments
"""

SCREENSHOT_3_OCR = """
20:38
Your orders
BING LEE
Bing Lee Electrics ... $71.50
4 of 4 • Sun, 13 Dec
U
UNITED BERRIMA $20.00
3 of 4 • Sun, 13 Dec
M
MARULAN IGA PL... $17.78
3 of 4 • Sun, 13 Dec
Amazon.com.au $31.57
2 of 4 • Sun, 13 Dec
Target $28.50
3 of 4 • Sun, 20 Dec
ebay
eBay $64.60
3 of 4 • Sun, 20 Dec
A
AMCALPHARMA... $75.00
3 of 4 • Sun, 20 Dec
Smash Forth Pty L... $43.87
Make multiple payments
"""

SCREENSHOT_4_OCR = """
20:38
Your orders
Target
2 of 4 • Sun, 6 Dec
Pay $28.50
ebay
eBay
2 of 4 • Sun, 6 Dec
Pay $64.60
A
AMCALPHARM...
2 of 4 • Sun, 6 Dec
Pay $75.00
Logo
Smash Forth Pt...
2 of 4 • Sun, 6 Dec
Pay $43.87
Amazon.com.au $18.99
4 of 4 • Sun, 13 Dec
Amazon.com.au $13.18
4 of 4 • Sun, 13 Dec
BING LEE
Bing Lee Electrics ... $71.50
4 of 4 • Sun, 13 Dec
Make multiple payments
"""

SCREENSHOT_5_OCR = """
20:38
Your orders
BING LEE
Bing Lee Electri...
3 of 4 • Sun, 29 Nov
Pay $71.50
U
UNITED BERRI...
2 of 4 • Sun, 29 Nov
Pay $20.00
M
MARULAN IGA ...
2 of 4 • Sun, 29 Nov
Pay $17.78
Amazon.com.au
1 of 4 • Sun, 29 Nov
Pay $31.57
M
MARULAN IGA ...
4 of 4 • Sun, 6 Dec
Pay $13.86
C
Creality
4 of 4 • Sun, 6 Dec
Pay $166.00
Target
2 of 4 • Sun, 6 Dec
Pay $28.50
eBay
Make multiple payments
"""

SCREENSHOT_6_OCR = """
20:37
Your orders
$1,341.03
Total you owe
$643.20
Due in 15 days
$1,028.19
Due in 30 days
$1,341.03
Due in 60 days
Upcoming payments
Active orders
History
A
AMCAL MARAL...
4 of 4 • Sun, 29 Nov
Pay $78.34
Amazon.com.au
3 of 4 • Sun, 29 Nov
Pay $19.00
Amazon.com.au
3 of 4 • Sun, 29 Nov
Pay $13.18
BING LEE
Bing Lee Electri...
3 of 4 • Sun, 29 Nov
Pay $71.50
Make multiple payments
"""

EXPECTED_SCREENSHOTS: dict[str, list[tuple[str, Decimal, date, int, int]]] = {
    "afterpay-1.png": [
        ("MARULAN IGA PL...", Decimal("17.76"), date(2026, 12, 27), 4, 4),
        ("Amazon.com.au", Decimal("31.57"), date(2026, 12, 27), 3, 4),
        ("Target", Decimal("28.50"), date(2027, 1, 3), 4, 4),
        ("eBay", Decimal("64.58"), date(2027, 1, 3), 4, 4),
        ("AMCALPHARMA...", Decimal("75.00"), date(2027, 1, 3), 4, 4),
        ("Smash Forth Pty L...", Decimal("43.87"), date(2027, 1, 3), 4, 4),
        ("Amazon.com.au", Decimal("31.56"), date(2027, 1, 10), 4, 4),
    ],
    "afterpay-2.png": [
        ("AMCALPHARMA...", Decimal("75.00"), date(2026, 12, 20), 3, 4),
        ("Smash Forth Pty L...", Decimal("43.87"), date(2026, 12, 20), 3, 4),
        ("UNITED BERRIMA", Decimal("20.00"), date(2026, 12, 27), 4, 4),
        ("MARULAN IGA PL...", Decimal("17.76"), date(2026, 12, 27), 4, 4),
        ("Amazon.com.au", Decimal("31.57"), date(2026, 12, 27), 3, 4),
        ("Target", Decimal("28.50"), date(2027, 1, 3), 4, 4),
        ("eBay", Decimal("64.58"), date(2027, 1, 3), 4, 4),
        ("AMCALPHARMA...", Decimal("75.00"), date(2027, 1, 3), 4, 4),
    ],
    "afterpay-3.png": [
        ("Bing Lee Electrics ...", Decimal("71.50"), date(2026, 12, 13), 4, 4),
        ("UNITED BERRIMA", Decimal("20.00"), date(2026, 12, 13), 3, 4),
        ("MARULAN IGA PL...", Decimal("17.78"), date(2026, 12, 13), 3, 4),
        ("Amazon.com.au", Decimal("31.57"), date(2026, 12, 13), 2, 4),
        ("Target", Decimal("28.50"), date(2026, 12, 20), 3, 4),
        ("eBay", Decimal("64.60"), date(2026, 12, 20), 3, 4),
        ("AMCALPHARMA...", Decimal("75.00"), date(2026, 12, 20), 3, 4),
    ],
    "afterpay-4.png": [
        ("Target", Decimal("28.50"), date(2026, 12, 6), 2, 4),
        ("eBay", Decimal("64.60"), date(2026, 12, 6), 2, 4),
        ("AMCALPHARM...", Decimal("75.00"), date(2026, 12, 6), 2, 4),
        ("Smash Forth Pt...", Decimal("43.87"), date(2026, 12, 6), 2, 4),
        ("Amazon.com.au", Decimal("18.99"), date(2026, 12, 13), 4, 4),
        ("Amazon.com.au", Decimal("13.18"), date(2026, 12, 13), 4, 4),
        ("Bing Lee Electrics ...", Decimal("71.50"), date(2026, 12, 13), 4, 4),
    ],
    "afterpay-5.png": [
        ("Bing Lee Electri...", Decimal("71.50"), date(2026, 11, 29), 3, 4),
        ("UNITED BERRI...", Decimal("20.00"), date(2026, 11, 29), 2, 4),
        ("MARULAN IGA ...", Decimal("17.78"), date(2026, 11, 29), 2, 4),
        ("Amazon.com.au", Decimal("31.57"), date(2026, 11, 29), 1, 4),
        ("MARULAN IGA ...", Decimal("13.86"), date(2026, 12, 6), 4, 4),
        ("Creality", Decimal("166.00"), date(2026, 12, 6), 4, 4),
        ("Target", Decimal("28.50"), date(2026, 12, 6), 2, 4),
    ],
    "afterpay-6.png": [
        ("AMCAL MARAL...", Decimal("78.34"), date(2026, 11, 29), 4, 4),
        ("Amazon.com.au", Decimal("19.00"), date(2026, 11, 29), 3, 4),
        ("Amazon.com.au", Decimal("13.18"), date(2026, 11, 29), 3, 4),
        ("Bing Lee Electri...", Decimal("71.50"), date(2026, 11, 29), 3, 4),
    ],
}

OCR_BY_FIXTURE = {
    "afterpay-1.png": SCREENSHOT_1_OCR,
    "afterpay-2.png": SCREENSHOT_2_OCR,
    "afterpay-3.png": SCREENSHOT_3_OCR,
    "afterpay-4.png": SCREENSHOT_4_OCR,
    "afterpay-5.png": SCREENSHOT_5_OCR,
    "afterpay-6.png": SCREENSHOT_6_OCR,
}


def _vision_payload_for(fixture_name: str) -> dict:
    """Build a realistic vision-model JSON response matching a screenshot."""
    raw_dates = {
        date(2026, 11, 29): "Sun, 29 Nov",
        date(2026, 12, 6): "Sun, 6 Dec",
        date(2026, 12, 13): "Sun, 13 Dec",
        date(2026, 12, 20): "Sun, 20 Dec",
        date(2026, 12, 27): "Sun, 27 Dec",
        date(2027, 1, 3): "3 Jan, 2027",
        date(2027, 1, 10): "10 Jan, 2027",
    }
    rows = []
    for merchant, amount, due, num, total in EXPECTED_SCREENSHOTS[fixture_name]:
        rows.append(
            {
                "merchant": merchant,
                "amount": (
                    f"Pay ${amount:.2f}" if due <= date(2026, 12, 6) else float(amount)
                ),
                "due_date": raw_dates[due],
                "installment_number": num,
                "total_installments": total,
                "installment_label": f"{num} of {total}",
            }
        )
    return {
        "provider": None,
        "amount": None,
        "currency": "AUD",
        "due_date": None,
        "period": None,
        "confidence": 0.95,
        "installments": rows,
    }


def _png_bytes(tag: str) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + tag.encode("utf-8")


def _upload(client, token, data: bytes, name: str = "IMG_0001.png"):
    return client.post(
        "/import/upload",
        files={"file": (name, data, "image/png")},
        headers=auth(token),
    )


# ---------------------------------------------------------------------------
# Unit: parser against all 6 screenshots (OCR text + vision JSON)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture_name", list(EXPECTED_SCREENSHOTS.keys()))
def test_parse_afterpay_orders_text_all_six_screenshots(fixture_name: str):
    rows = parse_afterpay_orders_text(
        OCR_BY_FIXTURE[fixture_name], reference_date=REF_DATE
    )
    expected = EXPECTED_SCREENSHOTS[fixture_name]
    assert len(rows) == len(expected)
    for got, (merchant, amount, due, num, total) in zip(rows, expected, strict=True):
        assert isinstance(got, BnplInstallmentRow)
        assert got.merchant == merchant
        assert got.amount == amount
        assert got.due_date == due
        assert got.installment_number == num
        assert got.total_installments == total
        assert got.installment_label == f"{num} of {total}"
        assert got.currency == "AUD"


@pytest.mark.parametrize("fixture_name", list(EXPECTED_SCREENSHOTS.keys()))
def test_parse_afterpay_installments_payload_all_six_screenshots(fixture_name: str):
    payload = _vision_payload_for(fixture_name)
    rows = parse_afterpay_installments_payload(payload, reference_date=REF_DATE)
    expected = EXPECTED_SCREENSHOTS[fixture_name]
    assert len(rows) == len(expected)
    for got, (merchant, amount, due, num, total) in zip(rows, expected, strict=True):
        assert got.merchant == merchant
        assert got.amount == amount
        assert got.due_date == due
        assert got.installment_number == num
        assert got.total_installments == total
        assert got.currency == "AUD"


def test_parse_bnpl_date_formats_and_year_rollover():
    assert parse_bnpl_date("Sun, 27 Dec", reference_date=REF_DATE) == date(2026, 12, 27)
    assert parse_bnpl_date("3 Jan, 2027", reference_date=REF_DATE) == date(2027, 1, 3)
    assert parse_bnpl_date("10 Jan, 2027", reference_date=REF_DATE) == date(2027, 1, 10)
    assert parse_bnpl_date("2027-01-03", reference_date=REF_DATE) == date(2027, 1, 3)
    # Yearless Jan when reference date is late Dec rolls into next year.
    assert parse_bnpl_date("Sun, 3 Jan", reference_date=date(2026, 12, 20)) == date(
        2027, 1, 3
    )
    # Explicit year on sibling rows resolves Dec before Jan 2027 to Dec 2026 even
    # if reference_date is far in another year.
    rows = parse_afterpay_orders_text(
        SCREENSHOT_1_OCR, reference_date=date(2028, 6, 15)
    )
    assert rows[0].due_date == date(2026, 12, 27)
    assert rows[2].due_date == date(2027, 1, 3)


def test_payload_without_installment_counters_is_not_treated_as_bnpl():
    payload = {
        "provider": "Sydney Water",
        "amount": 87.30,
        "currency": "AUD",
        "due_date": "2026-11-12",
        "installments": [
            {"merchant": "Water usage", "amount": 50.00, "due_date": "2026-11-12"},
            {"merchant": "Service charge", "amount": 37.30, "due_date": "2026-11-12"},
        ],
    }
    assert parse_afterpay_installments_payload(payload, reference_date=REF_DATE) == []


def test_document_shape_detection_ignores_filename_and_supports_two_phase_ocr():
    config = LlmConfig(provider="ollama", base_url="http://ollama.test", model="llava")

    # Generic filename still detected as BNPL list from payload shape.
    with patch(
        "app.services.bill_extract.generate_json",
        return_value=_vision_payload_for("afterpay-1.png"),
    ):
        doc = extract_document_items(
            _png_bytes("ap1"),
            config=config,
            content_type="image/png",
            filename="Screenshot_20261124_203812.png",
            reference_date=REF_DATE,
        )
    assert len(doc.bnpl_installments) == 7
    assert doc.bill is None

    # Afterpay-named file with an ordinary single-bill payload stays a single bill.
    single_payload = {
        "provider": "Sydney Water",
        "amount": 87.30,
        "currency": "AUD",
        "due_date": "2026-11-12",
        "period": "2026-10",
        "confidence": 0.9,
        "installments": None,
    }
    with patch("app.services.bill_extract.generate_json", return_value=single_payload):
        doc2 = extract_document_items(
            _png_bytes("single"),
            config=config,
            content_type="image/png",
            filename="afterpay-looking-name.png",
            reference_date=REF_DATE,
        )
    assert doc2.bnpl_installments == []
    assert doc2.bill is not None
    assert doc2.bill.provider == "Sydney Water"

    # Two-phase OCR fallback parses Afterpay screenshot text directly without
    # invoking the text LLM to aggregate rows.
    with (
        patch(
            "app.services.bill_extract.generate_json",
            side_effect=LlmError("vision json failed"),
        ),
        patch(
            "app.services.bill_extract.generate_text",
            return_value=SCREENSHOT_6_OCR,
        ),
    ):
        doc3 = extract_document_items(
            _png_bytes("ap6"),
            config=config,
            content_type="image/png",
            filename="IMG_9999.png",
            reference_date=REF_DATE,
        )
    assert len(doc3.bnpl_installments) == 4
    assert doc3.bill is None


# ---------------------------------------------------------------------------
# Unit & E2E: upload, dedupe, matching, no auto-confirm, no template creation
# ---------------------------------------------------------------------------


def test_e2e_upload_afterpay_screenshot_creates_n_pending_drafts_never_summed(
    client_db,
):
    client, db = client_db
    token = register_and_login(client, "ap_e2e@test.com")

    # Seed two real Afterpay templates; other merchants on the screenshot are unknown.
    r_target = client.post(
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
    assert r_target.status_code == 201, r_target.text
    target_bill_id = r_target.json()["id"]

    r_iga = client.post(
        "/bills",
        json={
            "name": "Afterpay: MARULAN IGA PLUS LIQ",
            "category": "other",
            "frequency": "weekly",
            "interval_count": 2,
            "max_occurrences": 4,
            "start_date": "2026-11-15",
            "amount": "17.78",
            "currency": "AUD",
        },
        headers=auth(token),
    )
    assert r_iga.status_code == 201, r_iga.text
    iga_bill_id = r_iga.json()["id"]

    instances_before = db.query(PaymentInstance).count()

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch(
            "app.services.bill_extract.generate_json",
            return_value=_vision_payload_for("afterpay-1.png"),
        ),
    ):
        resp = _upload(client, token, _png_bytes("afterpay-1"), name="IMG_1234.png")

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["drafts"]) == 7

    pending = client.get("/import/drafts?status=pending", headers=auth(token)).json()
    confirmed = client.get(
        "/import/drafts?status=confirmed", headers=auth(token)
    ).json()
    assert len(pending) == 7
    assert confirmed == []

    # Never a summed draft (292.84) or null due date.
    amounts = [Decimal(d["amount"]) for d in pending]
    assert Decimal("292.84") not in amounts
    assert sum(amounts, Decimal("0")) == Decimal("292.84")
    assert all(d["due_date"] is not None for d in pending)
    assert all(d["status"] == "pending" for d in pending)
    assert all(d["provider"].startswith("Afterpay: ") for d in pending)

    by_provider_date = {(d["provider"], d["due_date"]): d for d in pending}

    # Known templates match accurately (including truncated MARULAN IGA PL...).
    target_draft = by_provider_date[("Afterpay: Target", "2027-01-03")]
    assert target_draft["matched_bill_id"] == target_bill_id
    assert target_draft["meta"]["type"] == "afterpay"
    assert target_draft["meta"]["installment_number"] == 4
    assert target_draft["meta"]["total_installments"] == 4
    assert target_draft["meta"]["installment_label"] == "4 of 4"

    iga_draft = by_provider_date[("Afterpay: MARULAN IGA PL...", "2026-12-27")]
    assert iga_draft["matched_bill_id"] == iga_bill_id
    assert iga_draft["meta"]["installment_label"] == "4 of 4"

    # Unknown merchants stay unmatched (do NOT falsely match Afterpay: Target!).
    ebay_draft = by_provider_date[("Afterpay: eBay", "2027-01-03")]
    assert ebay_draft["matched_bill_id"] is None
    amazon_draft = by_provider_date[("Afterpay: Amazon.com.au", "2026-12-27")]
    assert amazon_draft["matched_bill_id"] is None
    assert amazon_draft["meta"]["installment_label"] == "3 of 4"

    # Unique source_ref per row.
    db_drafts = db.query(ImportDraft).all()
    assert len(db_drafts) == 7
    assert len({d.source_ref for d in db_drafts}) == 7
    assert all(":afterpay:" in d.source_ref for d in db_drafts)

    # No bill templates or payment instances were auto-created by the upload.
    assert db.query(BillTemplate).count() == 2
    assert db.query(PaymentInstance).count() == instances_before


def test_reupload_same_screenshot_creates_no_new_drafts(client_db):
    client, db = client_db
    token = register_and_login(client, "ap_reupload@test.com")
    img = _png_bytes("same-screenshot-bytes")

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch(
            "app.services.bill_extract.generate_json",
            return_value=_vision_payload_for("afterpay-1.png"),
        ) as mock_gen,
    ):
        first = _upload(client, token, img, name="shot1.png")
        assert first.status_code == 201, first.text
        assert mock_gen.call_count == 1

        second = _upload(client, token, img, name="shot1-copy.png")
        assert second.status_code == 409
        # Re-upload was blocked by source_ref before invoking the LLM again.
        assert mock_gen.call_count == 1

    assert db.query(ImportDraft).count() == 7


def test_overlapping_screenshots_create_only_new_instalments(client_db):
    client, db = client_db
    token = register_and_login(client, "ap_overlap@test.com")

    with patch.object(settings, "ollama_base_url", "http://ollama.test"):
        # Upload screenshot 1 (7 rows)
        with patch(
            "app.services.bill_extract.generate_json",
            return_value=_vision_payload_for("afterpay-1.png"),
        ):
            r1 = _upload(client, token, _png_bytes("shot-1"), name="shot1.png")
        assert r1.status_code == 201
        assert len(r1.json()["drafts"]) == 7

        # Upload screenshot 2 (8 rows: 5 overlap with #1, 3 are genuinely new)
        with patch(
            "app.services.bill_extract.generate_json",
            return_value=_vision_payload_for("afterpay-2.png"),
        ):
            r2 = _upload(client, token, _png_bytes("shot-2"), name="shot2.png")
        assert r2.status_code == 201, r2.text
        assert len(r2.json()["drafts"]) == 3
        assert r2.json()["skipped_duplicates"] == 5

        # Upload screenshots 3..6 sequentially
        expected_new = {
            "afterpay-3.png": 6,
            "afterpay-4.png": 6,
            "afterpay-5.png": 6,
            "afterpay-6.png": 3,
        }
        for name, expected_count in expected_new.items():
            with patch(
                "app.services.bill_extract.generate_json",
                return_value=_vision_payload_for(name),
            ):
                resp = _upload(client, token, _png_bytes(name), name=name)
            assert resp.status_code == 201, resp.text
            assert len(resp.json()["drafts"]) == expected_count

    all_drafts = db.query(ImportDraft).all()
    # 7 + 3 + 6 + 6 + 6 + 3 = 31 unique instalments totaling $1,341.03!
    assert len(all_drafts) == 31
    assert sum((d.amount for d in all_drafts if d.amount), Decimal("0")) == Decimal(
        "1341.03"
    )
    assert all(d.status == ImportStatus.pending for d in all_drafts)


def test_truncation_width_change_still_dedupes_but_distinct_stores_do_not(client_db):
    client, db = client_db
    token = register_and_login(client, "ap_trunc_dedupe@test.com")

    payload_wide = {
        "installments": [
            {
                "merchant": "Bing Lee Electrics ...",
                "amount": 71.50,
                "due_date": "Sun, 13 Dec",
                "installment_label": "4 of 4",
            },
            {
                "merchant": "AMCALPHARMA...",
                "amount": 75.00,
                "due_date": "Sun, 29 Nov",
                "installment_label": "4 of 4",
            },
        ]
    }
    payload_narrow = {
        "installments": [
            {
                # Shorter truncation width after Pay button appears — same instalment!
                "merchant": "Bing Lee Electri...",
                "amount": "Pay $71.50",
                "due_date": "Sun, 13 Dec",
                "installment_label": "4 of 4",
            },
            {
                # Different store with same amount & date — must NOT dedupe!
                "merchant": "AMCAL MARAL...",
                "amount": "Pay $75.00",
                "due_date": "Sun, 29 Nov",
                "installment_label": "4 of 4",
            },
        ]
    }

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.user_today", return_value=REF_DATE),
    ):
        with patch(
            "app.services.bill_extract.generate_json", return_value=payload_wide
        ):
            r1 = _upload(client, token, _png_bytes("wide"), name="wide.png")
        assert r1.status_code == 201
        assert len(r1.json()["drafts"]) == 2

        with patch(
            "app.services.bill_extract.generate_json", return_value=payload_narrow
        ):
            r2 = _upload(client, token, _png_bytes("narrow"), name="narrow.png")
        assert r2.status_code == 201
        assert len(r2.json()["drafts"]) == 1
        assert r2.json()["drafts"][0]["provider"] == "Afterpay: AMCAL MARAL..."
        assert r2.json()["skipped_duplicates"] == 1


def test_dedupes_against_existing_payment_instances_and_keeps_rounded_final(client_db):
    """Instalments already present as PaymentInstances with the same merchant,
    amount, and due_date are skipped; a final instalment whose amount differs
    (e.g. $17.76 vs scheduled $17.78) still creates a pending draft."""
    client, db = client_db
    token = register_and_login(client, "ap_reality@test.com")

    # Target: $28.50 fortnightly starting 2026-11-22 -> 2026-11-22, 12-06, 12-20, 2027-01-03
    r_target = client.post(
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
    assert r_target.status_code == 201
    sync_payments(client, token, "2027-01")

    # MARULAN IGA: $17.78 fortnightly starting 2026-11-15 -> 2026-12-27 is $17.78
    # Screenshot has $17.76 on 2026-12-27 (2c rounding on 4th instalment).
    r_iga = client.post(
        "/bills",
        json={
            "name": "Afterpay: MARULAN IGA PLUS LIQ",
            "category": "other",
            "frequency": "weekly",
            "interval_count": 2,
            "max_occurrences": 4,
            "start_date": "2026-11-15",
            "amount": "17.78",
            "currency": "AUD",
        },
        headers=auth(token),
    )
    assert r_iga.status_code == 201
    iga_bill_id = r_iga.json()["id"]
    sync_payments(client, token, "2026-12")

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch(
            "app.services.bill_extract.generate_json",
            return_value=_vision_payload_for("afterpay-1.png"),
        ),
    ):
        resp = _upload(client, token, _png_bytes("ap1-reality"), name="ap1.png")

    assert resp.status_code == 201, resp.text
    drafts = resp.json()["drafts"]
    # Target ($28.50 on 2027-01-03) already exists as a PaymentInstance -> skipped.
    # Remaining 6 rows (including MARULAN IGA $17.76 != $17.78) -> created!
    assert len(drafts) == 6
    assert resp.json()["skipped_duplicates"] == 1
    assert all(d["provider"] != "Afterpay: Target" for d in drafts)

    iga_draft = next(
        d for d in drafts if d["provider"] == "Afterpay: MARULAN IGA PL..."
    )
    assert iga_draft["matched_bill_id"] == iga_bill_id
    assert iga_draft["amount"] == "17.76"

    # Confirming the MARULAN IGA draft updates the exact 2026-12-27 instalment
    # (not the earlier 2026-12-13 instalment in the same month).
    r_conf = client.post(
        f"/import/drafts/{iga_draft['id']}/confirm",
        json={},
        headers=auth(token),
    )
    assert r_conf.status_code == 200, r_conf.text
    instances = (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == iga_bill_id)
        .order_by(PaymentInstance.due_date)
        .all()
    )
    by_due = {inst.due_date: inst.amount for inst in instances}
    assert by_due[date(2026, 12, 13)] == Decimal("17.78")
    assert by_due[date(2026, 12, 27)] == Decimal("17.76")


def test_poll_directory_imports_afterpay_screenshot_as_multiple_drafts(
    client_db, tmp_path
):
    client, db = client_db
    register_and_login(client, "ap_dir@test.com")

    watch = tmp_path / "import"
    watch.mkdir()
    (watch / "orders.png").write_bytes(_png_bytes("dir-ap6"))

    with (
        patch.object(settings, "data_dir", str(tmp_path)),
        patch.object(settings, "import_enabled", True),
        patch.object(settings, "import_dir", str(watch)),
        patch.object(settings, "import_keep_files", False),
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch(
            "app.services.bill_extract.generate_json",
            return_value=_vision_payload_for("afterpay-6.png"),
        ),
    ):
        result = poll_directory(db)
    assert result["processed"] == 4
    assert db.query(ImportDraft).count() == 4


def test_email_afterpay_path_unchanged(client_db):
    client, db = client_db
    register_and_login(client, "ap_email_unchanged@test.com")
    user = db.query(User).filter(User.email == "ap_email_unchanged@test.com").one()

    from tests.test_afterpay_parser import SAMPLE_HTML

    message = EmailMessage()
    message["From"] = "orders@afterpay.com"
    message["Message-ID"] = "<afterpay-unchanged@example>"
    message["Subject"] = "Your order with Bing Lee Electrics Pty Limited is confirmed"
    message.add_alternative(SAMPLE_HTML, subtype="html")
    app_settings.set_value(db, app_settings.IMAP_AFTERPAY_ENABLED_KEY, "1")

    drafts, skipped = _message_drafts(db, user, message.as_bytes())
    assert len(drafts) == 1
    assert skipped == 0
    assert drafts[0].source_ref == "email:<afterpay-unchanged@example>:afterpay"
    assert drafts[0].provider == "Afterpay: Bing Lee Electrics Pty Limited"


def test_reupload_after_discard_and_reencoded_duplicate_return_409(client_db):
    client, db = client_db
    token = register_and_login(client, "ap_discard_reup@test.com")
    img1 = _png_bytes("orig-ap6")
    img2 = _png_bytes("reencoded-ap6-different-bytes")

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch(
            "app.services.bill_extract.generate_json",
            return_value=_vision_payload_for("afterpay-6.png"),
        ),
    ):
        r1 = _upload(client, token, img1, name="ap6.png")
        assert r1.status_code == 201
        created_ids = [d["id"] for d in r1.json()["drafts"]]
        assert len(created_ids) == 4

        # Different bytes with identical instalments -> all 4 rows deduped -> 409.
        r_reencoded = _upload(client, token, img2, name="ap6-reencoded.png")
        assert r_reencoded.status_code == 409
        assert "already imported" in r_reencoded.json()["detail"].lower()

        # Discard all 4 drafts, then re-upload the exact same file -> still 409.
        for draft_id in created_ids:
            assert (
                client.post(
                    f"/import/drafts/{draft_id}/discard", headers=auth(token)
                ).status_code
                == 204
            )
        r_after_discard = _upload(client, token, img1, name="ap6.png")
        assert r_after_discard.status_code == 409

    assert db.query(ImportDraft).count() == 4


def test_afterpay_rows_do_not_match_non_afterpay_bills(client_db):
    client, db = client_db
    token = register_and_login(client, "ap_no_non_ap@test.com")

    # Non-Afterpay subscription sharing merchant name.
    r_prime = client.post(
        "/bills",
        json={
            "name": "Amazon Prime",
            "category": "subscriptions",
            "frequency": "monthly",
            "due_day": 15,
            "amount": "9.99",
            "currency": "AUD",
        },
        headers=auth(token),
    )
    assert r_prime.status_code == 201

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch(
            "app.services.bill_extract.generate_json",
            return_value=_vision_payload_for("afterpay-6.png"),
        ),
    ):
        resp = _upload(client, token, _png_bytes("ap6-prime"), name="ap6.png")
    assert resp.status_code == 201
    for draft in resp.json()["drafts"]:
        assert draft["matched_bill_id"] is None


def test_messy_vision_payload_skips_noise_and_clipped_rows():
    payload = {
        "installments": [
            # Summary header noise mistakenly included by model
            {
                "merchant": "Total you owe",
                "amount": "$1,341.03",
                "due_date": "2026-11-29",
                "installment_label": "1 of 4",
            },
            # Clipped row missing amount
            {
                "merchant": "eBay",
                "amount": None,
                "due_date": "Sun, 6 Dec",
                "installment_label": "2 of 4",
            },
            # Embedded counter inside due_date + double Afterpay prefix + AUD prefix
            {
                "merchant": "Afterpay: Target",
                "amount": "AUD $28.50",
                "due_date": "4 of 4 • 3 Jan, 2027",
                "installment_label": None,
            },
        ]
    }
    rows = parse_afterpay_installments_payload(payload, reference_date=REF_DATE)
    assert len(rows) == 1
    assert rows[0].merchant == "Target"
    assert rows[0].amount == Decimal("28.50")
    assert rows[0].due_date == date(2027, 1, 3)
    assert rows[0].installment_label == "4 of 4"


def test_real_fixture_png_files_upload_cleanly_when_present(client_db):
    """When /tmp/afterpay-fixtures exists locally, upload all 6 real PNG files."""
    from pathlib import Path

    fixture_dir = Path("/tmp/afterpay-fixtures")
    if not fixture_dir.is_dir():
        pytest.skip("local /tmp/afterpay-fixtures not present")

    client, db = client_db
    token = register_and_login(client, "ap_real_pngs@test.com")
    with patch.object(settings, "ollama_base_url", "http://ollama.test"):
        for idx in range(1, 7):
            fname = f"afterpay-{idx}.png"
            data = (fixture_dir / fname).read_bytes()
            with patch(
                "app.services.bill_extract.generate_json",
                return_value=_vision_payload_for(fname),
            ):
                resp = _upload(client, token, data, name=fname)
            assert resp.status_code == 201, resp.text

    assert db.query(ImportDraft).count() == 31


# ---------------------------------------------------------------------------
# Date-safe prompt & deterministic weekday/year reconciliation guard
# ---------------------------------------------------------------------------

DEC_2026_TODAY = date(2026, 12, 1)


def test_prompts_include_pinned_today_and_yearless_date_rule():
    from app.services.bill_extract import (
        extract_bnpl_from_text,
        extract_document_items,
        extract_from_text,
    )

    config = LlmConfig(provider="ollama", base_url="http://ollama.test", model="gemma4")

    with patch(
        "app.services.bill_extract.generate_json",
        return_value=_vision_payload_for("afterpay-1.png"),
    ) as mock_gen:
        extract_document_items(
            _png_bytes("prompt-check"),
            config=config,
            content_type="image/png",
            filename="orders.png",
            reference_date=DEC_2026_TODAY,
        )
    vision_prompt = mock_gen.call_args.kwargs["prompt"]
    assert "2026-12-01" in vision_prompt
    assert "next" in vision_prompt.lower()

    with patch(
        "app.services.bill_extract.generate_json",
        return_value={
            "provider": "Afterpay",
            "amount": 17.76,
            "currency": "AUD",
            "due_date": "2026-12-27",
            "period": None,
            "confidence": 0.9,
        },
    ) as mock_gen:
        extract_from_text(
            "Payment due Sun, 27 Dec — $17.76",
            config=config,
            reference_date=DEC_2026_TODAY,
        )
    text_prompt = mock_gen.call_args.kwargs["prompt"]
    assert "2026-12-01" in text_prompt

    with patch(
        "app.services.bill_extract.generate_json",
        return_value={
            "merchant": "MARULAN IGA",
            "installment_amount": 17.76,
            "start_date": "2026-12-27",
        },
    ) as mock_gen:
        extract_bnpl_from_text(
            "Afterpay order: first payment Sun, 27 Dec $17.76",
            config=config,
            reference_date=DEC_2026_TODAY,
        )
    bnpl_prompt = mock_gen.call_args.kwargs["prompt"]
    assert "2026-12-01" in bnpl_prompt
    assert "next" in bnpl_prompt.lower()


@pytest.mark.parametrize(
    ("source_line", "llm_due_date", "expected"),
    [
        ("4 of 4 • Sun, 27 Dec", "2027-12-27", date(2026, 12, 27)),
        ("3 of 4 • Sun, 20 Dec", "2023-12-20", date(2026, 12, 20)),
        ("4 of 4 • 3 Jan, 2027", "2027-01-03", date(2027, 1, 3)),
    ],
)
def test_weekday_guard_reconciles_single_bill_and_email_paths(
    source_line: str, llm_due_date: str, expected: date
):
    from app.services.bill_extract import extract_bnpl_from_text, extract_from_text

    config = LlmConfig(provider="ollama", base_url="http://ollama.test", model="gemma4")
    source_text = f"MARULAN IGA PL... $17.76\n{source_line}"

    with patch(
        "app.services.bill_extract.generate_json",
        return_value={
            "provider": "Afterpay: MARULAN IGA PL...",
            "amount": 17.76,
            "currency": "AUD",
            "due_date": llm_due_date,
            "period": None,
            "confidence": 0.9,
        },
    ):
        extracted = extract_from_text(
            source_text, config=config, reference_date=DEC_2026_TODAY
        )
    assert extracted.due_date == expected
    assert extracted.warnings == []

    with patch(
        "app.services.bill_extract.generate_json",
        return_value={
            "merchant": "MARULAN IGA PL...",
            "installment_amount": 17.76,
            "start_date": llm_due_date,
        },
    ):
        bnpl = extract_bnpl_from_text(
            source_text, config=config, reference_date=DEC_2026_TODAY
        )
    assert bnpl is not None
    assert bnpl.start_date == expected
    assert bnpl.warnings == []


def test_weekday_guard_reconciles_screenshot_payload_with_wrong_years():
    """Even if the vision model appends wrong years to weekday dates, the guard
    re-derives 2026 for Sun 27 Dec / Sun 20 Dec while leaving explicit 3 Jan, 2027."""
    payload = {
        "installments": [
            {
                "merchant": "MARULAN IGA PL...",
                "amount": 17.76,
                "due_date": "Sun, 27 Dec 2027",
                "installment_label": "4 of 4",
            },
            {
                "merchant": "AMCALPHARMA...",
                "amount": 75.00,
                "due_date": "Sun, 20 Dec 2023",
                "installment_label": "3 of 4",
            },
            {
                "merchant": "Target",
                "amount": 28.50,
                "due_date": "3 Jan, 2027",
                "installment_label": "4 of 4",
            },
        ]
    }
    rows = parse_afterpay_installments_payload(payload, reference_date=DEC_2026_TODAY)
    assert [r.due_date for r in rows] == [
        date(2026, 12, 27),
        date(2026, 12, 20),
        date(2027, 1, 3),
    ]
    assert all(not r.warnings for r in rows)


def test_weekday_guard_rolls_forward_to_next_year_when_current_year_mismatches():
    from app.services.bill_extract import extract_from_text

    config = LlmConfig(provider="ollama", base_url="http://ollama.test", model="gemma4")
    # 3 Jan 2026 is Saturday; 3 Jan 2027 is Sunday.
    with patch(
        "app.services.bill_extract.generate_json",
        return_value={
            "provider": "Afterpay: Target",
            "amount": 28.50,
            "currency": "AUD",
            "due_date": "2026-01-03",
            "period": None,
            "confidence": 0.9,
        },
    ):
        extracted = extract_from_text(
            "Target $28.50\n4 of 4 • Sun, 3 Jan",
            config=config,
            reference_date=date(2026, 12, 20),
        )
    assert extracted.due_date == date(2027, 1, 3)
    assert extracted.warnings == []


def test_weekday_guard_flags_irreconcilable_weekday_and_leaves_date_unchanged(
    client_db, caplog
):
    """27 Dec is Sun in 2026 and Mon in 2027 — 'Tue, 27 Dec' matches neither, so
    the parsed date is left unchanged and flagged via warnings and draft meta."""
    from app.services.bill_extract import extract_from_text

    config = LlmConfig(provider="ollama", base_url="http://ollama.test", model="gemma4")
    with (
        caplog.at_level("WARNING"),
        patch(
            "app.services.bill_extract.generate_json",
            return_value={
                "provider": "Afterpay: MARULAN IGA PL...",
                "amount": 17.76,
                "currency": "AUD",
                "due_date": "2027-12-27",
                "period": None,
                "confidence": 0.9,
            },
        ),
    ):
        extracted = extract_from_text(
            "MARULAN IGA PL... $17.76\nDue: Tue, 27 Dec",
            config=config,
            reference_date=DEC_2026_TODAY,
        )
    assert extracted.due_date == date(2027, 12, 27)
    assert len(extracted.warnings) == 1
    assert "Tue" in extracted.warnings[0]
    assert any("Tue" in rec.message for rec in caplog.records)

    # Also verify screenshot payload row carries the warning into ImportDraft.meta.
    client, db = client_db
    token = register_and_login(client, "ap_warn_meta@test.com")
    bad_payload = {
        "installments": [
            {
                "merchant": "MARULAN IGA PL...",
                "amount": 17.76,
                "due_date": "Tue, 27 Dec 2027",
                "installment_label": "4 of 4",
            }
        ]
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.user_today", return_value=DEC_2026_TODAY),
        patch("app.services.bill_extract.generate_json", return_value=bad_payload),
    ):
        resp = _upload(client, token, _png_bytes("irreconcilable"), name="bad.png")
    assert resp.status_code == 201, resp.text
    draft = resp.json()["drafts"][0]
    assert draft["due_date"] == "2027-12-27"
    assert draft["meta"] is not None
    assert draft["meta"].get("warnings")
    assert "Tue" in draft["meta"]["warnings"][0]
