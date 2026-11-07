"""
Track: one list of everything that moved money, and where each order is.
Used by the Track screen and by chat / voice.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from app.services import autopay_service, friend_pay_service, payout_service, refund_service, shop_service


def _today() -> date:
    return datetime.now(timezone.utc).date()


def delivery_status(delivery_by: str | None) -> tuple[str, str]:
    """-> (status, words). There is no carrier feed: this is the expected date only."""
    if not delivery_by:
        return "PROCESSING", "Delivery date not known yet"
    when = date.fromisoformat(delivery_by)
    if when >= _today():
        return "ON_THE_WAY", f"On the way, expected by {shop_service.delivery_words(delivery_by)}"
    return "DUE", f"Should have arrived by {shop_service.delivery_words(delivery_by)}"


def deliveries(orders: list[dict]) -> list[dict]:
    result = []
    for order in orders:
        if order["status"] != "PAID":
            continue
        status, words = delivery_status(order.get("delivery_by"))
        result.append({
            "code": order["code"], "name": order["name"], "delivery_by": order.get("delivery_by"),
            "status": status, "status_text": words,
        })
    return result


def payment_history(user, orders: list[dict] | None = None) -> list[dict]:
    """Everything that moved money, newest first."""
    from app.agents import chat_flow

    if orders is None:
        orders = shop_service.list_orders(user.id, 20)
    items = []

    for p in friend_pay_service.list_for(user.id):
        items.append({
            "kind": "friend", "title": f"${p['amount']} to {p['name']} (your PayPal)",
            "amount": p["amount"], "date": p["completed_at"] or p["created_at"],
            "status": p["status"],
            "status_text": {"COMPLETED": "Sent", "PENDING": "Sent, PayPal is still processing it",
                            "CREATED": "Not finished in PayPal", "FAILED": "Failed"}.get(
                p["status"], p["status"].lower()),
        })

    for order in orders:
        if order["status"] == "PAID":
            items.append({
                "kind": "shop", "title": f"${order['total']} at PayGuard Shop: {order['name']}",
                "amount": order["total"], "date": order["paid_at"] or order["created_at"],
                "status": "PAID", "status_text": f"Order {order['code']} paid",
            })

    for a in autopay_service.list_autopays(user.id):
        if a["last_paid_at"]:
            items.append({
                "kind": "autopay", "title": f"${a['last_amount'] or a['amount']} autopay to {a['name']}",
                "amount": a["last_amount"] or a["amount"], "date": a["last_paid_at"],
                "status": "PAID", "status_text": "Last autopay payment",
            })

    if chat_flow.is_merchant_admin(user):
        for p in payout_service.list_payouts(user.id, limit=20):
            view = chat_flow._payout_public(p)
            items.append({
                "kind": "sent", "title": f"${view['amount']} to {view['name']} (PayGuard wallet)",
                "amount": view["amount"], "date": view["created_at"],
                "status": view["status"], "status_text": view["status_text"],
            })
        for t in refund_service.list_transactions(20):
            view = chat_flow._public(t)
            items.append({
                "kind": "received", "title": f"${view['amount']} received (payment {view['number']})",
                "amount": view["amount"], "date": view["created_at"], "status": view["status"],
                "status_text": "Fully refunded" if Decimal(view["refundable"]) <= 0 else "Received",
            })

    items.sort(key=lambda i: i["date"] or "", reverse=True)
    return items[:40]
