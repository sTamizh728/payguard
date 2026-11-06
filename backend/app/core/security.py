import jwt

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def user_from_token(token: str | None) -> User | None:
    """The active user a login token belongs to, or None."""
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        user_id = int(payload["sub"])

    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None

    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(
                User.id == user_id,
                User.is_active.is_(True),
            )
        )

        if user is None:
            return None

        db.expunge(user)
        return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:

    user = user_from_token(credentials.credentials if credentials else None)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
