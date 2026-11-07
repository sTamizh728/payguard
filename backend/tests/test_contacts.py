"""People picked from the phone's contact book or typed in as a PayPal email."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import chat_flow
from app.api import track as track_api
from app.core.security import get_current_user
from app.services import contacts

ANNA = SimpleNamespace(id=1, email="anna@buyer.test", paypal_user_id="pp-anna")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(track_api.router)
    app.dependency_overrides[get_current_user] = lambda: ANNA
    return TestClient(app)


def test_save_and_list(client):
    r = client.post("/api/contacts/save", json={"name": "  Ravi   Kumar ", "email": "Ravi@Example.COM"})
    assert r.json() == {"name": "Ravi Kumar", "email": "ravi@example.com", "saved": True}
    people = client.get("/api/pay/contacts").json()["contacts"]
    assert [p["name"] for p in people][-1] == "Ravi Kumar"
    assert len(people) == 4  # 3 test accounts + Ravi


def test_typed_email_without_name_uses_the_email(client):
    assert client.post("/api/contacts/save", json={"email": "meena.s@example.com"}).json()["name"] == "meena.s"


def test_saving_twice_renames_not_duplicates(client):
    client.post("/api/contacts/save", json={"name": "Ravi", "email": "ravi@example.com"})
    client.post("/api/contacts/save", json={"name": "Ravi K", "email": "ravi@example.com"})
    assert [p["name"] for p in contacts.all_for(1) if p.get("saved")] == ["Ravi K"]


@pytest.mark.parametrize("email", ["not-an-email", "a@b", "anna@buyer.test"])
def test_bad_or_own_email_refused(client, email):
    assert client.post("/api/contacts/save", json={"name": "X", "email": email}).status_code == 400


def test_contacts_are_private():
    contacts.save(1, "Ravi", "ravi@example.com")
    assert contacts.find_by_email("ravi@example.com", 2) is None
    assert contacts.find_contacts("ravi", 2) == []
    assert contacts.find_contacts("ravi", 1)[0]["email"] == "ravi@example.com"


def test_voice_finds_a_saved_contact(monkeypatch):
    from app.services import friend_pay_service

    contacts.save(1, "Ravi Kumar", "ravi@example.com")
    made = []

    async def start(user, email, amount):
        made.append(email)
        return {"id": 1, "approval_url": "https://paypal.test/x"}

    monkeypatch.setattr(friend_pay_service, "start", start)
    chat_flow._sessions.clear()

    async def understand(t, role="customer"):
        return {"action": "send_money", "recipient_name": "Ravi", "amount": 5}

    r = asyncio.run(chat_flow.handle_message(ANNA, "send 5 dollars to Ravi", understand))
    assert made == ["ravi@example.com"] and r.pending_action["type"] == "checkout"
