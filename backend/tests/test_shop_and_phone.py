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
from app.services import address_service, catalog_service, payment_service, shop_service, webhook_service
from tests.conftest import HOME

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
    address_service.save(1, HOME)  # checkout needs a delivery address

    calls = []

    vault = SimpleNamespace(accepts=True)

    async def fake_order(lines, reference, shipping=None, vault_id=None, save_paypal=False):
        calls.append(dict(lines=lines, shipping=shipping, vault_id=vault_id, save_paypal=save_paypal))
        if vault_id:
            captures = [{"capture_id": f"CAP{len(calls)}", "status": "COMPLETED", "amount": "1.00",
                         "currency": "USD"}] if vault.accepts else []
            return {"order_id": f"PPORDER{len(calls)}", "approval_url": None,
                    "status": "COMPLETED" if vault.accepts else "PAYER_ACTION_REQUIRED", "captures": captures}
        return {"order_id": f"PPORDER{len(calls)}", "approval_url": f"https://paypal.test/checkout/{len(calls)}"}

    monkeypatch.setattr(payment_service, "create_paypal_item_order", fake_order)

    app = FastAPI()
    app.include_router(shop_api.router)
    app.include_router(phone_api.router)
    app.dependency_overrides[get_current_user] = lambda: BUYER
    return SimpleNamespace(Session=Session, calls=calls, client=TestClient(app), vault=vault)


def orders(Session):
    with Session() as db:
        return db.scalars(select(ShopOrder).order_by(ShopOrder.id)).all()


# ---- catalog, cart and checkout ----

CATALOG = {
    101: {"id": 101, "title": "Apple AirPods Max Silver", "brand": "Apple", "price": Decimal("549.99"),
          "rating": 3.5, "stock": 5, "thumbnail": None},
    104: {"id": 104, "title": "Apple iPhone Charger", "brand": "Apple", "price": Decimal("19.99"),
          "rating": 4.2, "stock": 30, "thumbnail": None},
    105: {"id": 105, "title": "Apple MagSafe Battery Pack", "brand": "Apple", "price": Decimal("99.99"),
          "rating": 3.6, "stock": 2, "thumbnail": None},
}


@pytest.fixture
def catalog(monkeypatch):
    async def search(query):
        return [dict(p) for p in CATALOG.values()] if "apple" in query.lower() or "phone" in query.lower() else []

    async def get_product(product_id):
        if product_id not in CATALOG:
            raise catalog_service.CatalogError("That product does not exist.")
        return {**CATALOG[product_id], "description": "Great sound. Long battery.", "category": "audio",
                "shipping": "Ships in 1 week", "returns": "30 days", "warranty": "1 year",
                "reviews": [{"name": "Eleanor", "rating": 3, "comment": "Would not recommend!"},
                            {"name": "Ravi", "rating": 5, "comment": "Excellent."}]}

    monkeypatch.setattr(catalog_service, "search", search)
    monkeypatch.setattr(catalog_service, "get_product", get_product)


def test_products_list_is_the_phone_menu(world):
    names = [p["name"] for p in world.client.get("/api/shop/products").json()["products"]]
    assert names == ["PayGuard coffee mug", "PayGuard T-shirt", "Wireless earbuds", "Braille learning book"]


def test_search_and_details_with_reviews(world, catalog):
    results = world.client.get("/api/shop/search", params={"q": "phone"}).json()["results"]
    assert [r["id"] for r in results] == [101, 104, 105]
    assert results[1]["price"] == "19.99" and results[1]["rating"] == 4.2

    details = world.client.get("/api/shop/products/104").json()
    assert details["reviews"][0] == {"name": "Eleanor", "rating": 3, "comment": "Would not recommend!"}
    assert world.client.get("/api/shop/products/999").status_code == 404


