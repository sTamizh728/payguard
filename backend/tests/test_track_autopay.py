"""
Track: autopays (real PayPal subscriptions + ones added by hand), reminders,
webhook updates, paying a friend from your own PayPal, the Track screen, and
the chat / voice commands for them. PayPal, Gemini and the database are faked.
"""
import asyncio
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import chat_flow
from app.api import track as track_api
from app.core.config import settings
from app.core.database import Base
from app.core.security import get_current_user
from app.models.autopay import Autopay, PayPalCatalog
from app.models.friend_payment import FriendPayment
from app.models.notification import Notification
from app.models.user import User
from app.services import (
    autopay_service, friend_pay_service, payment_service, payout_service, pin_service, refund_service,
    scam_guard, shop_service, webhook_service,
)

ANNA = SimpleNamespace(id=1, email="anna@buyer.test", paypal_user_id="pp-anna")
BEN = SimpleNamespace(id=2, email="ben@buyer.test", paypal_user_id="pp-ben")
PRIYA_EMAIL = "sb-oaavd53471227@business.example.com"


class FakePayPal:
    """Records every subscription call and answers like PayPal."""

    def __init__(self):
        self.calls = []
        self.subscriptions = {}

    async def __call__(self, method, path, body=None):
        self.calls.append((method, path))
        if path == "/v1/catalogs/products":
            return {"id": "PROD-1"}
        if path == "/v1/billing/plans":
            return {"id": f"P-{len(self.calls)}"}
        if path == "/v1/billing/subscriptions":
            sub_id = f"I-SUB{len(self.subscriptions) + 1}"
            self.subscriptions[sub_id] = {"id": sub_id, "status": "APPROVAL_PENDING"}
            return {"id": sub_id, "status": "APPROVAL_PENDING",
                    "links": [{"rel": "approve", "href": f"https://paypal.test/approve/{sub_id}"}]}
        if method == "GET":
            return self.subscriptions[path.rsplit("/", 1)[-1]]
        return {}

    def approve(self, sub_id, next_date="2026-12-07"):
        self.subscriptions[sub_id] = {
            "id": sub_id, "status": "ACTIVE",
            "billing_info": {"next_billing_time": f"{next_date}T10:00:00Z", "failed_payments_count": 0,
                             "last_payment": {"amount": {"value": "7.99"}, "time": "2026-11-07T10:00:00Z"}},
        }


@pytest.fixture(autouse=True)
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for module in (autopay_service, friend_pay_service, webhook_service, shop_service, refund_service,
                   payout_service, scam_guard, pin_service):
        monkeypatch.setattr(module, "SessionLocal", Session)
    monkeypatch.setattr(settings, "merchant_admin_emails", "owner@shop.test")
    monkeypatch.setattr(settings, "require_device_signature", False)
    with Session() as db:
        db.add_all([User(id=1, email=ANNA.email, paypal_user_id="pp-anna"),
                    User(id=2, email=BEN.email, paypal_user_id="pp-ben")])
        db.commit()
    paypal = FakePayPal()
    monkeypatch.setattr(autopay_service, "_paypal", paypal)
    chat_flow._sessions.clear()

    app = FastAPI()
    app.include_router(track_api.router)
    current = {"user": ANNA}
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    yield SimpleNamespace(Session=Session, paypal=paypal, client=TestClient(app), current=current)
    chat_flow._sessions.clear()


def run(coro):
    return asyncio.run(coro)


def notes(Session, user_id=1):
    with Session() as db:
        return [n.text for n in db.scalars(select(Notification).where(Notification.user_id == user_id))]


# ---------- PayPal autopay ----------

def test_start_autopay_needs_approval_in_paypal(world):
    item = run(autopay_service.start_paypal_autopay(1, "streambox"))
    assert item["status"] == "APPROVAL_PENDING"
    assert item["approval_url"] == "https://paypal.test/approve/I-SUB1"
    assert item["name"] == "StreamBox video" and item["amount"] == "7.99"


