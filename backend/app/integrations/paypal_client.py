
import httpx

from app.core.config import settings


async def get_access_token() -> dict:
    """
    Authenticate our application with PayPal and retrieve
    a Sandbox OAuth access token.
    """

    url = f"{settings.paypal_base_url.rstrip('/')}/v1/oauth2/token"

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.post(
                url,
                auth=(
                    settings.paypal_client_id,
                    settings.paypal_client_secret,
                ),
                data={"grant_type": "client_credentials"},
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "en_US",
                },
            )

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as exc:
            # Do not expose credentials, tokens, or raw API responses.
            raise RuntimeError(
                f"PayPal authentication failed (HTTP {exc.response.status_code}). "
                "Check your Sandbox credentials and developer app settings."
            ) from None

        except httpx.RequestError:
            raise RuntimeError(
                "Could not reach PayPal. Check your internet connection."
            ) from None
