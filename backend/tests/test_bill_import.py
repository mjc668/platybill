"""Bill import: upload, drafts, confirm/discard, directory and email pollers."""

from datetime import date, timedelta
from decimal import Decimal
from email.message import EmailMessage
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from app.models.import_draft import ImportDraft, ImportSource, ImportStatus
from app.models.user import User
from app.services import app_settings
from app.services.bill_import import _message_drafts, poll_directory, poll_email
from tests.conftest import auth, register_and_login, sync_payments

EXTRACTED = {
    "provider": "Sydney Water",
    "amount": 87.30,
    "currency": "AUD",
    "due_date": "2026-11-12",
    "period": "2026-10",
    "confidence": 0.9,
}

_BILL = {
    "name": "Sydney Water",
    "category": "utilities",
    "frequency": "monthly",
    "amount": "80.00",
    "amount_varies": True,
    "currency": "AUD",
    "due_day": 12,
    "notes": None,
    "is_paused": False,
}

PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def _create_bill(client, token, overrides=None) -> dict:
    r = client.post("/bills", json={**_BILL, **(overrides or {})}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _upload(
    client, token, data: bytes = PNG, name: str = "bill.png", ctype: str = "image/png"
):
    return client.post(
        "/import/upload",
        files={"file": (name, data, ctype)},
        headers=auth(token),
    )


# ---------------------------------------------------------------------------
# Upload + drafts
# ---------------------------------------------------------------------------


def test_upload_extracts_and_matches(client_db):
    client, db = client_db
    token = register_and_login(client, "imp1@test.com")
    bill = _create_bill(client, token)

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=EXTRACTED),
    ):
        r = _upload(client, token)

    assert r.status_code == 201, r.text
    draft = r.json()
    assert draft["provider"] == "Sydney Water"
    assert draft["amount"] == "87.30"
    assert draft["currency"] == "AUD"
    assert draft["due_date"] == "2026-11-12"
    assert draft["matched_bill_id"] == bill["id"]
    assert draft["matched_bill_name"] == "Sydney Water"
    assert draft["status"] == "pending"

    listed = client.get("/import/drafts", headers=auth(token)).json()
    assert [d["id"] for d in listed] == [draft["id"]]


def test_upload_requires_ollama(client_db):
    client, db = client_db
    token = register_and_login(client, "imp2@test.com")
    with patch.object(settings, "ollama_base_url", None):
        r = _upload(client, token)
    assert r.status_code == 503


def test_upload_rejects_type_size_and_duplicates(client_db):
    client, db = client_db
    token = register_and_login(client, "imp3@test.com")
    with patch.object(settings, "ollama_base_url", "http://ollama.test"):
        r = _upload(client, token, name="bill.txt", ctype="text/plain")
        assert r.status_code == 415

        with patch.object(settings, "import_max_file_mb", 0):
            r = _upload(client, token)
            assert r.status_code == 413

        with patch("app.services.bill_extract.generate_json", return_value=EXTRACTED):
            assert _upload(client, token).status_code == 201
            assert _upload(client, token).status_code == 409


def test_upload_rejects_spoofed_content_type_with_wrong_suffix(client_db):
    client, db = client_db
    token = register_and_login(client, "imp_suffix@test.com")
    with patch.object(settings, "ollama_base_url", "http://ollama.test"):
        # Correct content-type but a non-allowlisted filename is rejected.
        r = _upload(client, token, name="bill.txt", ctype="application/pdf")
        assert r.status_code == 415
        # Uppercase suffix still accepted.
        with patch("app.services.bill_extract.generate_json", return_value=EXTRACTED):
            assert _upload(client, token, name="BILL.PNG", ctype=None).status_code in (
                201,
                409,
            )


def test_extract_bnpl_from_text_forces_aud_currency():
    from app.services.bill_extract import extract_bnpl_from_text
    from app.services.llm import LlmConfig

    payload = {
        "merchant": "Bing Lee",
        "installment_amount": 71.50,
        "start_date": "2026-11-01",
        "currency": "USD",  # attacker-influenced: must be ignored
    }
    config = LlmConfig(provider="opencode", base_url="http://x", model="m")
    with patch("app.services.bill_extract.generate_json", return_value=payload):
        result = extract_bnpl_from_text("afterpay order", config=config)
    assert result is not None
    assert result.currency == "AUD"


# ---------------------------------------------------------------------------
# Confirm / discard
# ---------------------------------------------------------------------------


