from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.deps import current_user
from app.models.bill import BillTemplate, PaymentInstance, PaymentStatus
from app.models.payment import Payment
from app.models.user import User
from app.schemas.bill import (
    BillTemplateCreate,
    BillTemplateOut,
    BillTemplateUpdate,
    GenerateInstancesOut,
    GenerateInstancesRequest,
    HasDeletedFutureOut,
    InstanceAmountUpdate,
    MarkPaidRequest,
    PaymentCreate,
    PaymentInstanceOut,
    PendingConfirmationOut,
)
from app.services.categories import (
    CategoryError,
    get_for_user as get_category_for_user,
    resolve_legacy_key,
)
from app.services.payments import (
    clear_payments,
    delete_payment as delete_payment_record,
    get_total,
    recalculate_instance,
    record_payment,
)
from app.services.recurrence import (
    _due_date_for_period,
    backfill_template_instances,
    cancel_archived_occurrences,
    confirmed_amounts,
    suggested_amount,
    ensure_current_period_instances,
    generate_future_instances,
    generate_next_instance,
    prune_occurrences_beyond_cap,
    recompute_weekly_instances,
    seed_resumed_occurrences,
    validate_schedule,
)

router = APIRouter(prefix="/bills", tags=["bills"])


def _get_visible_bill(db: Session, bill_id: int, me: User) -> BillTemplate:
    """Scoped bill lookup returning 404 for missing, foreign or deleted bills."""
    bill = db.get(BillTemplate, bill_id)
    if not bill or bill.user_id != me.id or bill.is_deleted:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


def _resolve_category(
    db: Session,
    me: User,
    category_id: int | None,
    legacy_key: str | None,
    *,
    allow_archived_id: int | None = None,
):
    """Resolve a bill's category: `category_id` wins over the legacy string.

    `allow_archived_id` keeps an already-assigned archived category valid when
    a bill is edited without changing it.
    """
    try:
        if category_id is not None:
            return get_category_for_user(
                db,
                me.id,
                category_id,
                allow_archived=category_id == allow_archived_id,
            )
        if legacy_key is not None:
            return resolve_legacy_key(db, me.id, legacy_key)
    except CategoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="category_id or category is required",
    )


def _get_scoped_instance(db: Session, instance_id: int, me: User) -> PaymentInstance:
    """Load an instance and enforce ownership through bill → template.user_id."""
    instance = db.get(PaymentInstance, instance_id)
    if not instance or instance.template.user_id != me.id:
        raise HTTPException(status_code=404, detail="Payment instance not found")
    return instance


def _to_out(
    inst: PaymentInstance,
    *,
    override_status: PaymentStatus | None = None,
) -> PaymentInstanceOut:
    return PaymentInstanceOut.model_validate(
        {
            "id": inst.id,
            "bill_id": inst.bill_id,
            "period": inst.period,
            "due_date": inst.due_date,
            "amount": inst.amount,
            "amount_estimated": inst.amount_estimated,
            "status": override_status if override_status is not None else inst.status,
            "paid_at": inst.paid_at,
            "paid_amount": inst.paid_amount,
            "notes": inst.notes,
            "bill_name": inst.template.name,
            "currency": inst.template.currency,
            "frequency": inst.template.frequency,
            "interval_count": inst.template.interval_count,
            "max_occurrences": inst.template.max_occurrences,
            "start_date": inst.template.start_date,
            "category": inst.template.category,
            "email_sent_at": inst.email_sent_at,
            # Match the relationship's order_by even if the in-memory
            # collection was appended to before a reload.
            "payments": sorted(inst.payments, key=lambda p: (p.paid_on, p.id)),
        }
    )


