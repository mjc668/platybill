from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import current_user
from app.core.timezones import user_today
from app.models.user import User
from app.schemas.stats import StatsOverviewOut
from app.services.stats import build_stats_overview

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", response_model=StatsOverviewOut)
def stats_overview(
    month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    months: int = Query(6, ge=1, le=24),
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Read-only dashboard stats for the user's primary currency."""
    today = user_today(me.timezone)
    target = month if month is not None else today.strftime("%Y-%m")
    # The pattern above still admits year 0000, whose month arithmetic in the
    # forecast produces negative years; reject it explicitly.
    if int(target[:4]) == 0:
        raise HTTPException(status_code=422, detail="month must be a valid YYYY-MM")
    return build_stats_overview(db, me, target, months)