def test_cart_add_change_remove(world, catalog):
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 2})
    cart = world.client.post("/api/shop/cart", json={"product_id": 105, "quantity": 1}).json()
    assert cart["total"] == "139.97"
    assert [i["line_total"] for i in cart["items"]] == ["39.98", "99.99"]

    cart = world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 0}).json()
    assert [i["product_id"] for i in cart["items"]] == [105]


def test_cart_refuses_unknown_product_and_too_many(world, catalog):
    assert world.client.post("/api/shop/cart", json={"product_id": 999, "quantity": 1}).status_code == 400
    response = world.client.post("/api/shop/cart", json={"product_id": 105, "quantity": 3})
    assert response.status_code == 400 and "Only 2 left" in response.json()["detail"]
    assert world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 11}).status_code == 422


def test_checkout_uses_server_prices_and_empties_cart(world, catalog):
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 2})
    world.client.post("/api/shop/cart", json={"product_id": 105, "quantity": 1})

    order = world.client.post("/api/shop/checkout").json()

    assert order["total"] == "139.97"
    assert world.calls[0]["save_paypal"] is True and world.calls[0]["vault_id"] is None
    assert world.calls[0]["lines"] == [("Apple iPhone Charger", Decimal("19.99"), 2),
                                       ("Apple MagSafe Battery Pack", Decimal("99.99"), 1)]
    # The person's own delivery address goes to PayPal and onto the order.
    assert world.calls[0]["shipping"]["address"] == {
        "address_line_1": "12 Gandhi Road", "admin_area_2": "Chennai", "postal_code": "600001",
        "country_code": "IN", "admin_area_1": "Tamil Nadu"}
    assert orders(world.Session)[0].ship_to == "Anna Buyer, 12 Gandhi Road, Chennai, Tamil Nadu, 600001, IN"
    assert world.client.get("/api/shop/cart").json()["items"] == []
    [saved] = orders(world.Session)
    assert saved.summary == "2 x Apple iPhone Charger, 1 x Apple MagSafe Battery Pack"
    assert saved.user_id == 1 and saved.channel == "app"


def test_checkout_needs_an_address(world, catalog, side_db):
    from app.models.delivery_address import DeliveryAddress

    with side_db() as db:
        db.query(DeliveryAddress).delete()
        db.commit()
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    response = world.client.post("/api/shop/checkout")
    assert response.status_code == 400 and "delivery address" in response.json()["detail"]
    assert world.calls == []
    assert len(world.client.get("/api/shop/cart").json()["items"]) == 1


@pytest.mark.parametrize("change,error", [
    ({"postal_code": "6000"}, "6 digits"), ({"state": ""}, "state"), ({"country_code": "I1"}, "2 letters"),
    ({"phone": "call me"}, "phone"),
])
def test_bad_addresses_are_refused(world, change, error):
    response = world.client.put("/api/shop/address", json={**HOME, **change})
    assert response.status_code in (400, 422)
    if response.status_code == 400:
        assert error in response.json()["detail"]


def test_address_round_trip(world):
    saved = world.client.put("/api/shop/address", json={**HOME, "city": "Madurai", "postal_code": "625001"}).json()
    assert saved["address"]["city"] == "Madurai"
    assert world.client.get("/api/shop/address").json()["address"]["postal_code"] == "625001"


def test_checkout_empty_cart(world, catalog):
    response = world.client.post("/api/shop/checkout")
    assert response.status_code == 400 and response.json()["detail"] == "Your cart is empty."


def test_checkout_over_limit(world, catalog):
    world.client.post("/api/shop/cart", json={"product_id": 101, "quantity": 2})  # $1099.98
    response = world.client.post("/api/shop/checkout")
    assert response.status_code == 400 and "up to $1000" in response.json()["detail"]
    assert world.calls == []


def test_paypal_down_keeps_the_cart(world, catalog, monkeypatch):
    async def broken(lines, reference, **options):
        raise RuntimeError("PayPal order failed (HTTP 500).")

    monkeypatch.setattr(payment_service, "create_paypal_item_order", broken)
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    assert world.client.post("/api/shop/checkout").status_code == 400
    assert len(world.client.get("/api/shop/cart").json()["items"]) == 1
    assert orders(world.Session) == []


