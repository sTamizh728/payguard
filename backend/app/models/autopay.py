from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Autopay(Base):
    """
    A repeating payment PayGuard tracks.

    source 'paypal': a real PayPal subscription started in PayGuard. PayPal
    charges it; the status comes only from PayPal (API or verified webhook).
    source 'manual': an autopay set up somewhere else (gym, phone bill) that
    the person added by hand. PayGuard only tracks it and reminds before it charges.
    """

    __tablename__ = "autopays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    source: Mapped[str] = mapped_column(String(10), nullable=False)  # paypal / manual
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    interval: Mapped[str] = mapped_column(String(5), nullable=False)  # DAY / WEEK / MONTH / YEAR

    # APPROVAL_PENDING -> ACTIVE <-> SUSPENDED -> CANCELLED (or EXPIRED)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # Next charge, YYYY-MM-DD.
    next_date: Mapped[str | None] = mapped_column(String(10), nullable=True)

    paypal_subscription_id: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    approval_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    last_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # The next_date we already sent a reminder for (one reminder per charge).
    reminded_for: Mapped[str | None] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PayPalCatalog(Base):
    """PayPal product and plan ids PayGuard created once and reuses."""

    __tablename__ = "paypal_catalog"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(60), nullable=False)
