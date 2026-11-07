import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.services import address_service, contacts


@pytest.fixture(autouse=True)
def _no_app_pin_by_default(monkeypatch):
    # The PayGuard PIN has its own tests (test_app_pin.py); elsewhere it is off.
    monkeypatch.setattr(settings, "require_app_pin", False)


@pytest.fixture(autouse=True)
def side_db(monkeypatch):
    """
    Saved contacts and delivery addresses never touch the real database in tests.
    A test that needs them in its own fake database patches them again.
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(contacts, "SessionLocal", Session)
    monkeypatch.setattr(address_service, "SessionLocal", Session)
    return Session


HOME = {"full_name": "Anna Buyer", "line1": "12 Gandhi Road", "city": "Chennai", "state": "Tamil Nadu",
        "postal_code": "600001", "country_code": "IN"}
