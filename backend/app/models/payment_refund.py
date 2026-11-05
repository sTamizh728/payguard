from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PaymentRefund(Base):
    __tablename__ = "payment_refunds"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("payment_transactions.id"),
        nullable=False,
        index=True,
    )

    # Our idempotency key (sent as PayPal-Request-Id). One per confirmed action.
    request_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )

    # PayPal's refund ID, known only after PayPal answers.
    refund_id: Mapped[str | None] = mapped_column(
        String(50),
        unique=True,
        nullable=True,
    )

    amount: Mapped[float] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
    )

    # REQUESTED -> COMPLETED / PENDING / FAILED / CANCELLED,
    # or UNKNOWN when PayPal could not be reached.
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    requested_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
