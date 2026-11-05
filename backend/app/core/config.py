from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    paypal_client_id: str
    paypal_client_secret: str
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Log in with PayPal
    paypal_web_base_url: str = "https://www.sandbox.paypal.com"
    # Must match the Return URL saved in the PayPal developer dashboard exactly.
    paypal_login_redirect_uri: str = (
        "https://dismantle-scheming-pasty.ngrok-free.dev/api/auth/paypal/callback"
    )
    # Deep link that sends the user back into the mobile app.
    app_auth_redirect_uri: str = "accessiblecommerce://auth"

    database_url: str
    transaction_history_api_key: str | None = None

    # Comma-separated emails allowed to see store payments and issue refunds.
    merchant_admin_emails: str = ""

    # Money moves only with a signature from the phone's fingerprint/PIN key.
    require_device_signature: bool = True

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
