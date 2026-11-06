"""
PayGuard Shop: a few demo products sold through real PayPal checkout.
Used by the app, the chat assistant and the phone-call menu.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.shop_order import ShopOrder
from app.services import payment_service

MAX_QUANTITY = 10
MAX_TOTAL = Decimal("100.00")
CLAIM_MINUTES = 30  # a phone order code can be claimed in the app this long

# Keypad number on the phone menu = position in this list + 1.
PRODUCTS = [
    {"id": "mug", "name": "PayGuard coffee mug", "name_ta": "PayGuard காபி கோப்பை",
     "price": Decimal("12.00"), "words": ["mug", "cup", "coffee", "கோப்பை", "காபி"]},
    {"id": "tshirt", "name": "PayGuard T-shirt", "name_ta": "PayGuard டி-ஷர்ட்",
     "price": Decimal("20.00"), "words": ["shirt", "tshirt", "t-shirt", "tee", "ஷர்ட்", "சட்டை"]},
    {"id": "earbuds", "name": "Wireless earbuds", "name_ta": "வயர்லெஸ் இயர்பட்ஸ்",
     "price": Decimal("35.00"), "words": ["earbuds", "earbud", "earphones", "headphones", "இயர்பட்ஸ்"]},
    {"id": "braille_book", "name": "Braille learning book", "name_ta": "பிரெய்லி கற்றல் புத்தகம்",
     "price": Decimal("15.00"), "words": ["book", "braille", "புத்தகம்", "பிரெய்லி"]},
]


class ShopError(Exception):
    """Refused by our checks or by PayPal. Nothing was charged."""


def get_product(product_id: str) -> dict | None:
    return next((p for p in PRODUCTS if p["id"] == product_id), None)


def products_said(text: str) -> list[dict]:
    """Products whose words appear in what the person actually said."""
    lower = text.lower()
    said = set(re.findall(r"[a-z0-9\-]+", lower))
    return [
        p for p in PRODUCTS
        if any((w in said) if w.isascii() else (w in lower) for w in p["words"])
    ]


def public(product: dict, tamil: bool = False) -> dict:
    return {
        "id": product["id"],
        "name": product["name_ta"] if tamil else product["name"],
        "price": f"{product['price']:.2f}",
    }


def _new_code(db) -> str:
    while True:
        code = f"{secrets.randbelow(10**6):06d}"
        if db.scalar(select(ShopOrder.id).where(ShopOrder.code == code)) is None:
            return code


async def create_order(product_id: str, quantity: int, channel: str, user_id: int | None = None) -> dict:
    product = get_product(product_id)
    if product is None:
        raise ShopError("That product is not in the shop.")
    if not 1 <= quantity <= MAX_QUANTITY:
        raise ShopError(f"Please choose between 1 and {MAX_QUANTITY}.")

    total = (product["price"] * quantity).quantize(Decimal("0.01"))
    if total > MAX_TOTAL:
        raise ShopError(f"For your safety, one order can be up to ${MAX_TOTAL:.0f}.")

    with SessionLocal() as db:
        code = _new_code(db)

    try:
        paypal = await payment_service.create_paypal_item_order(
            name=product["name"],
            unit_price=product["price"],
            quantity=quantity,
            reference=f"shop-{code}-{secrets.token_hex(4)}",
        )
    except RuntimeError:
        raise ShopError("PayPal could not create the order right now.") from None

    with SessionLocal() as db:
        order = ShopOrder(
            code=code,
            user_id=user_id,
            channel=channel,
            product_id=product["id"],
            quantity=quantity,
            total=total,
            paypal_order_id=paypal["order_id"],
            approval_url=paypal["approval_url"],
            status="CREATED",
        )
        db.add(order)
        try:
            db.commit()
        except IntegrityError:  # two orders drew the same code at the same moment
            db.rollback()
            raise ShopError("Please try again.") from None

    return {
        "code": code,
        "product": product,
        "quantity": quantity,
        "total": total,
        "approval_url": paypal["approval_url"],
    }


def mark_paid(paypal_order_id: str) -> ShopOrder | None:
    """Called once PayPal captured the money. Returns the order, or None if it isn't a shop order."""
    with SessionLocal() as db:
        order = db.scalar(select(ShopOrder).where(ShopOrder.paypal_order_id == paypal_order_id))
        if order is None:
            return None
        order.status = "PAID"
        db.commit()
        db.refresh(order)
        db.expunge(order)
        return order


def claim_phone_order(code: str, user_id: int) -> dict:
    """Open a phone order in the app with the code read out on the call."""
    if not re.fullmatch(r"\d{6}", code or ""):
        raise ShopError("Please enter the 6-digit order code.")

    since = datetime.now(timezone.utc) - timedelta(minutes=CLAIM_MINUTES)
    with SessionLocal() as db:
        order = db.scalar(
            select(ShopOrder)
            .where(ShopOrder.code == code, ShopOrder.channel == "phone")
            .with_for_update()
        )
        if (
            order is None
            or order.user_id is not None  # already claimed
            or order.status != "CREATED"
            or order.created_at.replace(tzinfo=order.created_at.tzinfo or timezone.utc) < since
        ):
            raise ShopError("That order code is not valid. Codes work once, for 30 minutes.")
        order.user_id = user_id
        db.commit()
        return _view(order)


def _view(order: ShopOrder) -> dict:
    product = get_product(order.product_id) or {"name": order.product_id, "name_ta": order.product_id}
    return {
        "code": order.code,
        "name": product["name"],
        "name_ta": product["name_ta"],
        "quantity": order.quantity,
        "total": f"{Decimal(str(order.total)):.2f}",
        "status": order.status,
        "channel": order.channel,
        "approval_url": order.approval_url if order.status == "CREATED" else None,
        "created_at": order.created_at.isoformat(),
    }


def list_orders(user_id: int, limit: int = 20) -> list[dict]:
    with SessionLocal() as db:
        orders = db.scalars(
            select(ShopOrder)
            .where(ShopOrder.user_id == user_id)
            .order_by(ShopOrder.id.desc())
            .limit(limit)
        ).all()
        return [_view(o) for o in orders]
