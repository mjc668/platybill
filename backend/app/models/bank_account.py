from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.bill import BillTemplate
    from app.models.user import User


class BankAccount(Base):
    """Per-user bank account (e.g. checking, savings).

    Bills carry an optional `preferred_account_id`; payment views resolve the
    label live from the template, so renaming an account relabels every
    payment instantly. Deleting is refused while any template references the
    account; archive it instead.
    """

    __tablename__ = "bank_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_bank_accounts_user_id_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    iban: Mapped[str | None] = mapped_column(String(34))
    note: Mapped[str | None] = mapped_column(String(255))
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped[User] = relationship(back_populates="bank_accounts")
    bills: Mapped[list[BillTemplate]] = relationship(back_populates="preferred_account")
