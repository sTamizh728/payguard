from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeviceKey(Base):
    """
    The public half of a key kept in the phone's secure hardware. The phone can
    only use the private half after a fingerprint, strong face unlock or the
    phone's PIN, so a valid signature proves the owner was holding the phone.
    """

    __tablename__ = "device_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # One active key per person: registering a new phone replaces the old one.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True,
        nullable=False,
    )

    # Base64 X.509 SubjectPublicKeyInfo (EC P-256).
    public_key: Mapped[str] = mapped_column(String(400), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
