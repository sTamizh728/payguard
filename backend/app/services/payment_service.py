
from decimal import Decimal

import httpx

from app.core.config import settings
from app.integrations.paypal_client import get_access_token


async def create_paypal_order(
    amount: str = "500.00",
    currency: str = "USD",
) -> dict:
    token_data = await get_access_token()
    access_token = token_data["access_token"]

    url = f"{settings.paypal_base_url.rstrip('/')}/v2/checkout/orders"

    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "amount": {
                    "currency_code": currency,
                    "value": amount,
                },
                "description": "Accessible Commerce AI Sandbox Test",
            }
        ],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "user_action": "PAY_NOW",
                    "return_url": f"{settings.public_base_url}/api/paypal/payment-success",
                    "cancel_url": f"{settings.public_base_url}/api/paypal/payment-cancel",
                }
            }
        },
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

        response.raise_for_status()
        order_data = response.json()

    approval_url = next(
        (
            link["href"]
            for link in order_data.get("links", [])
            if link.get("rel") == "payer-action"
        ),
        None,
    )

    return {
        "order_id": order_data["id"],
        "status": order_data["status"],
        "approval_url": approval_url,
    }


async def capture_paypal_order(order_id: str) -> dict:
    token_data = await get_access_token()
    access_token = token_data["access_token"]

    url = (
        f"{settings.paypal_base_url.rstrip('/')}"
        f"/v2/checkout/orders/{order_id}/capture"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": f"capture-{order_id}",
                },
                json={},
            )

            response.raise_for_status()
            data = response.json()

        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"PayPal capture failed (HTTP {exc.response.status_code}). "
                "The order may be invalid, already captured, or not approved."
            ) from None

        except httpx.RequestError:
            raise RuntimeError(
                "Could not reach PayPal while capturing the order."
            ) from None

    captures = []

    for unit in data.get("purchase_units", []):
        payments = unit.get("payments", {})
        for capture in payments.get("captures", []):
            captures.append({
                "capture_id": capture.get("id"),
                "status": capture.get("status"),
                "amount": capture.get("amount", {}).get("value"),
                "currency": capture.get("amount", {}).get("currency_code"),
            })

    payer = data.get("payer") or {}

    return {
        "order_id": data.get("id"),
        "status": data.get("status"),
        "captures": captures,
        # Who paid: lets a customer see their own purchases later.
        "payer_email": payer.get("email_address"),
        "payer_id": payer.get("payer_id"),
    }


class PayPalRejected(Exception):
    """PayPal answered and refused the request. No money moved."""


class PayPalUncertain(Exception):
    """PayPal did not answer clearly. The money may or may not have moved."""


# Older names, used by the refund code and its tests.
RefundRejected = PayPalRejected
RefundUncertain = PayPalUncertain


async def refund_paypal_capture(
    capture_id: str,
    amount: str,
    currency: str,
    request_id: str,
) -> dict:
    """
    Refund all or part of a captured payment.
    request_id makes retries safe: PayPal returns the same refund
    instead of creating a second one.
    """

    try:
        token_data = await get_access_token()
    except RuntimeError:
        # Nothing was sent to the refund endpoint yet.
        raise RefundRejected("Could not sign in to PayPal.") from None

    access_token = token_data["access_token"]

    url = (
        f"{settings.paypal_base_url.rstrip('/')}"
        f"/v2/payments/captures/{capture_id}/refund"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": request_id,
                    "Prefer": "return=representation",
                },
                json={
                    "amount": {
                        "value": amount,
                        "currency_code": currency,
                    },
                },
            )

        except httpx.RequestError:
            # A timeout does NOT mean the refund failed - never retry blindly.
            raise RefundUncertain("No answer from PayPal.") from None

    if response.status_code >= 500:
        raise RefundUncertain(f"PayPal error (HTTP {response.status_code}).")

    if response.is_error:
        issue = None
        try:
            details = response.json().get("details") or []
            issue = details[0].get("issue") if details else None
        except ValueError:
            pass

        raise RefundRejected(issue or f"HTTP {response.status_code}")

    data = response.json()

    return {
        "refund_id": data.get("id"),
        "status": data.get("status"),
    }


async def get_paypal_order(order_id: str) -> dict:
    token_data = await get_access_token()
    access_token = token_data["access_token"]

    url = (
        f"{settings.paypal_base_url.rstrip('/')}"
        f"/v2/checkout/orders/{order_id}"
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
            },
        )

        if response.is_error:
            raise RuntimeError(
                f"PayPal order lookup failed: HTTP {response.status_code}"
            )

        data = response.json()

    return {
        "order_id": data.get("id"),
        "status": data.get("status"),
        "intent": data.get("intent"),
        "payer": data.get("payer"),
        "purchase_units": data.get("purchase_units"),
        "payment_source": data.get("payment_source"),
        "links": [
            {
                "rel": link.get("rel"),
                "method": link.get("method"),
            }
            for link in data.get("links", [])
        ],
    }