def test_confirm_applies_to_variable_queue(client_db):
    client, db = client_db
    token = register_and_login(client, "imp4@test.com")
    bill = _create_bill(client, token)
    sync_payments(client, token)

    today = date.today()
    document = {
        **EXTRACTED,
        "period": today.strftime("%Y-%m"),
        "due_date": today.replace(day=20).isoformat(),
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=document),
    ):
        draft = _upload(client, token).json()

    r = client.post(
        f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["created_instance"] is False

    instance = db.get(PaymentInstance, result["instance_id"])
    assert instance.amount == Decimal("87.30")
    assert instance.amount_estimated is False
    assert instance.bill_id == bill["id"]

    queue = client.get("/bills/payments/needs-confirmation", headers=auth(token)).json()
    assert queue == []
    drafts = client.get("/import/drafts", headers=auth(token)).json()
    assert drafts == []


def test_confirm_creates_instance_when_missing(client_db):
    client, db = client_db
    token = register_and_login(client, "imp5@test.com")
    bill = _create_bill(client, token)  # no sync: no instance exists yet

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=EXTRACTED),
    ):
        draft = _upload(client, token).json()

    r = client.post(
        f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["created_instance"] is True

    instance = db.get(PaymentInstance, result["instance_id"])
    # Period follows the due date (November), not the extracted billing period.
    assert instance.period == "2026-11"
    assert instance.due_date == date(2026, 11, 12)
    assert instance.amount == Decimal("87.30")
    assert instance.amount_estimated is False
    assert instance.bill_id == bill["id"]


def test_confirm_unmatched_needs_a_bill(client_db):
    client, db = client_db
    token = register_and_login(client, "imp6@test.com")
    bill = _create_bill(client, token, {"name": "Electricity"})

    unmatched = {**EXTRACTED, "provider": "Totally Different Provider"}
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=unmatched),
    ):
        draft = _upload(client, token).json()
    assert draft["matched_bill_id"] is None

    r = client.post(
        f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(token)
    )
    assert r.status_code == 422

    r = client.patch(
        f"/import/drafts/{draft['id']}",
        json={"matched_bill_id": bill["id"]},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["matched_bill_name"] == "Electricity"

    r = client.post(
        f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(token)
    )
    assert r.status_code == 200, r.text


def test_discard_and_scoping(client_db):
    client, db = client_db
    token = register_and_login(client, "imp7@test.com")
    other = register_and_login(client, "imp7-other@test.com")

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=EXTRACTED),
    ):
        draft = _upload(client, token).json()

    assert client.get(f"/import/drafts", headers=auth(other)).json() == []
    assert (
        client.post(
            f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(other)
        ).status_code
        == 404
    )

    r = client.post(f"/import/drafts/{draft['id']}/discard", headers=auth(token))
    assert r.status_code == 204
    drafts = client.get("/import/drafts?status=all", headers=auth(token)).json()
    assert drafts[0]["status"] == "discarded"


# ---------------------------------------------------------------------------
# Pollers
# ---------------------------------------------------------------------------


def test_poll_directory_processes_and_dedupes(client_db, tmp_path):
    client, db = client_db
    register_and_login(client, "imp8@test.com")

    watch = tmp_path / "import"
    watch.mkdir()
    (watch / "water.png").write_bytes(PNG)

    with (
        patch.object(settings, "data_dir", str(tmp_path)),
        patch.object(settings, "import_enabled", True),
        patch.object(settings, "import_dir", str(watch)),
        patch.object(settings, "import_keep_files", False),
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=EXTRACTED),
    ):
        first = poll_directory(db)
        assert first["processed"] == 1
        assert not (watch / "water.png").exists()

        # A re-dropped identical file dedupes on the hash.
        (watch / "water.png").write_bytes(PNG)
        second = poll_directory(db)
        assert second["processed"] == 0
        assert second["duplicates"] == 1

    assert db.query(ImportDraft).count() == 1


def test_poll_directory_disabled(client_db):
    client, db = client_db
    register_and_login(client, "imp9@test.com")
    with patch.object(settings, "import_enabled", False):
        result = poll_directory(db)
    assert result["processed"] == 0
    assert "skipped" in result


def test_poll_email_disabled(client_db):
    client, db = client_db
    register_and_login(client, "imp10@test.com")
    with patch.object(settings, "imap_host", None):
        result = poll_email(db)
    assert result["processed"] == 0
    assert "skipped" in result


def test_message_drafts_from_email(client_db):
    client, db = client_db
    register_and_login(client, "imp11@test.com")
    user = db.query(User).one()

    message = EmailMessage()
    message["From"] = "billing@sydneywater.example"
    message["Message-ID"] = "<bill-123@example>"
    message["Subject"] = "Your water bill"
    message.set_content("Please find your bill attached.")
    message.add_attachment(PNG, maintype="image", subtype="png", filename="bill.png")
    raw = message.as_bytes()

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=EXTRACTED),
    ):
        drafts, skipped = _message_drafts(db, user, raw)
        assert len(drafts) == 1
        assert skipped == 0
        assert drafts[0].source == ImportSource.email
        assert drafts[0].source_ref == "email:<bill-123@example>:0"

        again, skipped_again = _message_drafts(db, user, raw)
        assert again == []
        assert skipped_again == 1


def test_message_drafts_allowed_senders(client_db):
    client, db = client_db
    register_and_login(client, "imp12@test.com")
    user = db.query(User).one()

    message = EmailMessage()
    message["From"] = "spam@elsewhere.example"
    message["Message-ID"] = "<spam-1@example>"
    message.set_content("Water bill 87.30 AUD due 2026-11-12")
    raw = message.as_bytes()

    with (
        patch.object(settings, "imap_allowed_senders", ["billing@sydneywater.example"]),
        patch("app.services.bill_extract.generate_json", return_value=EXTRACTED),
    ):
        drafts, skipped = _message_drafts(db, user, raw)
    assert drafts == []
    assert skipped == 0


def test_message_drafts_afterpay_email(client_db):
    client, db = client_db
    register_and_login(client, "imp_afterpay@test.com")
    user = db.query(User).filter(User.email == "imp_afterpay@test.com").one()

    from tests.test_afterpay_parser import SAMPLE_HTML

    message = EmailMessage()
    message["From"] = "orders@afterpay.com"
    message["Message-ID"] = "<afterpay-123@example>"
    message["Subject"] = "Your order with Bing Lee Electrics Pty Limited is confirmed"
    message.set_content("Plain text fallback")
    message.add_alternative(SAMPLE_HTML, subtype="html")
    raw = message.as_bytes()

    app_settings.set_value(db, app_settings.IMAP_AFTERPAY_ENABLED_KEY, "1")

    drafts, skipped = _message_drafts(db, user, raw)
    assert len(drafts) == 1
    assert skipped == 0
    draft = drafts[0]
    assert draft.provider == "Afterpay: Bing Lee Electrics Pty Limited"
    assert draft.amount == Decimal("71.50")
    assert draft.due_date == date(2026, 11, 1)
    assert draft.meta is not None
    assert draft.meta["order_id"] == "1016080531"
    assert draft.meta["interval_count"] == 2
    assert draft.meta["max_occurrences"] == 4

    # Second poll dedupes
    again, skipped_again = _message_drafts(db, user, raw)
    assert again == []
    assert skipped_again == 1


