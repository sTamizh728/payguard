from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SavedPayPal(Base):
    """
    A buyer's PayPal saved by PayPal itself (Vault) after their first shop payment,
    so later orders are paid after the PayGuard PIN + fingerprint without the PayPal page.
    PayGuard stores only PayPal's token id, never login details.
    """

    __tablename__ = "saved_paypal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    vault_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