async def create_paypal_payout(
    recipient_email: str,
    amount: str,
    currency: str,
    sender_batch_id: str,
    note: str,
) -> dict:
    """
    Send money to one person by email (Payouts API).
    sender_batch_id makes retries safe: PayPal never pays the same ID twice.
    """

    try:
        token_data = await get_access_token()
    except RuntimeError:
        raise PayPalRejected("Could not sign in to PayPal.") from None

    url = f"{settings.paypal_base_url.rstrip('/')}/v1/payments/payouts"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token_data['access_token']}",
                    "Content-Type": "application/json",
                },
                json={
                    "sender_batch_header": {
                        "sender_batch_id": sender_batch_id,
                        "email_subject": "You received money with PayGuard",
                    },
                    "items": [
                        {
                            "recipient_type": "EMAIL",
                            "receiver": recipient_email,
                            "amount": {"value": amount, "currency": currency},
                            "note": note,
                            "sender_item_id": sender_batch_id,
                        }
                    ],
                },
            )

        except httpx.RequestError:
            # A timeout does NOT mean the payout failed - never retry blindly.
            raise PayPalUncertain("No answer from PayPal.") from None

    if response.status_code >= 500:
        raise PayPalUncertain(f"PayPal error (HTTP {response.status_code}).")

    if response.is_error:
        name = None
        try:
            name = response.json().get("name")
        except ValueError:
            pass
        raise PayPalRejected(name or f"HTTP {response.status_code}")

    header = response.json().get("batch_header") or {}

    return {
        "payout_batch_id": header.get("payout_batch_id"),
        "status": header.get("batch_status"),
    }


async def get_paypal_payout_status(payout_batch_id: str) -> str | None:
    """
    The status of the one item in a payout batch: SUCCESS, PENDING, UNCLAIMED,
    RETURNED, FAILED, ONHOLD, BLOCKED... Falls back to the batch status.
    Returns None if PayPal cannot be asked right now.
    """

    try:
        token_data = await get_access_token()
    except RuntimeError:
        return None

    url = (
        f"{settings.paypal_base_url.rstrip('/')}"
        f"/v1/payments/payouts/{payout_batch_id}"
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
        except httpx.RequestError:
            return None

    if response.is_error:
        return None

    data = response.json()
    items = data.get("items") or []

    if items and items[0].get("transaction_status"):
        return items[0]["transaction_status"]

    return (data.get("batch_header") or {}).get("batch_status")


async def get_paypal_balances() -> list[dict]:
    """The PayPal wallet balance of the account this app manages (Balances API)."""
    token_data = await get_access_token()

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.get(
                f"{settings.paypal_base_url.rstrip('/')}/v1/reporting/balances",
                params={"currency_code": "ALL"},
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"PayPal balance failed (HTTP {exc.response.status_code}).") from None
        except httpx.RequestError:
            raise RuntimeError("Could not reach PayPal.") from None

    return [
        {
            "currency": b.get("currency"),
            "available": (b.get("available_balance") or {}).get("value"),
            "total": (b.get("total_balance") or {}).get("value"),
            "on_hold": (b.get("withheld_balance") or {}).get("value"),
        }
        for b in response.json().get("balances", [])
    ]


async def create_paypal_item_order(
    name: str,
    unit_price: Decimal,
    quantity: int,
    reference: str,
) -> dict:
    """
    A PayPal order for one product line. PayPal refuses the order unless the
    item total equals unit price x quantity exactly, so all figures come from
    the same Decimal values.
    """
    total = (unit_price * quantity).quantize(Decimal("0.01"))
    money = lambda value: {"currency_code": "USD", "value": f"{value:.2f}"}  # noqa: E731

    token_data = await get_access_token()

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.post(
                f"{settings.paypal_base_url.rstrip('/')}/v2/checkout/orders",
                headers={
                    "Authorization": f"Bearer {token_data['access_token']}",
                    "Content-Type": "application/json",
                    "PayPal-Request-Id": f"create-{reference}",
                },
                json={
                    "intent": "CAPTURE",
                    "purchase_units": [{
                        "reference_id": reference,
                        "custom_id": reference,
                        "description": f"PayGuard Shop: {name}",
                        "amount": {**money(total), "breakdown": {"item_total": money(total)}},
                        "items": [{
                            "name": name[:127],
                            "quantity": str(quantity),
                            "unit_amount": money(unit_price),
                            "category": "PHYSICAL_GOODS",
                        }],
                    }],
                    "payment_source": {"paypal": {"experience_context": {
                        "user_action": "PAY_NOW",
                        "shipping_preference": "NO_SHIPPING",
                        "brand_name": "PayGuard Shop",
                        "return_url": f"{settings.public_base_url}/api/paypal/payment-success",
                        "cancel_url": f"{settings.public_base_url}/api/paypal/payment-cancel",
                    }}},
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"PayPal order failed (HTTP {exc.response.status_code}).") from None
        except httpx.RequestError:
            raise RuntimeError("Could not reach PayPal.") from None

    data = response.json()
    approval_url = next(
        (link["href"] for link in data.get("links", []) if link.get("rel") == "payer-action"),
        None,
    )
    if not approval_url:
        raise RuntimeError("PayPal did not return a checkout link.")

    return {"order_id": data["id"], "approval_url": approval_url}
