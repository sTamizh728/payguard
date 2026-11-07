from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FriendPayment(Base):
    """
    Money a person sends from THEIR OWN PayPal account to a friend. The person
    approves it on PayPal's own page; PayGuard then collects it (capture), and
    PayPal pays it straight to the friend's PayPal account.
    """

    __tablename__ = "friend_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    to_name: Mapped[str] = mapped_column(String(100), nullable=False)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    paypal_order_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    approval_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # CREATED -> COMPLETED (or FAILED)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")
    capture_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
