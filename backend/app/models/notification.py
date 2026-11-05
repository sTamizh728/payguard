from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    """An alert for the app, usually from a verified PayPal webhook event."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # PayPal's event id: the same event delivered twice is stored once.
    event_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    # Who sees it. None = every shop owner.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    # payment_received, payment_sent, payment_failed, refund_done, dispute, autopay
    kind: Mapped[str] = mapped_column(String(30), nullable=False)

    text: Mapped[str] = mapped_column(String(300), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