def test_mark_paid_and_my_orders(world, catalog):
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    world.client.post("/api/shop/checkout")

    order = shop_service.mark_paid("PPORDER1")

    assert order.status == "PAID"
    [mine] = world.client.get("/api/shop/orders").json()["orders"]
    assert mine["status"] == "PAID" and mine["approval_url"] is None
    assert mine["name"] == "1 x Apple iPhone Charger"
    assert shop_service.mark_paid("SOMEONE-ELSES-ORDER") is None


# ---- shopping by chat / voice ----

def say(text, **intent):
    async def understand(t, role="customer"):
        return intent
    return asyncio.run(chat_flow.handle_message(BUYER, text, understand))


def test_chat_search_reads_results(world, catalog):
    result = say("search for apple phone accessories", action="search_products", query="apple phone")
    assert result.reply.startswith("I found 3 products for apple phone. 1: Apple AirPods Max Silver, $549.99")
    assert "2: Apple iPhone Charger, $19.99, rated 4.2 out of 5." in result.reply


def test_chat_details_reads_reviews(world, catalog):
    say("search apple", action="search_products", query="apple")
    result = say("tell me about the second one", action="product_details", result_number=2)
    assert result.reply.startswith("Apple iPhone Charger, $19.99, rated 4.2 out of 5. Great sound")
    assert "Eleanor gave 3 stars: Would not recommend!" in result.reply


def test_chat_add_it_then_checkout(world, catalog):
    say("search apple", action="search_products", query="apple")
    say("tell me about number 2", action="product_details", result_number=2)
    added = say("add it to my cart", action="add_to_cart")
    assert added.reply.startswith("Added 1 Apple iPhone Charger to your cart. Your cart: 1: 1 x Apple iPhone Charger")

    paid = say("checkout", action="checkout_cart")
    assert paid.pending_action["type"] == "checkout"
    assert paid.pending_action["url"] == "https://paypal.test/checkout/1"
    assert paid.pending_action["summary"] == "1 x Apple iPhone Charger, $19.99"


def test_chat_add_by_number_and_quantity(world, catalog):
    say("search apple", action="search_products", query="apple")
    result = say("add 2 of number 3", action="add_to_cart", result_number=3, quantity=2)
    assert "Only 2 left" not in result.reply
    assert "2 x Apple MagSafe Battery Pack, $199.98" in result.reply


def test_chat_ai_invented_numbers_are_refused(world, catalog):
    say("search apple", action="search_products", query="apple")
    assert say("add something", action="add_to_cart", result_number=2).reply.startswith("Which product?")
    assert say("add number 1", action="add_to_cart", result_number=1, quantity=4).reply == "How many would you like?"
    assert say("tell me more", action="product_details", result_number=1).reply.startswith("Which result?")


def test_chat_number_without_search(world, catalog):
    assert say("add number 1", action="add_to_cart", result_number=1).reply.startswith("Which product?")


def test_chat_remove_and_show_cart(world, catalog):
    say("search apple", action="search_products", query="apple")
    say("add number 2", action="add_to_cart", result_number=2)
    assert say("remove item 1", action="remove_from_cart", item_number=1).reply == "Removed Apple iPhone Charger. Your cart is empty."
    assert say("what's in my cart", action="show_cart").reply == "Your cart is empty."


def test_chat_catalog_down(world, monkeypatch):
    async def broken(query):
        raise catalog_service.CatalogError("The product catalog is not reachable right now.")

    monkeypatch.setattr(catalog_service, "search", broken)
    result = say("search phones", action="search_products", query="phones")
    assert result.reply == "The product catalog is not reachable right now." and result.event == "failed"


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


