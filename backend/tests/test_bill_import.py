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