def test_product_and_plan_are_made_once(world):
    run(autopay_service.start_paypal_autopay(1, "streambox"))
    run(autopay_service.start_paypal_autopay(2, "streambox"))
    paths = [p for _, p in world.paypal.calls]
    assert paths.count("/v1/catalogs/products") == 1
    assert paths.count("/v1/billing/plans") == 1
    with world.Session() as db:
        assert len(db.scalars(select(PayPalCatalog)).all()) == 2


def test_status_comes_from_paypal_not_the_link(world):
    run(autopay_service.start_paypal_autopay(1, "streambox"))
    # The person came back, but PayPal says it is still not approved.
    assert run(autopay_service.refresh_by_subscription(1, "I-SUB1"))["status"] == "APPROVAL_PENDING"
    world.paypal.approve("I-SUB1")
    item = run(autopay_service.refresh_by_subscription(1, "I-SUB1"))
    assert item["status"] == "ACTIVE" and item["next_date"] == "2026-12-07"
    assert item["last_amount"] == "7.99"


def test_someone_else_cannot_open_your_autopay(world):
    run(autopay_service.start_paypal_autopay(1, "streambox"))
    with pytest.raises(autopay_service.AutopayError):
        run(autopay_service.refresh_by_subscription(2, "I-SUB1"))
    with pytest.raises(autopay_service.AutopayError):
        run(autopay_service.change(2, 1, "cancel"))


def test_no_second_autopay_for_the_same_biller(world):
    run(autopay_service.start_paypal_autopay(1, "streambox"))
    world.paypal.approve("I-SUB1")
    run(autopay_service.refresh(1, 1))
    with pytest.raises(autopay_service.AutopayError, match="already"):
        run(autopay_service.start_paypal_autopay(1, "streambox"))


def test_cancel_pause_resume_call_paypal(world):
    run(autopay_service.start_paypal_autopay(1, "fitlife"))
    world.paypal.approve("I-SUB1")
    run(autopay_service.refresh(1, 1))
    assert run(autopay_service.change(1, 1, "pause"))["status"] == "SUSPENDED"
    assert run(autopay_service.change(1, 1, "resume"))["status"] == "ACTIVE"
    assert run(autopay_service.change(1, 1, "cancel"))["status"] == "CANCELLED"
    posted = [p for m, p in world.paypal.calls if m == "POST"]
    assert posted[-3:] == ["/v1/billing/subscriptions/I-SUB1/suspend",
                           "/v1/billing/subscriptions/I-SUB1/activate",
                           "/v1/billing/subscriptions/I-SUB1/cancel"]
    with pytest.raises(autopay_service.AutopayError, match="ended"):
        run(autopay_service.change(1, 1, "resume"))


def test_unapproved_autopay_is_dropped_without_paypal(world):
    run(autopay_service.start_paypal_autopay(1, "fitlife"))
    with pytest.raises(autopay_service.AutopayError, match="not approved"):
        run(autopay_service.change(1, 1, "pause"))
    before = len(world.paypal.calls)
    assert run(autopay_service.change(1, 1, "cancel"))["status"] == "CANCELLED"
    assert len(world.paypal.calls) == before  # PayPal refuses to cancel an unapproved one


@pytest.mark.parametrize("text,key", [
    ("set up autopay for StreamBox", "streambox"), ("stream box please", "streambox"),
    ("my gym", "fitlife"), ("CloudSafe", "cloudsafe"), ("daily news", "dailynews"), ("netflix", None),
])
def test_biller_comes_from_the_words(text, key):
    assert autopay_service.find_biller(text) == key


# ---------- autopays added by hand + reminders ----------

def test_manual_autopay_is_checked(world):
    today = date.today().isoformat()
    with pytest.raises(autopay_service.AutopayError):
        autopay_service.add_manual(1, "x", "10", "MONTH", today)
    with pytest.raises(autopay_service.AutopayError):
        autopay_service.add_manual(1, "Phone bill", "0", "MONTH", today)
    with pytest.raises(autopay_service.AutopayError):
        autopay_service.add_manual(1, "Phone bill", "10", "HOURLY", today)
    with pytest.raises(autopay_service.AutopayError):
        autopay_service.add_manual(1, "Phone bill", "10", "MONTH", "2099-01-01")
    item = autopay_service.add_manual(1, "Phone bill", "12.5", "month", today)
    assert item["source"] == "manual" and item["amount"] == "12.50" and item["status"] == "ACTIVE"