def test_confirm_afterpay_draft(client_db):
    client, db = client_db
    token = register_and_login(client, "imp_confirm_ap@test.com")
    user = db.query(User).filter(User.email == "imp_confirm_ap@test.com").one()

    from tests.test_afterpay_parser import SAMPLE_HTML

    message = EmailMessage()
    message["From"] = "orders@afterpay.com"
    message["Message-ID"] = "<afterpay-456@example>"
    message["Subject"] = "Your order with Bing Lee Electrics Pty Limited is confirmed"
    message.add_alternative(SAMPLE_HTML, subtype="html")
    raw = message.as_bytes()

    app_settings.set_value(db, app_settings.IMAP_AFTERPAY_ENABLED_KEY, "1")
    drafts, _ = _message_drafts(db, user, raw)
    assert len(drafts) == 1
    draft = drafts[0]

    # Create bill
    r = client.post(
        "/bills",
        json={
            "name": "Afterpay: Bing Lee",
            "frequency": "weekly",
            "interval_count": 2,
            "max_occurrences": 4,
            "start_date": "2026-11-01",
            "amount": 71.50,
            "category": "other",
        },
        headers=auth(token),
    )
    assert r.status_code == 201
    bill_id = r.json()["id"]

    # Confirm the draft for this bill
    r_conf = client.post(
        f"/import/drafts/{draft.id}/confirm",
        json={"bill_id": bill_id},
        headers=auth(token),
    )
    assert r_conf.status_code == 200
    db.refresh(draft)
    assert draft.status == ImportStatus.confirmed
    assert draft.matched_bill_id == bill_id


def test_confirm_matches_exact_due_date_for_multi_instance_month(client_db):
    """When a bill has multiple unpaid instances in the same month (e.g. Afterpay
    fortnightly instalments), confirming a draft must update the instalment with
    the matching due_date rather than the earliest instance in that period."""
    client, db = client_db
    token = register_and_login(client, "imp_multi_inst@test.com")
    user = db.query(User).filter(User.email == "imp_multi_inst@test.com").one()

    r = client.post(
        "/bills",
        json={
            "name": "Afterpay: Bing Lee",
            "frequency": "weekly",
            "interval_count": 2,
            "max_occurrences": 4,
            "start_date": "2026-11-01",
            "amount": "71.50",
            "category": "other",
        },
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    bill_id = r.json()["id"]

    # Seed November 2026 — creates 2026-11-01, 2026-11-15, and 2026-11-29.
    sync_payments(client, token, "2026-11")
    instances = (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == bill_id)
        .order_by(PaymentInstance.due_date)
        .all()
    )
    assert [inst.due_date for inst in instances] == [
        date(2026, 11, 1),
        date(2026, 11, 15),
        date(2026, 11, 29),
    ]
    first, second, third = instances

    draft = ImportDraft(
        user_id=user.id,
        source=ImportSource.email,
        source_ref="email:<afterpay-inst2@example>:0",
        provider="Afterpay: Bing Lee",
        amount=Decimal("75.25"),
        currency="AUD",
        due_date=date(2026, 11, 15),
        period="2026-11",
        matched_bill_id=bill_id,
        status=ImportStatus.pending,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    r_conf = client.post(
        f"/import/drafts/{draft.id}/confirm", json={}, headers=auth(token)
    )
    assert r_conf.status_code == 200, r_conf.text
    result = r_conf.json()
    assert result["created_instance"] is False
    assert result["instance_id"] == second.id

    db.refresh(first)
    db.refresh(second)
    db.refresh(third)
    assert first.amount == Decimal("71.50")
    assert second.amount == Decimal("75.25")
    assert second.amount_estimated is False
    assert third.amount == Decimal("71.50")


def test_confirm_exact_due_date_paid_does_not_overwrite_earlier_instalment(client_db):
    """If the instalment matching due_date is already paid, confirm_draft must
    reject it instead of falling back to an earlier unpaid instalment in the
    same month."""
    client, db = client_db
    token = register_and_login(client, "imp_multi_paid@test.com")
    user = db.query(User).filter(User.email == "imp_multi_paid@test.com").one()

    r = client.post(
        "/bills",
        json={
            "name": "Afterpay: Paid Second",
            "frequency": "weekly",
            "interval_count": 2,
            "max_occurrences": 4,
            "start_date": "2026-11-01",
            "amount": "71.50",
            "category": "other",
        },
        headers=auth(token),
    )
    assert r.status_code == 201, r.text
    bill_id = r.json()["id"]

    sync_payments(client, token, "2026-11")
    instances = (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == bill_id)
        .order_by(PaymentInstance.due_date)
        .all()
    )
    first, second = instances[0], instances[1]
    second.status = PaymentStatus.paid
    db.commit()

    draft = ImportDraft(
        user_id=user.id,
        source=ImportSource.email,
        source_ref="email:<afterpay-paid2@example>:0",
        provider="Afterpay: Paid Second",
        amount=Decimal("80.00"),
        currency="AUD",
        due_date=date(2026, 11, 15),
        period="2026-11",
        matched_bill_id=bill_id,
        status=ImportStatus.pending,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    r_conf = client.post(
        f"/import/drafts/{draft.id}/confirm", json={}, headers=auth(token)
    )
    assert r_conf.status_code == 422, r_conf.text
    assert "already paid" in r_conf.json()["detail"].lower()

    db.refresh(first)
    db.refresh(second)
    assert first.amount == Decimal("71.50")
    assert second.amount == Decimal("71.50")


def test_confirm_monthly_bill_still_falls_back_to_period(client_db):
    """Monthly bills whose draft due_date differs from the scheduled due_day
    (or is omitted) must still match the month's instance via the period fallback."""
    client, db = client_db
    token = register_and_login(client, "imp_monthly_fb@test.com")
    user = db.query(User).filter(User.email == "imp_monthly_fb@test.com").one()
    bill = _create_bill(client, token)  # monthly, due_day=12, amount_varies=True

    today = date.today()
    period = today.strftime("%Y-%m")
    sync_payments(client, token, period)
    existing = (
        db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill["id"]).one()
    )
    assert existing.due_date == today.replace(day=12)
    assert existing.amount_estimated is True

    # Different due_date in the same month falls back to period match.
    draft_diff_day = ImportDraft(
        user_id=user.id,
        source=ImportSource.upload,
        source_ref="upload:monthly-diff-day",
        provider="Sydney Water",
        amount=Decimal("92.40"),
        currency="AUD",
        due_date=today.replace(day=20),
        period=period,
        matched_bill_id=bill["id"],
        status=ImportStatus.pending,
    )
    db.add(draft_diff_day)
    db.commit()
    db.refresh(draft_diff_day)

    r_conf = client.post(
        f"/import/drafts/{draft_diff_day.id}/confirm", json={}, headers=auth(token)
    )
    assert r_conf.status_code == 200, r_conf.text
    result = r_conf.json()
    assert result["created_instance"] is False
    assert result["instance_id"] == existing.id

    db.refresh(existing)
    assert existing.amount == Decimal("92.40")
    assert existing.amount_estimated is False

    # Omitted due_date with explicit period also falls back to period match.
    draft_no_due = ImportDraft(
        user_id=user.id,
        source=ImportSource.upload,
        source_ref="upload:monthly-no-due",
        provider="Sydney Water",
        amount=Decimal("95.10"),
        currency="AUD",
        due_date=None,
        period=period,
        matched_bill_id=bill["id"],
        status=ImportStatus.pending,
    )
    db.add(draft_no_due)
    db.commit()
    db.refresh(draft_no_due)

    r_conf2 = client.post(
        f"/import/drafts/{draft_no_due.id}/confirm", json={}, headers=auth(token)
    )
    assert r_conf2.status_code == 200, r_conf2.text
    result2 = r_conf2.json()
    assert result2["created_instance"] is False
    assert result2["instance_id"] == existing.id

    db.refresh(existing)
    assert existing.amount == Decimal("95.10")


