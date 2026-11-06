"""PayPal balance: owner only, and only with a fresh fingerprint/PIN signature."""
import base64
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import security as security_api
from app.core.config import settings
from app.core.database import Base
from app.core.security import get_current_user
from app.models.user import User
from app.services import payment_service, security_service

OWNER = SimpleNamespace(id=1, email="owner@shop.test", paypal_user_id="pp-owner")
CUSTOMER = SimpleNamespace(id=2, email="buyer@shop.test", paypal_user_id="pp-buyer")


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(security_service, "SessionLocal", Session)
    monkeypatch.setattr(settings, "merchant_admin_emails", "owner@shop.test")
    monkeypatch.setattr(settings, "require_device_signature", True)
    with Session() as db:
        db.add(User(id=1, email="owner@shop.test", paypal_user_id="pp-owner"))
        db.add(User(id=2, email="buyer@shop.test", paypal_user_id="pp-buyer"))
        db.commit()
    security_service._challenges.clear()

    calls = []

    async def balances():
        calls.append(1)
        return [{"currency": "USD", "available": "4660.72", "total": "4660.72", "on_hold": "0.00"}]

    monkeypatch.setattr(payment_service, "get_paypal_balances", balances)

    private = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo,
    )).decode()
    security_service.register_device_key(OWNER.id, public, token_age_seconds=10)

    state = SimpleNamespace(user=OWNER, key=private, calls=calls)
    app = FastAPI()
    app.include_router(security_api.router)
    app.dependency_overrides[get_current_user] = lambda: state.user
    state.client = TestClient(app)
    return state


def sign(private, code):
    return base64.b64encode(private.sign(
        security_service.challenge_payload(code), ec.ECDSA(hashes.SHA256())
    )).decode()


def get_balance(world, code, signature):
    return world.client.post("/api/security/balance", json={"challenge": code, "signature": signature})


def new_code(world):
    response = world.client.get("/api/security/balance-challenge")
    assert response.status_code == 200
    return response.json()["challenge"]


def test_signed_request_shows_balance(world):
    code = new_code(world)

    response = get_balance(world, code, sign(world.key, code))

    assert response.status_code == 200
    assert response.json()["balances"][0]["available"] == "4660.72"


def test_no_signature_shows_nothing(world):
    code = new_code(world)
    response = get_balance(world, code, None)
    assert response.status_code == 403
    assert world.calls == []


def test_signature_from_another_phone_shows_nothing(world):
    code = new_code(world)
    thief = ec.generate_private_key(ec.SECP256R1())
    assert get_balance(world, code, sign(thief, code)).status_code == 403
    assert world.calls == []


def test_code_works_only_once(world):
    code = new_code(world)
    signature = sign(world.key, code)
    assert get_balance(world, code, signature).status_code == 200
    assert get_balance(world, code, signature).status_code == 403


def test_payment_confirmation_signature_cannot_be_reused_for_balance(world):
    """Signatures are bound to their purpose: a confirm signature is not a balance one."""
    code = new_code(world)
    other = base64.b64encode(world.key.sign(
        security_service.confirmation_payload(code), ec.ECDSA(hashes.SHA256())
    )).decode()
    assert get_balance(world, code, other).status_code == 403


def test_made_up_code(world):
    assert get_balance(world, "z" * 32, sign(world.key, "z" * 32)).status_code == 403


def test_expired_code(world, monkeypatch):
    code = new_code(world)
    real = security_service.time.time
    monkeypatch.setattr(security_service.time, "time", lambda: real() + 61)
    assert get_balance(world, code, sign(world.key, code)).status_code == 403


def test_customers_cannot_see_the_shop_balance(world):
    world.user = CUSTOMER
    assert world.client.get("/api/security/balance-challenge").status_code == 403
    assert get_balance(world, "z" * 32, None).status_code == 403
    assert world.calls == []


def test_code_issued_to_someone_else_is_refused(world):
    code = new_code(world)  # issued to OWNER
    security_service._challenges[code] = (CUSTOMER.id, security_service._challenges[code][1])
    assert get_balance(world, code, sign(world.key, code)).status_code == 403


def test_paypal_down(world, monkeypatch):
    async def broken():
        raise RuntimeError("PayPal balance failed (HTTP 500).")

    monkeypatch.setattr(payment_service, "get_paypal_balances", broken)
    code = new_code(world)
    response = get_balance(world, code, sign(world.key, code))
    assert response.status_code == 502
