"""Dashboard stats aggregation.

All queries are scoped to one user and one currency (the user's primary
currency, derived from their non-archived templates). Soft-deleted payment
instances are excluded everywhere. Aggregation happens in SQL — rows are only
loaded for the bounded attention list.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, type_coerce
from sqlalchemy.orm import Session

from app.core.types import Money
from app.models.bill import (
    BillTemplate,
    PaymentInstance,
    PaymentStatus,
)
from app.models.category import Category
from app.models.payment import Payment
from app.models.user import User
from app.schemas.category import CategoryOut
from app.schemas.stats import (
    AttentionItem,
    CategoryStat,
    ForecastPoint,
    OverdueSummary,
    PaidWindow,
    StatsOverviewOut,
    StatsSummary,
    TrendPoint,
    UpcomingWindow,
)
from app.services.categories import category_label
from app.services.recurrence import _occurrences_in_period

DEFAULT_CURRENCY = "PLN"
ATTENTION_LIMIT = 10
ATTENTION_WINDOW_DAYS = 30
FORECAST_MONTHS = 6


def _shift_period(period: str, delta: int) -> str:
    """Shift a "YYYY-MM" period by `delta` months."""
    year, month = map(int, period.split("-"))
    total = year * 12 + (month - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _trend_periods(month: str, months: int) -> list[str]:
    """The `months` periods ending at `month`, oldest first."""
    return [_shift_period(month, i - (months - 1)) for i in range(months)]


def _primary_currency(db: Session, user_id: int) -> tuple[str, list[str]]:
    rows = (
        db.query(BillTemplate.currency, func.count(BillTemplate.id))
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.is_archived.is_(False),
        )
        .group_by(BillTemplate.currency)
        .all()
    )
    if not rows:
        return DEFAULT_CURRENCY, []

    ranked = sorted(rows, key=lambda row: (-int(row[1]), str(row[0])))
    primary = str(ranked[0][0])
    others = sorted({str(row[0]) for row in rows if str(row[0]) != primary})
    return primary, others


def _positive(value: Any) -> Any:
    """GREATEST(value, 0) replacement that also works on SQLite."""
    return case((value > 0, value), else_=0)


def _remaining_amount() -> Any:
    """Money-typed remaining balance (amount - paid).

    Arithmetic between a TypeDecorator and a literal loses the decorator
    (SQLAlchemy delegates binary ops to the impl), so without this coercion
    aggregates would return raw cents instead of Decimal.
    """
    return type_coerce(
        PaymentInstance.amount - func.coalesce(PaymentInstance.paid_amount, 0),
        Money,
    )


def _summary(
    db: Session, user_id: int, currency: str, month: str, today: date
) -> StatsSummary:
    remaining = _remaining_amount()
    effective_overdue = or_(
        PaymentInstance.status == PaymentStatus.overdue,
        and_(
            PaymentInstance.status == PaymentStatus.upcoming,
            PaymentInstance.due_date < today,
        ),
    )
    effective_upcoming = and_(
        PaymentInstance.status == PaymentStatus.upcoming,
        PaymentInstance.due_date >= today,
    )

    row = (
        db.query(
            func.coalesce(func.sum(PaymentInstance.amount), 0),
            func.coalesce(func.sum(func.coalesce(PaymentInstance.paid_amount, 0)), 0),
            func.coalesce(func.sum(_positive(remaining)), 0),
            func.count(PaymentInstance.id),
            func.count(case((PaymentInstance.status == PaymentStatus.paid, 1))),
            func.count(case((effective_upcoming, 1))),
            func.count(case((effective_overdue, 1))),
            func.coalesce(func.sum(case((effective_overdue, remaining), else_=0)), 0),
        )
        .select_from(PaymentInstance)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.period == month,
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(False),
        )
        .one()
    )

    return StatsSummary(
        due_total=Decimal(row[0]),
        paid_total=Decimal(row[1]),
        remaining_total=Decimal(row[2]),
        total_count=int(row[3]),
        paid_count=int(row[4]),
        upcoming_count=int(row[5]),
        overdue_count=int(row[6]),
        overdue_total=Decimal(row[7]),
    )


def _trend(
    db: Session, user_id: int, currency: str, periods: list[str]
) -> list[TrendPoint]:
    paid_period = func.strftime("%Y-%m", Payment.paid_on)
    paid_rows = (
        db.query(paid_period, func.coalesce(func.sum(Payment.amount), 0))
        .select_from(Payment)
        .join(PaymentInstance, Payment.instance_id == PaymentInstance.id)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.is_deleted.is_(False),
            paid_period.in_(periods),
        )
        .group_by(paid_period)
        .all()
    )
    paid_by_period = {str(row[0]): Decimal(row[1]) for row in paid_rows}

    due_rows = (
        db.query(
            PaymentInstance.period,
            func.coalesce(func.sum(PaymentInstance.amount), 0),
        )
        .select_from(PaymentInstance)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(False),
            PaymentInstance.period.in_(periods),
        )
        .group_by(PaymentInstance.period)
        .all()
    )
    due_by_period = {str(row[0]): Decimal(row[1]) for row in due_rows}

    return [
        TrendPoint(
            period=period,
            paid_total=paid_by_period.get(period, Decimal("0")),
            due_total=due_by_period.get(period, Decimal("0")),
        )
        for period in periods
    ]


def _forecast(
    db: Session, user_id: int, currency: str, month: str
) -> list[ForecastPoint]:
    """Expected spend for `month+1` … `month+6`, oldest first.

    Eligible templates are loaded once and aggregated in Python (the same
    recurrence helper used for generation decides which periods a template's
    schedule covers). Existing instances never subtract from the expectation.
    """
    periods = [_shift_period(month, offset) for offset in range(1, FORECAST_MONTHS + 1)]
    templates = (
        db.query(BillTemplate)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.is_archived.is_(False),
            BillTemplate.is_paused.is_(False),
            BillTemplate.currency == currency,
        )
        .all()
    )

    totals = {period: Decimal("0") for period in periods}
    for template in templates:
        for period in periods:
            # Weekly months can hold several occurrences, so count dates.
            totals[period] += template.amount * len(
                _occurrences_in_period(template, period)
            )

    return [
        ForecastPoint(period=period, expected_total=totals[period])
        for period in periods
    ]


def _by_category(
    db: Session,
    user_id: int,
    currency: str,
    periods: list[str],
    language: str | None,
) -> list[CategoryStat]:
    paid_period = func.strftime("%Y-%m", Payment.paid_on)
    paid_rows = (
        db.query(BillTemplate.category_id, func.coalesce(func.sum(Payment.amount), 0))
        .select_from(Payment)
        .join(PaymentInstance, Payment.instance_id == PaymentInstance.id)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.is_deleted.is_(False),
            paid_period.in_(periods),
        )
        .group_by(BillTemplate.category_id)
        .all()
    )
    due_rows = (
        db.query(
            BillTemplate.category_id,
            func.coalesce(func.sum(PaymentInstance.amount), 0),
        )
        .select_from(PaymentInstance)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(False),
            PaymentInstance.period.in_(periods),
        )
        .group_by(BillTemplate.category_id)
        .all()
    )

    paid_by_category = {int(row[0]): Decimal(row[1]) for row in paid_rows}
    due_by_category = {int(row[0]): Decimal(row[1]) for row in due_rows}

    stats: list[CategoryStat] = []
    category_ids = set(paid_by_category) | set(due_by_category)
    if not category_ids:
        return stats

    categories = {
        category.id: category
        for category in db.query(Category).filter(Category.id.in_(category_ids)).all()
    }
    for category_id in category_ids:
        paid = paid_by_category.get(category_id, Decimal("0"))
        due = due_by_category.get(category_id, Decimal("0"))
        if paid == 0 and due == 0:
            continue
        category = categories.get(category_id)
        if category is None:  # pragma: no cover — FK guarantees a row
            continue
        stats.append(
            CategoryStat(
                category=CategoryOut.model_validate(category),
                paid_total=paid,
                due_total=due,
            )
        )

    stats.sort(
        key=lambda item: (-item.paid_total, category_label(language, item.category))
    )
    return stats


def _attention(
    db: Session, user_id: int, currency: str, today: date
) -> list[AttentionItem]:
    rows = (
        db.query(PaymentInstance, BillTemplate.name)
        .select_from(PaymentInstance)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(False),
            PaymentInstance.status != PaymentStatus.paid,
            PaymentInstance.amount > func.coalesce(PaymentInstance.paid_amount, 0),
            PaymentInstance.due_date <= today + timedelta(days=ATTENTION_WINDOW_DAYS),
        )
        .order_by(PaymentInstance.due_date, PaymentInstance.id)
        .limit(ATTENTION_LIMIT)
        .all()
    )

    items: list[AttentionItem] = []
    for instance, bill_name in rows:
        paid = instance.paid_amount or Decimal("0")
        remaining = max(instance.amount - paid, Decimal("0"))
        items.append(
            AttentionItem(
                instance_id=instance.id,
                period=instance.period,
                bill_name=bill_name,
                due_date=instance.due_date,
                amount=instance.amount,
                paid_amount=instance.paid_amount,
                remaining=remaining,
                status=(
                    PaymentStatus.overdue
                    if instance.due_date < today
                    else PaymentStatus.upcoming
                ),
            )
        )
    return items


def _upcoming_window(
    db: Session, user_id: int, currency: str, today: date, days: int
) -> UpcomingWindow:
    """Unpaid primary-currency instances due in the next `days` days.

    Rolling from today (not calendar months); partial payments count with
    their remaining balance. Overdue instances are excluded.
    """
    remaining = _remaining_amount()
    row = (
        db.query(
            func.count(PaymentInstance.id),
            func.coalesce(func.sum(_positive(remaining)), 0),
        )
        .select_from(PaymentInstance)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(False),
            PaymentInstance.status != PaymentStatus.paid,
            remaining > 0,
            PaymentInstance.due_date >= today,
            PaymentInstance.due_date <= today + timedelta(days=days),
        )
        .one()
    )
    return UpcomingWindow(count=int(row[0]), total=Decimal(row[1]))


def _paid_window(db: Session, user_id: int, currency: str, today: date) -> PaidWindow:
    """Amounts paid (ledger) and billed over the rolling 30 days ending today."""
    start = today - timedelta(days=30)
    paid = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .select_from(Payment)
        .join(PaymentInstance, Payment.instance_id == PaymentInstance.id)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.is_deleted.is_(False),
            Payment.paid_on >= start,
            Payment.paid_on <= today,
        )
        .scalar()
    )
    due = (
        db.query(func.coalesce(func.sum(PaymentInstance.amount), 0))
        .select_from(PaymentInstance)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(False),
            PaymentInstance.due_date >= start,
            PaymentInstance.due_date <= today,
        )
        .scalar()
    )
    return PaidWindow(paid_total=Decimal(paid or 0), due_total=Decimal(due or 0))


def _overdue_summary(
    db: Session, user_id: int, currency: str, today: date
) -> OverdueSummary:
    """All unpaid overdue instances in any period, by remaining balance.

    Matches the payments list's Overdue section (which carries rows over from
    earlier periods), so the dashboard swatch and the list agree.
    """
    remaining = _remaining_amount()
    row = (
        db.query(
            func.count(PaymentInstance.id),
            func.coalesce(func.sum(_positive(remaining)), 0),
        )
        .select_from(PaymentInstance)
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_deleted.is_(False),
            BillTemplate.currency == currency,
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(False),
            PaymentInstance.status != PaymentStatus.paid,
            PaymentInstance.due_date < today,
        )
        .one()
    )
    return OverdueSummary(count=int(row[0]), total=Decimal(row[1]))


def build_stats_overview(
    db: Session, user: User, month: str, months: int
) -> StatsOverviewOut:
    today = date.today()
    currency, other_currencies = _primary_currency(db, user.id)
    periods = _trend_periods(month, months)

    return StatsOverviewOut(
        month=month,
        months=months,
        currency=currency,
        other_currencies=other_currencies,
        summary=_summary(db, user.id, currency, month, today),
        trend=_trend(db, user.id, currency, periods),
        forecast=_forecast(db, user.id, currency, month),
        upcoming_7d=_upcoming_window(db, user.id, currency, today, 7),
        upcoming_30d=_upcoming_window(db, user.id, currency, today, 30),
        paid_30d=_paid_window(db, user.id, currency, today),
        overdue=_overdue_summary(db, user.id, currency, today),
        by_category=_by_category(
            db, user.id, currency, periods, user.language_preference
        ),
        attention=_attention(db, user.id, currency, today),
    )
