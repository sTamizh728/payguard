import time

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import bearer_scheme, get_current_user
from app.models.user import User
from app.services import payment_service, security_service

router = APIRouter(prefix="/api/security", tags=["Security"])


class DeviceKeyRequest(BaseModel):
    public_key: str = Field(min_length=40, max_length=400)


def _token_age_seconds(credentials: HTTPAuthorizationCredentials | None) -> float:
    """How long ago this login token was issued. get_current_user already checked it."""
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return time.time() - float(claims["iat"])
    except Exception:
        return float("inf")


@router.get("/status")
def security_status(current_user: User = Depends(get_current_user)):
    return {
        "has_device_key": security_service.has_device_key(current_user.id),
        "required": settings.require_device_signature,
    }


@router.post("/device-key")
def register_device_key(
    data: DeviceKeyRequest,
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    try:
        security_service.register_device_key(
            current_user.id,
            data.public_key,
            _token_age_seconds(credentials),
        )
    except security_service.KeyNotAllowed as error:
        raise HTTPException(status_code=409, detail=str(error))

    return {"has_device_key": True}


# ---------- PayPal balance, behind fingerprint / PIN ----------

class BalanceRequest(BaseModel):
    challenge: str = Field(min_length=10, max_length=64)
    signature: str | None = Field(default=None, max_length=200)


def _owner_only(user: User) -> None:
    from app.agents.chat_flow import OWNER_ONLY, is_merchant_admin

    if not is_merchant_admin(user):
        raise HTTPException(status_code=403, detail=OWNER_ONLY)


@router.get("/balance-challenge")
def balance_challenge(current_user: User = Depends(get_current_user)):
    """Step 1: a one-time code the phone signs after fingerprint / PIN."""
    _owner_only(current_user)
    return {"challenge": security_service.issue_challenge(current_user.id)}


@router.post("/balance")
async def balance(data: BalanceRequest, current_user: User = Depends(get_current_user)):
    """Step 2: show the PayPal wallet balance only for a valid signature."""
    _owner_only(current_user)

    signed = security_service.verify_challenge(current_user.id, data.challenge, data.signature)
    if settings.require_device_signature and not signed:
        raise HTTPException(
            status_code=403,
            detail="Your fingerprint or PIN check did not match this phone.",
        )

    try:
        balances = await payment_service.get_paypal_balances()
    except RuntimeError:
        raise HTTPException(status_code=502, detail="PayPal is not reachable right now.")

    return {"balances": balances}
