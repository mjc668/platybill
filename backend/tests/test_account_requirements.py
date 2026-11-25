"""Tests for account resolution, ad-hoc payment instances, and GET /accounts/requirements."""

from datetime import date, timedelta
from decimal import Decimal

from app.models.bank_account import BankAccount
from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from app.models.import_draft import ImportDraft, ImportSource, ImportStatus
from app.models.user import User
from app.services.bank_accounts import resolve_instance_account
from app.services.recurrence import (
    ensure_current_period_instances,
    generate_future_instances,
)
from tests.conftest import auth, register_and_login

_BILL = {
    "name": "Electricity",
    "category": "utilities",
    "frequency": "monthly",
    "amount": "100.00",
    "currency": "AUD",
    "due_day": 15,
    "is_paused": False,
}


def _create_account(client, token: str, name: str) -> dict:
    r = client.post("/bank-accounts", json={"name": name}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _create_bill(client, token: str, **overrides) -> dict:
    body = {**_BILL, **overrides}
    r = client.post("/bills", json=body, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _insert_instance(
    db,
    *,
    bill_id: int | None = None,
    user_id: int | None = None,
    account_id: int | None = None,
    label: str | None = None,
    due_date: date,
    amount: str = "100.00",
    amount_estimated: bool = False,
    status: PaymentStatus = PaymentStatus.upcoming,
    paid_amount: str | None = None,
    is_deleted: bool = False,
) -> PaymentInstance:
    inst = PaymentInstance(
        bill_id=bill_id,
        user_id=user_id,
        account_id=account_id,
        label=label,
        period=due_date.strftime("%Y-%m"),
        due_date=due_date,
        amount=Decimal(amount),
        amount_estimated=amount_estimated,
        status=status,
        paid_amount=Decimal(paid_amount) if paid_amount is not None else None,
        is_deleted=is_deleted,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)
    return inst


def test_account_resolution_precedence(client_db):
    """instance.account_id -> template.preferred_account_id -> None (Unspecified)."""
    client, db = client_db
    token = register_and_login(client, "res_prec@test.com")
    user = db.query(User).filter(User.email == "res_prec@test.com").one()

    acc_template = _create_account(client, token, "ING card")
    acc_override = _create_account(client, token, "Everyday")

    bill_with_acc = _create_bill(
        client, token, name="AGL Gas", preferred_account_id=acc_template["id"]
    )
    bill_without_acc = _create_bill(client, token, name="Water")

    # 1. Explicit instance override wins over template preferred_account.
    inst_override = _insert_instance(
        db,
        bill_id=bill_with_acc["id"],
        user_id=user.id,
        account_id=acc_override["id"],
        due_date=date(2026, 12, 3),
        amount="120.00",
    )
    resolved = resolve_instance_account(inst_override)
    assert resolved is not None
    assert resolved.id == acc_override["id"]
    assert resolved.name == "Everyday"

    # 2. Falls back to template preferred_account when instance.account_id is None.
    inst_inherited = _insert_instance(
        db,
        bill_id=bill_with_acc["id"],
        user_id=user.id,
        due_date=date(2026, 12, 10),
        amount="130.00",
    )
    resolved = resolve_instance_account(inst_inherited)
    assert resolved is not None
    assert resolved.id == acc_template["id"]
    assert resolved.name == "ING card"

    # 3. Template with no preferred_account and no override -> None (Unspecified).
    inst_unspec = _insert_instance(
        db,
        bill_id=bill_without_acc["id"],
        user_id=user.id,
        due_date=date(2026, 12, 5),
        amount="45.00",
    )
    assert resolve_instance_account(inst_unspec) is None

    # 4. Ad-hoc with account_id -> resolves to that account.
    inst_adhoc_acc = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc_template["id"],
        label="Afterpay: AMCALPHARMA",
        due_date=date(2026, 12, 6),
        amount="145.87",
    )
    resolved = resolve_instance_account(inst_adhoc_acc)
    assert resolved is not None
    assert resolved.id == acc_template["id"]

    # 5. Ad-hoc with no account_id -> None (Unspecified).
    inst_adhoc_unspec = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        label="Afterpay: Kmart",
        due_date=date(2026, 12, 6),
        amount="28.50",
    )
    assert resolve_instance_account(inst_adhoc_unspec) is None