def test_past_date_rolls_to_the_next_charge(world):
    past = (date.today() - timedelta(days=10)).isoformat()
    item = autopay_service.add_manual(1, "Gym", "20", "WEEK", past)
    assert item["next_date"] == (date.today() - timedelta(days=10) + timedelta(weeks=2)).isoformat()


def test_month_end_dates():
    assert autopay_service._add_interval(date(2026, 1, 31), "MONTH") == date(2026, 2, 28)
    assert autopay_service._add_interval(date(2026, 12, 15), "MONTH") == date(2027, 1, 15)
    assert autopay_service._add_interval(date(2028, 2, 29), "YEAR") == date(2029, 2, 28)


def test_one_reminder_per_charge(world):
    autopay_service.add_manual(1, "Phone bill", "15", "MONTH", (date.today() + timedelta(days=1)).isoformat())
    autopay_service.add_manual(1, "Rent", "500", "MONTH", (date.today() + timedelta(days=9)).isoformat())
    assert autopay_service.make_reminders(1) == 1
    assert autopay_service.make_reminders(1) == 0
    assert notes(world.Session) == [
        f"Reminder: Phone bill autopay of $15.00 charges on {(date.today() + timedelta(days=1)).isoformat()}."
    ]


# ---------- verified webhooks update the right person's autopay ----------

def test_webhook_goes_to_the_subscriber(world):
    run(autopay_service.start_paypal_autopay(2, "dailynews"))
    stored = webhook_service.store({
        "id": "WH-1", "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {"billing_agreement_id": "I-SUB1", "amount": {"total": "1.00", "currency": "USD"}},
    })
    assert stored
    assert notes(world.Session, user_id=2) == ["Autopay paid: $1.00 to Daily News digest."]
    assert notes(world.Session, user_id=1) == []
    with world.Session() as db:
        assert db.scalar(select(Autopay)).last_amount == Decimal("1.00")


def test_failed_autopay_alert_and_no_double_count(world):
    run(autopay_service.start_paypal_autopay(1, "fitlife"))
    event = {"id": "WH-2", "event_type": "BILLING.SUBSCRIPTION.PAYMENT.FAILED", "resource": {"id": "I-SUB1"}}
    assert webhook_service.store(event)
    assert not webhook_service.store(event)  # PayPal sent it twice
    with world.Session() as db:
        assert db.scalar(select(Autopay)).failed_count == 1
    assert "did not go through" in notes(world.Session)[0]


def test_cancelled_webhook_updates_status(world):
    run(autopay_service.start_paypal_autopay(1, "fitlife"))
    webhook_service.store({"id": "WH-3", "event_type": "BILLING.SUBSCRIPTION.CANCELLED",
                           "resource": {"id": "I-SUB1", "status": "CANCELLED"}})
    assert autopay_service.list_autopays(1)[0]["status"] == "CANCELLED"
    assert notes(world.Session) == ["Your FitLife gym autopay was cancelled."]


def test_unknown_subscription_still_goes_to_owners(world):
    webhook_service.store({"id": "WH-4", "event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
                           "resource": {"id": "I-NOT-OURS"}})
    with world.Session() as db:
        assert db.scalar(select(Notification)).user_id is None


# ---------- pay a friend from your own PayPal ----------

