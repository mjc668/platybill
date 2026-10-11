from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.bill import BillFrequency, BillTemplate, PaymentInstance, PaymentStatus
from app.models.payment import Payment

# Allowed interval_count per unit: weekly 1-4, monthly 1-12, annual 1-5.
_INTERVAL_MAX: dict[BillFrequency, int] = {
    BillFrequency.weekly: 4,
    BillFrequency.monthly: 12,
    BillFrequency.annual: 5,
    BillFrequency.one_off: 1,
}


def confirmed_amounts(
    db: Session, template: BillTemplate, limit: int = 3
) -> list[Decimal]:
    """The most recent confirmed amounts for a template, newest first."""
    rows = (
        db.query(PaymentInstance.amount)
        .filter(
            PaymentInstance.bill_id == template.id,
            PaymentInstance.amount_estimated.is_(False),
            PaymentInstance.is_deleted.is_(False),
        )
        .order_by(PaymentInstance.due_date.desc(), PaymentInstance.id.desc())
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def suggested_amount(db: Session, template: BillTemplate) -> Decimal:
    """Median of the last 3 confirmed amounts; falls back to the template amount."""
    amounts = sorted(confirmed_amounts(db, template))
    if not amounts:
        return template.amount
    mid = len(amounts) // 2
    if len(amounts) % 2 == 1:
        return amounts[mid]
    return (amounts[mid - 1] + amounts[mid]) / Decimal(2)


def _new_instance_values(db: Session, template: BillTemplate) -> dict[str, object]:
    """Amount fields for a freshly generated instance.

    Variable-amount templates get a suggested amount flagged as estimated;
    fixed templates use the template amount.
    """
    if template.amount_varies:
        return {"amount": suggested_amount(db, template), "amount_estimated": True}
    return {"amount": template.amount}


def validate_schedule(
    frequency: BillFrequency,
    interval_count: int,
    start_date: date | None,
) -> str | None:
    """Return an error message when the effective schedule is invalid, else None.

    Callers must normalize `interval_count` to 1 for one_off bills before
    validating. `start_date` is only meaningful for weekly bills.
    """
    frequency = BillFrequency(frequency)
    if frequency == BillFrequency.one_off:
        return None
    maximum = _INTERVAL_MAX[frequency]
    if not 1 <= interval_count <= maximum:
        return f"interval_count for {frequency.value} bills must be between 1 and {maximum}"
    if frequency == BillFrequency.weekly and start_date is None:
        return "weekly bills require start_date"
    return None


def _add_months(period: str, delta: int) -> str:
    """Shift a "YYYY-MM" period by `delta` months."""
    year, month = map(int, period.split("-"))
    total = year * 12 + (month - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _next_period(period: str, frequency: BillFrequency, interval: int) -> str:
    """Shift a month-anchored period by one recurrence step.

    Non month-anchored units (weekly/one_off) are handled by their callers;
    this returns the period unchanged for them.
    """
    if frequency == BillFrequency.monthly:
        return _add_months(period, interval)
    if frequency == BillFrequency.annual:
        return _add_months(period, 12 * interval)
    return period


def _due_date_for_period(period: str, due_day: int | None) -> date:
    year, month = map(int, period.split("-"))
    day = due_day or 1
    # clamp to last day of month (e.g. due_day=31 in Feb → 28/29)
    last_day = monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _step_weeks(start: date, interval: int, k: int) -> date:
    """The k-th weekly occurrence after `start`: start + 7*interval*k days."""
    return start + timedelta(days=7 * interval * k)


def _step_months(template: BillTemplate) -> int:
    """Months between occurrences for month-anchored units."""
    if template.frequency == BillFrequency.annual:
        return 12 * template.interval_count
    return template.interval_count


def _occurrence_index(template: BillTemplate, due_date: date) -> int:
    """Zero-based index of `due_date` in the template's occurrence sequence.

    Weekly bills count steps from `start_date`; month-anchored bills count
    steps of `_step_months` from the `start_period` anchor (falling back to
    the creation month); one-off bills have a single occurrence at index 0.
    """
    if template.frequency == BillFrequency.one_off:
        return 0
    if template.frequency == BillFrequency.weekly:
        if template.start_date is None:
            return 0
        return (due_date - template.start_date).days // (7 * template.interval_count)

    # Use start_period (YYYY-MM) as the recurrence anchor when set.
    # Falls back to created_at UTC month for rows predating the column.
    anchor = template.start_period or template.created_at.strftime("%Y-%m")
    anchor_year, anchor_month = map(int, anchor.split("-"))
    months_diff = (due_date.year - anchor_year) * 12 + (due_date.month - anchor_month)
    return months_diff // _step_months(template)


def _cap_reached(template: BillTemplate, due_date: date) -> bool:
    """True when `due_date` is at or past the template's occurrence cap."""
    cap = template.max_occurrences
    return cap is not None and _occurrence_index(template, due_date) >= cap


def _bill_active_in_period(template: BillTemplate, period: str) -> bool:
    """Return True if a month-anchored template's schedule hits the period.

    Weekly templates are occurrence-based and always return False here; use
    `_occurrences_in_period` for them.
    """
    if template.frequency not in (BillFrequency.monthly, BillFrequency.annual):
        return False

    # Use start_period (YYYY-MM) as the recurrence anchor when set.
    # Falls back to created_at UTC month for rows predating the column.
    anchor = template.start_period or template.created_at.strftime("%Y-%m")
    start_year, start_month = map(int, anchor.split("-"))
    target_year, target_month = map(int, period.split("-"))
    months_diff = (target_year - start_year) * 12 + (target_month - start_month)

    if months_diff < 0:
        return False

    return months_diff % _step_months(template) == 0


def _weekly_occurrences_in_period(template: BillTemplate, period: str) -> list[date]:
    """All weekly occurrence dates that fall inside the given month."""
    start = template.start_date
    if start is None:
        return []
    year, month = map(int, period.split("-"))
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    if start > last_day:
        return []

    step_days = 7 * template.interval_count
    # First k with start + step*k >= first_day (k >= 0).
    delta = (first_day - start).days
    k = max(0, -(-delta // step_days))
    occurrences: list[date] = []
    current = _step_weeks(start, template.interval_count, k)
    while current <= last_day:
        occurrences.append(current)
        k += 1
        current = _step_weeks(start, template.interval_count, k)
    return occurrences


def _raw_occurrences_in_period(template: BillTemplate, period: str) -> list[date]:
    """Scheduled due dates in a period, before the occurrence cap is applied."""
    if template.frequency == BillFrequency.weekly:
        return _weekly_occurrences_in_period(template, period)
    if template.frequency == BillFrequency.one_off:
        anchor = template.start_period or template.created_at.strftime("%Y-%m")
        return (
            [_due_date_for_period(period, template.due_day)] if period == anchor else []
        )
    if _bill_active_in_period(template, period):
        return [_due_date_for_period(period, template.due_day)]
    return []


def _occurrences_in_period(template: BillTemplate, period: str) -> list[date]:
    """Due dates this template's schedule produces inside a "YYYY-MM" period.

    Weekly schedules can yield several occurrences per month; month-anchored
    units yield zero or one; one-off bills yield their single due date in the
    anchor period. Occurrences at or past `max_occurrences` are filtered out
    here — the single funnel shared by seeding, backfill, the series generator
    and the dashboard forecast.
    """
    return [
        due_date
        for due_date in _raw_occurrences_in_period(template, period)
        if not _cap_reached(template, due_date)
    ]


def _first_occurrence_on_or_after(start: date, interval: int, target: date) -> date:
    """First weekly occurrence on/after `target`, or `start` when it is future."""
    if target <= start:
        return start
    step_days = 7 * interval
    delta = (target - start).days
    k = -(-delta // step_days)
    return _step_weeks(start, interval, k)


def backfill_template_instances(
    db: Session, template: BillTemplate, from_period: str, to_period: str
) -> int:
    """Create missing instances for a single template from from_period to to_period inclusive.

    One instance per occurrence (weekly templates may have several per month).
    Returns the number of instances actually inserted (0 when every occurrence
    already has a row, including soft-deleted tombstones). The idempotency key
    is (bill_id, due_date).
    """
    candidate_due_dates: list[date] = []
    period = from_period
    while period <= to_period:
        candidate_due_dates.extend(_occurrences_in_period(template, period))
        period = _add_months(period, 1)

    if not candidate_due_dates:
        return 0

    # Single query for all existing rows — avoids N+1 per occurrence.
    existing_due_dates = {
        row.due_date
        for row in db.query(PaymentInstance.due_date).filter(
            PaymentInstance.bill_id == template.id,
            PaymentInstance.due_date.in_(candidate_due_dates),
        )
    }

    created = 0
    for due_date in candidate_due_dates:
        if due_date in existing_due_dates:
            continue
        db.add(
            PaymentInstance(
                bill_id=template.id,
                period=due_date.strftime("%Y-%m"),
                due_date=due_date,
                **(_new_instance_values(db, template)),
                status=PaymentStatus.upcoming,
            )
        )
        created += 1

    if db.new:
        try:
            db.commit()
        except IntegrityError:
            # Concurrent insert won the race: the whole batch rolled back.
            db.rollback()
            return 0

    return created


def eligible_for_generation(
    db: Session, user_id: int, bill_ids: list[int] | None = None
) -> list[BillTemplate]:
    """User's non-archived, non-paused, recurring templates (optionally subset)."""
    query = db.query(BillTemplate).filter(
        BillTemplate.user_id == user_id,
        BillTemplate.is_archived.is_(False),
        BillTemplate.is_paused.is_(False),
        BillTemplate.frequency != BillFrequency.one_off,
    )
    if bill_ids is not None:
        query = query.filter(BillTemplate.id.in_(bill_ids))
    return query.order_by(BillTemplate.id).all()


def generate_future_instances(
    db: Session,
    user_id: int,
    months: int,
    bill_ids: list[int] | None = None,
) -> tuple[int, int]:
    """Generate instances for current UTC month+1 through +months inclusive.

    Returns `(created, template_count)`; creation is idempotent via the
    `(bill_id, due_date)` uniqueness check in `backfill_template_instances`.
    """
    current = datetime.now(timezone.utc).strftime("%Y-%m")
    from_period = _add_months(current, 1)
    to_period = _add_months(current, months)

    templates = eligible_for_generation(db, user_id, bill_ids)
    created = 0
    for template in templates:
        created += backfill_template_instances(db, template, from_period, to_period)
    return created, len(templates)


def ensure_current_period_instances(db: Session, period: str, user_id: int) -> None:
    """Idempotently seed payment instances for eligible templates in period.

    Weekly templates get one row per occurrence; existence is keyed on
    (bill_id, due_date) ignoring `is_deleted` so tombstones still block.
    One-off bills are included here (their single occurrence) — unlike the
    series generator, which deliberately skips them.
    """
    templates = (
        db.query(BillTemplate)
        .filter(
            BillTemplate.user_id == user_id,
            BillTemplate.is_archived.is_(False),
            BillTemplate.is_paused.is_(False),
        )
        .all()
    )
    for template in templates:
        occurrences = _occurrences_in_period(template, period)
        if not occurrences:
            continue
        existing_due_dates = {
            row.due_date
            for row in db.query(PaymentInstance.due_date).filter(
                PaymentInstance.bill_id == template.id,
                PaymentInstance.due_date.in_(occurrences),
            )
        }
        for due_date in occurrences:
            if due_date in existing_due_dates:
                continue
            db.add(
                PaymentInstance(
                    bill_id=template.id,
                    period=period,
                    due_date=due_date,
                    **(_new_instance_values(db, template)),
                    status=PaymentStatus.upcoming,
                )
            )
    if db.new:
        db.commit()


def generate_next_instance(
    db: Session, template: BillTemplate, paid_due_date: date
) -> PaymentInstance | None:
    """Create the next instance after a payment. Idempotent on (bill_id, due_date)."""
    if template.frequency == BillFrequency.one_off:
        return None

    if template.frequency == BillFrequency.weekly:
        if template.start_date is None:
            return None
        next_due_date = paid_due_date + timedelta(days=7 * template.interval_count)
    else:
        next_period = _next_period(
            paid_due_date.strftime("%Y-%m"),
            template.frequency,
            template.interval_count,
        )
        next_due_date = _due_date_for_period(next_period, template.due_day)

    if _cap_reached(template, next_due_date):
        return None

    # idempotent: skip if already exists
    existing = (
        db.query(PaymentInstance)
        .filter(
            PaymentInstance.bill_id == template.id,
            PaymentInstance.due_date == next_due_date,
        )
        .first()
    )
    if existing:
        return existing

    instance = PaymentInstance(
        bill_id=template.id,
        period=next_due_date.strftime("%Y-%m"),
        due_date=next_due_date,
        **(_new_instance_values(db, template)),
        status=PaymentStatus.upcoming,
    )
    db.add(instance)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return (
            db.query(PaymentInstance)
            .filter(
                PaymentInstance.bill_id == template.id,
                PaymentInstance.due_date == next_due_date,
            )
            .first()
        )
    db.refresh(instance)
    return instance


def prune_occurrences_beyond_cap(
    db: Session, template: BillTemplate, today: date
) -> int:
    """Delete future unpaid instances that sit at or past the occurrence cap.

    Only non-deleted rows with no payment events are removed, so paid and
    partially-paid history is never touched. Returns the number of deleted
    rows; the caller owns the commit.
    """
    if template.max_occurrences is None:
        return 0

    candidates = (
        db.query(PaymentInstance)
        .filter(
            PaymentInstance.bill_id == template.id,
            PaymentInstance.due_date >= today,
            PaymentInstance.status != PaymentStatus.paid,
            PaymentInstance.is_deleted.is_(False),
        )
        .all()
    )
    beyond_cap = [
        instance
        for instance in candidates
        if _occurrence_index(template, instance.due_date) >= template.max_occurrences
    ]
    if not beyond_cap:
        return 0

    candidate_ids = [instance.id for instance in beyond_cap]
    with_events = {
        row[0]
        for row in db.query(Payment.instance_id)
        .filter(Payment.instance_id.in_(candidate_ids))
        .all()
    }

    deleted = 0
    for instance in beyond_cap:
        if instance.id in with_events:
            continue
        db.delete(instance)
        deleted += 1
    return deleted


def _first_active_period_on_or_after(template: BillTemplate, today: date) -> str | None:
    """First month-anchored period on/after today whose due date is not past.

    The scan is bounded so an annual bill or a long paused gap cannot loop
    forever: one full recurrence step plus one month, with a 24-month floor
    (e.g. 60 // interval steps for monthly bills).
    """
    period = today.strftime("%Y-%m")
    limit = max(24, _step_months(template) + 1)
    for _ in range(limit):
        if _bill_active_in_period(template, period) and (
            _due_date_for_period(period, template.due_day) >= today
        ):
            return period
        period = _add_months(period, 1)
    return None


def _next_active_occurrence(template: BillTemplate, today: date) -> date | None:
    """First occurrence on/after `today` for a template not active this period."""
    if template.frequency == BillFrequency.one_off:
        anchor = template.start_period or template.created_at.strftime("%Y-%m")
        return _due_date_for_period(anchor, template.due_day)
    if template.frequency == BillFrequency.weekly:
        if template.start_date is None:
            return None
        return _first_occurrence_on_or_after(
            template.start_date, template.interval_count, today
        )
    period = _first_active_period_on_or_after(template, today)
    return _due_date_for_period(period, template.due_day) if period else None


def _reanchor_for_cap(
    db: Session, template: BillTemplate, dates: list[date], period: str
) -> list[date]:
    """Re-anchor a cap-blocked schedule so its remaining payments resume.

    Used when a period's occurrences already sit at/past the cap by anchor
    index (the bill was paused across periods) while fewer rows exist than the
    cap. Returns the dates to seed after re-anchoring and reducing the cap.
    """
    assert template.max_occurrences is not None
    row_count = (
        db.query(PaymentInstance).filter(PaymentInstance.bill_id == template.id).count()
    )
    remaining = template.max_occurrences - row_count
    if remaining <= 0:
        return []
    if template.frequency == BillFrequency.weekly:
        template.start_date = dates[0]
    template.start_period = period
    template.max_occurrences = remaining
    return dates[:remaining]


def seed_resumed_occurrences(
    db: Session, template: BillTemplate, today: date
) -> list[PaymentInstance]:
    """Seed the current period's occurrences for a resumed (unarchived) bill.

    Behaves like the normal current-period seeder so a resumed bill looks
    exactly like an active one: this month's occurrences are created even when
    their due date has already passed (they show as overdue). Periods before
    the current month are never backfilled. When the template is not active in
    the current period (e.g. an annual bill whose month is elsewhere), the next
    scheduled occurrence is seeded instead.

    Existence is keyed on `(bill_id, due_date)` including soft-deleted
    tombstones (a deleted date is never resurrected) and the occurrence cap is
    respected with schedule re-anchoring. New rows are appended to the session
    without committing — the caller owns the commit.
    """
    current = today.strftime("%Y-%m")
    raw = _raw_occurrences_in_period(template, current)
    candidates = _occurrences_in_period(template, current)

    if raw and not candidates and template.max_occurrences is not None:
        candidates = _reanchor_for_cap(db, template, raw, current)
    elif not raw:
        candidate = _next_active_occurrence(template, today)
        if candidate is None:
            candidates = []
        elif _cap_reached(template, candidate):
            candidates = _reanchor_for_cap(
                db, template, [candidate], candidate.strftime("%Y-%m")
            )
        else:
            candidates = [candidate]

    if not candidates:
        return []

    existing_dates = {
        row.due_date
        for row in db.query(PaymentInstance.due_date).filter(
            PaymentInstance.bill_id == template.id
        )
    }
    created: list[PaymentInstance] = []
    for due_date in candidates:
        if due_date in existing_dates:
            continue
        instance = PaymentInstance(
            bill_id=template.id,
            period=due_date.strftime("%Y-%m"),
            due_date=due_date,
            **(_new_instance_values(db, template)),
            status=PaymentStatus.upcoming,
        )
        db.add(instance)
        created.append(instance)
    return created


def recompute_weekly_instances(db: Session, template: BillTemplate, today: date) -> int:
    """Re-space future unpaid instances after a weekly schedule change.

    The first future instance moves to the first occurrence on/after `today`
    (or `start_date` when it is still in the future); each following instance
    lands one step later. Paid and soft-deleted rows are untouched. Returns the
    number of rows updated; the caller owns the commit.
    """
    if template.frequency != BillFrequency.weekly or template.start_date is None:
        return 0

    instances = (
        db.query(PaymentInstance)
        .filter(
            PaymentInstance.bill_id == template.id,
            PaymentInstance.status != PaymentStatus.paid,
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.due_date >= today,
        )
        .order_by(PaymentInstance.due_date, PaymentInstance.id)
        .all()
    )
    if not instances:
        return 0

    first_due = _first_occurrence_on_or_after(
        template.start_date, template.interval_count, today
    )
    for index, instance in enumerate(instances):
        new_due_date = _step_weeks(first_due, template.interval_count, index)
        instance.due_date = new_due_date
        instance.period = new_due_date.strftime("%Y-%m")
    return len(instances)