# ---------------------------------------------------------------------------
# Status endpoints
# ---------------------------------------------------------------------------


def test_status_and_test_ollama(client_db):
    client, db = client_db
    token = register_and_login(client, "imp13@test.com")

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch.object(settings, "ollama_model", "numind/nuextract3"),
        patch("app.services.ollama.list_models", return_value=["numind/nuextract3"]),
    ):
        status = client.get("/import/status", headers=auth(token)).json()
        assert status["ollama_configured"] is True
        assert status["ollama_reachable"] is True
        assert status["model_available"] is True

        r = client.post("/import/test-ollama", headers=auth(token))
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    with patch.object(settings, "ollama_base_url", None):
        r = client.post("/import/test-ollama", headers=auth(token))
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is False
        assert r.json()["error"]


def test_confirm_variable_other_period_does_not_overwrite_confirmed(client_db):
    """A draft for a later month must not rewrite an already-confirmed month."""
    client, db = client_db
    token = register_and_login(client, "imp14@test.com")
    bill = _create_bill(client, token)
    sync_payments(client, token)

    today = date.today()
    current_doc = {
        **EXTRACTED,
        "period": today.strftime("%Y-%m"),
        "due_date": today.replace(day=20).isoformat(),
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=current_doc),
    ):
        draft_one = _upload(client, token).json()
    client.post(
        f"/import/drafts/{draft_one['id']}/confirm", json={}, headers=auth(token)
    )
    current = (
        db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill["id"]).one()
    )
    assert current.amount == Decimal("87.30")

    first_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    later_doc = {
        **EXTRACTED,
        "amount": 91.10,
        "period": "2026-08",  # deliberately disagreeing billing period
        "due_date": first_next.replace(day=12).isoformat(),
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=later_doc),
    ):
        draft_two = _upload(client, token, data=PNG + b"second").json()

    r = client.post(
        f"/import/drafts/{draft_two['id']}/confirm", json={}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["created_instance"] is True

    instances = (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == bill["id"])
        .order_by(PaymentInstance.due_date)
        .all()
    )
    assert len(instances) == 2
    assert instances[0].amount == Decimal("87.30")  # current month untouched
    assert instances[1].period == first_next.strftime("%Y-%m")
    assert instances[1].amount == Decimal("91.10")


def test_confirm_without_period_updates_pending_estimate(client_db):
    """A past-dated document with no period is treated as the pending bill."""
    client, db = client_db
    token = register_and_login(client, "imp15@test.com")
    bill = _create_bill(client, token)
    sync_payments(client, token)

    today = date.today()
    last_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    undated = {
        **EXTRACTED,
        "period": None,
        "due_date": f"{last_month}-05",
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=undated),
    ):
        draft = _upload(client, token).json()
    assert draft["period"] is None

    r = client.post(
        f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["created_instance"] is False

    instances = (
        db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill["id"]).all()
    )
    assert len(instances) == 1
    assert instances[0].period == today.strftime("%Y-%m")
    assert instances[0].amount == Decimal("87.30")
    assert instances[0].amount_estimated is False


