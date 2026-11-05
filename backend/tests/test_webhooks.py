"""PayPal webhooks: verified before trusted, stored once, shown to the right person."""
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import webhooks as webhooks_api
from app.core.config import settings
from app.core.database import Base
from app.models.notification import Notification
from app.models.payout import Payout
from app.models.user import User
from app.services import webhook_service


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(webhook_service, "SessionLocal", Session)
    monkeypatch.setattr(settings, "paypal_webhook_id", "WH-TEST")
    with Session() as db:
        db.add(User(id=1, email="owner@shop.test", paypal_user_id="pp-owner"))
        db.add(User(id=2, email="other@shop.test", paypal_user_id="pp-other"))
        db.add(Payout(sender_batch_id="s1", payout_batch_id="BATCH1", recipient_name="Priya Raj",
                      recipient_email="p@x.test", amount=Decimal("20"), currency="USD",
                      status="PENDING", requested_by=1))
        db.commit()
    return Session


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(webhooks_api.router)
    return TestClient(app)


HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert",
    "PAYPAL-TRANSMISSION-ID": "t-1",
    "PAYPAL-TRANSMISSION-SIG": "sig",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-05T10:00:00Z",
}


def payout_event(event_type="PAYMENT.PAYOUTS-ITEM.SUCCEEDED", event_id="WH-1"):
    return {
        "id": event_id,
        "event_type": event_type,
        "resource": {
            "payout_batch_id": "BATCH1",
            "payout_item": {"amount": {"value": "20.00", "currency": "USD"}},
        },
    }


def verified(monkeypatch, ok=True):
    seen = []

    async def fake_verify(headers, event):
        seen.append(headers)
        return ok

    monkeypatch.setattr(webhook_service, "verify", fake_verify)
    return seen


def notes(Session):
    with Session() as db:
        return db.scalars(select(Notification).order_by(Notification.id)).all()


def test_verified_payout_success_updates_status_and_alerts_the_sender(world, client, monkeypatch):
    seen = verified(monkeypatch)

    response = client.post("/api/webhooks/paypal", json=payout_event(), headers=HEADERS)

    assert response.status_code == 200
    assert seen[0]["paypal-transmission-id"] == "t-1"
    with world() as db:
        assert db.scalar(select(Payout.status)) == "SUCCESS"
    [note] = notes(world)
    assert note.user_id == 1
    assert note.text == "Your payment of $20.00 USD was received."


def test_failed_payout_alert(world, client, monkeypatch):
    verified(monkeypatch)
    client.post("/api/webhooks/paypal", json=payout_event("PAYMENT.PAYOUTS-ITEM.UNCLAIMED"), headers=HEADERS)

    [note] = notes(world)
    assert note.kind == "payment_failed"
    assert "unclaimed" in note.text


def test_unverified_event_is_ignored(world, client, monkeypatch):
    verified(monkeypatch, ok=False)

    response = client.post("/api/webhooks/paypal", json=payout_event(), headers=HEADERS)

    assert response.status_code == 401
    assert notes(world) == []
    with world() as db:
        assert db.scalar(select(Payout.status)) == "PENDING"


def test_same_event_twice_is_stored_once(world, client, monkeypatch):
    verified(monkeypatch)
    client.post("/api/webhooks/paypal", json=payout_event(), headers=HEADERS)
    client.post("/api/webhooks/paypal", json=payout_event(), headers=HEADERS)

    assert len(notes(world)) == 1


def test_money_received_goes_to_owners(world, client, monkeypatch):
    verified(monkeypatch)
    event = {"id": "WH-2", "event_type": "PAYMENT.CAPTURE.COMPLETED",
             "resource": {"amount": {"value": "12.50", "currency_code": "USD"}}}
    client.post("/api/webhooks/paypal", json=event, headers=HEADERS)

    assert webhook_service.list_for(1, is_owner=True)[0]["text"] == "You received $12.50 USD."
    assert webhook_service.list_for(2, is_owner=False) == []


def test_alerts_are_private(world, client, monkeypatch):
    verified(monkeypatch)
    client.post("/api/webhooks/paypal", json=payout_event(), headers=HEADERS)

    assert len(webhook_service.list_for(1, is_owner=False)) == 1
    assert webhook_service.list_for(2, is_owner=False) == []


def test_after_id_returns_only_new_alerts(world, client, monkeypatch):
    verified(monkeypatch)
    client.post("/api/webhooks/paypal", json=payout_event(event_id="A"), headers=HEADERS)
    first = webhook_service.list_for(1, is_owner=True)[0]["id"]
    client.post("/api/webhooks/paypal", json=payout_event("PAYMENT.PAYOUTS-ITEM.RETURNED", "B"), headers=HEADERS)

    newer = webhook_service.list_for(1, is_owner=True, after_id=first)
    assert [n["kind"] for n in newer] == ["payment_failed"]


def test_unknown_event_types_are_accepted_but_not_shown(world, client, monkeypatch):
    verified(monkeypatch)
    response = client.post("/api/webhooks/paypal", json={"id": "X", "event_type": "SOMETHING.NEW"}, headers=HEADERS)
    assert response.status_code == 200
    assert notes(world) == []


def test_bad_json(client):
    response = client.post("/api/webhooks/paypal", content=b"not json", headers=HEADERS)
    assert response.status_code == 400


def test_verify_refuses_without_webhook_id(monkeypatch):
    import asyncio
    monkeypatch.setattr(settings, "paypal_webhook_id", None)
    assert asyncio.run(webhook_service.verify({k.lower(): v for k, v in HEADERS.items()}, {})) is False


def test_verify_refuses_missing_headers(monkeypatch):
    import asyncio
    assert asyncio.run(webhook_service.verify({}, {})) is False


def test_notifications_need_login(client):
    assert client.get("/api/notifications").status_code == 401
