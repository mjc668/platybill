from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.bill import BillTemplate
    from app.models.category import Category


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_version: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    language_preference: Mapped[str | None] = mapped_column(
        String(5), nullable=True, default=None
    )
    # IANA timezone name (e.g. "Australia/Sydney"). Drives day detection
    # (overdue, due-soon, resume dates) and reminder scheduling. NULL falls
    # back to UTC, the pre-timezone behaviour.
    timezone: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None
    )
    default_currency: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default=None
    )
    email_reminders_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    notify_2_days_before: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    notify_1_day_before: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    notify_on_day: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    notify_1_day_after: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    reminder_send_minute: Mapped[int] = mapped_column(
        nullable=False, default=480, server_default=text("480")
    )
    monthly_summary_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    monthly_summary_last_sent: Mapped[str | None] = mapped_column(
        String(7), nullable=True, default=None
    )
    # Weekly due-overview digest: sent on the chosen local weekday at the
    # chosen local minute, covering overdue plus the next N days of dues.
    # `upcoming_digest_last_sent` stores the local YYYY-MM-DD it last went out.
    upcoming_digest_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    upcoming_digest_weekday: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default=text("0")
    )  # 0=Monday .. 6=Sunday, local to the user's timezone
    upcoming_digest_minute: Mapped[int] = mapped_column(
        nullable=False, default=480, server_default=text("480")
    )
    upcoming_digest_days: Mapped[int] = mapped_column(
        nullable=False, default=7, server_default=text("7")
    )
    upcoming_digest_last_sent: Mapped[str | None] = mapped_column(
        String(10), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc)
    )

    bills: Mapped[list[BillTemplate]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    categories: Mapped[list[Category]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