def test_confirm_explicit_other_period_ignores_pending_estimate(client_db):
    """An explicit later period creates its own instance, leaving the estimate."""
    client, db = client_db
    token = register_and_login(client, "imp16@test.com")
    bill = _create_bill(client, token)
    sync_payments(client, token)

    today = date.today()
    first_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    future = {
        **EXTRACTED,
        "amount": 91.10,
        "period": first_next.strftime("%Y-%m"),
        "due_date": first_next.isoformat(),
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=future),
    ):
        draft = _upload(client, token).json()

    r = client.post(
        f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(token)
    )
    assert r.status_code == 200, r.text
    assert r.json()["created_instance"] is True

    instances = (
        db.query(PaymentInstance)
        .filter(PaymentInstance.bill_id == bill["id"])
        .order_by(PaymentInstance.due_date)
        .all()
    )
    assert len(instances) == 2
    assert instances[0].period == today.strftime("%Y-%m")
    assert instances[0].amount_estimated is True  # estimate untouched
    assert instances[1].period == first_next.strftime("%Y-%m")
    assert instances[1].amount == Decimal("91.10")


def test_sync_does_not_duplicate_import_created_instance(client_db):
    """Import-created instances carry the document's due date; the month sync
    must not add the scheduled occurrence beside them."""
    client, db = client_db
    token = register_and_login(client, "imp17@test.com")
    bill = _create_bill(client, token)  # schedule due day 12

    today = date.today()
    first_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    period = first_next.strftime("%Y-%m")
    document = {
        **EXTRACTED,
        "amount": 91.10,
        "period": period,
        "due_date": first_next.replace(day=20).isoformat(),
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=document),
    ):
        draft = _upload(client, token).json()
    r = client.post(
        f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(token)
    )
    assert r.status_code == 200, r.text

    # What the payments page does when the month is viewed.
    client.post(f"/bills/sync-instances?month={period}", headers=auth(token))

    rows = db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill["id"]).all()
    assert len(rows) == 1
    assert rows[0].due_date == first_next.replace(day=20)
    assert rows[0].amount == Decimal("91.10")
    assert rows[0].amount_estimated is False


def test_sync_keeps_single_instance_after_estimate_confirm(client_db):
    """Confirming a same-period import leaves one instance; sync stays idempotent."""
    client, db = client_db
    token = register_and_login(client, "imp18@test.com")
    bill = _create_bill(client, token)
    sync_payments(client, token)

    today = date.today()
    document = {
        **EXTRACTED,
        "amount": 87.30,
        "period": today.strftime("%Y-%m"),
        "due_date": today.replace(day=20).isoformat(),
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=document),
    ):
        draft = _upload(client, token).json()
    client.post(f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(token))
    sync_payments(client, token)

    rows = db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill["id"]).all()
    assert len(rows) == 1
    assert rows[0].amount == Decimal("87.30")
    assert rows[0].amount_estimated is False


def test_confirm_period_follows_the_due_date(client_db):
    """The document's billing period may disagree with the due date; the
    instance's period must match the due date like every other instance."""
    client, db = client_db
    token = register_and_login(client, "imp19@test.com")
    bill = _create_bill(client, token)

    today = date.today()
    first_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    document = {
        **EXTRACTED,
        "period": "2026-08",  # billing period read off the document
        "due_date": first_next.replace(day=15).isoformat(),
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=document),
    ):
        draft = _upload(client, token).json()
    r = client.post(
        f"/import/drafts/{draft['id']}/confirm", json={}, headers=auth(token)
    )
    assert r.status_code == 200, r.text

    instance = (
        db.query(PaymentInstance).filter(PaymentInstance.bill_id == bill["id"]).one()
    )
    assert instance.period == first_next.strftime("%Y-%m")
    assert instance.due_date == first_next.replace(day=15)


# ---------------------------------------------------------------------------
# Extractor prompt selection
# ---------------------------------------------------------------------------


def test_nuextract_uses_template_prompt_without_schema():
    from app.services.bill_extract import (
        EXTRACTION_SCHEMA,
        extract_from_image,
    )
    from app.services.llm import LlmConfig

    config = LlmConfig(
        provider="ollama",
        base_url="http://ollama.test",
        model="numind/nuextract3:q4_k_m",
        timeout=60,
    )
    with patch(
        "app.services.bill_extract.generate_json",
        return_value={**EXTRACTED, "confidence": 1.0},
    ) as mock_generate:
        extract_from_image(PNG, config=config)
        kwargs = mock_generate.call_args.kwargs
        assert kwargs["schema"] is None
        assert "verbatim-string" in kwargs["prompt"]


def test_other_models_use_schema_prompt():
    from app.services.bill_extract import EXTRACTION_SCHEMA, extract_from_image
    from app.services.llm import LlmConfig

    config = LlmConfig(
        provider="ollama",
        base_url="http://ollama.test",
        model="gemma4:latest",
        timeout=60,
    )
    with patch(
        "app.services.bill_extract.generate_json", return_value=EXTRACTED
    ) as mock_generate:
        extract_from_image(PNG, config=config)
        kwargs = mock_generate.call_args.kwargs
        assert kwargs["schema"] == EXTRACTION_SCHEMA
        assert "verbatim-string" not in kwargs["prompt"]


def test_period_normalization_accepts_month_names():
    from app.services.bill_extract import _normalize_period

    assert _normalize_period("2026-10") == "2026-10"
    assert _normalize_period("01 Oct 2026 - 31 Oct 2026") == "2026-10"
    assert _normalize_period("October 2026") == "2026-10"
    assert _normalize_period("Dec 2026") == "2026-12"
    assert _normalize_period("gibberish") is None
    assert _normalize_period(None) is None


def test_thinking_field_fallback(monkeypatch):
    """Models that emit structured output in `thinking` are still parsed."""
    import httpx

    from app.services.llm import LlmConfig, generate_json

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "response": "",
                "thinking": '{"provider": "X", "amount": 1.0, "due_date": "2026-01-01"}',
            }

    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse())
    config = LlmConfig(
        provider="ollama",
        base_url="http://ollama.test",
        model="qwen3-vl:8b",
        timeout=10,
    )
    result = generate_json(config=config, prompt="p")
    assert result["provider"] == "X"