@pytest.fixture
def friend_orders(monkeypatch):
    made = []

    async def create(to_email, amount, reference):
        made.append((to_email, amount))
        return {"order_id": f"ORDER{len(made)}", "approval_url": f"https://paypal.test/pay/{len(made)}"}

    captured = []

    async def capture(order_id):
        captured.append(order_id)
        return {"order_id": order_id, "status": "COMPLETED",
                "captures": [{"capture_id": "CAP9", "status": "COMPLETED", "amount": "5.00", "currency": "USD"}]}

    monkeypatch.setattr(friend_pay_service, "_create_order", create)
    monkeypatch.setattr(payment_service, "capture_paypal_order", capture)
    return SimpleNamespace(made=made, captured=captured)


def test_pay_friend_flow(world, friend_orders):
    started = run(friend_pay_service.start(ANNA, PRIYA_EMAIL, Decimal("5")))
    assert started["approval_url"] == "https://paypal.test/pay/1" and started["status"] == "CREATED"
    assert friend_orders.made == [(PRIYA_EMAIL, Decimal("5.00"))]

    done = run(friend_pay_service.complete(1, "ORDER1"))
    assert done["status"] == "COMPLETED" and done["transaction_id"] == "CAP9"
    run(friend_pay_service.complete(1, "ORDER1"))  # back twice: no second capture
    assert friend_orders.captured == ["ORDER1"]
    assert notes(world.Session) == ["You sent $5.00 to Priya Raj from your PayPal."]


def test_pay_friend_checks(world, friend_orders):
    with pytest.raises(friend_pay_service.FriendPayError, match="contacts"):
        run(friend_pay_service.start(ANNA, "stranger@evil.test", Decimal("5")))
    with pytest.raises(friend_pay_service.FriendPayError, match="up to"):
        run(friend_pay_service.start(ANNA, PRIYA_EMAIL, Decimal("100.01")))
    run(friend_pay_service.start(ANNA, PRIYA_EMAIL, Decimal("5")))
    with pytest.raises(friend_pay_service.FriendPayError, match="not found"):
        run(friend_pay_service.complete(2, "ORDER1"))  # Ben cannot finish Anna's payment
    assert friend_orders.captured == []


# ---------- the Track screen ----------

def test_track_shows_everything(world, friend_orders):
    run(friend_pay_service.start(ANNA, PRIYA_EMAIL, Decimal("5")))
    run(friend_pay_service.complete(1, "ORDER1"))
    with world.Session() as db:
        from app.models.shop_order import ShopOrder

        db.add(ShopOrder(code="123456", user_id=1, channel="app", product_id="cart", quantity=1, total=19.99,
                         summary="1 x Charger", paypal_order_id="SHOP1", approval_url="https://x",
                         status="PAID", delivery_by=(date.today() + timedelta(days=3)).isoformat()))
        db.commit()
    autopay_service.add_manual(1, "Phone bill", "15", "MONTH", (date.today() + timedelta(days=20)).isoformat())

    data = world.client.get("/api/track").json()
    kinds = {p["kind"] for p in data["payments"]}
    assert kinds == {"friend", "shop"}
    assert data["autopays"][0]["name"] == "Phone bill"
    assert data["orders"][0]["code"] == "123456"
    assert data["deliveries"][0]["status"] == "ON_THE_WAY"
    assert data["deliveries"][0]["status_text"].startswith("On the way, expected by")
    assert {b["key"] for b in data["billers"]} == set(autopay_service.BILLERS)


