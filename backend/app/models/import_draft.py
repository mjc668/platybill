from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import Money, UTCDateTime

if TYPE_CHECKING:
    from app.models.bill import BillTemplate
    from app.models.user import User


class ImportSource(str, Enum):
    upload = "upload"
    directory = "directory"
    email = "email"


class ImportStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    discarded = "discarded"
    failed = "failed"


class ImportDraft(Base):
    """An extracted bill awaiting user confirmation.

    `source_ref` is unique: a file hash (upload/directory) or an IMAP
    message-id + attachment index, so re-polls never duplicate drafts.
    """

    __tablename__ = "import_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    source: Mapped[ImportSource] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    filename: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str | None] = mapped_column(String(10))
    due_date: Mapped[date | None] = mapped_column(Date)
    period: Mapped[str | None] = mapped_column(String(7))
    raw_text: Mapped[str | None] = mapped_column(Text)
    matched_bill_id: Mapped[int | None] = mapped_column(ForeignKey("bill_templates.id"))
    status: Mapped[ImportStatus] = mapped_column(
        String(20), nullable=False, default=ImportStatus.pending
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc)
    )
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship()
    matched_bill: Mapped[BillTemplate | None] = relationship()