def test_two_phase_uses_text_ocr_then_extracts():
    from app.services.bill_extract import _extract_image_two_phase
    from app.services.llm import LlmConfig

    config = LlmConfig(
        provider="ollama",
        base_url="http://ollama.test",
        model="gemma4",
        timeout=60,
    )
    with (
        patch(
            "app.services.bill_extract.generate_text", return_value="BILL 87.30"
        ) as mock_text,
        patch(
            "app.services.bill_extract.generate_json", return_value=EXTRACTED
        ) as mock_json,
    ):
        result = _extract_image_two_phase(PNG, config=config)
        assert mock_text.call_count == 1
        assert mock_json.call_count == 1
        assert result.amount == Decimal("87.30")


# ---------------------------------------------------------------------------
# Multi-template issuer disambiguation (due_day + service keywords)
# ---------------------------------------------------------------------------


def test_match_bill_disambiguates_same_issuer_by_due_day(client_db):
    """Two templates sharing an issuer: due_day picks the second template."""
    from app.services.bill_extract import ExtractedBill
    from app.services.bill_import import match_bill

    client, db = client_db
    token = register_and_login(client, "imp_disambig_day@test.com")
    user = db.query(User).filter(User.email == "imp_disambig_day@test.com").one()

    _create_bill(
        client,
        token,
        {
            "name": "Goulburn Mulwaree Council Rates",
            "interval_count": 3,
            "due_day": 30,
        },
    )
    water = _create_bill(
        client,
        token,
        {
            "name": "Goulburn Mulwaree Council Water",
            "interval_count": 3,
            "due_day": 11,
        },
    )

    extracted = ExtractedBill(
        provider="Goulburn Mulwaree Council",
        amount=Decimal("574.13"),
        currency="AUD",
        due_date=date(2026, 12, 11),
        period="2026-12",
        confidence=0.95,
        raw_text=None,
    )
    assert match_bill(db, user.id, extracted) == water["id"]


def test_match_bill_disambiguates_same_issuer_by_service_keyword(client_db):
    """Service keywords in extracted text disambiguate same-issuer templates."""
    from app.services.bill_extract import ExtractedBill
    from app.services.bill_import import match_bill

    client, db = client_db
    token = register_and_login(client, "imp_disambig_kw@test.com")
    user = db.query(User).filter(User.email == "imp_disambig_kw@test.com").one()

    _create_bill(
        client,
        token,
        {
            "name": "Goulburn Mulwaree Council Rates",
            "interval_count": 3,
            "due_day": 30,
        },
    )
    water = _create_bill(
        client,
        token,
        {
            "name": "Goulburn Mulwaree Council Water",
            "interval_count": 3,
            "due_day": 11,
        },
    )

    extracted = ExtractedBill(
        provider="Goulburn Mulwaree Council",
        amount=Decimal("574.13"),
        currency="AUD",
        due_date=date(2026, 12, 18),  # matches neither template's due_day
        period="2026-12",
        confidence=0.95,
        raw_text="Goulburn Mulwaree Council Water & Sewer Usage Account",
    )
    assert match_bill(db, user.id, extracted) == water["id"]


def test_match_bill_stays_unmatched_when_same_issuer_ambiguous(client_db):
    """When neither due_day nor service keywords break a tie, stay unmatched."""
    from app.services.bill_extract import ExtractedBill
    from app.services.bill_import import match_bill

    client, db = client_db
    token = register_and_login(client, "imp_disambig_tie@test.com")
    user = db.query(User).filter(User.email == "imp_disambig_tie@test.com").one()

    _create_bill(
        client,
        token,
        {
            "name": "Goulburn Mulwaree Council Rates",
            "interval_count": 3,
            "due_day": 30,
        },
    )
    _create_bill(
        client,
        token,
        {
            "name": "Goulburn Mulwaree Council Water",
            "interval_count": 3,
            "due_day": 11,
        },
    )

    ambiguous = ExtractedBill(
        provider="Goulburn Mulwaree Council",
        amount=Decimal("574.13"),
        currency="AUD",
        due_date=date(2026, 12, 20),  # matches neither 30 nor 11
        period="2026-12",
        confidence=0.95,
        raw_text=None,
    )
    assert match_bill(db, user.id, ambiguous) is None


def test_match_bill_rejects_service_contradiction_on_rates_template(client_db):
    """A water notice must never match a council rates template."""
    from app.services.bill_extract import ExtractedBill
    from app.services.bill_import import match_bill

    client, db = client_db
    token = register_and_login(client, "imp_disambig_conflict@test.com")
    user = db.query(User).filter(User.email == "imp_disambig_conflict@test.com").one()

    _create_bill(
        client,
        token,
        {
            "name": "Goulburn Mulwaree Council Rates",
            "interval_count": 3,
            "due_day": 30,
        },
    )
    water = _create_bill(
        client,
        token,
        {
            "name": "Water",
            "interval_count": 3,
            "due_day": 11,
            "notes": None,
        },
    )

    extracted = ExtractedBill(
        provider="Goulburn Mulwaree Council",
        amount=Decimal("574.13"),
        currency="AUD",
        due_date=date(2026, 12, 11),
        period="2026-12",
        confidence=0.95,
        raw_text="Goulburn Mulwaree Council Water Notice",
    )
    # Without council name in Water's name/notes, Rates must NOT be matched.
    assert match_bill(db, user.id, extracted) is None

    # With council name in Water's notes, it disambiguates onto Water.
    water_row = db.get(BillTemplate, water["id"])
    assert water_row is not None
    water_row.notes = "Goulburn Mulwaree Council"
    db.commit()
    assert match_bill(db, user.id, extracted) == water["id"]


