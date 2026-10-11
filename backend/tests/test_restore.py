"""Integration tests for POST /export/restore."""

import json
from decimal import Decimal

import pytest

from app.core.config import settings
from app.core.ratelimit import reset_rate_limits
from tests.conftest import auth, register_and_login, sync_payments

_BILL = {
    "name": "Electricity",
    "category": "utilities",
    "frequency": "monthly",
    "amount": 120.00,
    "currency": "PLN",
    "due_day": 15,
    "notes": None,
    "is_paused": False,
}

_BILL2 = {
    "name": "Internet",
    "category": "utilities",
    "frequency": "monthly",
    "amount": 50.00,
    "currency": "PLN",
    "due_day": 10,
    "notes": None,
    "is_paused": False,
}

_BILL_ALPHA = {
    "name": "Alpha Bill",
    "category": "utilities",
    "frequency": "monthly",
    "amount": 50.00,
    "currency": "PLN",
    "due_day": 5,
    "notes": None,
    "is_paused": False,
}

_BILL_BETA = {
    "name": "Beta Bill",
    "category": "entertainment",
    "frequency": "monthly",
    "amount": 75.00,
    "currency": "EUR",
    "due_day": 20,
    "notes": "template note",
    "is_paused": False,
}


def _upload(client, token, payload):
    return client.post(
        "/export/restore",
        files={
            "file": ("backup.json", json.dumps(payload).encode(), "application/json")
        },
        headers=auth(token),
    )


def _make_backup(templates, instances, schema_version: int = 3):
    return {
        "schema_version": schema_version,
        "exported_by": "test@example.com",
        "exported_at": "2026-01-01T00:00:00+00:00",
        "bill_templates": templates,
        "payment_instances": instances,
    }


# Fields not preserved through restore (created_at uses DB default on insert)
_EXCLUDE_TEMPLATE = {"id", "created_at"}
_EXCLUDE_INSTANCE = {"id", "bill_id", "created_at"}
_EXCLUDE_PAYMENT = {"id", "instance_id"}


def _norm_template(t: dict) -> dict:
    return {k: v for k, v in t.items() if k not in _EXCLUDE_TEMPLATE}


def _norm_instance(i: dict) -> dict:
    return {k: v for k, v in i.items() if k not in _EXCLUDE_INSTANCE}


def _norm_payment(p: dict) -> dict:
    return {k: v for k, v in p.items() if k not in _EXCLUDE_PAYMENT}


