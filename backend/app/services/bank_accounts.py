"""Per-user bank accounts.

Bills reference `preferred_account_id`; renaming an account relabels existing
bills and payments, and accounts are archived rather than deleted while any
template still references them.

Nothing here commits — callers own the transaction.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.bank_account import BankAccount
from app.models.bill import BillTemplate


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
    """Hard-delete an unused account; refuse while any template references it."""
    account = get_for_user(db, user_id, account_id, allow_archived=True)
    in_use = (
        db.query(BillTemplate.id)
        .filter(BillTemplate.preferred_account_id == account.id)
        .first()
    )
    if in_use is not None:
        raise BankAccountInUseError(
            "Bank account is used by existing bills; archive it instead"
        )
    db.delete(account)
    db.flush()


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