def test_upload_same_issuer_water_notice_lands_on_water_not_rates(client_db):
    """End-to-end upload: notice due day 11 matches second template and stays pending."""
    client, db = client_db
    token = register_and_login(client, "imp_disambig_e2e@test.com")

    _create_bill(
        client,
        token,
        {
            "name": "Goulburn Mulwaree Council Rates",
            "interval_count": 3,
            "due_day": 30,
        },
    )
    water = _create_bill(
        client,
        token,
        {
            "name": "Goulburn Mulwaree Council Water",
            "interval_count": 3,
            "due_day": 11,
        },
    )

    notice = {
        "provider": "Goulburn Mulwaree Council",
        "amount": 574.13,
        "currency": "AUD",
        "due_date": "2026-12-11",
        "period": "2026-12",
        "confidence": 0.95,
    }
    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=notice),
    ):
        r = _upload(client, token, name="water-notice.png")

    assert r.status_code == 201, r.text
    draft = r.json()
    assert draft["status"] == "pending"
    assert draft["matched_bill_id"] == water["id"]
    assert draft["matched_bill_name"] == "Goulburn Mulwaree Council Water"


# ---------------------------------------------------------------------------
# Email import robustness: MIME fallback, inline images, HTML body, re-import,
# and visible failures
# ---------------------------------------------------------------------------


def test_email_accepts_pdf_sent_as_octet_stream_and_x_pdf(client_db):
    """PDFs sent as application/octet-stream or application/x-pdf are accepted."""
    from app.services.bill_extract import ExtractedBill

    client, db = client_db
    register_and_login(client, "imp_mime@test.com")
    user = db.query(User).filter(User.email == "imp_mime@test.com").one()

    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"

    msg_octet = EmailMessage()
    msg_octet["From"] = "enotice@council.example"
    msg_octet["Message-ID"] = "<council-octet@example>"
    msg_octet["Subject"] = "Water Notice"
    msg_octet.set_content("See attached notice.")
    msg_octet.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="octet-stream",
        filename="water-notice.pdf",
    )

    msg_xpdf = EmailMessage()
    msg_xpdf["From"] = "enotice@council.example"
    msg_xpdf["Message-ID"] = "<council-xpdf@example>"
    msg_xpdf["Subject"] = "Rates Notice"
    msg_xpdf.set_content("See attached notice.")
    msg_xpdf.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="x-pdf",
        filename="notice-download",
    )

    fake_extracted = ExtractedBill(
        provider="Goulburn Mulwaree Council",
        amount=Decimal("574.13"),
        currency="AUD",
        due_date=date(2026, 12, 11),
        period="2026-12",
        confidence=0.9,
        raw_text="Water Notice",
    )
    seen_types: list[str | None] = []

    def fake_extract(
        data, *, config, content_type=None, filename=None, reference_date=None
    ):
        seen_types.append(content_type)
        return fake_extracted

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.extract_document", side_effect=fake_extract),
    ):
        drafts1, skipped1 = _message_drafts(db, user, msg_octet.as_bytes())
        drafts2, skipped2 = _message_drafts(db, user, msg_xpdf.as_bytes())

    assert len(drafts1) == 1 and skipped1 == 0
    assert len(drafts2) == 1 and skipped2 == 0
    assert seen_types == ["application/pdf", "application/pdf"]


def test_email_ignores_inline_images_and_recovers_from_bad_attachment(client_db):
    """Inline logos never count as attachments and bad parts don't abort the PDF."""
    from email.mime.application import MIMEApplication
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from app.services.bill_extract import ExtractedBill
    from app.services.llm import LlmError

    client, db = client_db
    register_and_login(client, "imp_inline@test.com")
    user = db.query(User).filter(User.email == "imp_inline@test.com").one()

    pdf_bytes = b"%PDF-1.4\nfake-pdf-body"

    # Case A: inline logo BEFORE a real PDF attachment.
    msg_with_pdf = MIMEMultipart("mixed")
    msg_with_pdf["From"] = "enotice@council.example"
    msg_with_pdf["Message-ID"] = "<inline-before-pdf@example>"
    msg_with_pdf["Subject"] = "Council Water Bill"
    logo = MIMEImage(PNG, _subtype="png")
    logo.add_header("Content-Disposition", "inline", filename="logo.png")
    logo.add_header("Content-ID", "<logo@council.example>")
    msg_with_pdf.attach(logo)
    # Also include an image with NO Content-Disposition (common in mailers)
    bare_img = MIMEImage(PNG, _subtype="png")
    msg_with_pdf.attach(bare_img)
    pdf_part = MIMEApplication(pdf_bytes, _subtype="octet-stream")
    pdf_part.add_header("Content-Disposition", "attachment", filename="water.pdf")
    msg_with_pdf.attach(pdf_part)

    fake_extracted = ExtractedBill(
        provider="Goulburn Mulwaree Council",
        amount=Decimal("574.13"),
        currency="AUD",
        due_date=date(2026, 12, 11),
        period="2026-12",
        confidence=0.9,
        raw_text="Water Notice",
    )

    def reject_images(
        data, *, config, content_type=None, filename=None, reference_date=None
    ):
        if content_type and content_type.startswith("image/"):
            raise LlmError("logo should never be sent to LLM")
        return fake_extracted

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.extract_document", side_effect=reject_images),
    ):
        drafts, skipped = _message_drafts(db, user, msg_with_pdf.as_bytes())
    assert len(drafts) == 1
    assert skipped == 0
    assert drafts[0].filename == "water.pdf"

    # Case B: inline logo + text body only (no real attachments) -> body fallback runs.
    msg_logo_body = MIMEMultipart("related")
    msg_logo_body["From"] = "enotice@council.example"
    msg_logo_body["Message-ID"] = "<inline-body-fallback@example>"
    msg_logo_body["Subject"] = "Bill Ready"
    msg_logo_body.attach(MIMEText("Water bill $574.13 due 2026-12-11", "plain"))
    logo2 = MIMEImage(PNG, _subtype="png")
    logo2.add_header("Content-Disposition", "inline", filename="sig.png")
    msg_logo_body.attach(logo2)

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=EXTRACTED),
    ):
        drafts_b, skipped_b = _message_drafts(db, user, msg_logo_body.as_bytes())
    assert len(drafts_b) == 1
    assert skipped_b == 0
    assert drafts_b[0].source_ref == "email:<inline-body-fallback@example>:text"

    # Case C: first real attachment raises LlmError; second PDF still succeeds.
    msg_two = MIMEMultipart("mixed")
    msg_two["From"] = "enotice@council.example"
    msg_two["Message-ID"] = "<two-attachments@example>"
    msg_two["Subject"] = "Two Attachments"
    bad_img = MIMEImage(PNG, _subtype="png")
    bad_img.add_header("Content-Disposition", "attachment", filename="banner.png")
    msg_two.attach(bad_img)
    good_pdf = MIMEApplication(pdf_bytes, _subtype="pdf")
    good_pdf.add_header("Content-Disposition", "attachment", filename="invoice.pdf")
    msg_two.attach(good_pdf)

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_import.extract_document", side_effect=reject_images),
    ):
        drafts_c, skipped_c = _message_drafts(db, user, msg_two.as_bytes())
    assert len(drafts_c) == 1
    assert skipped_c == 0
    assert drafts_c[0].filename == "invoice.pdf"