def _make_instance_dict(
    template_id: int,
    period: str,
    *,
    include_reminder_fields: bool = True,
    reminder_sent_upcoming: bool = False,
    reminder_sent_overdue: bool = False,
    **overrides,
) -> dict:
    """Build a BackupInstance-shaped dict. Pass include_reminder_fields=False for a true v2 payload."""
    year, month = int(period[:4]), int(period[5:7])
    base: dict = {
        "id": 1,
        "bill_id": template_id,
        "period": period,
        "due_date": f"{year}-{month:02d}-15",
        "amount": 100.0,
        "status": "upcoming",
        "paid_at": None,
        "paid_amount": None,
        "notes": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    if include_reminder_fields:
        base["reminder_sent_upcoming"] = reminder_sent_upcoming
        base["reminder_sent_overdue"] = reminder_sent_overdue
    base.update(overrides)
    return base


def test_restore_happy_path(client):
    tok = register_and_login(client, "a@test.com")

    r = client.post("/bills", json=_BILL, headers=auth(tok))
    assert r.status_code == 201
    sync_payments(client, tok)
    client.get("/bills/payments", headers=auth(tok))

    backup = client.get("/export/json", headers=auth(tok)).json()
    assert backup["schema_version"] == 8

    r = _upload(client, tok, backup)
    assert r.status_code == 200
    data = r.json()
    assert data["restored_templates"] == len(backup["bill_templates"])
    assert data["restored_instances"] == len(backup["payment_instances"])

    after = client.get("/export/json", headers=auth(tok)).json()
    assert len(after["bill_templates"]) == len(backup["bill_templates"])
    assert len(after["payment_instances"]) == len(backup["payment_instances"])
    assert after["bill_templates"][0]["name"] == backup["bill_templates"][0]["name"]


def test_restore_wrong_schema_version(client):
    tok = register_and_login(client, "a@test.com")
    payload = _make_backup([], [])
    payload["schema_version"] = 1

    r = _upload(client, tok, payload)
    assert r.status_code == 422
    assert "schema version" in r.json()["detail"].lower()


def test_restore_orphaned_instance(client):
    tok = register_and_login(client, "a@test.com")

    r = client.post("/bills", json=_BILL, headers=auth(tok))
    assert r.status_code == 201
    sync_payments(client, tok)
    client.get("/bills/payments", headers=auth(tok))

    backup = client.get("/export/json", headers=auth(tok)).json()

    backup["payment_instances"][0]["bill_id"] = 99999

    r = _upload(client, tok, backup)
    assert r.status_code == 422
    assert "orphaned" in r.json()["detail"].lower()


def test_restore_orphaned_payment_returns_422(client):
    tok = register_and_login(client, "orphan_pay@test.com")

    r = client.post("/bills", json=_BILL, headers=auth(tok))
    assert r.status_code == 201
    template_id = r.json()["id"]

    template_dict = {
        "id": template_id,
        "name": _BILL["name"],
        "category": _BILL["category"],
        "frequency": _BILL["frequency"],
        "amount": _BILL["amount"],
        "currency": _BILL["currency"],
        "due_day": _BILL["due_day"],
        "notes": None,
        "is_archived": False,
        "is_paused": False,
        "start_period": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    instance_dict = _make_instance_dict(template_id, "2026-03", status="paid")
    payload = _make_backup([template_dict], [instance_dict], schema_version=4)
    payload["payments"] = [
        {
            "id": 1,
            "instance_id": 99999,
            "amount": 10.0,
            "paid_on": "2026-03-15",
            "note": None,
            "created_at": "2026-03-15T00:00:00+00:00",
        }
    ]

    r = _upload(client, tok, payload)
    assert r.status_code == 422
    assert "orphaned" in r.json()["detail"].lower()


def test_restore_replaces_existing_data(client):
    tok = register_and_login(client, "a@test.com")

    r1 = client.post("/bills", json=_BILL, headers=auth(tok))
    assert r1.status_code == 201
    r2 = client.post("/bills", json=_BILL2, headers=auth(tok))
    assert r2.status_code == 201

    template_id = r1.json()["id"]
    one_template_backup = _make_backup(
        [
            {
                "id": template_id,
                "name": _BILL["name"],
                "category": _BILL["category"],
                "frequency": _BILL["frequency"],
                "amount": _BILL["amount"],
                "currency": _BILL["currency"],
                "due_day": _BILL["due_day"],
                "notes": None,
                "is_archived": False,
                "is_paused": False,
                "start_period": None,
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        [],
    )

    r = _upload(client, tok, one_template_backup)
    assert r.status_code == 200

    bills = client.get("/bills", headers=auth(tok)).json()
    assert len(bills) == 1
    assert bills[0]["name"] == _BILL["name"]


def test_restore_user_isolation(client):
    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    r = client.post("/bills", json=_BILL, headers=auth(tok_a))
    assert r.status_code == 201

    empty_backup = _make_backup([], [])
    r = _upload(client, tok_b, empty_backup)
    assert r.status_code == 200

    bills_a = client.get("/bills", headers=auth(tok_a)).json()
    assert len(bills_a) == 1
    assert bills_a[0]["name"] == _BILL["name"]


def test_restore_requires_auth(client):
    payload = _make_backup([], [])
    r = client.post(
        "/export/restore",
        files={
            "file": ("backup.json", json.dumps(payload).encode(), "application/json")
        },
    )
    assert r.status_code == 401


def test_round_trip_field_level(client):
    """Seed → export → restore → re-export: all schema fields (except id/bill_id/created_at) survive unchanged."""
    tok = register_and_login(client, "rt@test.com")

    r1 = client.post("/bills", json=_BILL_ALPHA, headers=auth(tok))
    assert r1.status_code == 201
    r2 = client.post("/bills", json=_BILL_BETA, headers=auth(tok))
    assert r2.status_code == 201

    sync_payments(client, tok)
    payments = client.get("/bills/payments", headers=auth(tok)).json()
    assert len(payments) >= 2

    alpha_instance = next(p for p in payments if p["bill_name"] == "Alpha Bill")
    r = client.post(
        f"/bills/payments/{alpha_instance['id']}/pay",
        json={"paid_amount": 45.00, "notes": "paid early"},
        headers=auth(tok),
    )
    assert r.status_code == 200

    backup = client.get("/export/json", headers=auth(tok)).json()
    assert backup["schema_version"] == 8
    n_templates = len(backup["bill_templates"])
    n_instances = len(backup["payment_instances"])
    n_payments = len(backup["payments"])
    assert n_instances >= 2  # ensure field-level loop actually exercises rows
    assert n_payments >= 1  # the legacy /pay above recorded one ledger event

    r = _upload(client, tok, backup)
    assert r.status_code == 200
    data = r.json()
    assert data["restored_templates"] == n_templates
    assert data["restored_instances"] == n_instances

    after = client.get("/export/json", headers=auth(tok)).json()
    assert len(after["bill_templates"]) == n_templates
    assert len(after["payment_instances"]) == n_instances
    assert len(after["payments"]) == n_payments

    before_templates = sorted(backup["bill_templates"], key=lambda t: t["name"])
    after_templates = sorted(after["bill_templates"], key=lambda t: t["name"])
    for b, a in zip(before_templates, after_templates):
        assert _norm_template(b) == _norm_template(a), f"Template mismatch: {b['name']}"

    before_instances = sorted(
        backup["payment_instances"],
        key=lambda i: (i["period"], i["amount"], i["status"]),
    )
    after_instances = sorted(
        after["payment_instances"],
        key=lambda i: (i["period"], i["amount"], i["status"]),
    )
    for b, a in zip(before_instances, after_instances):
        assert _norm_instance(b) == _norm_instance(
            a
        ), f"Instance mismatch: period={b['period']}"

    before_payments = sorted(
        backup["payments"], key=lambda p: (p["paid_on"], p["amount"], p["note"] or "")
    )
    after_payments = sorted(
        after["payments"], key=lambda p: (p["paid_on"], p["amount"], p["note"] or "")
    )
    for b, a in zip(before_payments, after_payments):
        assert _norm_payment(b) == _norm_payment(
            a
        ), f"Payment mismatch: paid_on={b['paid_on']}"


def test_v2_backup_defaults_reminder_fields(client):
    """A v2-format backup (no reminder fields in instance dicts) restores with reminder flags = False."""
    tok = register_and_login(client, "v2@test.com")

    r = client.post("/bills", json=_BILL_ALPHA, headers=auth(tok))
    assert r.status_code == 201
    template_id = r.json()["id"]

    template_dict = {
        "id": template_id,
        "name": _BILL_ALPHA["name"],
        "category": _BILL_ALPHA["category"],
        "frequency": _BILL_ALPHA["frequency"],
        "amount": _BILL_ALPHA["amount"],
        "currency": _BILL_ALPHA["currency"],
        "due_day": _BILL_ALPHA["due_day"],
        "notes": None,
        "is_archived": False,
        "is_paused": False,
        "start_period": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    instance_dict = _make_instance_dict(
        template_id, "2026-01", include_reminder_fields=False
    )
    payload = _make_backup([template_dict], [instance_dict], schema_version=2)

    r = _upload(client, tok, payload)
    assert r.status_code == 200
    assert r.json()["restored_instances"] == 1

    after = client.get("/export/json", headers=auth(tok)).json()
    assert len(after["payment_instances"]) == 1
    inst = after["payment_instances"][0]
    assert inst["reminder_sent_upcoming"] is False
    assert inst["reminder_sent_overdue"] is False


def test_restore_cross_user_import(client):
    """User B can upload a backup created by user A; data lands under B's account, A's data untouched."""
    tok_a = register_and_login(client, "cross_a@test.com")
    tok_b = register_and_login(client, "cross_b@test.com")

    r = client.post("/bills", json=_BILL, headers=auth(tok_a))
    assert r.status_code == 201
    sync_payments(client, tok_a)
    client.get("/bills/payments", headers=auth(tok_a))

    backup_a = client.get("/export/json", headers=auth(tok_a)).json()
    assert backup_a["exported_by"] == "cross_a@test.com"
    assert len(backup_a["bill_templates"]) == 1

    r = _upload(client, tok_b, backup_a)
    assert r.status_code == 200
    data = r.json()
    assert data["restored_templates"] == 1

    bills_b = client.get("/bills", headers=auth(tok_b)).json()
    assert len(bills_b) == 1
    assert bills_b[0]["name"] == _BILL["name"]

    bills_a = client.get("/bills", headers=auth(tok_a)).json()
    assert len(bills_a) == 1
    assert bills_a[0]["name"] == _BILL["name"]

    backup_b_after = client.get("/export/json", headers=auth(tok_b)).json()
    assert backup_b_after["exported_by"] == "cross_b@test.com"


def test_v3_backup_preserves_reminder_flags(client):
    """A v3 backup with reminder_sent_upcoming=True preserves the flag through restore."""
    tok = register_and_login(client, "v3@test.com")

    r = client.post("/bills", json=_BILL_ALPHA, headers=auth(tok))
    assert r.status_code == 201
    template_id = r.json()["id"]

    template_dict = {
        "id": template_id,
        "name": _BILL_ALPHA["name"],
        "category": _BILL_ALPHA["category"],
        "frequency": _BILL_ALPHA["frequency"],
        "amount": _BILL_ALPHA["amount"],
        "currency": _BILL_ALPHA["currency"],
        "due_day": _BILL_ALPHA["due_day"],
        "notes": None,
        "is_archived": False,
        "is_paused": False,
        "start_period": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    instance_dict = _make_instance_dict(
        template_id,
        "2026-01",
        reminder_sent_upcoming=True,
        reminder_sent_overdue=False,
    )
    v3_payload = _make_backup([template_dict], [instance_dict])
    v3_payload["schema_version"] = 3

    r = _upload(client, tok, v3_payload)
    assert r.status_code == 200

    after = client.get("/export/json", headers=auth(tok)).json()
    assert len(after["payment_instances"]) == 1
    inst = after["payment_instances"][0]
    assert inst["reminder_sent_upcoming"] is True
    assert inst["reminder_sent_overdue"] is False


def test_v3_backup_synthesizes_ledger_payments(client):
    """A v3 backup's paid instance gets one synthetic ledger row on restore."""
    tok = register_and_login(client, "v3synth@test.com")

    r = client.post("/bills", json=_BILL_ALPHA, headers=auth(tok))
    assert r.status_code == 201
    template_id = r.json()["id"]

    template_dict = {
        "id": template_id,
        "name": _BILL_ALPHA["name"],
        "category": _BILL_ALPHA["category"],
        "frequency": _BILL_ALPHA["frequency"],
        "amount": _BILL_ALPHA["amount"],
        "currency": _BILL_ALPHA["currency"],
        "due_day": _BILL_ALPHA["due_day"],
        "notes": None,
        "is_archived": False,
        "is_paused": False,
        "start_period": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    instance_dict = _make_instance_dict(
        template_id,
        "2026-01",
        status="paid",
        paid_at="2026-01-20T10:30:00+00:00",
        paid_amount=42.00,
        notes="legacy note",
    )
    payload = _make_backup([template_dict], [instance_dict], schema_version=3)

    r = _upload(client, tok, payload)
    assert r.status_code == 200
    assert r.json()["restored_instances"] == 1

    after = client.get("/export/json", headers=auth(tok)).json()
    assert after["schema_version"] == 8
    assert len(after["payments"]) == 1
    payment = after["payments"][0]
    assert payment["instance_id"] == after["payment_instances"][0]["id"]
    assert Decimal(str(payment["amount"])) == Decimal("42.00")
    assert payment["paid_on"] == "2026-01-20"
    assert payment["note"] == "legacy note"


def test_v3_backup_synthesis_falls_back_to_amount_and_due_date(client):
    """A paid instance without paid_amount/paid_at synthesizes amount + due_date."""
    tok = register_and_login(client, "v3synth_fallback@test.com")

    r = client.post("/bills", json=_BILL_ALPHA, headers=auth(tok))
    assert r.status_code == 201
    template_id = r.json()["id"]

    template_dict = {
        "id": template_id,
        "name": _BILL_ALPHA["name"],
        "category": _BILL_ALPHA["category"],
        "frequency": _BILL_ALPHA["frequency"],
        "amount": _BILL_ALPHA["amount"],
        "currency": _BILL_ALPHA["currency"],
        "due_day": _BILL_ALPHA["due_day"],
        "notes": None,
        "is_archived": False,
        "is_paused": False,
        "start_period": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    instance_dict = _make_instance_dict(
        template_id,
        "2026-02",
        status="paid",
        paid_at=None,
        paid_amount=None,
        notes=None,
    )
    payload = _make_backup([template_dict], [instance_dict], schema_version=3)

    r = _upload(client, tok, payload)
    assert r.status_code == 200

    after = client.get("/export/json", headers=auth(tok)).json()
    assert len(after["payments"]) == 1
    payment = after["payments"][0]
    assert Decimal(str(payment["amount"])) == Decimal("100.0")
    assert payment["paid_on"] == "2026-02-15"
    assert payment["note"] is None


# ---------------------------------------------------------------------------
# POST /export/restore — error paths (lines 182–198 of export.py)
# ---------------------------------------------------------------------------


def test_restore_invalid_json_returns_422(client):
    """Malformed JSON body → 422 with 'Invalid JSON' detail."""
    tok = register_and_login(client, "inv_json@test.com")
    r = client.post(
        "/export/restore",
        files={"file": ("backup.json", b"not { valid json }", "application/json")},
        headers=auth(tok),
    )
    assert r.status_code == 422
    assert "json" in r.json()["detail"].lower()


def test_restore_unsupported_content_type_returns_415(client):
    """Non-JSON, non-plain content type → 415."""
    tok = register_and_login(client, "inv_ct@test.com")
    r = client.post(
        "/export/restore",
        files={"file": ("backup.json", b"{}", "application/pdf")},
        headers=auth(tok),
    )
    assert r.status_code == 415


def test_restore_file_too_large_returns_413(client):
    """File exceeding 10 MB → 413."""
    tok = register_and_login(client, "too_large@test.com")
    big_content = b"x" * (10 * 1024 * 1024 + 1)
    r = client.post(
        "/export/restore",
        files={"file": ("backup.json", big_content, "application/json")},
        headers=auth(tok),
    )
    assert r.status_code == 413


def test_restore_pydantic_validation_error_returns_422(client):
    """Valid schema_version but structurally invalid payload → 422 from Pydantic."""
    tok = register_and_login(client, "pydantic_err@test.com")
    # schema_version is valid (3) but bill_templates contains invalid data
    payload = {
        "schema_version": 3,
        "exported_by": "x@x.com",
        "exported_at": "2026-01-01T00:00:00+00:00",
        "bill_templates": [{"id": "not-an-int", "name": 123}],
        "payment_instances": [],
    }
    r = client.post(
        "/export/restore",
        files={
            "file": (
                "backup.json",
                __import__("json").dumps(payload).encode(),
                "application/json",
            )
        },
        headers=auth(tok),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# v5 schema: interval_count / start_date and legacy frequency normalization
# ---------------------------------------------------------------------------


def _template_dict(**overrides) -> dict:
    base = {
        "id": 1,
        "name": "Legacy Bill",
        "category": "utilities",
        "frequency": "monthly",
        "amount": 120.00,
        "currency": "PLN",
        "due_day": 15,
        "notes": None,
        "is_archived": False,
        "is_paused": False,
        "start_period": "2026-01",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "legacy,interval",
    [("every_2_months", 2), ("quarterly", 3)],
)
def test_restore_normalizes_legacy_frequency(client, legacy, interval):
    """v2-v4 backups map every_2_months/quarterly to monthly + interval."""
    tok = register_and_login(client, f"legacy_{legacy}@test.com")
    payload = _make_backup([_template_dict(frequency=legacy)], [], schema_version=3)

    r = _upload(client, tok, payload)
    assert r.status_code == 200, r.text

    bills = client.get("/bills", headers=auth(tok)).json()
    assert len(bills) == 1
    assert bills[0]["frequency"] == "monthly"
    assert bills[0]["interval_count"] == interval


def test_restore_legacy_frequency_with_interval_count_is_rejected(client):
    """Normalization only applies when interval_count is absent (v5 payloads
    always carry it), so an explicit interval with a legacy unit is invalid."""
    tok = register_and_login(client, "legacy_interval@test.com")
    payload = _make_backup(
        [_template_dict(frequency="quarterly", interval_count=3)],
        [],
        schema_version=3,
    )

    r = _upload(client, tok, payload)
    assert r.status_code == 422


def test_v5_round_trip_weekly_interval_and_start_date(client):
    tok = register_and_login(client, "v5weekly@test.com")
    r = client.post(
        "/bills",
        json={
            **_BILL,
            "frequency": "weekly",
            "start_date": "2026-01-05",
            "interval_count": 2,
            "due_day": None,
        },
        headers=auth(tok),
    )
    assert r.status_code == 201, r.text

    backup = client.get("/export/json", headers=auth(tok)).json()
    assert backup["schema_version"] == 8
    template = backup["bill_templates"][0]
    assert template["frequency"] == "weekly"
    assert template["interval_count"] == 2
    assert template["start_date"] == "2026-01-05"

    r = _upload(client, tok, backup)
    assert r.status_code == 200, r.text

    bills = client.get("/bills", headers=auth(tok)).json()
    assert len(bills) == 1
    assert bills[0]["frequency"] == "weekly"
    assert bills[0]["interval_count"] == 2
    assert bills[0]["start_date"] == "2026-01-05"


# ---------------------------------------------------------------------------
# v6 schema: categories export as key (defaults) or name (customs)
# ---------------------------------------------------------------------------


def _create_bill_with_category(
    client, token: str, name: str, category_id: int, **overrides
):
    payload = {
        **_BILL,
        "name": name,
        "category_id": category_id,
        **overrides,
    }
    payload.pop("category", None)
    r = client.post("/bills", json=payload, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def test_v6_export_default_category_as_key(client):
    tok = register_and_login(client, "v6key@test.com")
    cats = client.get("/categories", headers=auth(tok)).json()
    utilities = next(c for c in cats if c["key"] == "utilities")

    _create_bill_with_category(client, tok, "Power", utilities["id"])

    backup = client.get("/export/json", headers=auth(tok)).json()
    assert backup["schema_version"] == 8
    assert backup["bill_templates"][0]["category"] == "utilities"


def test_v6_round_trip_custom_category_name(client):
    tok = register_and_login(client, "v6custom@test.com")
    r = client.post("/categories", json={"name": "Streaming"}, headers=auth(tok))
    assert r.status_code == 201
    custom = r.json()

    bill = _create_bill_with_category(client, tok, "Netflix", custom["id"])
    assert bill["category"]["name"] == "Streaming"

    backup = client.get("/export/json", headers=auth(tok)).json()
    assert backup["bill_templates"][0]["category"] == "Streaming"

    r = _upload(client, tok, backup)
    assert r.status_code == 200, r.text

    bills = client.get("/bills", headers=auth(tok)).json()
    assert bills[0]["category"]["name"] == "Streaming"
    assert bills[0]["category"]["key"] is None

    cats = client.get("/categories", headers=auth(tok)).json()
    assert sum(1 for c in cats if (c["name"] or "").lower() == "streaming") == 1


def test_v6_rename_of_default_survives_restore(client):
    tok = register_and_login(client, "v6renamed@test.com")
    cats = client.get("/categories", headers=auth(tok)).json()
    utilities = next(c for c in cats if c["key"] == "utilities")
    r = client.patch(
        f"/categories/{utilities['id']}", json={"name": "Prąd"}, headers=auth(tok)
    )
    assert r.status_code == 200
    _create_bill_with_category(client, tok, "Power", utilities["id"])

    backup = client.get("/export/json", headers=auth(tok)).json()
    # Defaults always export their key so the rename resolves to the same row.
    assert backup["bill_templates"][0]["category"] == "utilities"

    r = _upload(client, tok, backup)
    assert r.status_code == 200, r.text
    bills = client.get("/bills", headers=auth(tok)).json()
    assert bills[0]["category"]["key"] == "utilities"
    assert bills[0]["category"]["name"] == "Prąd"


def test_v6_restore_creates_missing_default_key(client):
    tok = register_and_login(client, "v6missingkey@test.com")
    cats = client.get("/categories", headers=auth(tok)).json()
    insurance = next(c for c in cats if c["key"] == "insurance")
    r = client.delete(f"/categories/{insurance['id']}", headers=auth(tok))
    assert r.status_code == 204

    payload = _make_backup([_template_dict(category="insurance")], [])
    r = _upload(client, tok, payload)
    assert r.status_code == 200, r.text

    bills = client.get("/bills", headers=auth(tok)).json()
    assert bills[0]["category"]["key"] == "insurance"
    assert bills[0]["category"]["name"] is None


def test_v6_restore_null_category_maps_to_other(client):
    tok = register_and_login(client, "v6null@test.com")

    payload = _make_backup([_template_dict(category=None)], [])
    r = _upload(client, tok, payload)
    assert r.status_code == 200, r.text

    bills = client.get("/bills", headers=auth(tok)).json()
    assert bills[0]["category"]["key"] == "other"


def test_restore_never_deletes_user_categories(client):
    tok = register_and_login(client, "v6keep@test.com")
    r = client.post("/categories", json={"name": "Pets"}, headers=auth(tok))
    assert r.status_code == 201

    r = _upload(client, tok, _make_backup([], []))
    assert r.status_code == 200

    cats = client.get("/categories", headers=auth(tok)).json()
    assert "Pets" in [c["name"] for c in cats]


# ---------------------------------------------------------------------------
# v7 schema: max_occurrences
# ---------------------------------------------------------------------------


def test_v7_round_trip_max_occurrences(client):
    tok = register_and_login(client, "v7max@test.com")
    r = client.post("/bills", json={**_BILL, "max_occurrences": 4}, headers=auth(tok))
    assert r.status_code == 201, r.text

    backup = client.get("/export/json", headers=auth(tok)).json()
    assert backup["schema_version"] == 8
    assert backup["bill_templates"][0]["max_occurrences"] == 4

    r = _upload(client, tok, backup)
    assert r.status_code == 200, r.text

    bills = client.get("/bills", headers=auth(tok)).json()
    assert len(bills) == 1
    assert bills[0]["max_occurrences"] == 4


def test_v7_export_includes_null_max_occurrences(client):
    tok = register_and_login(client, "v7null@test.com")
    r = client.post("/bills", json=_BILL, headers=auth(tok))
    assert r.status_code == 201

    backup = client.get("/export/json", headers=auth(tok)).json()
    assert backup["schema_version"] == 8
    assert backup["bill_templates"][0]["max_occurrences"] is None


def test_v6_backup_restores_with_null_max_occurrences(client):
    """A v6 payload has no max_occurrences field; it restores as unlimited."""
    tok = register_and_login(client, "v6max@test.com")
    payload = _make_backup([_template_dict()], [], schema_version=6)

    r = _upload(client, tok, payload)
    assert r.status_code == 200, r.text

    bills = client.get("/bills", headers=auth(tok)).json()
    assert len(bills) == 1
    assert bills[0]["max_occurrences"] is None


def test_v7_backup_can_clear_existing_cap(client):
    """Restore is destructive: a v7 backup without a cap clears a live one."""
    tok = register_and_login(client, "v7clear@test.com")
    r = client.post("/bills", json={**_BILL, "max_occurrences": 6}, headers=auth(tok))
    assert r.status_code == 201

    payload = _make_backup([_template_dict()], [], schema_version=7)
    r = _upload(client, tok, payload)
    assert r.status_code == 200, r.text

    bills = client.get("/bills", headers=auth(tok)).json()
    assert bills[0]["max_occurrences"] is None


# ---------------------------------------------------------------------------
# Restore payload validation (hardening)
# ---------------------------------------------------------------------------


def _valid_instance(**overrides) -> dict:
    base = {
        "id": 1,
        "bill_id": 1,
        "period": "2026-01",
        "due_date": "2026-01-15",
        "amount": 100.0,
        "status": "upcoming",
        "paid_at": None,
        "paid_amount": None,
        "notes": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "period",
    ["2026-13", "2026-00", "2026-1", "202601", "not-a-period"],
)
def test_restore_invalid_instance_period_returns_422(client, period):
    tok = register_and_login(client, "bad_period@test.com")
    payload = _make_backup(
        [_template_dict()], [_valid_instance(period=period)], schema_version=7
    )
    r = _upload(client, tok, payload)
    assert r.status_code == 422, period


@pytest.mark.parametrize("start_period", ["2026-13", "2026-1", "nope"])
def test_restore_invalid_start_period_returns_422(client, start_period):
    tok = register_and_login(client, "bad_start_period@test.com")
    payload = _make_backup(
        [_template_dict(start_period=start_period)], [], schema_version=7
    )
    r = _upload(client, tok, payload)
    assert r.status_code == 422, start_period


@pytest.mark.parametrize(
    "field,value",
    [
        ("due_date", "15/01/2026"),
        ("due_date", "2026-13-01"),
        ("paid_at", "yesterday"),
        ("created_at", "not-a-datetime"),
    ],
)
def test_restore_invalid_instance_dates_return_422(client, field, value):
    tok = register_and_login(client, "bad_date@test.com")
    payload = _make_backup(
        [_template_dict()], [_valid_instance(**{field: value})], schema_version=7
    )
    r = _upload(client, tok, payload)
    assert r.status_code == 422, f"{field}={value}"


@pytest.mark.parametrize("currency", ["pln", "€", "US D", "TOOLONGVALUE"])
def test_restore_invalid_currency_returns_422(client, currency):
    tok = register_and_login(client, "bad_currency@test.com")
    payload = _make_backup([_template_dict(currency=currency)], [], schema_version=7)
    r = _upload(client, tok, payload)
    assert r.status_code == 422, currency


def test_restore_invalid_payment_fields_return_422(client):
    tok = register_and_login(client, "bad_payment@test.com")
    instance = _valid_instance(status="paid", paid_at="2026-01-15T00:00:00+00:00")
    payload = _make_backup([_template_dict()], [instance], schema_version=7)
    payload["payments"] = [
        {
            "id": 1,
            "instance_id": 1,
            "amount": 10.0,
            "paid_on": "15-01-2026",
            "note": None,
            "created_at": "2026-01-15T00:00:00+00:00",
        }
    ]
    r = _upload(client, tok, payload)
    assert r.status_code == 422


def test_restore_non_object_json_returns_422(client):
    tok = register_and_login(client, "non_object@test.com")
    r = client.post(
        "/export/restore",
        files={"file": ("backup.json", b"[1, 2, 3]", "application/json")},
        headers=auth(tok),
    )
    assert r.status_code == 422


@pytest.mark.parametrize("collection", ["bill_templates", "payment_instances"])
def test_restore_collection_cap_returns_422(client, collection):
    tok = register_and_login(client, "too_many@test.com")
    payload = _make_backup([], [])
    payload[collection] = [{} for _ in range(5001)]
    r = _upload(client, tok, payload)
    assert r.status_code == 422


def test_restore_rate_limited_returns_429(client):
    tok = register_and_login(client, "restore_rl@test.com")
    original = settings.restore_rate_limit
    try:
        settings.restore_rate_limit = 1
        reset_rate_limits("restore")
        first = _upload(client, tok, _make_backup([], []))
        assert first.status_code == 200
        second = _upload(client, tok, _make_backup([], []))
        assert second.status_code == 429
    finally:
        settings.restore_rate_limit = original
        reset_rate_limits("restore")
