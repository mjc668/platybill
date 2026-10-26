from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.types import UTCDateTime

if TYPE_CHECKING:
    from app.models.user import User


class Passkey(Base):
    """Registered WebAuthn credential (Passkey) for a user."""

    __tablename__ = "passkeys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default=text("0")
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False, default="Passkey", server_default=text("'Passkey'")
    )
    aaguid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    transports: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=lambda: datetime.now(timezone.utc)
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True, default=None
    )

    user: Mapped[User] = relationship(back_populates="passkeys")
