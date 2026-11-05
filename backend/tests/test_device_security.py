"""
Fingerprint / PIN confirmation, checked by the server. A real EC P-256 key
stands in for the phone's secure hardware key.
"""
import asyncio
import base64
from decimal import Decimal
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents import chat_flow
from app.core.config import settings
from app.core.database import Base
from app.models.device_key import DeviceKey  # noqa: F401 - registers the table
from app.models.user import User
from app.services import payment_service, payout_service, refund_service, security_service

OWNER = SimpleNamespace(id=1, email="owner@shop.test", paypal_user_id="pp-owner")


@pytest.fixture(autouse=True)
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    for module in (refund_service, payout_service, security_service):
        monkeypatch.setattr(module, "SessionLocal", Session)
    monkeypatch.setattr(settings, "merchant_admin_emails", "owner@shop.test")
    monkeypatch.setattr(settings, "require_device_signature", True)
    with Session() as db:
        db.add(User(id=1, email="owner@shop.test", paypal_user_id="pp-owner"))
        db.commit()
    chat_flow._sessions.clear()

    calls = []

    async def create(recipient_email, amount, currency, sender_batch_id, note):
        calls.append(amount)
        return {"payout_batch_id": "B1", "status": "PENDING"}

    monkeypatch.setattr(payment_service, "create_paypal_payout", create)
    yield calls
    chat_flow._sessions.clear()


def new_phone_key():
    private = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )).decode()
    return private, public


def sign(private, action_id):
    return base64.b64encode(private.sign(
        security_service.confirmation_payload(action_id), ec.ECDSA(hashes.SHA256())
    )).decode()


def prepare(amount="20"):
    return asyncio.run(chat_flow.prepare_payout_from_form(
        OWNER, "sb-oaavd53471227@business.example.com", Decimal(amount)
    ))


def confirm(action_id, signature):
    return asyncio.run(chat_flow.confirm(OWNER, action_id, signature))


def test_signed_confirm_sends(world):
    private, public = new_phone_key()
    security_service.register_device_key(OWNER.id, public, token_age_seconds=10)
    action = prepare().pending_action

    result = confirm(action["id"], sign(private, action["id"]))

    assert result.event == "payment_sent"
    assert world == ["20.00"]


def test_no_signature_sends_nothing(world):
    _, public = new_phone_key()
    security_service.register_device_key(OWNER.id, public, token_age_seconds=10)
    action = prepare().pending_action

    result = confirm(action["id"], None)

    assert result.reply.startswith("Your fingerprint or PIN check did not match")
    assert world == []


def test_signature_from_another_phone_is_refused(world):
    _, public = new_phone_key()
    thief, _ = new_phone_key()
    security_service.register_device_key(OWNER.id, public, token_age_seconds=10)
    action = prepare().pending_action

    assert confirm(action["id"], sign(thief, action["id"])).event == "failed"
    assert world == []


def test_signature_for_a_different_action_is_refused(world):
    """An old signature cannot be replayed for a new payment."""
    private, public = new_phone_key()
    security_service.register_device_key(OWNER.id, public, token_age_seconds=10)
    first = prepare().pending_action
    old_signature = sign(private, first["id"])
    second = prepare("30").pending_action

    assert confirm(second["id"], old_signature).event == "failed"
    assert world == []


def test_no_registered_key_sends_nothing(world):
    private, _ = new_phone_key()
    action = prepare().pending_action
    assert confirm(action["id"], sign(private, action["id"])).event == "failed"
    assert world == []


def test_failed_check_burns_the_action(world):
    private, public = new_phone_key()
    security_service.register_device_key(OWNER.id, public, token_age_seconds=10)
    action = prepare().pending_action

    confirm(action["id"], "bm90LWEtc2lnbmF0dXJl")
    retry = confirm(action["id"], sign(private, action["id"]))

    assert retry.reply == "There is nothing to confirm. Please ask again."
    assert world == []


def test_spoken_yes_confirm_never_sends_when_signature_required(world):
    prepare()

    async def understand(text, role="owner"):
        raise AssertionError("AI must not be called")

    result = asyncio.run(chat_flow.handle_message(OWNER, "yes, confirm", understand))

    assert result.reply == "Please tap Confirm and use your fingerprint or PIN."
    assert result.pending_action["type"] == "payout"
    assert world == []


def test_replacing_a_key_needs_a_fresh_login():
    _, first = new_phone_key()
    _, second = new_phone_key()
    security_service.register_device_key(OWNER.id, first, token_age_seconds=3600)

    with pytest.raises(security_service.KeyNotAllowed, match="log in again"):
        security_service.register_device_key(OWNER.id, second, token_age_seconds=3600)

    security_service.register_device_key(OWNER.id, second, token_age_seconds=30)
    security_service.register_device_key(OWNER.id, second, token_age_seconds=3600)  # same key: fine


@pytest.mark.parametrize("bad", ["not-base64!!", base64.b64encode(b"junk" * 20).decode()])
def test_garbage_keys_are_refused(bad):
    with pytest.raises(security_service.KeyNotAllowed):
        security_service.register_device_key(OWNER.id, bad, token_age_seconds=10)


def test_rsa_key_is_refused():
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    public = base64.b64encode(key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )).decode()
    with pytest.raises(security_service.KeyNotAllowed, match="not supported"):
        security_service.register_device_key(OWNER.id, public, token_age_seconds=10)
