"""
PayGuard Shop (app + chat) and the phone-call menu. PayPal and the database are
faked; phone calls are signed exactly the way Twilio signs them.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from twilio.request_validator import RequestValidator

from app.agents import chat_flow
from app.api import phone as phone_api
from app.api import shop as shop_api
from app.core.config import settings
from app.core.database import Base
from app.core.security import get_current_user
from app.models.notification import Notification  # noqa: F401
from app.models.shop_order import ShopOrder
from app.models.user import User
from app.services import payment_service, shop_service, webhook_service

TOKEN = "twilio-test-token"
BUYER = SimpleNamespace(id=1, email="buyer@shop.test", paypal_user_id="pp-buyer")


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for module in (shop_service, webhook_service):
        monkeypatch.setattr(module, "SessionLocal", Session)
    monkeypatch.setattr(settings, "twilio_auth_token", TOKEN)
    monkeypatch.setattr(settings, "merchant_admin_emails", "owner@shop.test")
    with Session() as db:
        db.add(User(id=1, email="buyer@shop.test", paypal_user_id="pp-buyer"))
        db.commit()
    chat_flow._sessions.clear()

    calls = []

    async def fake_order(name, unit_price, quantity, reference):
        calls.append(dict(name=name, unit_price=unit_price, quantity=quantity))
        return {"order_id": f"PPORDER{len(calls)}", "approval_url": f"https://paypal.test/checkout/{len(calls)}"}

    monkeypatch.setattr(payment_service, "create_paypal_item_order", fake_order)

    app = FastAPI()
    app.include_router(shop_api.router)
    app.include_router(phone_api.router)
    app.dependency_overrides[get_current_user] = lambda: BUYER
    return SimpleNamespace(Session=Session, calls=calls, client=TestClient(app))


def orders(Session):
    with Session() as db:
        return db.scalars(select(ShopOrder).order_by(ShopOrder.id)).all()


# ---- app shop ----

def test_products_list(world):
    names = [p["name"] for p in world.client.get("/api/shop/products").json()["products"]]
    assert names == ["PayGuard coffee mug", "PayGuard T-shirt", "Wireless earbuds", "Braille learning book"]


def test_app_order_creates_paypal_checkout(world):
    response = world.client.post("/api/shop/orders", json={"product_id": "mug", "quantity": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == "24.00"
    assert body["approval_url"] == "https://paypal.test/checkout/1"
    assert re.fullmatch(r"\d{6}", body["code"])
    assert world.calls == [dict(name="PayGuard coffee mug", unit_price=Decimal("12.00"), quantity=2)]
    [order] = orders(world.Session)
    assert order.user_id == 1 and order.channel == "app" and order.status == "CREATED"


@pytest.mark.parametrize("product, quantity", [("mug", 0), ("mug", 11), ("rocket", 1)])
def test_bad_orders_are_refused(world, product, quantity):
    response = world.client.post("/api/shop/orders", json={"product_id": product, "quantity": quantity})
    assert response.status_code in (400, 422)
    assert world.calls == []


def test_order_over_100_dollars_is_refused(world):
    response = world.client.post("/api/shop/orders", json={"product_id": "earbuds", "quantity": 3})
    assert response.status_code == 400
    assert "up to $100" in response.json()["detail"]


def test_paypal_down_creates_nothing(world, monkeypatch):
    async def broken(**kwargs):
        raise RuntimeError("PayPal order failed (HTTP 500).")

    monkeypatch.setattr(payment_service, "create_paypal_item_order", broken)
    response = world.client.post("/api/shop/orders", json={"product_id": "mug", "quantity": 1})
    assert response.status_code == 400
    assert orders(world.Session) == []


def test_mark_paid_and_my_orders(world):
    world.client.post("/api/shop/orders", json={"product_id": "tshirt", "quantity": 1})

    order = shop_service.mark_paid("PPORDER1")

    assert order.status == "PAID"
    [mine] = world.client.get("/api/shop/orders").json()["orders"]
    assert mine["status"] == "PAID" and mine["approval_url"] is None
    assert shop_service.mark_paid("SOMEONE-ELSES-ORDER") is None


# ---- buy by chat ----

def say(text, **intent):
    async def understand(t, role="customer"):
        return {"action": "buy_product", **intent}
    return asyncio.run(chat_flow.handle_message(BUYER, text, understand))


def test_buy_by_chat(world):
    result = say("buy 2 coffee mugs", product="mug", quantity=2)

    assert result.pending_action["type"] == "checkout"
    assert result.pending_action["url"] == "https://paypal.test/checkout/1"
    assert result.pending_action["summary"] == "2 x PayGuard coffee mug, $24.00"
    assert result.event == "request_sent"


def test_buy_in_tamil(world):
    result = say("ஒரு காபி கோப்பை வேண்டும்", product="mug")
    assert result.pending_action["summary"] == "1 x PayGuard coffee mug, $12.00"


def test_ai_invented_product_is_refused(world):
    result = say("buy me something nice", product="earbuds")
    assert result.reply.startswith("Which one would you like?")
    assert world.calls == []


def test_ai_invented_quantity_is_refused(world):
    result = say("buy a mug", product="mug", quantity=5)
    assert result.reply == "How many would you like?"
    assert world.calls == []


def test_two_products_at_once_asks(world):
    result = say("buy a mug and a book", product="mug")
    assert result.reply.startswith("Which one would you like?")


# ---- phone call (signed like Twilio) ----

def call(world, path, digits=None, **query):
    """POST a Twilio webhook with a real Twilio signature."""
    q = urlencode({k: v for k, v in query.items() if v is not None})
    url_path = path + (f"?{q}" if q else "")
    form = {"CallSid": "CA123", "From": "+910000000000"}
    if digits is not None:
        form["Digits"] = digits
    signature = RequestValidator(TOKEN).compute_signature(settings.public_base_url + url_path, form)
    return world.client.post(url_path, data=form, headers={"X-Twilio-Signature": signature})


def test_unsigned_call_is_refused(world):
    response = world.client.post("/api/phone/voice", data={"CallSid": "CA1"})
    assert response.status_code == 403


def test_signature_for_another_step_is_refused(world):
    """A signature is bound to the exact URL: changing the quantity breaks it."""
    form = {"CallSid": "CA1", "Digits": "1"}
    signed_for = settings.public_base_url + "/api/phone/confirm?l=en&p=1&q=1"
    signature = RequestValidator(TOKEN).compute_signature(signed_for, form)
    response = world.client.post("/api/phone/confirm?l=en&p=1&q=8", data=form,
                                 headers={"X-Twilio-Signature": signature})
    assert response.status_code == 403
    assert world.calls == []


def test_calls_refused_when_twilio_not_set_up(world, monkeypatch):
    monkeypatch.setattr(settings, "twilio_auth_token", None)
    assert world.client.post("/api/phone/voice").status_code == 503


def test_welcome_offers_english_and_tamil(world):
    xml = call(world, "/api/phone/voice").text
    assert "Welcome to PayGuard Shop" in xml and "தமிழுக்கு 2" in xml
    assert 'action="/api/phone/lang' in xml


def test_language_choice(world):
    assert "/api/phone/products?l=ta" in call(world, "/api/phone/lang", "2").text
    assert "/api/phone/voice?r=1" in call(world, "/api/phone/lang", "7").text


def test_product_menu_lists_every_product(world):
    xml = call(world, "/api/phone/products", l="en").text
    for n, product in enumerate(shop_service.PRODUCTS, start=1):
        assert f"For {product['name']}" in xml and f"press {n}" in xml
    tamil = call(world, "/api/phone/products", l="ta").text
    assert "காபி கோப்பை" in tamil and "Google.ta-IN-Standard-A" in tamil


def test_no_key_pressed_asks_once_then_says_goodbye(world):
    first = call(world, "/api/phone/products", l="en").text
    assert "/api/phone/products?l=en&amp;r=1" in first
    second = call(world, "/api/phone/products", l="en", r="1").text
    assert "Goodbye" in second and "<Hangup" in second


def test_full_call_places_an_order(world):
    assert "/api/phone/how-many?l=en&amp;p=1" in call(world, "/api/phone/product", "1", l="en").text
    assert "/api/phone/review?l=en&amp;p=1&amp;q=3" in call(world, "/api/phone/quantity", "3", l="en", p="1").text
    review = call(world, "/api/phone/review", l="en", p="1", q="3").text
    assert "3 PayGuard coffee mug, total 36 dollars" in review

    done = call(world, "/api/phone/confirm", "1", l="en", p="1", q="3").text

    [order] = orders(world.Session)
    assert order.channel == "phone" and order.user_id is None and order.quantity == 3
    assert " ".join(order.code) in done  # code read out digit by digit
    assert "<Hangup" in done


def test_cancel_on_the_call(world):
    xml = call(world, "/api/phone/confirm", "2", l="en", p="1", q="1").text
    assert "Order cancelled. Nothing was charged." in xml
    assert orders(world.Session) == []


def test_too_much_on_the_call(world):
    xml = call(world, "/api/phone/quantity", "3", l="en", p="3").text  # 3 x $35
    assert "up to 100 dollars" in xml


def test_tampered_numbers_never_create_an_order(world):
    for p, q in [("9", "1"), ("1", "0"), ("3", "9"), ("x", "1")]:
        call(world, "/api/phone/confirm", "1", l="en", p=p, q=q)
    assert orders(world.Session) == []


# ---- claiming a phone order in the app ----

def phone_order(world):
    call(world, "/api/phone/confirm", "1", l="en", p="2", q="1")
    return orders(world.Session)[-1].code


def test_claim_phone_order_gives_checkout(world):
    code = phone_order(world)

    response = world.client.post("/api/shop/claim", json={"code": code})

    assert response.status_code == 200
    assert response.json()["approval_url"].startswith("https://paypal.test/checkout/")
    assert orders(world.Session)[0].user_id == BUYER.id


def test_code_can_be_claimed_once(world):
    code = phone_order(world)
    assert world.client.post("/api/shop/claim", json={"code": code}).status_code == 200
    assert world.client.post("/api/shop/claim", json={"code": code}).status_code == 400


def test_old_code_expires(world):
    code = phone_order(world)
    with world.Session() as db:
        order = db.scalar(select(ShopOrder))
        order.created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        db.commit()
    assert world.client.post("/api/shop/claim", json={"code": code}).status_code == 400


def test_app_order_code_cannot_be_claimed(world):
    code = world.client.post("/api/shop/orders", json={"product_id": "mug", "quantity": 1}).json()["code"]
    assert world.client.post("/api/shop/claim", json={"code": code}).status_code == 400


# ---- the real PayPal order body ----

def test_paypal_item_order_totals_match(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "O1", "links": [{"rel": "payer-action", "href": "https://pp/approve"}]})

    async def token():
        return {"access_token": "t"}

    monkeypatch.setattr(payment_service, "get_access_token", token)
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(payment_service.httpx, "AsyncClient", lambda *a, **k: real(*a, **{**k, "transport": transport}))

    result = asyncio.run(payment_service.create_paypal_item_order("Mug", Decimal("12.00"), 3, "shop-1"))

    assert result == {"order_id": "O1", "approval_url": "https://pp/approve"}
    import json
    unit = json.loads(seen[0].content)["purchase_units"][0]
    assert unit["amount"]["value"] == "36.00"
    assert unit["amount"]["breakdown"]["item_total"]["value"] == "36.00"
    assert unit["items"][0] == {
        "name": "Mug", "quantity": "3", "unit_amount": {"currency_code": "USD", "value": "12.00"},
        "category": "PHYSICAL_GOODS",
    }


def test_phone_orders_flag(world, monkeypatch):
    monkeypatch.setattr(settings, "twilio_phone_number", None)
    assert world.client.get("/api/shop/products").json()["phone_orders"] is False
    monkeypatch.setattr(settings, "twilio_phone_number", "+15550001111")
    body = world.client.get("/api/shop/products").json()
    assert body["phone_orders"] is True and body["phone_number"] == "+15550001111"
