import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy.exc import IntegrityError
import jwt
from pwdlib import PasswordHash
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.refresh_token import RefreshToken
from app.models.user import User

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(
            minutes=settings.access_token_expire_minutes
        ),
    }

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def register_user(email: str, password: str, full_name: str) -> User:
    normalized_email = email.strip().lower()

    with SessionLocal() as db:
        existing_user = db.scalar(
            select(User).where(User.email == normalized_email)
        )

        if existing_user:
            raise ValueError("An account with this email already exists.")

        user = User(
            email=normalized_email,
            full_name=full_name.strip(),
            password_hash=hash_password(password),
        )

        db.add(user)

        try:
            db.commit()
            db.refresh(user)
            db.expunge(user)
            return user
        except Exception:
            db.rollback()
            raise


def authenticate_user(email: str, password: str) -> User | None:
    normalized_email = email.strip().lower()

    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == normalized_email)
        )

        if not user or not user.password_hash:
            return None

        if not verify_password(password, user.password_hash):
            return None

        if not user.is_active:
            return None

        db.expunge(user)
        return user



def authenticate_paypal_user(
    paypal_user_id: str,
    email: str,
    full_name: str | None,
) -> User:
    normalized_email = email.strip().lower()

    with SessionLocal() as db:
        # Check whether this PayPal account already exists.
        user = db.scalar(
            select(User).where(User.paypal_user_id == paypal_user_id)
        )

        if user:
            if not user.is_active:
                raise ValueError("This account is inactive.")

            db.expunge(user)
            return user

        # Never silently link PayPal to an existing password account.
        existing_user = db.scalar(
            select(User).where(User.email == normalized_email)
        )

        if existing_user:
            raise ValueError(
                "An account with this email already exists. "
                "Sign in with your email and password instead."
            )

        user = User(
            email=normalized_email,
            full_name=full_name,
            paypal_user_id=paypal_user_id,
            password_hash=None,
        )

        db.add(user)

        try:
            db.commit()
            db.refresh(user)
            db.expunge(user)
            return user
        except IntegrityError:
            db.rollback()
            raise ValueError(
                "This PayPal account could not be registered. Please try again."
            ) from None

# ---------- long-lasting login (until the person logs out) ----------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    with SessionLocal() as db:
        db.add(RefreshToken(user_id=user_id, token_hash=_hash_token(token)))
        db.commit()
    return token


def use_refresh_token(token: str) -> int | None:
    """The user id for a valid (not logged-out) token, or None."""
    with SessionLocal() as db:
        row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(token)))
        if row is None or row.revoked_at is not None:
            return None
        user = db.get(User, row.user_id)
        if user is None or not user.is_active:
            return None
        row.last_used_at = datetime.now(timezone.utc)
        db.commit()
        return row.user_id


def revoke_refresh_token(token: str) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _hash_token(token)))
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            db.commit()
