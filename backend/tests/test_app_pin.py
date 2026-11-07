"""
The PayGuard PIN: set, check, lock after 5 wrong tries, and required (on top of the
fingerprint signature) before a payment moves. PayPal and the database are faked.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import chat_flow
from app.core.config import settings
from app.core.database import Base
from app.models.app_pin import AppPin
from app.models.user import User
from app.services import payment_service, payout_service, pin_service, refund_service, scam_guard

OWNER = SimpleNamespace(id=1, email="owner@shop.test", paypal_user_id="pp-owner")


@pytest.fixture(autouse=True)
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for module in (refund_service, payout_service, scam_guard, pin_service):
        monkeypatch.setattr(module, "SessionLocal", Session)
    monkeypatch.setattr(settings, "merchant_admin_emails", "owner@shop.test")
    monkeypatch.setattr(settings, "require_device_signature", False)
    monkeypatch.setattr(settings, "require_app_pin", True)
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


def prepare():
    async def understand(t, role="owner"):
        return {"action": "send_money", "recipient_name": "Priya", "amount": 20}
    return asyncio.run(chat_flow.handle_message(OWNER, "send $20 to Priya", understand))


def confirm(action_id, pin):
    return asyncio.run(chat_flow.confirm(OWNER, action_id, None, pin))


# ---- setting a PIN ----

@pytest.mark.parametrize("pin", ["12", "1234567", "12a4", "0000", "1234", "9876", "123456"])
def test_weak_or_bad_pins_are_refused(pin):
    with pytest.raises(pin_service.PinError):
        pin_service.set_pin(1, pin, None, 0)
    assert not pin_service.has_pin(1)


def test_pin_is_stored_hashed(world):
    pin_service.set_pin(1, "4826", None, 0)
    with world.Session() as db:
        row = db.scalar(select(AppPin))
    assert "4826" not in row.pin_hash
    assert pin_service.check_pin(1, "4826").ok


def test_changing_pin_needs_old_pin_or_fresh_login():
    pin_service.set_pin(1, "4826", None, 0)

    # A stolen, older login token cannot set a new PIN.
    with pytest.raises(pin_service.PinError, match="current PIN"):
        pin_service.set_pin(1, "5937", None, 3600)
    with pytest.raises(pin_service.PinError, match="not right"):
        pin_service.set_pin(1, "5937", "1111", 3600)
    assert pin_service.check_pin(1, "4826").ok

    pin_service.set_pin(1, "5937", "4826", 3600)
    assert pin_service.check_pin(1, "5937").ok
    pin_service.set_pin(1, "7148", None, 30)   # just logged in again
    assert pin_service.check_pin(1, "7148").ok


def test_five_wrong_tries_lock_the_pin(world):
    pin_service.set_pin(1, "4826", None, 0)
    for left in (4, 3, 2, 1):
        assert f"{left} tr" in pin_service.check_pin(1, "1111").message
    last = pin_service.check_pin(1, "1111")
    assert last.locked and "locked for 15 minutes" in last.message
    # Even the right PIN does nothing while locked.
    assert not pin_service.check_pin(1, "4826").ok

    with world.Session() as db:
        db.scalar(select(AppPin)).locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert pin_service.check_pin(1, "4826").ok


def test_right_pin_resets_the_count():
    pin_service.set_pin(1, "4826", None, 0)
    pin_service.check_pin(1, "1111")
    pin_service.check_pin(1, "1111")
    assert pin_service.check_pin(1, "4826").ok
    assert "4 tries left" in pin_service.check_pin(1, "1111").message


# ---- the PIN guards payments ----

def test_payment_needs_a_pin_set_first(world):
    action = prepare().pending_action
    result = confirm(action["id"], "4826")
    assert "set up your PayGuard PIN" in result.reply
    assert world.calls == []


def test_wrong_pin_sends_nothing_and_can_try_again(world):
    pin_service.set_pin(1, "4826", None, 0)
    action = prepare().pending_action

    wrong = confirm(action["id"], "1111")
    assert "not right" in wrong.reply and wrong.event == "failed"
    assert wrong.pending_action["id"] == action["id"]   # still waiting
    assert world.calls == []

    right = confirm(action["id"], "4826")
    assert right.event == "payment_sent"
    assert len(world.calls) == 1


def test_missing_pin_sends_nothing(world):
    pin_service.set_pin(1, "4826", None, 0)
    action = prepare().pending_action
    assert "type your PayGuard PIN" in confirm(action["id"], None).reply
    assert world.calls == []


def test_locked_pin_drops_the_payment(world):
    pin_service.set_pin(1, "4826", None, 0)
    action = prepare().pending_action
    for _ in range(5):
        result = confirm(action["id"], "1111")
    assert "locked" in result.reply and result.pending_action is None
    assert "nothing to confirm" in confirm(action["id"], "4826").reply.lower()
    assert world.calls == []


def test_spoken_yes_never_skips_the_pin(world, monkeypatch):
    """With the fingerprint off, a spoken "yes, confirm" confirms - but still needs the PIN."""
    pin_service.set_pin(1, "4826", None, 0)
    prepare()

    async def understand(t, role="owner"):
        raise AssertionError("not used")

    result = asyncio.run(chat_flow.handle_message(OWNER, "yes, confirm", understand))
    assert "PIN" in result.reply
    assert world.calls == []
