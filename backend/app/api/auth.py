import json
from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.agents.chat_flow import is_merchant_admin
from app.api.schemas import (
    MeResponse,
    PayPalExchangeRequest,
    PayPalFinishRequest,
    RefreshRequest,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)
from app.core.config import settings
from app.core.security import get_current_user
from app.models.user import User
from app.services import paypal_login_service
from app.services import auth_service
from app.services.auth_service import (
    authenticate_paypal_user,
    authenticate_user,
    create_access_token,
    issue_refresh_token,
    register_user,
    revoke_refresh_token,
    use_refresh_token,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def _login_tokens(user_id: int) -> TokenResponse:
    """A short access token plus a long-lasting login for this phone."""
    return TokenResponse(
        access_token=create_access_token(user_id),
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_token=issue_refresh_token(user_id),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(data: RefreshRequest):
    """A fresh access token for a phone that is still logged in."""
    found = auth_service.use_refresh_token_with_login_time(data.refresh_token)
    if found is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please log in again.")
    user_id, logged_in_at = found
    return TokenResponse(
        access_token=create_access_token(user_id, logged_in_at),
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout")
def logout(data: RefreshRequest):
    """Log this phone out for good: its long-lasting login stops working."""
    revoke_refresh_token(data.refresh_token)
    return {"logged_out": True}


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(data: UserRegister):

    try:
        user = register_user(
            email=str(data.email),
            password=data.password,
            full_name=data.full_name,
        )

        return user

    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        )


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin):

    user = authenticate_user(
        email=str(data.email),
        password=data.password,
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    return _login_tokens(user.id)

@router.get("/me", response_model=MeResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return MeResponse(
        **UserResponse.model_validate(current_user).model_dump(),
        is_owner=is_merchant_admin(current_user),
    )


@router.get("/paypal/start")
def paypal_login_start(app_nonce: str = Query(min_length=32, max_length=128)):
    """
    The app opens this in the phone browser. It sends the user
    on to PayPal's login page.
    """

    try:
        authorize_url = paypal_login_service.build_authorize_url(app_nonce)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid login request.",
        )

    return RedirectResponse(authorize_url, status_code=302)


def _back_to_app(**params: str) -> HTMLResponse:
    """
    A small page that opens the app again. Some browsers block a
    plain redirect to an app link, so it also shows a button.
    """

    app_url = f"{settings.app_auth_redirect_uri}?{urlencode(params)}"
    safe_url = escape(app_url, quote=True)

    if "code" in params:
        message = "Login complete. Returning to the app."
    else:
        message = "Login did not complete. Return to the app to try again."

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Accessible Commerce AI</title>
</head>
<body style="font-family: sans-serif; padding: 24px;">
<h1 style="font-size: 22px;">{escape(message)}</h1>
<p><a href="{safe_url}" style="font-size: 20px;">Open the app</a></p>
<script>window.location.replace({json.dumps(app_url)});</script>
</body>
</html>"""

    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("/paypal/callback", response_class=HTMLResponse)
async def paypal_login_callback(
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
):
    """PayPal sends the user here after they log in (the Return URL)."""

    if not state:
        return _back_to_app(error="missing_state")

    try:
        app_nonce_hash = paypal_login_service.consume_state(state)
    except ValueError:
        return _back_to_app(error="expired")

    if error or not code:
        return _back_to_app(error="cancelled")

    try:
        profile = await paypal_login_service.fetch_paypal_profile(code)
    except ValueError as error:
        print(f"[PayPal login] {error}")  # for the developer, no secrets
        return _back_to_app(error="no_email")
    except RuntimeError as error:
        print(f"[PayPal login] {error}")  # for the developer, no secrets
        return _back_to_app(error="paypal_unavailable")

    try:
        user = authenticate_paypal_user(
            paypal_user_id=profile["paypal_user_id"],
            email=profile["email"],
            full_name=profile["full_name"],
        )
    except ValueError:
        return _back_to_app(error="account_conflict")

    login_code = paypal_login_service.issue_login_code(user.id, app_nonce_hash)
    return _back_to_app(code=login_code)


@router.get("/paypal/login-url")
def paypal_login_url(app_nonce: str = Query(min_length=32, max_length=128)):
    """
    The app opens this PayPal address itself. PayPal then returns straight
    into the app, so the phone browser never opens our server.
    """
    try:
        url = paypal_login_service.build_authorize_url(
            app_nonce, redirect_uri=settings.paypal_app_redirect_uri
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid login request.")
    return {"url": url}


@router.post("/paypal/finish", response_model=TokenResponse)
async def paypal_login_finish(data: PayPalFinishRequest):
    """The app hands over PayPal's code, plus the secret nonce only it knows."""
    refused = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="PayPal login could not be completed. Please try again.",
    )
    try:
        app_nonce_hash = paypal_login_service.consume_state(data.state)
    except ValueError:
        raise refused
    if not paypal_login_service.nonce_matches(app_nonce_hash, data.app_nonce):
        raise refused

    try:
        profile = await paypal_login_service.fetch_paypal_profile(data.code)
    except ValueError as error:
        print(f"[PayPal login] {error}")
        raise HTTPException(status_code=400, detail="PayPal did not share your email address.")
    except RuntimeError as error:
        print(f"[PayPal login] {error}")
        raise HTTPException(status_code=502, detail="PayPal is not reachable right now. Please try again.")

    try:
        user = authenticate_paypal_user(
            paypal_user_id=profile["paypal_user_id"],
            email=profile["email"],
            full_name=profile["full_name"],
        )
    except ValueError:
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Log in with your email and password instead.",
        )

    return _login_tokens(user.id)


@router.post("/paypal/exchange", response_model=TokenResponse)
def paypal_login_exchange(data: PayPalExchangeRequest):
    """The app swaps its one-time login code for an access token."""

    try:
        user_id = paypal_login_service.redeem_login_code(
            data.code,
            data.app_nonce,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login code is invalid or expired.",
        )

    return _login_tokens(user_id)
