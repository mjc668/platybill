from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import Money, UTCDateTime

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.payment import Payment
    from app.models.user import User


class BillFrequency(str, Enum):
    weekly = "weekly"
    monthly = "monthly"
    annual = "annual"
    one_off = "one_off"


class PaymentStatus(str, Enum):
    upcoming = "upcoming"
    overdue = "overdue"
    paid = "paid"


class BillTemplate(Base):
    """Recurring bill definition. Instances are generated from this."""

    __tablename__ = "bill_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False
    )
    frequency: Mapped[BillFrequency] = mapped_column(String(20), nullable=False)
    interval_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )  # repeat every N units (weeks/months/years)
    # Optional total number of occurrences (1-999), counted from the anchor.
    # NULL means unlimited. Forced NULL for one_off bills.
    max_occurrences: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date | None] = mapped_column(Date)  # weekly anchor
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    # Usage-based bills (utilities): generated instances get a suggested
    # amount from history and must be confirmed before they count.
    amount_varies: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="PLN")
    due_day: Mapped[int | None] = mapped_column(
        Integer
    )  # day-of-month for monthly/annual bills
    notes: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    # Recurrence anchor: YYYY-MM string set at creation from UTC month.
    # Avoids UTC-vs-local off-by-one when created_at straddles a month boundary.
    # NULL for rows created before this column existed; code falls back to created_at.
    start_period: Mapped[str | None] = mapped_column(String(7))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped[User] = relationship(back_populates="bills")
    category: Mapped[Category] = relationship(back_populates="bills")
    instances: Mapped[list["PaymentInstance"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )


class PaymentInstance(Base):
    """A single payment record. Idempotent: (bill_id, due_date) is unique."""

    __tablename__ = "payment_instances"
    __table_args__ = (
        UniqueConstraint(
            "bill_id", "due_date", name="uq_payment_instance_bill_due_date"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(
        ForeignKey("bill_templates.id"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    # True while the amount is an unconfirmed estimate (variable bills).
    amount_estimated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    status: Mapped[PaymentStatus] = mapped_column(
        String(10), nullable=False, default=PaymentStatus.upcoming
    )
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    paid_amount: Mapped[Decimal | None] = mapped_column(Money)
    notes: Mapped[str | None] = mapped_column(Text)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    reminder_sent_upcoming: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    reminder_sent_overdue: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    reminder_sent_2_days_before: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    reminder_sent_on_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    email_sent_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc)
    )

    template: Mapped["BillTemplate"] = relationship(back_populates="instances")
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="instance",
        cascade="all, delete-orphan",
        order_by="Payment.paid_on, Payment.id",
    )
