from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Payout(Base):
    """Money sent from the shop's PayPal wallet to a person (PayPal Payouts API)."""

    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # Our idempotency key: PayPal never pays the same sender_batch_id twice.
    sender_batch_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )

    # PayPal's batch ID, known once PayPal accepts the payout.
    payout_batch_id: Mapped[str | None] = mapped_column(
        String(50),
        unique=True,
        nullable=True,
    )

    recipient_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    recipient_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    amount: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    # REQUESTED -> PENDING / SUCCESS / FAILED / UNCLAIMED / RETURNED / ...
    # or UNKNOWN when PayPal could not be reached.
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    requested_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