def test_track_api_autopay_and_pay(world, friend_orders):
    r = world.client.post("/api/autopay/start", json={"biller": "cloudsafe"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVAL_PENDING"
    world.paypal.approve("I-SUB1")
    assert world.client.post("/api/autopay/return", json={"subscription_id": "I-SUB1"}).json()["status"] == "ACTIVE"
    assert world.client.post("/api/autopay/1/pause").json()["status"] == "SUSPENDED"
    assert world.client.post("/api/autopay/1/explode").status_code == 404
    assert world.client.post("/api/autopay/start", json={"biller": "nope"}).status_code == 400

    r = world.client.post("/api/pay/start", json={"email": PRIYA_EMAIL, "amount": "5.00"})
    assert r.json()["approval_url"]
    done = world.client.post("/api/pay/complete", json={"order_id": "ORDER1"}).json()
    assert done.get("status") == "COMPLETED", done
    contacts = world.client.get("/api/pay/contacts").json()["contacts"]
    assert PRIYA_EMAIL in [c["email"] for c in contacts]


def test_delivery_words():
    from app.services import track_service

    assert track_service.delivery_status(None)[0] == "PROCESSING"
    assert track_service.delivery_status((date.today() - timedelta(days=1)).isoformat())[0] == "DUE"


# ---------- chat / voice ----------

def say(text, intent, user=ANNA):
    async def understand(t, role="customer"):
        return intent
    return run(chat_flow.handle_message(user, text, understand))


def test_voice_start_autopay_uses_the_persons_words(world):
    # The AI says FitLife, but the person said StreamBox: StreamBox wins.
    r = say("set up autopay for StreamBox", {"action": "start_autopay", "biller": "FitLife"})
    assert r.pending_action["type"] == "checkout"
    assert "StreamBox video" in r.pending_action["summary"]
    r = say("start a subscription", {"action": "start_autopay", "biller": "StreamBox"})
    assert r.pending_action is None and "Which autopay" in r.reply


def test_voice_lists_autopays(world):
    assert "no autopays" in say("my autopays?", {"action": "show_autopays"}).reply
    autopay_service.add_manual(1, "Phone bill", "15", "MONTH", (date.today() + timedelta(days=20)).isoformat())
    assert "Autopay 1: Phone bill, $15.00 every month" in say("my autopays?", {"action": "show_autopays"}).reply


def test_cancel_my_autopay_is_not_the_cancel_shortcut(world):
    """'Cancel' usually drops what is pending - but 'cancel my autopay' is a request."""
    autopay_service.add_manual(1, "Phone bill", "15", "MONTH", (date.today() + timedelta(days=20)).isoformat())
    r = say("cancel autopay 1", {"action": "change_autopay", "autopay_number": 1, "change": "cancel"})
    assert r.pending_action["type"] == "autopay"
    assert r.reply.startswith("Cancel autopay 1: Phone bill")

    done = run(chat_flow.confirm(ANNA, r.pending_action["id"], None, None))
    assert done.reply == "Done. Your Phone bill autopay is cancelled."
    assert autopay_service.list_autopays(1)[0]["status"] == "CANCELLED"


def test_plain_cancel_still_cancels(world):
    assert say("cancel", {"action": "show_autopays"}).reply == chat_flow.CANCELLED


def test_autopay_number_must_be_said(world):
    autopay_service.add_manual(1, "Phone bill", "15", "MONTH", (date.today() + timedelta(days=20)).isoformat())
    autopay_service.add_manual(1, "Rent", "500", "MONTH", (date.today() + timedelta(days=20)).isoformat())
    # The AI guessed 2, the person never said a number or a name.
    r = say("pause that autopay", {"action": "change_autopay", "autopay_number": 2, "change": "pause"})
    assert r.pending_action is None and r.reply.startswith("Which autopay?")
    # The change word comes from the person, not the AI.
    r = say("pause autopay 2", {"action": "change_autopay", "autopay_number": 2, "change": "cancel"})
    assert r.reply.startswith("Pause autopay 2: Rent")


def test_autopay_by_name(world):
    autopay_service.add_manual(1, "Phone bill", "15", "MONTH", (date.today() + timedelta(days=20)).isoformat())
    r = say("stop my phone bill autopay", {"action": "change_autopay", "change": "cancel"})
    assert r.reply.startswith("Cancel autopay 1: Phone bill")


def test_autopay_change_needs_the_pin(world, monkeypatch):
    monkeypatch.setattr(settings, "require_app_pin", True)
    pin_service.set_pin(1, "4826", None, 0)
    autopay_service.add_manual(1, "Phone bill", "15", "MONTH", (date.today() + timedelta(days=20)).isoformat())
    r = say("cancel autopay 1", {"action": "change_autopay", "autopay_number": 1})
    assert "not right" in run(chat_flow.confirm(ANNA, r.pending_action["id"], None, "1111")).reply
    assert autopay_service.list_autopays(1)[0]["status"] == "ACTIVE"
    assert "cancelled" in run(chat_flow.confirm(ANNA, r.pending_action["id"], None, "4826")).reply


def test_voice_payment_history(world, friend_orders):
    assert say("my payments", {"action": "show_payment_history"}).reply == "You have no payments yet."
    run(friend_pay_service.start(ANNA, PRIYA_EMAIL, Decimal("5")))
    run(friend_pay_service.complete(1, "ORDER1"))
    assert "$5.00 to Priya Raj (your PayPal)" in say("my payments", {"action": "show_payment_history"}).reply


# ---------- review fixes ----------

def test_two_taps_make_one_subscription(world):
    first = run(autopay_service.start_paypal_autopay(1, "streambox"))
    second = run(autopay_service.start_paypal_autopay(1, "streambox"))
    assert second["id"] == first["id"] and second["approval_url"] == first["approval_url"]
    assert len(world.paypal.subscriptions) == 1


def test_track_buttons_need_the_pin(world, monkeypatch):
    monkeypatch.setattr(settings, "require_app_pin", True)
    pin_service.set_pin(1, "4826", None, 0)
    autopay_service.add_manual(1, "Phone bill", "15", "MONTH", (date.today() + timedelta(days=20)).isoformat())
    assert world.client.post("/api/autopay/1/cancel").status_code == 403
    assert world.client.post("/api/autopay/1/cancel", json={"pin": "1111"}).status_code == 403
    assert autopay_service.list_autopays(1)[0]["status"] == "ACTIVE"
    assert world.client.post("/api/autopay/1/cancel", json={"pin": "4826"}).json()["status"] == "CANCELLED"
    # Checking the status again needs no PIN.
    assert world.client.post("/api/autopay/1/refresh").status_code == 200


def test_pending_capture_counts_as_sent(world, monkeypatch):
    async def create(to_email, amount, reference):
        return {"order_id": "ORDER1", "approval_url": "https://paypal.test/pay/1"}

    async def capture(order_id):
        return {"order_id": order_id, "status": "COMPLETED",
                "captures": [{"capture_id": "CAP1", "status": "PENDING", "amount": "5.00", "currency": "USD"}]}

    monkeypatch.setattr(friend_pay_service, "_create_order", create)
    monkeypatch.setattr(payment_service, "capture_paypal_order", capture)
    run(friend_pay_service.start(ANNA, PRIYA_EMAIL, Decimal("5")))
    done = run(friend_pay_service.complete(1, "ORDER1"))
    assert done["status"] == "PENDING" and done["transaction_id"] == "CAP1"
    assert "still processing" in notes(world.Session)[0]
    from app.services import track_service

    assert track_service.payment_history(ANNA)[0]["status_text"] == "Sent, PayPal is still processing it"


def test_track_buttons_need_the_fingerprint_signature(world, monkeypatch):
    from app.services import security_service

    monkeypatch.setattr(settings, "require_device_signature", True)
    autopay_service.add_manual(1, "Phone bill", "15", "MONTH", (date.today() + timedelta(days=20)).isoformat())
    assert world.client.post("/api/autopay/1/cancel", json={}).status_code == 403
    code = security_service.issue_challenge(1)
    monkeypatch.setattr(security_service, "_verify", lambda user_id, payload, sig: payload == f"payguard-action:{code}".encode() and sig == "SIG")
    assert world.client.post("/api/autopay/1/cancel", json={"challenge": code, "signature": "BAD"}).status_code == 403
    code = security_service.issue_challenge(1)
    monkeypatch.setattr(security_service, "_verify", lambda user_id, payload, sig: payload == f"payguard-action:{code}".encode() and sig == "SIG")
    r = world.client.post("/api/autopay/1/cancel", json={"challenge": code, "signature": "SIG"})
    assert r.json()["status"] == "CANCELLED"
    # A code works once.
    assert world.client.post("/api/autopay/1/pause", json={"challenge": code, "signature": "SIG"}).status_code == 403
