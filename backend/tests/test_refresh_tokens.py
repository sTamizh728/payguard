"""Stay logged in until logout: long-lasting login keys (in-memory database)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import auth as auth_api
from app.core.database import Base
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import auth_service


@pytest.fixture
def world(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(auth_service, "SessionLocal", Session)
    with Session() as db:
        db.add(User(id=1, email="sam@buyer.test", paypal_user_id="pp-sam"))
        db.commit()
    app = FastAPI()
    app.include_router(auth_api.router)
    return Session, TestClient(app)


def test_refresh_gives_a_new_access_token(world):
    _, client = world
    token = auth_service.issue_refresh_token(1)

    response = client.post("/api/auth/refresh", json={"refresh_token": token})

    assert response.status_code == 200
    assert response.json()["access_token"] and response.json()["refresh_token"] is None


def test_only_a_hash_is_stored(world):
    Session, _ = world
    token = auth_service.issue_refresh_token(1)
    with Session() as db:
        stored = db.scalar(select(RefreshToken.token_hash))
    assert stored != token and len(stored) == 64


def test_logout_ends_the_login_for_good(world):
    _, client = world
    token = auth_service.issue_refresh_token(1)

    assert client.post("/api/auth/logout", json={"refresh_token": token}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_logout_on_one_phone_keeps_the_other(world):
    _, client = world
    phone_a = auth_service.issue_refresh_token(1)
    phone_b = auth_service.issue_refresh_token(1)
    client.post("/api/auth/logout", json={"refresh_token": phone_a})
    assert client.post("/api/auth/refresh", json={"refresh_token": phone_b}).status_code == 200


def test_made_up_token(world):
    _, client = world
    assert client.post("/api/auth/refresh", json={"refresh_token": "x" * 40}).status_code == 401


def test_deactivated_user_cannot_refresh(world):
    Session, client = world
    token = auth_service.issue_refresh_token(1)
    with Session() as db:
        db.get(User, 1).is_active = False
        db.commit()
    assert client.post("/api/auth/refresh", json={"refresh_token": token}).status_code == 401