def test_requirements_window_boundaries_inclusive(client_db):
    """Window is inclusive on both ends: from and to count; day before/after do not."""
    client, db = client_db
    token = register_and_login(client, "req_bounds@test.com")
    user = db.query(User).filter(User.email == "req_bounds@test.com").one()
    acc = _create_account(client, token, "ING card")

    _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc["id"],
        label="Before window",
        due_date=date(2026, 11, 30),
        amount="10.00",
    )
    on_from = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc["id"],
        label="On from",
        due_date=date(2026, 12, 1),
        amount="20.00",
    )
    on_to = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc["id"],
        label="On to",
        due_date=date(2026, 12, 7),
        amount="30.50",
    )
    _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc["id"],
        label="After window",
        due_date=date(2026, 12, 8),
        amount="40.00",
    )

    r = client.get(
        "/accounts/requirements?from=2026-12-01&to=2026-12-07",
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["from"] == "2026-12-01"
    assert data["to"] == "2026-12-07"
    assert len(data["buckets"]) == 1
    bucket = data["buckets"][0]
    assert bucket["account_id"] == acc["id"]
    assert bucket["account_name"] == "ING card"
    assert bucket["total_due"] == "50.50"
    assert bucket["total_estimated"] == "0.00"
    assert [item["instance_id"] for item in bucket["items"]] == [on_from.id, on_to.id]


def test_requirements_default_window_and_empty_omission(client_db):
    """Defaults to today..today+7 and omits accounts with no items in window."""
    client, db = client_db
    token = register_and_login(client, "req_default@test.com")
    user = db.query(User).filter(User.email == "req_default@test.com").one()
    _create_account(client, token, "Empty Account")
    active = _create_account(client, token, "ING card")

    today = date.today()
    _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=active["id"],
        label="Due in 3 days",
        due_date=today + timedelta(days=3),
        amount="55.00",
    )
    _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=active["id"],
        label="Due in 8 days",
        due_date=today + timedelta(days=8),
        amount="99.00",
    )

    r = client.get("/accounts/requirements", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["from"] == today.isoformat()
    assert data["to"] == (today + timedelta(days=7)).isoformat()
    assert len(data["buckets"]) == 1
    assert data["buckets"][0]["account_name"] == "ING card"
    assert data["buckets"][0]["total_due"] == "55.00"


def test_requirements_excludes_paid_and_deleted(client_db):
    """Paid and soft-deleted instances are excluded from account requirements."""
    client, db = client_db
    token = register_and_login(client, "req_excl@test.com")
    user = db.query(User).filter(User.email == "req_excl@test.com").one()
    acc = _create_account(client, token, "ING card")

    unpaid = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc["id"],
        label="Still unpaid",
        due_date=date(2026, 12, 3),
        amount="75.00",
        status=PaymentStatus.upcoming,
    )
    _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc["id"],
        label="Already paid",
        due_date=date(2026, 12, 4),
        amount="80.00",
        status=PaymentStatus.paid,
        paid_amount="80.00",
    )
    _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc["id"],
        label="Deleted row",
        due_date=date(2026, 12, 5),
        amount="90.00",
        is_deleted=True,
    )

    r = client.get(
        "/accounts/requirements?from=2026-12-01&to=2026-12-07",
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    buckets = r.json()["buckets"]
    assert len(buckets) == 1
    assert buckets[0]["total_due"] == "75.00"
    assert [i["instance_id"] for i in buckets[0]["items"]] == [unpaid.id]


def test_requirements_estimates_override_and_unspecified_bucket(client_db):
    """Estimated amounts count in total_due AND total_estimated; override wins; Unspecified bucket shown."""
    client, db = client_db
    token = register_and_login(client, "req_full@test.com")
    user = db.query(User).filter(User.email == "req_full@test.com").one()

    ing = _create_account(client, token, "ING card")
    other = _create_account(client, token, "Other card")

    gas = _create_bill(
        client,
        token,
        name="AGL Retail Energy Limited GAS",
        preferred_account_id=ing["id"],
        amount_varies=True,
    )
    phone = _create_bill(
        client,
        token,
        name="Mobile",
        preferred_account_id=other["id"],
    )

    # Estimated template-backed bill inheriting ING card.
    gas_inst = _insert_instance(
        db,
        bill_id=gas["id"],
        user_id=user.id,
        due_date=date(2026, 12, 3),
        amount="266.43",
        amount_estimated=True,
    )
    # Ad-hoc payment assigned directly to ING card.
    ap_inst = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=ing["id"],
        label="Afterpay: AMCALPHARMA",
        due_date=date(2026, 12, 6),
        amount="145.87",
    )
    # Template has "Other card", but instance overrides to "ING card".
    override_inst = _insert_instance(
        db,
        bill_id=phone["id"],
        user_id=user.id,
        account_id=ing["id"],
        due_date=date(2026, 12, 7),
        amount="50.00",
    )
    # Unspecified ad-hoc payment.
    unspec_inst = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        label="Afterpay: Unassigned",
        due_date=date(2026, 12, 4),
        amount="28.50",
    )

    r = client.get(
        "/accounts/requirements?from=2026-12-01&to=2026-12-07",
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    data = r.json()

    # "Other card" has no items after override so it is omitted.
    assert [b["account_name"] for b in data["buckets"]] == ["ING card", "Unspecified"]

    ing_bucket = data["buckets"][0]
    assert ing_bucket["account_id"] == ing["id"]
    assert ing_bucket["total_due"] == "462.30"
    assert ing_bucket["total_estimated"] == "266.43"
    assert [i["instance_id"] for i in ing_bucket["items"]] == [
        gas_inst.id,
        ap_inst.id,
        override_inst.id,
    ]
    assert ing_bucket["items"][0]["label"] == "AGL Retail Energy Limited GAS"
    assert ing_bucket["items"][0]["amount"] == "266.43"
    assert ing_bucket["items"][0]["amount_estimated"] is True
    assert ing_bucket["items"][1]["label"] == "Afterpay: AMCALPHARMA"
    assert ing_bucket["items"][1]["amount"] == "145.87"
    assert ing_bucket["items"][1]["amount_estimated"] is False

    unspec_bucket = data["buckets"][1]
    assert unspec_bucket["account_id"] is None
    assert unspec_bucket["account_name"] == "Unspecified"
    assert unspec_bucket["total_due"] == "28.50"
    assert unspec_bucket["total_estimated"] == "0.00"
    assert [i["instance_id"] for i in unspec_bucket["items"]] == [unspec_inst.id]


def test_requirements_user_scoping_and_invalid_range(client_db):
    """Other users' payments (template or ad-hoc) never leak; to < from returns 422."""
    client, db = client_db
    tok_a = register_and_login(client, "req_a@test.com")
    tok_b = register_and_login(client, "req_b@test.com")
    user_a = db.query(User).filter(User.email == "req_a@test.com").one()

    _insert_instance(
        db,
        bill_id=None,
        user_id=user_a.id,
        label="A's ad-hoc",
        due_date=date(2026, 12, 3),
        amount="33.00",
    )

    r = client.get(
        "/accounts/requirements?from=2026-12-01&to=2026-12-07",
        headers=auth(tok_b),
    )
    assert r.status_code == 200, r.text
    assert r.json()["buckets"] == []

    bad = client.get(
        "/accounts/requirements?from=2026-12-10&to=2026-12-01",
        headers=auth(tok_a),
    )
    assert bad.status_code == 422


def test_two_adhoc_instances_same_due_date_coexist(client_db):
    """NULL bill_id values are distinct in uq_payment_instance_bill_due_date."""
    client, db = client_db
    token = register_and_login(client, "adhoc_same_day@test.com")
    user = db.query(User).filter(User.email == "adhoc_same_day@test.com").one()

    i1 = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        label="Afterpay: Merchant A",
        due_date=date(2026, 12, 5),
        amount="40.00",
    )
    i2 = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        label="Afterpay: Merchant B",
        due_date=date(2026, 12, 5),
        amount="60.00",
    )
    assert i1.id != i2.id
    r = client.get(
        "/accounts/requirements?from=2026-12-05&to=2026-12-05",
        headers=auth(token),
    )
    assert r.status_code == 200
    assert r.json()["buckets"][0]["total_due"] == "100.00"
    assert len(r.json()["buckets"][0]["items"]) == 2


