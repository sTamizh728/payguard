import base64
import binascii
import secrets
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.device_key import DeviceKey

# A fresh login is needed to replace an existing phone key, so a stolen
# login token cannot quietly swap in the thief's own key.
REPLACE_KEY_MAX_TOKEN_AGE_SECONDS = 5 * 60


class KeyNotAllowed(Exception):
    pass


def confirmation_payload(action_id: str) -> bytes:
    """Exactly what the phone signs for one Confirm. Never reused: action ids are random."""
    return f"payguard-confirm:{action_id}".encode()


def _load_public_key(public_key_b64: str):
    try:
        key = load_der_public_key(base64.b64decode(public_key_b64, validate=True))
    except (ValueError, binascii.Error):
        raise KeyNotAllowed("That security key could not be read.") from None

    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        raise KeyNotAllowed("That security key is not supported.")

    return key


def has_device_key(user_id: int) -> bool:
    with SessionLocal() as db:
        return db.scalar(select(DeviceKey.id).where(DeviceKey.user_id == user_id)) is not None


def register_device_key(user_id: int, public_key_b64: str, token_age_seconds: float) -> None:
    _load_public_key(public_key_b64)

    with SessionLocal() as db:
        existing = db.scalar(
            select(DeviceKey).where(DeviceKey.user_id == user_id).with_for_update()
        )

        if existing is not None:
            if existing.public_key == public_key_b64:
                return
            if token_age_seconds > REPLACE_KEY_MAX_TOKEN_AGE_SECONDS:
                raise KeyNotAllowed(
                    "To set up security on a new phone, please log out and log in again first."
                )
            existing.public_key = public_key_b64
        else:
            db.add(DeviceKey(user_id=user_id, public_key=public_key_b64))

        db.commit()


def verify_confirmation(user_id: int, action_id: str, signature_b64: str | None) -> bool:
    return _verify(user_id, confirmation_payload(action_id), signature_b64)


# One-time codes for "show my balance": the phone signs one after fingerprint/PIN.
CHALLENGE_TTL_SECONDS = 60
_challenges: dict[str, tuple[int, float]] = {}  # code -> (user_id, expires_at)


def issue_challenge(user_id: int) -> str:
    now = time.time()
    for code in [c for c, (_, expires) in _challenges.items() if expires < now]:
        _challenges.pop(code, None)
    code = secrets.token_urlsafe(24)
    _challenges[code] = (user_id, now + CHALLENGE_TTL_SECONDS)
    return code


def challenge_payload(code: str) -> bytes:
    return f"payguard-balance:{code}".encode()


def verify_challenge(user_id: int, code: str, signature_b64: str | None) -> bool:
    """Single use: the code is gone after one try, right or wrong."""
    entry = _challenges.pop(code, None)
    if entry is None or entry[0] != user_id or entry[1] < time.time():
        return False
    return _verify(user_id, challenge_payload(code), signature_b64)


def _verify(user_id: int, payload: bytes, signature_b64: str | None) -> bool:
    if not signature_b64:
        return False

    with SessionLocal() as db:
        public_key_b64 = db.scalar(
            select(DeviceKey.public_key).where(DeviceKey.user_id == user_id)
        )

    if public_key_b64 is None:
        return False

    try:
        key = _load_public_key(public_key_b64)
        signature = base64.b64decode(signature_b64, validate=True)
        key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
        return True
    except (KeyNotAllowed, InvalidSignature, ValueError, binascii.Error):
        return False
