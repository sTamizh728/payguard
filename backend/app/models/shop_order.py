from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ShopOrder(Base):
    """A PayGuard Shop purchase, made in the app or by phone call."""

    __tablename__ = "shop_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # 6 digits, read out on a phone call so the order can be opened in the app.
    code: Mapped[str] = mapped_column(String(6), unique=True, nullable=False, index=True)

    # Set for app orders, and for phone orders once claimed in the app.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    channel: Mapped[str] = mapped_column(String(10), nullable=False)  # app / phone

    product_id: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # What was bought, e.g. '2 x Apple iPhone Charger, 1 x ...'.
    summary: Mapped[str | None] = mapped_column(String(300), nullable=True)

    paypal_order_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    approval_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # CREATED -> PAID
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CREATED")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
