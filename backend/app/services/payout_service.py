from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.payout import Payout
from app.models.user import User
from app.services import payment_service

MAX_PAYOUT = Decimal("100.00")   # safety limit per payment
DAILY_LIMIT = Decimal("200.00")  # safety limit for one person in 24 hours

# Payouts in these states count toward the daily limit: money left or may still leave.
COUNTED_STATUSES = (
    "REQUESTED", "UNKNOWN", "PENDING", "PROCESSING", "SUCCESS",
    "UNCLAIMED", "ONHOLD", "NEW",
)
# PayPal may still change these, so history refreshes them.
OPEN_STATUSES = ("REQUESTED", "UNKNOWN", "PENDING", "PROCESSING", "UNCLAIMED", "ONHOLD", "NEW")
FAILED_STATUSES = ("FAILED", "DENIED", "RETURNED", "BLOCKED", "REFUNDED", "REVERSED", "CANCELED")


class PayoutNotAllowed(Exception):
    """Refused by our own checks or by PayPal. No money was sent."""


def _sent_last_24h(db, user_id: int) -> Decimal:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    total = db.scalar(
        select(func.coalesce(func.sum(Payout.amount), 0)).where(
            Payout.requested_by == user_id,
            Payout.created_at >= since,
            Payout.status.in_(COUNTED_STATUSES),
        )
    )
    return Decimal(str(total))


def left_today(user_id: int) -> Decimal:
    with SessionLocal() as db:
        return max(DAILY_LIMIT - _sent_last_24h(db, user_id), Decimal("0"))


def _check(db, user_id: int, amount: Decimal) -> None:
    if amount < Decimal("0.01"):
        raise PayoutNotAllowed("The amount must be more than zero.")
    if amount > MAX_PAYOUT:
        raise PayoutNotAllowed(f"For your safety, I can send up to ${MAX_PAYOUT:.0f} at a time.")

    left = max(DAILY_LIMIT - _sent_last_24h(db, user_id), Decimal("0"))
    if amount > left:
        raise PayoutNotAllowed(
            f"For your safety, the daily limit is ${DAILY_LIMIT:.0f}. "
            f"You can send ${left:.2f} more today."
        )


def check_limits(user_id: int, amount: Decimal) -> None:
    with SessionLocal() as db:
        _check(db, user_id, amount)


def _reserve(user_id: int, sender_batch_id: str, name: str, email: str, amount: Decimal) -> int:
    """Record the payout as REQUESTED before PayPal is called, re-checking the limits."""
    with SessionLocal() as db:
        # Lock this person's row so two confirms at once cannot both pass the limit.
        db.scalar(select(User.id).where(User.id == user_id).with_for_update())
        _check(db, user_id, amount)

        payout = Payout(
            sender_batch_id=sender_batch_id,
            recipient_name=name,
            recipient_email=email,
            amount=amount,
            currency="USD",
            status="REQUESTED",
            requested_by=user_id,
        )
        db.add(payout)
        db.commit()
        return payout.id


def _finish(payout_id: int, status: str, payout_batch_id: str | None = None) -> None:
    with SessionLocal() as db:
        payout = db.get(Payout, payout_id)
        payout.status = status
        if payout_batch_id:
            payout.payout_batch_id = payout_batch_id
        payout.updated_at = datetime.now(timezone.utc)
        db.commit()


async def send_payout(
    user_id: int,
    sender_batch_id: str,
    name: str,
    email: str,
    amount: Decimal,
) -> dict:
    """
    Send money for real. Returns {"outcome": "sent" | "unknown", "payout_batch_id"}.
    Raises PayoutNotAllowed when our checks or PayPal refuse it.
    """
    payout_id = _reserve(user_id, sender_batch_id, name, email, amount)

    try:
        result = await payment_service.create_paypal_payout(
            recipient_email=email,
            amount=f"{amount:.2f}",
            currency="USD",
            sender_batch_id=sender_batch_id,
            note="Sent with PayGuard",
        )
    except payment_service.PayPalUncertain:
        # Keep it counted against the limit: PayPal may still send it.
        _finish(payout_id, "UNKNOWN")
        return {"outcome": "unknown"}
    except payment_service.PayPalRejected as error:
        print(f"[Payout rejected] payout {payout_id}: {error}")  # for the developer, no secrets
        _finish(payout_id, "FAILED")
        raise PayoutNotAllowed("PayPal did not accept this payment.") from None

    status = (result.get("status") or "PENDING").upper()
    _finish(payout_id, status, result.get("payout_batch_id"))
    return {"outcome": "sent", "payout_batch_id": result.get("payout_batch_id"), "status": status}


async def refresh_open_payouts(user_id: int | None = None, limit: int = 10) -> None:
    """Ask PayPal again about payouts that may still change."""
    with SessionLocal() as db:
        query = select(Payout.id, Payout.payout_batch_id).where(
            Payout.status.in_(OPEN_STATUSES),
            Payout.payout_batch_id.is_not(None),
        )
        if user_id is not None:
            query = query.where(Payout.requested_by == user_id)
        rows = db.execute(query.order_by(Payout.id.desc()).limit(limit)).all()

    for payout_id, batch_id in rows:
        status = await payment_service.get_paypal_payout_status(batch_id)
        if status:
            _finish(payout_id, status.upper())


def list_payouts(user_id: int | None = None, only_failed: bool = False, limit: int = 10) -> list[dict]:
    with SessionLocal() as db:
        query = select(Payout)
        if user_id is not None:
            query = query.where(Payout.requested_by == user_id)
        if only_failed:
            query = query.where(Payout.status.in_(FAILED_STATUSES + ("UNCLAIMED", "UNKNOWN")))
        payouts = db.scalars(query.order_by(Payout.created_at.desc(), Payout.id.desc()).limit(limit)).all()

        return [
            {
                "number": p.id,
                "name": p.recipient_name,
                "amount": Decimal(str(p.amount)),
                "currency": p.currency,
                "status": p.status,
                "created_at": p.created_at,
            }
            for p in payouts
        ]
