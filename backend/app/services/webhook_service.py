"""
PayPal webhooks: PayPal calls us the moment something happens. Every event is
verified with PayPal before we trust it, then turned into a short alert.
"""
from datetime import datetime, timezone

import httpx
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import SessionLocal
from app.integrations.paypal_client import get_access_token
from app.models.notification import Notification
from app.models.payout import Payout

# PayPal payout item event -> our payout status
PAYOUT_EVENTS = {
    "PAYMENT.PAYOUTS-ITEM.SUCCEEDED": "SUCCESS",
    "PAYMENT.PAYOUTS-ITEM.FAILED": "FAILED",
    "PAYMENT.PAYOUTS-ITEM.UNCLAIMED": "UNCLAIMED",
    "PAYMENT.PAYOUTS-ITEM.RETURNED": "RETURNED",
    "PAYMENT.PAYOUTS-ITEM.BLOCKED": "BLOCKED",
    "PAYMENT.PAYOUTS-ITEM.DENIED": "DENIED",
    "PAYMENT.PAYOUTS-ITEM.REFUNDED": "REFUNDED",
    "PAYMENT.PAYOUTS-ITEM.CANCELED": "CANCELED",
    "PAYMENT.PAYOUTS-ITEM.HELD": "ONHOLD",
}

EVENT_TYPES = [
    *PAYOUT_EVENTS,
    "PAYMENT.CAPTURE.COMPLETED",
    "PAYMENT.CAPTURE.REFUNDED",
    "CUSTOMER.DISPUTE.CREATED",
    "BILLING.SUBSCRIPTION.ACTIVATED",
    "BILLING.SUBSCRIPTION.CANCELLED",
    "BILLING.SUBSCRIPTION.PAYMENT.FAILED",
    "PAYMENT.SALE.COMPLETED",
]

HEADERS = {
    "auth_algo": "paypal-auth-algo",
    "cert_url": "paypal-cert-url",
    "transmission_id": "paypal-transmission-id",
    "transmission_sig": "paypal-transmission-sig",
    "transmission_time": "paypal-transmission-time",
}


async def verify(headers: dict[str, str], event: dict) -> bool:
    """Ask PayPal whether this event really came from PayPal for our webhook."""
    if not settings.paypal_webhook_id:
        return False

    values = {key: headers.get(name) for key, name in HEADERS.items()}
    if not all(values.values()):
        return False

    try:
        token = (await get_access_token())["access_token"]
    except RuntimeError:
        return False

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.post(
                f"{settings.paypal_base_url.rstrip('/')}/v1/notifications/verify-webhook-signature",
                headers={"Authorization": f"Bearer {token}"},
                json={**values, "webhook_id": settings.paypal_webhook_id, "webhook_event": event},
            )
        except httpx.RequestError:
            return False

    return response.is_success and response.json().get("verification_status") == "SUCCESS"


def _money(resource: dict, *keys) -> str:
    for key in keys:
        amount = resource.get(key) or {}
        if amount.get("value"):
            return f"${amount['value']} {amount.get('currency_code') or amount.get('currency') or ''}".strip()
    return "money"


def describe(event: dict) -> tuple[str, str, int | None, str | None, str | None] | None:
    """
    -> (kind, text, user_id or None for owners, payout_batch_id, new payout status)
    or None for events we don't show.
    """
    kind = event.get("event_type", "")
    resource = event.get("resource") or {}

    if kind in PAYOUT_EVENTS:
        status = PAYOUT_EVENTS[kind]
        batch_id = resource.get("payout_batch_id")
        amount = _money((resource.get("payout_item") or {}), "amount")
        if status == "SUCCESS":
            return "payment_sent", f"Your payment of {amount} was received.", None, batch_id, status
        return "payment_failed", f"Your payment of {amount} is {status.lower()}. Open History for details.", None, batch_id, status

    if kind == "PAYMENT.CAPTURE.COMPLETED":
        return "payment_received", f"You received {_money(resource, 'amount')}.", None, None, None

    if kind == "PAYMENT.CAPTURE.REFUNDED":
        return "refund_done", f"A refund of {_money(resource, 'amount')} was completed.", None, None, None

    if kind == "CUSTOMER.DISPUTE.CREATED":
        reason = str(resource.get("reason") or "a problem").replace("_", " ").lower()
        return "dispute", f"A customer opened a dispute ({reason}). Please review it.", None, None, None

    if kind.startswith("BILLING.SUBSCRIPTION.") or kind == "PAYMENT.SALE.COMPLETED":
        # An autopay started in PayGuard: update it and tell its subscriber.
        from app.services import autopay_service

        ours = autopay_service.apply_webhook(kind, resource)
        if ours is not None:
            user_id, text = ours
            return "autopay", text, user_id, None, None

    if kind.startswith("BILLING.SUBSCRIPTION."):
        what = kind.split(".")[-1].replace("_", " ").lower()
        if kind.endswith("PAYMENT.FAILED"):
            what = "payment failed"
        return "autopay", f"Autopay subscription update: {what}.", None, None, None

    if kind == "PAYMENT.SALE.COMPLETED":
        return "autopay", f"Autopay charged {_money(resource, 'amount')}.", None, None, None

    return None


def store(event: dict) -> bool:
    """Save the alert (and update the payout). Returns False for a duplicate event."""
    event_id = str(event.get("id") or "")[:64] or None
    if event_id:
        # PayPal re-sends events: never apply the same one twice.
        with SessionLocal() as db:
            if db.scalar(select(Notification.id).where(Notification.event_id == event_id)) is not None:
                return False

    described = describe(event)
    if described is None:
        return True

    kind, text, user_id, batch_id, status = described

    with SessionLocal() as db:
        if batch_id and status:
            payout = db.scalar(select(Payout).where(Payout.payout_batch_id == batch_id))
            if payout is not None:
                payout.status = status
                payout.updated_at = datetime.now(timezone.utc)
                user_id = payout.requested_by

        db.add(Notification(
            event_id=event_id,
            user_id=user_id,
            kind=kind,
            text=text[:300],
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False

    return True


def list_for(user_id: int, is_owner: bool, after_id: int = 0, limit: int = 20) -> list[dict]:
    with SessionLocal() as db:
        who = Notification.user_id == user_id
        if is_owner:
            who = or_(who, Notification.user_id.is_(None))
        rows = db.scalars(
            select(Notification)
            .where(who, Notification.id > after_id)
            .order_by(Notification.id.desc())
            .limit(limit)
        ).all()

        return [
            {
                "id": n.id,
                "kind": n.kind,
                "text": n.text,
                "created_at": n.created_at.isoformat(),
            }
            for n in rows
        ]


def add_notification(user_id: int | None, kind: str, text: str) -> None:
    """An alert made by PayGuard itself (not from a PayPal webhook)."""
    with SessionLocal() as db:
        db.add(Notification(user_id=user_id, kind=kind, text=text[:300]))
        db.commit()
