"""Per-user data isolation tests.

Each test registers two users (A and B), creates data as A, then asserts
B cannot see or mutate it.
"""

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


def _create_bill(client, token: str) -> int:
    r = client.post("/bills", json=_BILL, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_payment(client, token: str, bill_id: int) -> int:
    """Sync instances then return the instance id for bill_id."""
    sync_payments(client, token)
    r = client.get("/bills/payments", headers=auth(token))
    assert r.status_code == 200, r.text
    instances = [i for i in r.json() if i["bill_id"] == bill_id]
    assert instances, f"No payment instance found for bill_id={bill_id}"
    return instances[0]["id"]


# ---------------------------------------------------------------------------
# List endpoints
# ---------------------------------------------------------------------------


def test_list_bills_scoped(client):
    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    _create_bill(client, tok_a)
    _create_bill(client, tok_a)

    r = client.get("/bills", headers=auth(tok_b))
    assert r.status_code == 200
    assert r.json() == []


def test_list_payments_scoped(client):
    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    _create_bill(client, tok_a)
    sync_payments(client, tok_a)
    client.get("/bills/payments", headers=auth(tok_a))

    r = client.get("/bills/payments", headers=auth(tok_b))
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Mutation endpoints — must return 404 for cross-user access (no existence oracle)
# ---------------------------------------------------------------------------


def test_mark_paid_other_user_returns_404(client):
    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    bill_id = _create_bill(client, tok_a)
    instance_id = _seed_payment(client, tok_a, bill_id)

    r = client.post(
        f"/bills/payments/{instance_id}/pay",
        json={"paid_amount": None, "notes": None},
        headers=auth(tok_b),
    )
    assert r.status_code == 404


def test_revert_payment_other_user_returns_404(client):
    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    bill_id = _create_bill(client, tok_a)
    instance_id = _seed_payment(client, tok_a, bill_id)

    # A marks paid first
    client.post(
        f"/bills/payments/{instance_id}/pay",
        json={"paid_amount": None, "notes": None},
        headers=auth(tok_a),
    )

    r = client.post(
        f"/bills/payments/{instance_id}/unpay",
        headers=auth(tok_b),
    )
    assert r.status_code == 404


def test_update_bill_other_user_returns_404(client):
    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    bill_id = _create_bill(client, tok_a)

    r = client.patch(
        f"/bills/{bill_id}",
        json={"name": "Hacked"},
        headers=auth(tok_b),
    )
    assert r.status_code == 404


def test_archive_bill_other_user_returns_404(client):
    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    bill_id = _create_bill(client, tok_a)

    r = client.post(f"/bills/{bill_id}/archive", headers=auth(tok_b))
    assert r.status_code == 404


def test_delete_payment_other_user_returns_404(client):
    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    bill_id = _create_bill(client, tok_a)
    instance_id = _seed_payment(client, tok_a, bill_id)

    r = client.delete(f"/bills/payments/{instance_id}", headers=auth(tok_b))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------


def test_export_json_scoped(client):
    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    _create_bill(client, tok_a)
    _create_bill(client, tok_a)

    r = client.get("/export/json", headers=auth(tok_b))
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 8
    assert data["exported_by"] == "b@test.com"
    assert "users" not in data
    assert data["bill_templates"] == []
    assert data["payment_instances"] == []
    assert data["payments"] == []


def test_export_xlsx_scoped(client):
    import io
    import openpyxl

    tok_a = register_and_login(client, "a@test.com")
    tok_b = register_and_login(client, "b@test.com")

    _create_bill(client, tok_a)

    r = client.get("/export/xlsx", headers=auth(tok_b))
    assert r.status_code == 200
    assert (
        r.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    for sheet in wb.worksheets:
        # Each sheet has a header row only; no data rows for user B.
        assert sheet.max_row <= 1, f"Sheet {sheet.title} has unexpected data rows"
