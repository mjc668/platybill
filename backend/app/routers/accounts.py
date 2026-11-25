from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import WorkspaceContext, workspace_context
from app.core.timezones import user_today
from app.schemas.bank_account import AccountRequirementsOut
from app.services import bank_accounts as bank_accounts_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("/requirements", response_model=AccountRequirementsOut)
def account_requirements(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
    ws: WorkspaceContext = Depends(workspace_context("bills:read")),
):
    """Unpaid cash requirements grouped by resolved bank account for an inclusive due-date window."""
    today = user_today(ws.actor.timezone)
    start = from_date if from_date is not None else today
    end = to_date if to_date is not None else start + timedelta(days=7)
    if end < start:
        raise HTTPException(
            status_code=422,
            detail="'to' date must be on or after 'from' date",
        )
    return bank_accounts_service.get_account_requirements(
        db,
        ws.owner_id,
        start,
        end,
        default_currency=ws.actor.default_currency,
    )