def test_app_order_code_cannot_be_claimed(world, catalog):
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    code = world.client.post("/api/shop/checkout").json()["code"]
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

    result = asyncio.run(payment_service.create_paypal_item_order(
        [("Mug", Decimal("12.00"), 3), ("Book", Decimal("15.50"), 1)], "shop-1"))

    assert result == {"order_id": "O1", "approval_url": "https://pp/approve"}
    import json
    unit = json.loads(seen[0].content)["purchase_units"][0]
    assert unit["amount"]["value"] == "51.50"
    assert unit["amount"]["breakdown"]["item_total"]["value"] == "51.50"
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


# ---- checkout returns into the app ----

def test_complete_checkout_from_the_app(world, catalog, monkeypatch):
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    world.client.post("/api/shop/checkout")
    captured, saved = [], []

    async def capture(order_id):
        captured.append(order_id)
        return {"order_id": order_id, "status": "COMPLETED", "payer_email": "b@x.test", "payer_id": "P1",
                "captures": [{"capture_id": "CAP1", "status": "COMPLETED", "amount": "19.99", "currency": "USD"}]}

    monkeypatch.setattr(payment_service, "capture_paypal_order", capture)
    from app.services import transaction_service
    monkeypatch.setattr(transaction_service, "save_completed_capture",
                        lambda order_id, capture, **k: saved.append((order_id, capture["capture_id"])))

    response = world.client.post("/api/shop/complete", json={"order_id": "PPORDER1"})

    assert response.status_code == 200 and response.json()["order"]["status"] == "PAID"
    assert captured == ["PPORDER1"] and saved == [("PPORDER1", "CAP1")]
    assert webhook_service.list_for(1, is_owner=False)[0]["kind"] == "order_paid"


def test_cannot_complete_someone_elses_order(world, catalog):
    assert world.client.post("/api/shop/complete", json={"order_id": "NOT-MINE-1"}).status_code == 404


def test_checkout_returns_into_the_app(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(201, json={"id": "O1", "links": [{"rel": "payer-action", "href": "https://pp/a"}]})

    async def token():
        return {"access_token": "t"}

    monkeypatch.setattr(payment_service, "get_access_token", token)
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(payment_service.httpx, "AsyncClient", lambda *a, **k: real(*a, **{**k, "transport": transport}))
    asyncio.run(payment_service.create_paypal_item_order([("Mug", Decimal("12.00"), 1)], "shop-2"))

    import json
    context = json.loads(seen[0].content)["payment_source"]["paypal"]["experience_context"]
    assert context["return_url"] == "accessiblecommerce://shop/paid"
    assert context["cancel_url"] == "accessiblecommerce://shop/cancel"


# ---- smarter search (no network: the catalog call is faked) ----

def test_search_falls_back_to_words_and_categories(monkeypatch):
    asked = []

    async def fake_get(path, params=None):
        asked.append((path, (params or {}).get("q")))
        if path == "/products/category/smartphones":
            return {"products": [{"id": 1, "title": "iPhone 9", "price": 549, "rating": 4.7, "stock": 9}]}
        return {"products": []}

    monkeypatch.setattr(catalog_service, "_get", fake_get)
    results = asyncio.run(catalog_service.search("show me cheap mobiles"))

    assert [r["title"] for r in results] == ["iPhone 9"]
    assert asked[0] == ("/products/search", "show me cheap mobiles")
    assert ("/products/search", "mobile") in asked  # plural made singular, stop words dropped
    assert ("/products/search", "show") not in asked and ("/products/search", "cheap") not in asked


def test_search_stops_early_when_exact_words_find_enough(monkeypatch):
    asked = []

    async def fake_get(path, params=None):
        asked.append(path)
        return {"products": [{"id": i, "title": f"P{i}", "price": 1, "rating": 4, "stock": 1} for i in range(3)]}

    monkeypatch.setattr(catalog_service, "_get", fake_get)
    assert len(asyncio.run(catalog_service.search("phone"))) == 3
    assert asked == ["/products/search"]


# ---- confirmation, receipt and delivery date ----

def pay_cart(world, monkeypatch):
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 2})
    code = world.client.post("/api/shop/checkout").json()["code"]

    async def capture(order_id):
        return {"order_id": order_id, "status": "COMPLETED", "payer_email": "b@x.test", "payer_id": "P1",
                "captures": [{"capture_id": "CAPTURE-77", "status": "COMPLETED", "amount": "39.98", "currency": "USD"}]}

    monkeypatch.setattr(payment_service, "capture_paypal_order", capture)
    from app.services import transaction_service
    monkeypatch.setattr(transaction_service, "save_completed_capture", lambda *a, **k: None)
    world.client.post("/api/shop/complete", json={"order_id": "PPORDER1"})
    return code