def test_email_html_only_falls_back_to_text_extraction(client_db):
    """HTML-only non-Afterpay emails strip HTML and extract via text fallback."""
    client, db = client_db
    register_and_login(client, "imp_html@test.com")
    user = db.query(User).filter(User.email == "imp_html@test.com").one()

    msg = EmailMessage()
    msg["From"] = "billing@council.example"
    msg["Message-ID"] = "<html-only-1@example>"
    msg["Subject"] = "Your Council Water Notice"
    msg.set_content(
        "<html><head><style>.hidden{display:none}</style></head>"
        "<body><h1>Goulburn Mulwaree Council</h1>"
        "<p>Amount Due: $574.13</p><p>Due Date: 11 Dec 2026</p></body></html>",
        subtype="html",
    )

    captured: list[str] = []

    def fake_extract_text(text, *, config, reference_date=None):
        captured.append(text)
        from app.services.bill_extract import ExtractedBill

        return ExtractedBill(
            provider="Goulburn Mulwaree Council",
            amount=Decimal("574.13"),
            currency="AUD",
            due_date=date(2026, 12, 11),
            period="2026-12",
            confidence=0.9,
            raw_text=text,
        )

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch(
            "app.services.bill_import.extract_from_text", side_effect=fake_extract_text
        ),
    ):
        drafts, skipped = _message_drafts(db, user, msg.as_bytes())

    assert len(drafts) == 1
    assert skipped == 0
    assert "Goulburn Mulwaree Council" in captured[0]
    assert "$574.13" in captured[0]
    assert "display:none" not in captured[0]
    assert "<p>" not in captured[0]


def test_discarded_or_failed_source_ref_allows_reimport(client_db):
    """Discarded or failed drafts never permanently suppress re-importing."""
    client, db = client_db
    token = register_and_login(client, "imp_reimport@test.com")
    user = db.query(User).filter(User.email == "imp_reimport@test.com").one()

    message = EmailMessage()
    message["From"] = "billing@sydneywater.example"
    message["Message-ID"] = "<reimport-1@example>"
    message["Subject"] = "Water bill"
    message.set_content("See attached.")
    message.add_attachment(PNG, maintype="image", subtype="png", filename="bill.png")
    raw = message.as_bytes()

    with (
        patch.object(settings, "ollama_base_url", "http://ollama.test"),
        patch("app.services.bill_extract.generate_json", return_value=EXTRACTED),
    ):
        first, _ = _message_drafts(db, user, raw)
        assert len(first) == 1
        # Pending still dedupes
        dup, skipped = _message_drafts(db, user, raw)
        assert dup == [] and skipped == 1

        # Discard the draft -> re-import succeeds
        r = client.post(f"/import/drafts/{first[0].id}/discard", headers=auth(token))
        assert r.status_code == 204
        second, skipped2 = _message_drafts(db, user, raw)
        assert len(second) == 1 and skipped2 == 0
        assert second[0].id != first[0].id

        # Mark failed -> re-import also succeeds
        second[0].status = ImportStatus.failed
        second[0].error = "temporary error"
        db.commit()
        third, skipped3 = _message_drafts(db, user, raw)
        assert len(third) == 1 and skipped3 == 0
        assert third[0].id != second[0].id


def test_email_yielding_nothing_surfaces_visible_failure(client_db):
    """An allowed-sender email with no usable attachment or text fails visibly."""
    client, db = client_db
    token = register_and_login(client, "imp_empty_fail@test.com")
    user = db.query(User).filter(User.email == "imp_empty_fail@test.com").one()

    empty_msg = EmailMessage()
    empty_msg["From"] = "enotice@council.example"
    empty_msg["Message-ID"] = "<empty-msg@example>"
    empty_msg["Subject"] = "Council eNotice"
    empty_msg.add_attachment(
        b"PK\x03\x04not-a-pdf",
        maintype="application",
        subtype="zip",
        filename="archive.zip",
    )

    with pytest.raises(ValueError):
        _message_drafts(db, user, empty_msg.as_bytes())

    failed_drafts = client.get(
        "/import/drafts?status=failed", headers=auth(token)
    ).json()
    assert len(failed_drafts) == 1
    assert failed_drafts[0]["status"] == "failed"
    assert failed_drafts[0]["error"]

    status_resp = client.get("/import/status", headers=auth(token)).json()
    assert status_resp["last_error"] == failed_drafts[0]["error"]
