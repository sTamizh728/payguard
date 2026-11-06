import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import quote, urlencode

import httpx

from app.core.config import settings

LOGIN_SCOPES = "openid profile email"
STATE_TTL_SECONDS = 10 * 60      # time allowed to finish the PayPal login page
LOGIN_CODE_TTL_SECONDS = 2 * 60  # time allowed for the app to collect its token
APP_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")

# In-memory stores. Fine for a single backend process; they reset on restart.
# state -> (app_nonce_hash, expires_at)
_pending_states: dict[str, tuple[str, float]] = {}
# one-time login code -> (user_id, app_nonce_hash, expires_at)
_login_codes: dict[str, tuple[int, str, float]] = {}


def _hash_nonce(app_nonce: str) -> str:
    return hashlib.sha256(app_nonce.encode()).hexdigest()


def _drop_expired(store: dict, now: float) -> None:
    for key in [key for key, value in store.items() if value[-1] < now]:
        store.pop(key, None)


def is_valid_app_nonce(app_nonce: str) -> bool:
    return bool(APP_NONCE_PATTERN.fullmatch(app_nonce))


def build_authorize_url(app_nonce: str, redirect_uri: str | None = None) -> str:
    """
    Remember which app started this login and return the
    PayPal page where the user signs in.
    """

    if not is_valid_app_nonce(app_nonce):
        raise ValueError("Invalid app nonce.")

    now = time.time()
    _drop_expired(_pending_states, now)

    state = secrets.token_urlsafe(32)
    _pending_states[state] = (_hash_nonce(app_nonce), now + STATE_TTL_SECONDS)

    query = urlencode({
        "flowEntry": "static",
        "client_id": settings.paypal_client_id,
        "response_type": "code",
        "scope": LOGIN_SCOPES,
        "redirect_uri": redirect_uri or settings.paypal_login_redirect_uri,
        "state": state,
        "fullPage": "true",
    }, quote_via=quote)

    return f"{settings.paypal_web_base_url.rstrip('/')}/connect/?{query}"


def nonce_matches(app_nonce_hash: str, app_nonce: str) -> bool:
    return hmac.compare_digest(app_nonce_hash, _hash_nonce(app_nonce))


def consume_state(state: str) -> str:
    """Return the app nonce hash for a state. Each state works only once."""

    now = time.time()
    _drop_expired(_pending_states, now)

    entry = _pending_states.pop(state, None)

    if entry is None:
        raise ValueError("This login link has expired. Please try again.")

    return entry[0]


def issue_login_code(user_id: int, app_nonce_hash: str) -> str:
    now = time.time()
    _drop_expired(_login_codes, now)

    code = secrets.token_urlsafe(32)
    _login_codes[code] = (user_id, app_nonce_hash, now + LOGIN_CODE_TTL_SECONDS)
    return code


def redeem_login_code(code: str, app_nonce: str) -> int:
    """
    Swap a one-time login code for the user id.
    The app must send the same nonce it used to start the login,
    so a code stolen from a redirect is useless on another device.
    """

    now = time.time()
    _drop_expired(_login_codes, now)

    # Pop first: a code is burned even when the nonce is wrong.
    entry = _login_codes.pop(code, None)

    if entry is None:
        raise ValueError("Login code is invalid or expired.")

    user_id, app_nonce_hash, _ = entry

    if not hmac.compare_digest(app_nonce_hash, _hash_nonce(app_nonce)):
        raise ValueError("Login code is invalid or expired.")

    return user_id


def _extract_profile(data: dict) -> dict:
    paypal_user_id = data.get("user_id") or data.get("payer_id")

    email = data.get("email")
    emails = data.get("emails") or []

    if not email and emails:
        primary = next(
            (item for item in emails if item.get("primary")),
            emails[0],
        )
        email = primary.get("value")

    if not paypal_user_id:
        raise ValueError("PayPal did not return an account ID.")

    if not email:
        raise ValueError(
            "PayPal did not share an email address. "
            "Enable Email under Log in with PayPal in the developer dashboard."
        )

    return {
        "paypal_user_id": str(paypal_user_id),
        "email": email.strip().lower(),
        "full_name": data.get("name"),
    }


async def fetch_paypal_profile(code: str) -> dict:
    """
    Exchange the authorization code from PayPal for an access token,
    then read the user's PayPal profile.
    """

    base_url = settings.paypal_base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            token_response = await client.post(
                f"{base_url}/v1/oauth2/token",
                auth=(
                    settings.paypal_client_id,
                    settings.paypal_client_secret,
                ),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]

            profile_headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
            profile_response = await client.get(
                f"{base_url}/v1/identity/oauth2/userinfo",
                params={"schema": "paypalv1.1"},
                headers=profile_headers,
            )

            # Some accounts (seen with the app's own business account) get
            # 400 invalid_request here; PayPal's OpenID endpoint still works.
            if profile_response.status_code == 400:
                profile_response = await client.get(
                    f"{base_url}/v1/identity/openidconnect/userinfo",
                    params={"schema": "openid"},
                    headers=profile_headers,
                )

            profile_response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            # Do not expose tokens or raw API responses: only the step,
            # the status code and PayPal's short error name.
            step = "token" if exc.request.url.path.endswith("/token") else "userinfo"
            error_name = ""
            try:
                body = exc.response.json()
                error_name = str(body.get("error") or body.get("name") or "")[:60]
            except ValueError:
                pass
            raise RuntimeError(
                f"PayPal login failed at {step} (HTTP {exc.response.status_code}"
                f"{', ' + error_name if error_name else ''})."
            ) from None

        except httpx.RequestError:
            raise RuntimeError(
                "Could not reach PayPal. Check your internet connection."
            ) from None

        except (KeyError, ValueError):
            raise RuntimeError("PayPal returned an unexpected response.") from None

    return _extract_profile(profile_response.json())
