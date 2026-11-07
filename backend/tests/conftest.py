import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _no_app_pin_by_default(monkeypatch):
    # The PayGuard PIN has its own tests (test_app_pin.py); elsewhere it is off.
    monkeypatch.setattr(settings, "require_app_pin", False)