def test_receipt_after_payment(world, catalog, monkeypatch):
    code = pay_cart(world, monkeypatch)

    receipt = world.client.get(f"/api/shop/orders/{code}").json()

    assert receipt["status"] == "PAID" and receipt["total"] == "39.98"
    assert receipt["items"] == [{"title": "Apple iPhone Charger", "price": "19.99", "quantity": 2}]
    assert receipt["transaction_id"] == "CAPTURE-77"
    assert receipt["paid_at"] is not None
    expected = shop_service.expected_delivery(["Ships in 1 week"]).isoformat()
    assert receipt["delivery_by"] == expected


def test_confirmation_alert_has_delivery_date(world, catalog, monkeypatch):
    code = pay_cart(world, monkeypatch)
    [alert] = webhook_service.list_for(1, is_owner=False)
    when = shop_service.delivery_words(shop_service.expected_delivery(["Ships in 1 week"]).isoformat())
    assert alert["text"] == (
        f"Order {code} confirmed: 2 x Apple iPhone Charger, $39.98 paid with PayPal. "
        f"Expected delivery by {when}."
    )


def test_receipt_is_private(world, catalog, monkeypatch):
    code = pay_cart(world, monkeypatch)
    with world.Session() as db:
        db.scalar(select(ShopOrder)).user_id = 999
        db.commit()
    assert world.client.get(f"/api/shop/orders/{code}").status_code == 404


def test_chat_where_is_my_order(world, catalog, monkeypatch):
    code = pay_cart(world, monkeypatch)
    reply = say("where is my order", action="show_orders").reply
    assert reply.startswith(f"Your latest orders. Order {code}: 2 x Apple iPhone Charger, $39.98, paid, expected delivery by")


def test_chat_no_orders(world):
    assert say("where is my order", action="show_orders").reply == "You have no shop orders yet."


@pytest.mark.parametrize("text, expected", [
    ("Ships overnight", "2026-11-09"),             # Fri + 1 day + 2 transit
    ("Ships in 1-2 business days", "2026-11-12"),  # skips the weekend
    ("Ships in 3-5 business days", "2026-11-15"),
    ("Ships in 2 weeks", "2026-11-22"),
    ("Ships in 1 month", "2026-12-08"),
    (None, "2026-11-15"),
])
def test_expected_delivery(text, expected):
    from datetime import date
    assert shop_service.expected_delivery([text], date(2026, 11, 6)).isoformat() == expected


def test_order_waits_for_the_slowest_item():
    from datetime import date
    days = shop_service.expected_delivery(["Ships overnight", "Ships in 2 weeks"], date(2026, 11, 6))
    assert days.isoformat() == "2026-11-22"


# ---------- voice checkout: address one question at a time, then PIN + fingerprint ----------

def answer(text):
    async def understand(t, role="customer"):
        # In Live voice the AI calls answer_question; its 'answer' is ignored, the words are used.
        return {"action": "answer_question", "answer": "IGNORED 999 Fake Street"}
    return asyncio.run(chat_flow.handle_message(BUYER, text, understand))


def clear_address(side_db):
    from app.models.delivery_address import DeliveryAddress

    with side_db() as db:
        db.query(DeliveryAddress).delete()
        db.commit()