@router.get("", response_model=list[BillTemplateOut])
def list_bills(
    include_archived: bool = False,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    q = (
        db.query(BillTemplate)
        .options(selectinload(BillTemplate.category))
        .filter(
            BillTemplate.user_id == me.id,
            BillTemplate.is_deleted.is_(False),
        )
    )
    if not include_archived:
        q = q.filter(BillTemplate.is_archived.is_(False))
    templates = q.order_by(BillTemplate.name).all()

    # Next unpaid instance per template (feeds the "next due" bills view).
    next_by_bill: dict[int, tuple[date, Decimal, PaymentStatus]] = {}
    if templates:
        rows = (
            db.query(
                PaymentInstance.bill_id,
                PaymentInstance.due_date,
                PaymentInstance.amount,
                PaymentInstance.status,
            )
            .filter(
                PaymentInstance.bill_id.in_([t.id for t in templates]),
                PaymentInstance.is_deleted.is_(False),
                PaymentInstance.status != PaymentStatus.paid,
            )
            .order_by(PaymentInstance.due_date, PaymentInstance.id)
            .all()
        )
        for bill_id, due_date, amount, status in rows:
            next_by_bill.setdefault(bill_id, (due_date, amount, status))

    result: list[BillTemplateOut] = []
    for template in templates:
        out = BillTemplateOut.model_validate(template)
        next_due = next_by_bill.get(template.id)
        if next_due is not None:
            out = out.model_copy(
                update={
                    "next_due_date": next_due[0],
                    "next_due_amount": next_due[1],
                    "next_due_status": next_due[2],
                }
            )
        result.append(out)
    return result


@router.post("", response_model=BillTemplateOut, status_code=status.HTTP_201_CREATED)
def create_bill(
    body: BillTemplateCreate,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    from app.models.bill import BillFrequency as BF

    now = datetime.now(timezone.utc)
    frequency = body.frequency
    interval_count = 1 if frequency == BF.one_off else body.interval_count
    max_occurrences = None if frequency == BF.one_off else body.max_occurrences
    start_date = body.start_date if frequency == BF.weekly else None
    due_day = None if frequency == BF.weekly else body.due_day

    error = validate_schedule(frequency, interval_count, start_date)
    if error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error
        )

    if frequency == BF.weekly:
        assert start_date is not None  # guaranteed by validate_schedule
        start_period = start_date.strftime("%Y-%m")
    elif body.due_month and frequency == BF.annual:
        # Annual renewals: a month that already passed means next year's cycle.
        year = now.year if body.due_month >= now.month else now.year + 1
        start_period = f"{year:04d}-{body.due_month:02d}"
    elif body.due_month:
        # Monthly/one-off: anchor to the current year so a date that already
        # passed lands as overdue instead of being pushed a year out.
        start_period = f"{now.year:04d}-{body.due_month:02d}"
    else:
        start_period = now.strftime("%Y-%m")

    category = _resolve_category(db, me, body.category_id, body.category)

    bill = BillTemplate(
        name=body.name,
        category_id=category.id,
        frequency=frequency,
        interval_count=interval_count,
        max_occurrences=max_occurrences,
        start_date=start_date,
        amount=body.amount,
        currency=body.currency,
        due_day=due_day,
        notes=body.notes,
        is_paused=body.is_paused,
        amount_varies=body.amount_varies,
        user_id=me.id,
        start_period=start_period,
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)

    current_period = now.strftime("%Y-%m")
    if frequency == BF.weekly or start_period < current_period:
        # Weekly runs from its first date; past-anchored bills (monthly,
        # annual, one-off) materialize their overdue occurrence(s) now.
        backfill_template_instances(db, bill, start_period, current_period)

    return bill


# Literal-path routes declared before parameterized /{bill_id} routes to prevent
# FastAPI from matching "payments" as an integer bill_id.
@router.get("/payments", response_model=list[PaymentInstanceOut])
def list_payments(
    month: str | None = None,  # "YYYY-MM"
    include_overdue: bool = Query(False),
    window_days: int | None = Query(None, ge=1, le=365),
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    today = date.today()
    current_month = today.strftime("%Y-%m")
    if month is None:
        month = current_month

    # NOTE: instance seeding was intentionally moved to POST /bills/sync-instances
    # so that GET list_payments remains side-effect free.

    if window_days is not None:
        # Rolling view: every unpaid overdue row plus everything due (or paid)
        # within +/- window_days, regardless of calendar month.
        scope = or_(
            and_(
                PaymentInstance.status != PaymentStatus.paid,
                PaymentInstance.due_date < today,
            ),
            and_(
                PaymentInstance.due_date >= today - timedelta(days=window_days),
                PaymentInstance.due_date <= today + timedelta(days=window_days),
            ),
        )
    elif include_overdue:
        # The selected month plus unpaid, already-overdue rows from earlier
        # periods, so the current view's Overdue section is complete.
        scope = or_(
            PaymentInstance.period == month,
            and_(
                PaymentInstance.period < month,
                PaymentInstance.status != PaymentStatus.paid,
                PaymentInstance.due_date < today,
            ),
        )
    else:
        scope = PaymentInstance.period == month

    instances = (
        db.query(PaymentInstance)
        .options(
            selectinload(PaymentInstance.template).selectinload(BillTemplate.category),
            selectinload(PaymentInstance.payments),
        )
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == me.id,
            BillTemplate.is_deleted.is_(False),
            # Archived bills are quiet: their untouched pending rows stay out
            # of the list until the bill is unarchived. Rows with payment
            # events (paid or partially paid) remain visible as history.
            or_(
                BillTemplate.is_archived.is_(False),
                PaymentInstance.status == PaymentStatus.paid,
                PaymentInstance.payments.any(),
            ),
            PaymentInstance.is_deleted.is_(False),
            # Estimated variable-bill instances stay out of the normal list
            # until their amount is confirmed (see /payments/needs-confirmation).
            PaymentInstance.amount_estimated.is_(False),
            scope,
        )
        .order_by(PaymentInstance.due_date)
        .all()
    )

    result = []
    for inst in instances:
        # Dynamic overdue: override status in response without writing to DB
        override = (
            PaymentStatus.overdue
            if inst.status == PaymentStatus.upcoming and inst.due_date < today
            else None
        )
        result.append(_to_out(inst, override_status=override))
    return result


@router.post("/payments/{instance_id}/payments", response_model=PaymentInstanceOut)
def add_payment(
    instance_id: int,
    body: PaymentCreate,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Record a partial or full payment event against an instance."""
    instance = _get_scoped_instance(db, instance_id, me)
    template = instance.template

    _, became_fully_paid = record_payment(
        db,
        instance,
        amount=body.amount,
        paid_on=body.paid_on or date.today(),
        note=body.note,
    )
    paid_due_date = instance.due_date
    db.commit()

    # auto-create next instance only on the transition to fully paid
    if became_fully_paid and not template.is_paused:
        generate_next_instance(db, template, paid_due_date)

    db.refresh(instance)
    return _to_out(instance)


@router.delete(
    "/payments/{instance_id}/payments/{payment_id}",
    response_model=PaymentInstanceOut,
)
def delete_payment_event(
    instance_id: int,
    payment_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Delete a single payment event and recompute the instance summary."""
    instance = _get_scoped_instance(db, instance_id, me)

    deleted = delete_payment_record(db, instance, payment_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Payment not found")

    db.commit()
    db.refresh(instance)
    return _to_out(instance)


@router.post("/payments/{instance_id}/pay", response_model=PaymentInstanceOut)
def mark_paid(
    instance_id: int,
    body: MarkPaidRequest,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Legacy mark-as-paid: record one event for the remaining balance.

    `paid_amount` defaults to `max(amount - ledger_total, 0)`. An explicit
    lower amount leaves the instance partially paid. Calling this on an
    already fully-paid instance is a no-op (prevents duplicate events from
    retries/double-clicks).
    """
    instance = _get_scoped_instance(db, instance_id, me)
    template = instance.template

    if instance.status == PaymentStatus.paid:
        return _to_out(instance)

    total = get_total(instance)
    remaining = max(instance.amount - total, Decimal("0"))
    if remaining == 0:
        # Ledger already covers the amount but the summary is stale (only
        # possible if the instance amount changed): treat as already paid.
        return _to_out(instance)

    amount = body.paid_amount if body.paid_amount is not None else remaining
    _, became_fully_paid = record_payment(
        db,
        instance,
        amount=amount,
        paid_on=date.today(),
        note=body.notes,
    )
    paid_due_date = instance.due_date
    db.commit()

    # auto-create next instance only on the transition to fully paid
    if became_fully_paid and not template.is_paused:
        generate_next_instance(db, template, paid_due_date)

    db.refresh(instance)
    return _to_out(instance)


@router.post("/payments/{instance_id}/unpay", response_model=PaymentInstanceOut)
def revert_payment(
    instance_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Revert a fully-paid instance by clearing every payment event."""
    instance = _get_scoped_instance(db, instance_id, me)
    if instance.status != PaymentStatus.paid:
        raise HTTPException(status_code=400, detail="Payment is not marked as paid")

    clear_payments(db, instance)
    db.commit()
    db.refresh(instance)
    return _to_out(instance)


@router.delete("/payments/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(
    instance_id: int,
    delete_future: bool = Query(False),
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    instance = db.get(PaymentInstance, instance_id)
    if not instance or instance.template.user_id != me.id:
        raise HTTPException(status_code=404, detail="Payment instance not found")

    instance.is_deleted = True

    if delete_future:
        db.query(PaymentInstance).filter(
            PaymentInstance.bill_id == instance.bill_id,
            PaymentInstance.due_date > instance.due_date,
            PaymentInstance.status != PaymentStatus.paid,
            PaymentInstance.is_deleted.is_(False),
        ).update({"is_deleted": True}, synchronize_session=False)

    db.commit()


@router.get("/payments/needs-confirmation", response_model=list[PendingConfirmationOut])
def needs_confirmation(
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Variable-bill instances whose amount is still an unconfirmed estimate.

    Only instances whose period has arrived are surfaced; future pre-generated
    periods are not nagged about.
    """
    current_month = date.today().strftime("%Y-%m")
    instances = (
        db.query(PaymentInstance)
        .options(
            selectinload(PaymentInstance.template).selectinload(BillTemplate.category),
            selectinload(PaymentInstance.payments),
        )
        .join(BillTemplate, PaymentInstance.bill_id == BillTemplate.id)
        .filter(
            BillTemplate.user_id == me.id,
            # Archived and deleted bills are quiet: their estimates never nag.
            BillTemplate.is_deleted.is_(False),
            BillTemplate.is_archived.is_(False),
            PaymentInstance.is_deleted.is_(False),
            PaymentInstance.amount_estimated.is_(True),
            PaymentInstance.status != PaymentStatus.paid,
            PaymentInstance.period <= current_month,
        )
        .order_by(PaymentInstance.due_date)
        .all()
    )
    return [
        PendingConfirmationOut(
            **(_to_out(inst).model_dump()),
            basis_amounts=confirmed_amounts(db, inst.template),
        )
        for inst in instances
    ]


@router.patch("/payments/{instance_id}/amount", response_model=PaymentInstanceOut)
def update_instance_amount(
    instance_id: int,
    body: InstanceAmountUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Set the real amount for an instance and mark it confirmed."""
    instance = _get_scoped_instance(db, instance_id, me)
    if instance.status == PaymentStatus.paid:
        raise HTTPException(
            status_code=400,
            detail="Cannot change the amount of a paid instance",
        )
    instance.amount = body.amount
    instance.amount_estimated = False
    recalculate_instance(instance)
    db.commit()
    db.refresh(instance)
    return _to_out(instance)


@router.post("/sync-instances", status_code=status.HTTP_204_NO_CONTENT)
def sync_instances(
    month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Explicitly seed payment instances for the given month (or current month).
    Replaces the previous seed-on-read side effect in list_payments."""
    today = date.today()
    current_month = today.strftime("%Y-%m")
    target = month or current_month
    if target >= current_month:
        ensure_current_period_instances(db, target, me.id)


@router.post("/generate-instances", response_model=GenerateInstancesOut)
def generate_instances(
    body: GenerateInstancesRequest,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Pre-generate future payment instances for eligible templates.

    Range is current UTC month+1 through +months inclusive. Idempotent: an
    existing row (including a soft-deleted tombstone) blocks regeneration.
    """
    if body.bill_ids is not None:
        requested = set(body.bill_ids)
        owned = {
            row[0]
            for row in db.query(BillTemplate.id).filter(
                BillTemplate.id.in_(requested),
                BillTemplate.user_id == me.id,
                BillTemplate.is_deleted.is_(False),
            )
        }
        if owned != requested:
            raise HTTPException(status_code=404, detail="Bill not found")

    created, bill_count = generate_future_instances(
        db, me.id, body.months, body.bill_ids
    )
    return GenerateInstancesOut(
        created=created, bill_count=bill_count, months=body.months
    )


# Declared with the literal-path routes, before the /{bill_id} block, so a
# broader /{bill_id} route can never shadow it.
@router.post("/{bill_id}/unarchive", response_model=BillTemplateOut)
def unarchive_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Restore an archived bill and resume from the next scheduled occurrence.

    Occurrences whose due date fell inside the archived span are cancelled
    (unpaid event-free rows are soft-deleted, missing dates get tombstones);
    periods before the current month are never backfilled. The schedule then
    resumes at the first occurrence on/after today (idempotent on
    `(bill_id, due_date)` and cap-aware).
    """
    bill = _get_visible_bill(db, bill_id, me)
    bill.is_archived = False
    bill.is_paused = False
    if bill.archived_at is not None:
        cancel_archived_occurrences(db, bill, bill.archived_at, date.today())
    bill.archived_at = None
    seed_resumed_occurrences(db, bill, date.today())
    db.commit()
    db.refresh(bill)
    return bill


@router.get("/{bill_id}/has-deleted-future", response_model=HasDeletedFutureOut)
def has_deleted_future(
    bill_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    bill = _get_visible_bill(db, bill_id, me)
    today = date.today()
    exists = (
        db.query(PaymentInstance)
        .filter(
            PaymentInstance.bill_id == bill_id,
            PaymentInstance.is_deleted.is_(True),
            PaymentInstance.due_date >= today,
        )
        .first()
        is not None
    )
    return HasDeletedFutureOut(has_deleted_future=exists)


@router.patch("/{bill_id}", response_model=BillTemplateOut)
def update_bill(
    bill_id: int,
    body: BillTemplateUpdate,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    bill = _get_visible_bill(db, bill_id, me)

    from app.models.bill import BillFrequency as BF

    updates = body.model_dump(exclude_unset=True)
    updates.pop("recreate_deleted_future", None)
    due_month = updates.pop("due_month", None)
    category_id = updates.pop("category_id", None)
    legacy_key = updates.pop("category", None)

    old_frequency = bill.frequency
    old_max_occurrences = bill.max_occurrences
    effective_frequency = updates.get("frequency", old_frequency)
    effective_interval = updates.get("interval_count", bill.interval_count)
    effective_start_date = updates.get("start_date", bill.start_date)
    effective_max_occurrences = updates.get("max_occurrences", old_max_occurrences)
    if effective_frequency == BF.one_off:
        effective_interval = 1
        effective_max_occurrences = None  # one-off bills ignore the cap

    error = validate_schedule(
        effective_frequency, effective_interval, effective_start_date
    )
    if error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error
        )

    schedule_changed = (
        effective_frequency != old_frequency
        or effective_interval != bill.interval_count
        or ("start_date" in updates and updates["start_date"] != bill.start_date)
    )

    cap_shrank = effective_max_occurrences is not None and (
        old_max_occurrences is None or effective_max_occurrences < old_max_occurrences
    )
    # A schedule change can also push existing future rows past the cap.
    prune_needed = cap_shrank or (
        schedule_changed and effective_max_occurrences is not None
    )

    updates["frequency"] = effective_frequency
    updates["interval_count"] = effective_interval
    updates["max_occurrences"] = effective_max_occurrences
    if effective_frequency == BF.weekly:
        updates["due_day"] = None  # due_day is ignored for weekly bills
    else:
        updates["start_date"] = None  # start_date is ignored for non-weekly bills

    if category_id is not None or legacy_key is not None:
        bill.category_id = _resolve_category(
            db, me, category_id, legacy_key, allow_archived_id=bill.category_id
        ).id

    due_day_changed = "due_day" in updates and updates["due_day"] != bill.due_day
    for field, value in updates.items():
        setattr(bill, field, value)

    # Recalculate start_period when due_month changes for annual/one_off
    if due_month is not None and effective_frequency in (BF.annual, BF.one_off):
        now = datetime.now(timezone.utc)
        if effective_frequency == BF.annual:
            year = now.year if due_month >= now.month else now.year + 1
        else:
            year = now.year
        bill.start_period = f"{year:04d}-{due_month:02d}"

    if effective_frequency == BF.weekly:
        if schedule_changed and bill.start_date is not None:
            bill.start_period = bill.start_date.strftime("%Y-%m")
            recompute_weekly_instances(db, bill, date.today())
    elif due_day_changed:
        unpaid = (
            db.query(PaymentInstance)
            .filter(
                PaymentInstance.bill_id == bill.id,
                PaymentInstance.status != PaymentStatus.paid,
                PaymentInstance.is_deleted.is_(False),
            )
            .all()
        )
        # A frequency change (e.g. weekly -> monthly) can leave several rows in
        # one period; a monthly due-date recompute would collapse them onto the
        # same date and break the (bill_id, due_date) key. Keep one event-free
        # row per period, drop the redundant ones, and never touch rows that
        # carry payment events.
        with_events = (
            {
                row[0]
                for row in db.query(Payment.instance_id)
                .filter(Payment.instance_id.in_([inst.id for inst in unpaid]))
                .all()
            }
            if unpaid
            else set()
        )
        by_period: dict[str, list[PaymentInstance]] = {}
        for inst in unpaid:
            by_period.setdefault(inst.period, []).append(inst)
        for period, rows in by_period.items():
            target = _due_date_for_period(period, bill.due_day)
            stable = [inst for inst in rows if inst.id in with_events]
            plain = [inst for inst in rows if inst.id not in with_events]
            if not plain:
                continue
            if any(inst.due_date == target for inst in stable):
                for inst in plain:
                    db.delete(inst)
                continue
            keeper = min(plain, key=lambda inst: inst.id)
            keeper.due_date = target
            for inst in plain:
                if inst is not keeper:
                    db.delete(inst)

    if body.recreate_deleted_future:
        today = date.today()
        tombstones = (
            db.query(PaymentInstance)
            .filter(
                PaymentInstance.bill_id == bill.id,
                PaymentInstance.is_deleted.is_(True),
                # "Future payments" means future: a tombstone for a due date
                # that already passed (e.g. cancelled inside an archived span)
                # is never resurrected.
                PaymentInstance.due_date >= today,
            )
            .all()
        )
        for inst in tombstones:
            inst.is_deleted = False
            if bill.amount_varies:
                inst.amount = suggested_amount(db, bill)
                inst.amount_estimated = True
            else:
                inst.amount = bill.amount
            if bill.frequency != BF.weekly:
                # Weekly tombstones keep their occurrence date; period already
                # matches it and a month can hold several occurrences.
                inst.due_date = _due_date_for_period(inst.period, bill.due_day)
            inst.status = PaymentStatus.upcoming

    if prune_needed:
        prune_occurrences_beyond_cap(db, bill, date.today())

    db.commit()
    db.refresh(bill)
    return bill


@router.post("/{bill_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
def archive_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    bill = _get_visible_bill(db, bill_id, me)
    bill.is_archived = True
    # Stamped so unarchive can cancel occurrences due inside the archived span.
    bill.archived_at = datetime.now(timezone.utc)
    db.commit()


@router.delete("/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    me: User = Depends(current_user),
):
    """Soft-delete an archived bill.

    The row (and its whole history) stays in the database and in exports, but
    is hidden from every frontend view. Bills must be archived first so the
    delete is always a deliberate second step.
    """
    bill = _get_visible_bill(db, bill_id, me)
    if not bill.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Archive the bill before deleting it",
        )
    bill.is_deleted = True
    db.commit()
