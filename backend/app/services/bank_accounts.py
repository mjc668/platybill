"""Per-user bank accounts.

Bills reference `preferred_account_id`; renaming an account relabels existing
bills and payments, and accounts are archived rather than deleted while any
template still references them.

Nothing here commits — callers own the transaction.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, selectinload

from app.models.bank_account import BankAccount
from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from app.schemas.bank_account import (
    AccountRequirementBucket,
    AccountRequirementItem,
    AccountRequirementsOut,
)

UNSPECIFIED_ACCOUNT_NAME = "Unspecified"
_CENTS = Decimal("0.01")


def resolve_instance_account(instance: PaymentInstance) -> BankAccount | None:
    """Resolve effective bank account for a payment instance.

    Precedence:
      1. instance.account (when instance.account_id is set)
      2. instance.template.preferred_account (when bill_id is set)
      3. None (Unspecified)
    """
    if instance.account_id is not None:
        return instance.account
    if instance.template is not None:
        return instance.template.preferred_account
    return None


def resolve_instance_label(instance: PaymentInstance) -> str:
    """Display label for a payment instance (ad-hoc label or template name)."""
    if instance.label:
        return instance.label
    if instance.template is not None:
        return instance.template.name
    return f"Payment #{instance.id}"


class BankAccountError(Exception):
    """Base class for service-level bank-account failures.

    Routers map `status_code` onto the HTTP response.
    """

    status_code: int = 400


class BankAccountNotFoundError(BankAccountError):
    status_code = 404


class BankAccountArchivedError(BankAccountError):
    status_code = 422


class BankAccountInvalidError(BankAccountError):
    status_code = 422


class BankAccountNameConflictError(BankAccountError):
    status_code = 409


class BankAccountInUseError(BankAccountError):
    status_code = 400


def list_accounts(
    db: Session, user_id: int, *, include_archived: bool = False
) -> list[BankAccount]:
    """Accounts in stable order: by name, then id."""
    query = db.query(BankAccount).filter(BankAccount.user_id == user_id)
    if not include_archived:
        query = query.filter(BankAccount.is_archived.is_(False))
    return query.order_by(func.lower(BankAccount.name), BankAccount.id).all()


def get_for_user(
    db: Session, user_id: int, account_id: int, *, allow_archived: bool = False
) -> BankAccount:
    account = db.get(BankAccount, account_id)
    if account is None or account.user_id != user_id:
        raise BankAccountNotFoundError("Bank account not found")
    if account.is_archived and not allow_archived:
        raise BankAccountArchivedError("Bank account is archived")
    return account


def _find_by_name(
    db: Session, user_id: int, name: str, *, exclude_id: int | None = None
) -> BankAccount | None:
    query = db.query(BankAccount).filter(
        BankAccount.user_id == user_id,
        func.lower(BankAccount.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.filter(BankAccount.id != exclude_id)
    return query.first()


def create_account(
    db: Session,
    user_id: int,
    name: str,
    iban: str | None = None,
    note: str | None = None,
) -> BankAccount:
    """Create an account, rejecting case-insensitive duplicate names."""
    cleaned = name.strip()
    if not cleaned:
        raise BankAccountInvalidError("Bank account name must not be blank")
    if _find_by_name(db, user_id, cleaned) is not None:
        raise BankAccountNameConflictError(
            "A bank account with this name already exists"
        )
    account = BankAccount(
        user_id=user_id,
        name=cleaned,
        iban=iban.strip() or None if iban else None,
        note=note.strip() or None if note else None,
    )
    db.add(account)
    db.flush()
    return account


def update_account(
    db: Session,
    user_id: int,
    account_id: int,
    *,
    name: str | None = None,
    iban: str | None = None,
    note: str | None = None,
    is_archived: bool | None = None,
) -> BankAccount:
    account = get_for_user(db, user_id, account_id, allow_archived=True)
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise BankAccountInvalidError("Bank account name must not be blank")
        if _find_by_name(db, user_id, cleaned, exclude_id=account.id) is not None:
            raise BankAccountNameConflictError(
                "A bank account with this name already exists"
            )
        account.name = cleaned
    if iban is not None:
        account.iban = iban.strip() or None
    if note is not None:
        account.note = note.strip() or None
    if is_archived is not None:
        account.is_archived = is_archived
    db.flush()
    return account


def delete_account(db: Session, user_id: int, account_id: int) -> None:
    """Hard-delete an unused account; refuse while any template or payment references it."""
    account = get_for_user(db, user_id, account_id, allow_archived=True)
    in_use_bill = (
        db.query(BillTemplate.id)
        .filter(BillTemplate.preferred_account_id == account.id)
        .first()
    )
    in_use_instance = (
        db.query(PaymentInstance.id)
        .filter(PaymentInstance.account_id == account.id)
        .first()
    )
    if in_use_bill is not None or in_use_instance is not None:
        raise BankAccountInUseError(
            "Bank account is used by existing bills or payments; archive it instead"
        )
    db.delete(account)
    db.flush()


def get_account_requirements(
    db: Session,
    owner_id: int,
    from_date: date,
    to_date: date,
    *,
    default_currency: str | None = None,
) -> AccountRequirementsOut:
    """Aggregate unpaid, non-deleted payment instances by resolved bank account.

    Includes both template-backed and ad-hoc (`bill_id IS NULL`) instances whose
    `due_date` falls within `[from_date, to_date]` inclusive. Estimated amounts
    are included in `total_due` and summed separately in `total_estimated`.
    Empty accounts are omitted; an `Unspecified` bucket (`account_id=None`) is
    appended when any matching instance has no resolvable account.
    """
    instances = (
        db.query(PaymentInstance)
        .options(
            selectinload(PaymentInstance.account),
            selectinload(PaymentInstance.template).selectinload(
                BillTemplate.preferred_account
            ),
            selectinload(PaymentInstance.user),
        )
        .outerjoin(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            or_(
                and_(
                    PaymentInstance.bill_id.is_not(None),
                    BillTemplate.user_id == owner_id,
                    BillTemplate.is_deleted.is_(False),
                    or_(
                        BillTemplate.is_archived.is_(False),
                        PaymentInstance.payments.any(),
                    ),
                ),
                and_(
                    PaymentInstance.bill_id.is_(None),
                    PaymentInstance.user_id == owner_id,
                ),
            ),
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.status != PaymentStatus.paid,
            PaymentInstance.due_date >= from_date,
            PaymentInstance.due_date <= to_date,
        )
        .order_by(PaymentInstance.due_date, PaymentInstance.id)
        .all()
    )

    fallback_currency = default_currency or "PLN"
    grouped: dict[int | None, tuple[str, list[AccountRequirementItem]]] = {}

    for inst in instances:
        account = resolve_instance_account(inst)
        account_id = account.id if account is not None else None
        account_name = account.name if account is not None else UNSPECIFIED_ACCOUNT_NAME

        paid = inst.paid_amount or Decimal("0.00")
        remaining = max(inst.amount - paid, Decimal("0.00")).quantize(_CENTS)
        if inst.template is not None:
            currency = inst.template.currency
        elif inst.user is not None and inst.user.default_currency:
            currency = inst.user.default_currency
        else:
            currency = fallback_currency

        item = AccountRequirementItem(
            instance_id=inst.id,
            label=resolve_instance_label(inst),
            due_date=inst.due_date,
            amount=remaining,
            amount_estimated=inst.amount_estimated,
            currency=currency,
        )
        if account_id not in grouped:
            grouped[account_id] = (account_name, [])
        grouped[account_id][1].append(item)

    named_keys = sorted(
        (key for key in grouped if key is not None),
        key=lambda key: (grouped[key][0].lower(), key),
    )
    ordered_keys: list[int | None] = list(named_keys)
    if None in grouped:
        ordered_keys.append(None)

    buckets: list[AccountRequirementBucket] = []
    for key in ordered_keys:
        account_name, items = grouped[key]
        total_due = sum((item.amount for item in items), Decimal("0.00")).quantize(
            _CENTS
        )
        total_estimated = sum(
            (item.amount for item in items if item.amount_estimated), Decimal("0.00")
        ).quantize(_CENTS)
        buckets.append(
            AccountRequirementBucket(
                account_id=key,
                account_name=account_name,
                total_due=total_due,
                total_estimated=total_estimated,
                items=items,
            )
        )

    return AccountRequirementsOut(
        from_date=from_date,
        to_date=to_date,
        buckets=buckets,
    )


def resolve_backup_value(
    db: Session, user_id: int, value: str | None
) -> BankAccount | None:
    """Resolve a backup `bank_account` name to the user's account row.

    Blank/absent values map to None (no preferred account). Anything else is
    a case-insensitive find-or-create so restores never fail on new names.
    """
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    existing = _find_by_name(db, user_id, cleaned)
    if existing is not None:
        return existing
    account = BankAccount(user_id=user_id, name=cleaned)
    db.add(account)
    db.flush()
    return account