def test_voice_asks_the_address_one_by_one(world, catalog, side_db):
    clear_address(side_db)
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})

    first = say("checkout", action="checkout_cart")
    assert first.reply.startswith("Before you pay, I need your delivery address.")
    assert first.reply.endswith("What is the full name for the delivery?")
    assert first.pending_action is None

    steps = [
        ("Anna Buyer", "house number and street"),
        ("12 Gandhi Road", "area or landmark"),
        ("skip", "Which city?"),
        ("Chennai", "PIN code"),
        ("six zero zero, double zero one", "Which country?"),
        ("India", "Which state?"),
        ("Tamil Nadu", "phone number"),
    ]
    for said, next_question in steps:
        assert next_question in answer(said).reply, said
    readback = answer("skip")
    assert readback.reply == ("I have: Anna Buyer, 12 Gandhi Road, Chennai, Tamil Nadu, 600001, IN. "
                              "Say yes to save it, or say change and the part, like change city.")

    assert answer("change the city").reply == "Which city?"
    assert "Madurai" in answer("Madurai").reply  # straight back to the read-back
    assert world.calls == []  # nothing ordered yet

    done = answer("yes")
    assert done.reply.startswith("Address saved. Your order")
    assert "delivered to Madurai, 600001" in done.reply
    assert done.pending_action["type"] == "checkout"
    assert address_service.get(1)["city"] == "Madurai"
    assert world.calls[0]["shipping"]["address"]["admin_area_2"] == "Madurai"


def test_voice_address_bad_pin_code_asks_again(world, catalog, side_db):
    clear_address(side_db)
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    say("checkout", action="checkout_cart")
    for said in ("Anna", "12 Gandhi Road", "skip", "Chennai"):
        answer(said)
    assert "digit by digit" in answer("near the temple").reply
    assert "Which country?" in answer("6 0 0 0 0 1").reply


def test_voice_address_save_error_reasks_that_part(world, catalog, side_db):
    clear_address(side_db)
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    say("checkout", action="checkout_cart")
    for said in ("Anna", "12 Gandhi Road", "skip", "Chennai", "6000", "India", "Tamil Nadu", "skip"):
        answer(said)
    retry = answer("yes")
    assert retry.reply.startswith("An Indian PIN code has 6 digits.") and "PIN code" in retry.reply
    assert answer("600001").reply.startswith("I have:")
    assert answer("yes").reply.startswith("Address saved.")


def test_cancel_stops_the_address_questions(world, catalog, side_db):
    clear_address(side_db)
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    say("checkout", action="checkout_cart")
    assert answer("cancel").reply == "Okay, I stopped. Nothing was saved or paid."
    assert address_service.get(1) is None
    assert chat_flow._session(1).address_step is None


def save_paypal_for_buyer():
    shop_service._save_paypal(1, "VAULT-1", "buyer@paypal.test")


def test_first_payment_saves_paypal(world, catalog, monkeypatch):
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    world.client.post("/api/shop/checkout")

    async def capture(order_id):
        return {"order_id": order_id, "status": "COMPLETED", "payer_email": "Buyer@Shop.test", "payer_id": "P1",
                "vault_id": "VAULT-9",
                "captures": [{"capture_id": "CAP1", "status": "COMPLETED", "amount": "19.99", "currency": "USD"}]}

    monkeypatch.setattr(payment_service, "capture_paypal_order", capture)
    from app.services import transaction_service
    monkeypatch.setattr(transaction_service, "save_completed_capture", lambda *a, **k: None)
    world.client.post("/api/shop/complete", json={"order_id": "PPORDER1"})
    assert shop_service.saved_paypal(1) == "VAULT-9"


