"""
Pay a friend from your own PayPal account. PayGuard creates a PayPal order whose
payee is the friend, the person approves it on PayPal's page (PayPal's own login
and checks), and PayGuard collects it only for the person who created it.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.integrations.paypal_client import get_access_token
from app.models.friend_payment import FriendPayment
from app.services import contacts, payment_service

MAX_AMOUNT = Decimal("100.00")


class FriendPayError(Exception):
    pass


async def _create_order(to_email: str, amount: Decimal, reference: str) -> dict:
    """Tests replace this."""
    token = (await get_access_token())["access_token"]
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.post(
                f"{settings.paypal_base_url.rstrip('/')}/v2/checkout/orders",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": f"friend-{reference}",
                },
                json={
                    "intent": "CAPTURE",
                    "purchase_units": [{
                        "reference_id": reference,
                        "description": "Sent with PayGuard",
                        "amount": {"currency_code": "USD", "value": f"{amount:.2f}"},
                        # The money goes to the friend, not to PayGuard.
                        "payee": {"email_address": to_email},
                    }],
                    "payment_source": {"paypal": {"experience_context": {
                        "user_action": "PAY_NOW",
                        "shipping_preference": "NO_SHIPPING",
                        "brand_name": "PayGuard",
                        "return_url": settings.app_pay_return_uri,
                        "cancel_url": settings.app_pay_cancel_uri,
                    }}},
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FriendPayError(f"PayPal refused this payment (HTTP {exc.response.status_code}).") from None
        except httpx.RequestError:
            raise FriendPayError("Could not reach PayPal. Please try again.") from None
    data = response.json()
    url = next((link["href"] for link in data.get("links", []) if link.get("rel") == "payer-action"), None)
    if not url:
        raise FriendPayError("PayPal did not return a payment page.")
    return {"order_id": data["id"], "approval_url": url}


def _view(row: FriendPayment) -> dict:
    return {
        "id": row.id,
        "name": row.to_name,
        "email": row.to_email,
        "amount": f"{Decimal(str(row.amount)):.2f}",
        "currency": row.currency,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "transaction_id": row.capture_id,
    }


async def start(user, to_email: str, amount: Decimal) -> dict:
    contact = contacts.find_by_email(to_email, user.id)
    if contact is None:
        raise FriendPayError("Please choose someone from your contacts.")
    if contact["email"] == user.email.strip().lower():
        raise FriendPayError("You can't send money to yourself.")
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if not (Decimal("0") < amount <= MAX_AMOUNT):
        raise FriendPayError(f"You can send up to ${MAX_AMOUNT:.2f} at a time.")

    order = await _create_order(contact["email"], amount, uuid.uuid4().hex[:20])
    with SessionLocal() as db:
        row = FriendPayment(
            user_id=user.id, to_name=contact["name"], to_email=contact["email"], amount=amount,
            paypal_order_id=order["order_id"], approval_url=order["approval_url"],
        )
        db.add(row)
        db.commit()
        return {**_view(row), "approval_url": row.approval_url}


async def complete(user_id: int, paypal_order_id: str) -> dict:
    """After approval in PayPal. Only the person who started it can finish it; safe to repeat."""
    with SessionLocal() as db:
        row = db.scalar(select(FriendPayment).where(FriendPayment.paypal_order_id == paypal_order_id))
        if row is None or row.user_id != user_id:
            raise FriendPayError("That payment was not found.")
        if row.status in ("COMPLETED", "PENDING"):
            return _view(row)

    try:
        result = await payment_service.capture_paypal_order(paypal_order_id)
    except RuntimeError:
        raise FriendPayError("PayPal could not finish this payment. Nothing was sent twice.") from None

    # PENDING: PayPal took the money but is still processing it - that is sent, not an error.
    capture = next((c for c in result["captures"] if c.get("status") in ("COMPLETED", "PENDING")), None)
    with SessionLocal() as db:
        row = db.scalar(select(FriendPayment).where(FriendPayment.paypal_order_id == paypal_order_id))
        if capture is None:
            if result.get("status") not in ("COMPLETED", "APPROVED", "PAYER_ACTION_REQUIRED"):
                row.status = "FAILED"
                db.commit()
            raise FriendPayError("The payment is not finished yet.")
        row.status = capture["status"]
        row.capture_id = capture.get("capture_id")
        row.completed_at = datetime.now(timezone.utc)
        db.commit()
        view = _view(row)

    from app.services import webhook_service

    webhook_service.add_notification(
        user_id, "payment_sent",
        f"You sent ${view['amount']} to {view['name']} from your PayPal."
        + (" PayPal is still processing it." if view["status"] == "PENDING" else ""),
    )
    return view


def list_for(user_id: int, limit: int = 20) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(FriendPayment).where(FriendPayment.user_id == user_id)
            .order_by(FriendPayment.id.desc()).limit(limit)
        ).all()
        return [_view(r) for r in rows]
