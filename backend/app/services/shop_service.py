"""
PayGuard Shop: a few demo products sold through real PayPal checkout.
Used by the app, the chat assistant and the phone-call menu.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.cart_item import CartItem
from app.models.shop_order import ShopOrder
from app.services import catalog_service, payment_service

MAX_QUANTITY = 10
MAX_TOTAL = Decimal("100.00")  # phone orders
CART_MAX_TOTAL = Decimal("1000.00")  # app / chat cart
CART_MAX_LINES = 10
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
            [(product["name"], product["price"], quantity)],
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
            summary=f"{quantity} x {product['name']}",
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
    product = get_product(order.product_id) or {}
    summary = order.summary or product.get("name") or order.product_id
    return {
        "code": order.code,
        "name": summary,
        "name_ta": product.get("name_ta") or summary,
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


# ---------- cart (searchable catalog) ----------

async def set_cart_quantity(user_id: int, product_id: int, quantity: int) -> None:
    """Set how many of a product are in the cart; 0 removes it."""
    if not 0 <= quantity <= MAX_QUANTITY:
        raise ShopError(f"Please choose between 1 and {MAX_QUANTITY}.")
    if quantity:
        try:
            product = await catalog_service.get_product(product_id)  # must exist
        except catalog_service.CatalogError as error:
            raise ShopError(str(error)) from None
        if product["stock"] < quantity:
            raise ShopError(f"Only {product['stock']} left in stock.")

    with SessionLocal() as db:
        item = db.scalar(select(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product_id))
        if quantity == 0:
            if item:
                db.delete(item)
        elif item:
            item.quantity = quantity
        else:
            lines = db.scalar(select(func.count(CartItem.id)).where(CartItem.user_id == user_id))
            if lines >= CART_MAX_LINES:
                raise ShopError(f"Your cart can hold up to {CART_MAX_LINES} different products.")
            db.add(CartItem(user_id=user_id, product_id=product_id, quantity=quantity))
        db.commit()


async def get_cart(user_id: int) -> dict:
    """The cart with current prices from the catalog."""
    with SessionLocal() as db:
        rows = db.execute(
            select(CartItem.product_id, CartItem.quantity)
            .where(CartItem.user_id == user_id)
            .order_by(CartItem.id)
        ).all()

    items = []
    for product_id, quantity in rows:
        try:
            product = await catalog_service.get_product(product_id)
        except catalog_service.CatalogError as error:
            raise ShopError(str(error)) from None
        items.append({
            "product_id": product_id,
            "title": product["title"],
            "price": product["price"],
            "quantity": quantity,
            "line_total": (product["price"] * quantity).quantize(Decimal("0.01")),
        })
    total = sum((i["line_total"] for i in items), Decimal("0.00"))
    return {"items": items, "total": total}


async def checkout_cart(user_id: int) -> dict:
    """Turn the cart into one PayPal order. The cart is emptied once the order exists."""
    cart = await get_cart(user_id)
    if not cart["items"]:
        raise ShopError("Your cart is empty.")
    if cart["total"] > CART_MAX_TOTAL:
        raise ShopError(f"For your safety, one order can be up to ${CART_MAX_TOTAL:.0f}.")

    with SessionLocal() as db:
        code = _new_code(db)

    lines = [(i["title"], i["price"], i["quantity"]) for i in cart["items"]]
    try:
        paypal = await payment_service.create_paypal_item_order(
            lines, reference=f"shop-{code}-{secrets.token_hex(4)}"
        )
    except RuntimeError:
        raise ShopError("PayPal could not create the order right now.") from None

    units = sum(i["quantity"] for i in cart["items"])
    summary = ", ".join(f"{i['quantity']} x {i['title']}" for i in cart["items"])[:300]

    with SessionLocal() as db:
        db.add(ShopOrder(
            code=code, user_id=user_id, channel="app", product_id="cart", quantity=units,
            total=cart["total"], summary=summary, paypal_order_id=paypal["order_id"],
            approval_url=paypal["approval_url"], status="CREATED",
        ))
        for item in db.scalars(select(CartItem).where(CartItem.user_id == user_id)).all():
            db.delete(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ShopError("Please try again.") from None

    return {"code": code, "total": cart["total"], "summary": summary, "approval_url": paypal["approval_url"]}