def test_generation_and_stats_ignore_adhoc_instances(client_db):
    """Recurrence generation and stats overview ignore bill_id IS NULL without error."""
    client, db = client_db
    token = register_and_login(client, "adhoc_safe@test.com")
    user = db.query(User).filter(User.email == "adhoc_safe@test.com").one()

    _create_bill(client, token, name="Internet", amount="80.00", due_day=10)
    today = date.today()
    _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        label="Afterpay: One-off",
        due_date=today,
        amount="50.00",
    )

    ensure_current_period_instances(db, today.strftime("%Y-%m"), user.id)
    created, bill_count = generate_future_instances(db, user.id, months=2, today=today)
    assert bill_count == 1
    assert created >= 1

    r = client.get("/stats/overview", headers=auth(token))
    assert r.status_code == 200, r.text
    # Stats counts the 80.00 template bill and does not crash on the ad-hoc row.
    assert Decimal(str(r.json()["summary"]["due_total"])) == Decimal("80.00")


def test_patch_payment_instance_account_and_amount(client_db):
    """PATCH /bills/payments/{id} sets, changes, clears account_id and edits amount."""
    client, db = client_db
    token = register_and_login(client, "patch_inst@test.com")
    other = register_and_login(client, "patch_inst_other@test.com")
    user = db.query(User).filter(User.email == "patch_inst@test.com").one()

    acc1 = _create_account(client, token, "ING card")
    acc2 = _create_account(client, token, "Everyday")
    foreign_acc = _create_account(client, other, "Foreign")
    bill = _create_bill(client, token, name="Gas", preferred_account_id=acc1["id"])
    inst = _insert_instance(
        db,
        bill_id=bill["id"],
        user_id=user.id,
        due_date=date(2026, 12, 10),
        amount="90.00",
        amount_estimated=True,
    )

    # Set explicit override + confirm amount in one PATCH.
    r = client.patch(
        f"/bills/payments/{inst.id}",
        json={"account_id": acc2["id"], "amount": "95.50"},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account_id"] == acc2["id"]
    assert body["preferred_account"]["id"] == acc2["id"]
    assert body["amount"] == "95.50"
    assert body["amount_estimated"] is False

    # Clear override with null -> falls back to template's preferred_account.
    r = client.patch(
        f"/bills/payments/{inst.id}",
        json={"account_id": None},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account_id"] is None
    assert body["preferred_account"]["id"] == acc1["id"]

    # Foreign account -> 404.
    r = client.patch(
        f"/bills/payments/{inst.id}",
        json={"account_id": foreign_acc["id"]},
        headers=auth(token),
    )
    assert r.status_code == 404


def test_import_confirm_accepts_account_id_and_adhoc(client_db):
    """POST /import/drafts/{id}/confirm applies optional account_id to template and ad-hoc instances."""
    client, db = client_db
    token = register_and_login(client, "imp_acc@test.com")
    user = db.query(User).filter(User.email == "imp_acc@test.com").one()

    acc = _create_account(client, token, "ING card")
    bill = _create_bill(client, token, name="Sydney Water")

    # 1. Template-backed confirm with account_id override.
    draft1 = ImportDraft(
        user_id=user.id,
        source=ImportSource.upload,
        source_ref="upload:acc-test-1",
        provider="Sydney Water",
        amount=Decimal("112.40"),
        currency="AUD",
        due_date=date(2026, 12, 4),
        period="2026-12",
        matched_bill_id=bill["id"],
        status=ImportStatus.pending,
    )
    db.add(draft1)
    db.commit()
    db.refresh(draft1)

    r = client.post(
        f"/import/drafts/{draft1.id}/confirm",
        json={"bill_id": bill["id"], "account_id": acc["id"]},
        headers=auth(token),
    )
    assert r.status_code == 200, r.text
    inst1 = db.get(PaymentInstance, r.json()["instance_id"])
    assert inst1 is not None
    assert inst1.account_id == acc["id"]
    assert inst1.bill_id == bill["id"]

    # 2. Ad-hoc confirm (no template) with account_id.
    draft2 = ImportDraft(
        user_id=user.id,
        source=ImportSource.email,
        source_ref="email:acc-test-2",
        provider="Afterpay: AMCALPHARMA",
        amount=Decimal("45.00"),
        currency="AUD",
        due_date=date(2026, 12, 5),
        period="2026-12",
        matched_bill_id=None,
        status=ImportStatus.pending,
    )
    db.add(draft2)
    db.commit()
    db.refresh(draft2)

    r2 = client.post(
        f"/import/drafts/{draft2.id}/confirm",
        json={"ad_hoc": True, "account_id": acc["id"]},
        headers=auth(token),
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["bill_id"] is None
    assert body2["created_instance"] is True
    inst2 = db.get(PaymentInstance, body2["instance_id"])
    assert inst2 is not None
    assert inst2.bill_id is None
    assert inst2.label == "Afterpay: AMCALPHARMA"
    assert inst2.account_id == acc["id"]
    assert inst2.user_id == user.id


def test_payments_list_uses_resolved_account_and_handles_adhoc(client_db):
    """GET /bills/payments displays resolved account and includes ad-hoc instances."""
    client, db = client_db
    token = register_and_login(client, "list_res@test.com")
    user = db.query(User).filter(User.email == "list_res@test.com").one()

    acc_tpl = _create_account(client, token, "ING card")
    acc_ovr = _create_account(client, token, "Everyday")
    bill = _create_bill(
        client, token, name="Internet", preferred_account_id=acc_tpl["id"]
    )

    inst_override = _insert_instance(
        db,
        bill_id=bill["id"],
        user_id=user.id,
        account_id=acc_ovr["id"],
        due_date=date(2026, 12, 3),
        amount="80.00",
    )
    inst_adhoc = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc_tpl["id"],
        label="Afterpay: Bunnings",
        due_date=date(2026, 12, 5),
        amount="35.00",
    )

    r = client.get("/bills/payments?month=2026-12", headers=auth(token))
    assert r.status_code == 200, r.text
    by_id = {row["id"]: row for row in r.json()}

    assert by_id[inst_override.id]["preferred_account"]["name"] == "Everyday"
    assert by_id[inst_override.id]["account_id"] == acc_ovr["id"]
    assert by_id[inst_adhoc.id]["bill_id"] is None
    assert by_id[inst_adhoc.id]["bill_name"] == "Afterpay: Bunnings"
    assert by_id[inst_adhoc.id]["preferred_account"]["name"] == "ING card"

    # Paying an ad-hoc instance must not crash trying to generate next recurrence.
    pay_r = client.post(
        f"/bills/payments/{inst_adhoc.id}/pay",
        json={},
        headers=auth(token),
    )
    assert pay_r.status_code == 200, pay_r.text
    assert pay_r.json()["status"] == "paid"


def test_delete_account_blocked_when_referenced_by_instance(client_db):
    """Deleting a bank account referenced by PaymentInstance.account_id is refused."""
    client, db = client_db
    token = register_and_login(client, "del_acc_inst@test.com")
    user = db.query(User).filter(User.email == "del_acc_inst@test.com").one()

    acc = _create_account(client, token, "ING card")
    _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        account_id=acc["id"],
        label="Afterpay: Store",
        due_date=date(2026, 12, 5),
        amount="50.00",
    )

    r = client.delete(f"/bank-accounts/{acc['id']}", headers=auth(token))
    assert r.status_code == 400, r.text


def test_delete_adhoc_with_delete_future_does_not_wipe_other_adhoc(client_db):
    """DELETE /bills/payments/{id}?delete_future=true on an ad-hoc row only deletes that row."""
    client, db = client_db
    token = register_and_login(client, "del_adhoc@test.com")
    user = db.query(User).filter(User.email == "del_adhoc@test.com").one()

    first = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        label="Afterpay: One",
        due_date=date(2026, 12, 2),
        amount="25.00",
    )
    second = _insert_instance(
        db,
        bill_id=None,
        user_id=user.id,
        label="Afterpay: Two",
        due_date=date(2026, 12, 6),
        amount="30.00",
    )

    r = client.delete(
        f"/bills/payments/{first.id}?delete_future=true", headers=auth(token)
    )
    assert r.status_code == 204, r.text

    db.expire_all()
    assert db.get(PaymentInstance, first.id).is_deleted is True
    assert db.get(PaymentInstance, second.id).is_deleted is False
