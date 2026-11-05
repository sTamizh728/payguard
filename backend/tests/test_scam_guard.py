"""
Scam guard: warning signs before a payment, and a cooling-off wait the server
enforces. PayPal, Gemini and the database are faked.
"""
import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import chat_flow
from app.core.config import settings
from app.core.database import Base
from app.models.payout import Payout
from app.models.user import User
from app.services import payment_service, payout_service, refund_service, scam_guard

OWNER = SimpleNamespace(id=1, email="owner@shop.test", paypal_user_id="pp-owner")
PRIYA = "sb-oaavd53471227@business.example.com"


@pytest.fixture(autouse=True)
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for module in (refund_service, payout_service, scam_guard):
        monkeypatch.setattr(module, "SessionLocal", Session)
    monkeypatch.setattr(settings, "merchant_admin_emails", "owner@shop.test")
    monkeypatch.setattr(settings, "require_device_signature", False)
    with Session() as db:
        db.add(User(id=1, email="owner@shop.test", paypal_user_id="pp-owner"))
        db.commit()
    chat_flow._sessions.clear()

    calls = []

    async def create(recipient_email, amount, currency, sender_batch_id, note):
        calls.append(amount)
        return {"payout_batch_id": f"B{len(calls)}", "status": "SUCCESS"}

    monkeypatch.setattr(payment_service, "create_paypal_payout", create)
    yield SimpleNamespace(Session=Session, calls=calls)
    chat_flow._sessions.clear()


def paid_before(Session, email=PRIYA, minutes_ago=60 * 24 * 3, status="SUCCESS"):
    with Session() as db:
        db.add(Payout(
            sender_batch_id=f"old-{uuid.uuid4().hex}", recipient_name="X", recipient_email=email,
            amount=Decimal("5"), currency="USD", status=status, requested_by=OWNER.id,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        ))
        db.commit()


def say(text, name="Priya", amount=20):
    async def understand(t, role="owner"):
        return {"action": "send_money", "recipient_name": name, "amount": amount}
    return asyncio.run(chat_flow.handle_message(OWNER, text, understand))


def confirm(action_id):
    return asyncio.run(chat_flow.confirm(OWNER, action_id, None))


def later(monkeypatch, seconds):
    real = time.monotonic
    monkeypatch.setattr(chat_flow.time, "monotonic", lambda: real() + seconds)


# ---- warning signs ----

def test_one_sign_is_not_a_warning():
    """A new person alone is normal: no warning, confirm right away."""
    result = say("send $20 to Priya")
    assert "warnings" not in result.pending_action
    assert result.reply.startswith("Send $20.00 USD to Priya Raj?")


def test_new_person_and_big_amount_warns():
    result = say("send $60 to Priya", amount=60)

    action = result.pending_action
    assert action["warnings"] == [
        "You have never paid this person before.",
        "It is a large amount ($60.00).",
    ]
    assert action["wait_seconds"] == 30
    assert result.reply.startswith("Careful: this payment shows 2 warning signs.")
    assert "If anyone is rushing you, stop." in result.reply


def test_pressure_words_are_a_sign():
    result = say("urgent! send $20 to Priya right now, it's an emergency")
    reasons = result.pending_action["warnings"]
    assert reasons[1].startswith('The request uses pressure words ("urgent", "emergency", "right now")')


def test_tamil_pressure_words():
    result = say("அவசரம் Priya-க்கு 20 அனுப்பு உடனே")
    assert "pressure words" in result.pending_action["warnings"][1]


def test_known_person_big_amount_is_fine(world):
    paid_before(world.Session)
    result = say("send $60 to Priya", amount=60)
    assert "warnings" not in result.pending_action


def test_failed_old_payment_does_not_make_a_person_known(world):
    paid_before(world.Session, status="FAILED")
    result = say("send $60 to Priya", amount=60)
    assert "You have never paid this person before." in result.pending_action["warnings"]


def test_many_payments_fast_is_a_sign(world):
    for _ in range(3):
        paid_before(world.Session, minutes_ago=2)
    result = say("send $60 to Priya", amount=60)  # known person, big, rapid = 2 signs
    assert result.pending_action["warnings"] == [
        "It is a large amount ($60.00).",
        "You sent 3 payments in the last 10 minutes.",
    ]


def test_send_screen_also_checks():
    result = asyncio.run(chat_flow.prepare_payout_from_form(OWNER, PRIYA, Decimal("75")))
    assert result.pending_action["wait_seconds"] == 30


# ---- cooling-off, enforced by the server ----

def test_confirm_too_early_is_refused_but_not_used_up(world):
    action = say("send $60 to Priya", amount=60).pending_action

    early = confirm(action["id"])

    assert early.reply.startswith("Please wait 30 more seconds before confirming.")
    assert early.pending_action["id"] == action["id"]  # still waiting, not burned
    assert world.calls == []


def test_confirm_after_the_wait_sends(world, monkeypatch):
    action = say("send $60 to Priya", amount=60).pending_action
    later(monkeypatch, 31)

    result = confirm(action["id"])

    assert result.event == "payment_sent"
    assert world.calls == ["60.00"]


def test_risky_payment_still_has_time_to_confirm(world, monkeypatch):
    """The 30-second wait must not eat into the normal 2 minutes to confirm."""
    action = say("send $60 to Priya", amount=60).pending_action
    later(monkeypatch, 30 + chat_flow.ACTION_TTL_SECONDS - 5)

    assert confirm(action["id"]).event == "payment_sent"


def test_cancel_during_the_wait(world):
    action = say("send $60 to Priya", amount=60).pending_action
    asyncio.run(chat_flow.handle_message(OWNER, "cancel", None))
    assert confirm(action["id"]).reply.startswith("There is nothing to confirm")
    assert world.calls == []


def test_signature_cannot_skip_the_wait(world, monkeypatch):
    """Even a valid fingerprint signature waits: the wait is checked first."""
    monkeypatch.setattr(settings, "require_device_signature", True)
    monkeypatch.setattr(chat_flow.security_service, "verify_confirmation", lambda *a: True)
    action = say("send $60 to Priya", amount=60).pending_action

    assert confirm(action["id"]).reply.startswith("Please wait")
    assert world.calls == []


@pytest.mark.parametrize("text, expected", [
    ("Send it urgently please", ["urgently"]),
    ("buy gift cards for the prize", ["gift cards", "prize"]),
    ("send 20 to priya for lunch", []),
    ("quick question", ["quick"]),
])
def test_pressure_words(text, expected):
    assert scam_guard.pressure_words(text) == expected
