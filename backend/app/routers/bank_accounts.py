from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import current_user
from app.models.user import User
from app.schemas.bank_account import (
    BankAccountCreate,
    BankAccountOut,
    BankAccountUpdate,
)
from app.services import bank_accounts as bank_accounts_service
from app.services.bank_accounts import BankAccountError

router = APIRouter(prefix="/bank-accounts", tags=["bank-accounts"])


def _raise_http(exc: BankAccountError) -> NoReturn:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("", response_model=list[BankAccountOut])
def list_bank_accounts(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """List the user's bank accounts ordered by name."""
    return bank_accounts_service.list_accounts(
        db, me.id, include_archived=include_archived
    )


@router.post("", response_model=BankAccountOut, status_code=status.HTTP_201_CREATED)
def create_bank_account(
    body: BankAccountCreate,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    try:
        account = bank_accounts_service.create_account(
            db, me.id, body.name, iban=body.iban, note=body.note
        )
    except BankAccountError as exc:
        _raise_http(exc)
    db.commit()
    db.refresh(account)
    return account


@router.patch("/{account_id}", response_model=BankAccountOut)
def update_bank_account(
    account_id: int,
    body: BankAccountUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Rename, edit details, and/or archive a bank account."""
    updates = body.model_dump(exclude_unset=True)
    try:
        account = bank_accounts_service.update_account(db, me.id, account_id, **updates)
    except BankAccountError as exc:
        _raise_http(exc)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bank_account(
    account_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Delete an unused bank account. In-use accounts must be archived instead."""
    try:
        bank_accounts_service.delete_account(db, me.id, account_id)
    except BankAccountError as exc:
        _raise_http(exc)
    db.commit()
