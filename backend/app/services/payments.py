"""Payment ledger business logic.

A payment instance's `status`/`paid_at`/`paid_amount` are a denormalized
summary derived from the individual `Payment` events. Every mutation goes
through this module so the invariant holds:

    paid_amount == ledger total (or None when the ledger is empty)
    paid_at is set if and only if status == paid
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.bill import PaymentInstance, PaymentStatus
from app.models.payment import Payment


def get_total(instance: PaymentInstance) -> Decimal:
    """Return the sum of all payment events recorded against `instance`."""
    return sum((p.amount for p in instance.payments), Decimal("0"))


def recalculate_instance(
    instance: PaymentInstance, *, today: date | None = None
) -> None:
    """Recompute the denormalized summary from the ledger.

    Fully paid means ledger total >= instance amount. `today` exists for
    testability; it defaults to the server's local date.
    """
    if today is None:
        today = date.today()

    total = get_total(instance)
    if total == 0:
        instance.status = (
            PaymentStatus.overdue
            if instance.due_date < today
            else PaymentStatus.upcoming
        )
        instance.paid_amount = None
        instance.paid_at = None
    elif total < instance.amount:
        instance.status = (
            PaymentStatus.overdue
            if instance.due_date < today
            else PaymentStatus.upcoming
        )
        instance.paid_amount = total
        instance.paid_at = None
    else:
        instance.status = PaymentStatus.paid
        instance.paid_amount = total
        instance.paid_at = max(p.created_at for p in instance.payments)
        if instance.amount_estimated:
            # Paying settles the estimate: the ledger total is the real amount
            # and becomes part of the history the next suggestion is built on.
            instance.amount = total
            instance.amount_estimated = False


def record_payment(
    db: Session,
    instance: PaymentInstance,
    *,
    amount: Decimal,
    paid_on: date,
    note: str | None = None,
) -> tuple[Payment, bool]:
    """Append a payment event and recompute the summary.

    Returns `(payment, became_fully_paid)` where `became_fully_paid` is True
    only when the instance transitioned from not-fully-paid to fully-paid.
    """
    previous_status = instance.status

    payment = Payment(amount=amount, paid_on=paid_on, note=note)
    instance.payments.append(payment)
    # Flush so `created_at` is populated before recalculate_instance reads it.
    db.flush()
    recalculate_instance(instance)

    became_fully_paid = (
        previous_status != PaymentStatus.paid and instance.status == PaymentStatus.paid
    )
    return payment, became_fully_paid


def delete_payment(db: Session, instance: PaymentInstance, payment_id: int) -> bool:
    """Delete a single event that belongs to `instance`.

    Returns True when the event was found and deleted (the summary is
    recomputed), False when no such event exists on this instance.
    """
    for payment in instance.payments:
        if payment.id == payment_id:
            instance.payments.remove(payment)
            db.flush()
            recalculate_instance(instance)
            return True
    return False


def clear_payments(db: Session, instance: PaymentInstance) -> int:
    """Delete every event on `instance` and recompute the summary.

    Returns the number of events removed.
    """
    count = len(instance.payments)
    instance.payments.clear()
    db.flush()
    recalculate_instance(instance)
    return count
