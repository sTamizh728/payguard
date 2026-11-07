from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AppPin(Base):
    """
    The person's own PayGuard PIN (4-6 digits), asked before money is sent,
    a refund is made or the balance is shown - on top of the phone's
    fingerprint / face / phone-PIN signature, never instead of it.
    """

    __tablename__ = "app_pins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)

    # Argon2 hash: the PIN itself is never stored.
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Wrong tries in a row. Kept in the database so a server restart cannot reset it.
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
