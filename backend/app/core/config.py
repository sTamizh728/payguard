from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


PAYPAL_URLS = {
    "sandbox": ("https://api-m.sandbox.paypal.com", "https://www.sandbox.paypal.com"),
    "live": ("https://api-m.paypal.com", "https://www.paypal.com"),
}


class Settings(BaseSettings):
    # One switch for test money vs real money. Live also needs LIVE client
    # id/secret and PayPal's approval for Payouts and Log in with PayPal.
    paypal_env: Literal["sandbox", "live"] = "sandbox"
    paypal_client_id: str
    paypal_client_secret: str
    paypal_base_url: str | None = None
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Log in with PayPal
    paypal_web_base_url: str | None = None
    # Must match the Return URL saved in the PayPal developer dashboard exactly.
    paypal_login_redirect_uri: str = (
        "https://dismantle-scheming-pasty.ngrok-free.dev/api/auth/paypal/callback"
    )
    # Deep link that sends the user back into the mobile app.
    app_auth_redirect_uri: str = "accessiblecommerce://auth"
    # PayPal sends the login straight back into the app (no browser visit to
    # our server). Must also be a Return URL in the PayPal dashboard.
    paypal_app_redirect_uri: str = "accessiblecommerce://auth/paypal"
    # Where PayPal checkout returns: into the app as well.
    app_shop_return_uri: str = "accessiblecommerce://shop/paid"
    app_shop_cancel_uri: str = "accessiblecommerce://shop/cancel"

    database_url: str
    transaction_history_api_key: str | None = None

    # PayPal webhook ID (from creating the webhook); needed to verify events.
    paypal_webhook_id: str | None = None

    # Twilio phone-call shop. Without the auth token every call is refused.
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_phone_number: str | None = None

    @model_validator(mode="after")
    def paypal_addresses_match_env(self):
        api_url, web_url = PAYPAL_URLS[self.paypal_env]
        self.paypal_base_url = self.paypal_base_url or api_url
        self.paypal_web_base_url = self.paypal_web_base_url or web_url

        # Fail loudly instead of mixing real and test money.
        uses_sandbox = "sandbox" in self.paypal_base_url or "sandbox" in self.paypal_web_base_url
        if uses_sandbox != (self.paypal_env == "sandbox"):
            raise ValueError(
                f"PAYPAL_ENV is {self.paypal_env!r} but a PayPal address says otherwise. "
                "Remove PAYPAL_BASE_URL / PAYPAL_WEB_BASE_URL or make them match."
            )
        return self

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, value: str) -> str:
        # Railway (and most hosts) give postgres:// or postgresql://;
        # SQLAlchemy needs to be told to use the psycopg 3 driver.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    # Comma-separated emails allowed to see store payments and issue refunds.
    merchant_admin_emails: str = ""

    # Money moves only with a signature from the phone's fingerprint/PIN key.
    require_device_signature: bool = True

    # ...and with the person's own PayGuard PIN as well.
    require_app_pin: bool = True

    # PayPal sends people back into the app after approving an autopay or a payment.
    app_autopay_return_uri: str = "accessiblecommerce://autopay/done"
    app_autopay_cancel_uri: str = "accessiblecommerce://autopay/cancel"
    app_pay_return_uri: str = "accessiblecommerce://pay/done"
    app_pay_cancel_uri: str = "accessiblecommerce://pay/cancel"

    @property
    def public_base_url(self) -> str:
        """This server's public address, e.g. https://payguard-api-0msk.onrender.com."""
        return self.paypal_login_redirect_uri.split("/api/")[0].rstrip("/")

    @property
    def merchant_admins(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.merchant_admin_emails.split(",")
            if email.strip()
        }

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