def test_saved_paypal_pays_after_pin_and_fingerprint(world, catalog, monkeypatch):
    from app.services import pin_service, transaction_service

    monkeypatch.setattr(pin_service, "SessionLocal", world.Session)
    monkeypatch.setattr(settings, "require_app_pin", True)
    monkeypatch.setattr(settings, "require_device_signature", False)
    monkeypatch.setattr(transaction_service, "save_completed_capture", lambda *a, **k: None)
    pin_service.set_pin(1, "4826", None, 0)
    save_paypal_for_buyer()
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 2})

    ready = say("checkout", action="checkout_cart")
    assert ready.pending_action["type"] == "shop_pay"
    assert "Total $39.98, delivered to Chennai, 600001" in ready.reply
    assert world.calls == []  # nothing charged before the PIN + fingerprint

    wrong = asyncio.run(chat_flow.confirm(BUYER, ready.pending_action["id"], None, "1111"))
    assert "not right" in wrong.reply and world.calls == []

    paid = asyncio.run(chat_flow.confirm(BUYER, ready.pending_action["id"], None, "4826"))
    assert paid.event == "payment_sent" and paid.reply.startswith("Paid. Order ")
    assert world.calls[0]["vault_id"] == "VAULT-1"
    assert orders(world.Session)[0].status == "PAID"
    assert world.client.get("/api/shop/cart").json()["items"] == []


def test_shop_pay_button_uses_the_same_flow(world, catalog):
    save_paypal_for_buyer()
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    r = world.client.post("/api/shop/pay").json()
    assert r["pending_action"]["type"] == "shop_pay" and world.calls == []
    world.client.delete("/api/shop/saved-paypal")
    r = world.client.post("/api/shop/pay").json()
    assert r["pending_action"]["type"] == "checkout"


def test_cart_changed_after_confirm_box_pays_nothing(world, catalog, monkeypatch):
    monkeypatch.setattr(settings, "require_device_signature", False)
    save_paypal_for_buyer()
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    ready = say("checkout", action="checkout_cart")
    world.client.post("/api/shop/cart", json={"product_id": 105, "quantity": 1})
    result = asyncio.run(chat_flow.confirm(BUYER, ready.pending_action["id"], None, None))
    assert "cart changed" in result.reply and world.calls == []


def test_refused_saved_paypal_is_forgotten_and_cart_kept(world, catalog, monkeypatch):
    monkeypatch.setattr(settings, "require_device_signature", False)
    save_paypal_for_buyer()
    world.vault.accepts = False
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    ready = say("checkout", action="checkout_cart")
    result = asyncio.run(chat_flow.confirm(BUYER, ready.pending_action["id"], None, None))
    assert "did not accept your saved PayPal" in result.reply and result.event == "failed"
    assert shop_service.saved_paypal(1) is None
    assert len(world.client.get("/api/shop/cart").json()["items"]) == 1


@pytest.mark.parametrize("text,digits", [("six zero zero zero zero one", "600001"), ("600 001", "600001"),
                                         ("double nine triple four 1", "994441"), ("oh one two", "012")])
def test_spoken_digits(text, digits):
    assert chat_flow._digits(text) == digits


def test_someone_else_paying_my_link_never_becomes_my_saved_paypal(world, catalog, monkeypatch):
    """Anna sends her checkout link to Vijay; Vijay pays and saves PayPal. Anna must not get it."""
    world.client.post("/api/shop/cart", json={"product_id": 104, "quantity": 1})
    world.client.post("/api/shop/checkout")

    async def capture(order_id):
        return {"order_id": order_id, "status": "COMPLETED", "payer_email": "vijay@other.test", "payer_id": "P2",
                "vault_id": "VAULT-VIJAY",
                "captures": [{"capture_id": "CAP1", "status": "COMPLETED", "amount": "19.99", "currency": "USD"}]}

    monkeypatch.setattr(payment_service, "capture_paypal_order", capture)
    from app.services import transaction_service
    monkeypatch.setattr(transaction_service, "save_completed_capture", lambda *a, **k: None)
    world.client.post("/api/shop/complete", json={"order_id": "PPORDER1"})
    assert shop_service.saved_paypal(1) is None
