"""
The PayGuard PIN: a second secret, on top of the phone's fingerprint signature.
Wrong tries are counted in the database; 5 in a row lock the PIN for 15 minutes.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pwdlib import PasswordHash
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.app_pin import AppPin

MAX_TRIES = 5
LOCK_MINUTES = 15
# Changing the PIN without the old one needs a login from the last 5 minutes,
# so a stolen login token cannot quietly set a new PIN.
FRESH_LOGIN_SECONDS = 5 * 60

_hasher = PasswordHash.recommended()


class PinError(Exception):
    pass


@dataclass
class PinCheck:
    ok: bool
    message: str = ""
    locked: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite gives naive datetimes back; PostgreSQL gives aware ones.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def validate_new_pin(pin: str) -> None:
    if not (pin.isdigit() and 4 <= len(pin) <= 6):
        raise PinError("Your PayGuard PIN must be 4 to 6 digits.")
    if len(set(pin)) == 1:
        raise PinError("That PIN is too easy to guess. Please don't repeat one digit.")
    steps = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    if steps in ({1}, {-1}):
        raise PinError("That PIN is too easy to guess. Please don't use a run like 1234.")


def has_pin(user_id: int) -> bool:
    with SessionLocal() as db:
        return db.scalar(select(AppPin.id).where(AppPin.user_id == user_id)) is not None


def set_pin(user_id: int, new_pin: str, old_pin: str | None, token_age_seconds: float) -> None:
    validate_new_pin(new_pin)

    with SessionLocal() as db:
        row = db.scalar(select(AppPin).where(AppPin.user_id == user_id).with_for_update())

        if row is not None:
            if old_pin:
                if not _check_row(db, row, old_pin).ok:
                    db.commit()  # keep the wrong-try count
                    raise PinError("Your current PIN is not right, so the PIN was not changed.")
            elif token_age_seconds > FRESH_LOGIN_SECONDS:
                raise PinError(
                    "To change your PIN, type your current PIN, or log out and log in again first."
                )
            row.pin_hash = _hasher.hash(new_pin)
            row.failed_count = 0
            row.locked_until = None
            row.updated_at = _now()
        else:
            db.add(AppPin(user_id=user_id, pin_hash=_hasher.hash(new_pin)))

        db.commit()


def _check_row(db, row: AppPin, pin: str) -> PinCheck:
    locked_until = _aware(row.locked_until)
    if locked_until and locked_until > _now():
        minutes = max(1, round((locked_until - _now()).total_seconds() / 60))
        return PinCheck(False, f"Your PayGuard PIN is locked for {minutes} more minutes.", locked=True)

    if pin and pin.isdigit() and _hasher.verify(pin, row.pin_hash):
        row.failed_count = 0
        row.locked_until = None
        return PinCheck(True)

    row.failed_count += 1
    if row.failed_count >= MAX_TRIES:
        row.failed_count = 0
        row.locked_until = _now() + timedelta(minutes=LOCK_MINUTES)
        return PinCheck(
            False,
            f"Wrong PIN {MAX_TRIES} times. Your PayGuard PIN is locked for {LOCK_MINUTES} minutes.",
            locked=True,
        )

    left = MAX_TRIES - row.failed_count
    return PinCheck(False, f"That PIN is not right. {left} {'try' if left == 1 else 'tries'} left.")


def check_pin(user_id: int, pin: str | None) -> PinCheck:
    with SessionLocal() as db:
        row = db.scalar(select(AppPin).where(AppPin.user_id == user_id).with_for_update())
        if row is None:
            return PinCheck(False, "Please set up your PayGuard PIN first (Profile tab).")
        if not pin:
            return PinCheck(False, "Please type your PayGuard PIN.")
        result = _check_row(db, row, pin)
        db.commit()
        return result
