
from app.integrations.paypal_client import get_access_token
from app.services.payment_service import (
    capture_paypal_order,
    create_paypal_order,
    get_paypal_order,
)
from app.core.config import settings
from app.core.database import Base, engine
from app.models import app_pin, autopay, delivery_address, friend_payment, saved_contact, saved_paypal  # noqa: F401  (new tables: import before create_all)
from app.services.transaction_service import save_completed_capture
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.security import router as security_router
from app.api.webhooks import router as webhooks_router
from app.api.shop import router as shop_router
from app.api.phone import router as phone_router
from app.api.live import router as live_router
from app.api.track import router as track_router
from app.services import shop_service, webhook_service
from decimal import Decimal
from html import escape

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import text

app = FastAPI(
    title="Accessible Commerce AI",
    description="Voice-first AI shopping and secure payment assistant",
    version="0.1.0"
)
Base.metadata.create_all(bind=engine)

# create_all never changes an existing table, so add new columns here.
with engine.begin() as connection:
    connection.execute(text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS paypal_user_id VARCHAR(255)"
    ))
    connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_paypal_user_id "
        "ON users (paypal_user_id)"
    ))
    connection.execute(text(
        "ALTER TABLE payment_transactions "
        "ADD COLUMN IF NOT EXISTS payer_email VARCHAR(255)"
    ))
    connection.execute(text(
        "ALTER TABLE payment_transactions "
        "ADD COLUMN IF NOT EXISTS payer_id VARCHAR(50)"
    ))
    connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_payment_transactions_payer_email "
        "ON payment_transactions (payer_email)"
    ))
    for column in (
        "summary VARCHAR(300)", "items_json TEXT", "delivery_by VARCHAR(10)",
        "paid_at TIMESTAMP WITH TIME ZONE", "transaction_id VARCHAR(50)", "ship_to VARCHAR(400)",
    ):
        connection.execute(text(f"ALTER TABLE shop_orders ADD COLUMN IF NOT EXISTS {column}"))

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(security_router)
app.include_router(webhooks_router)
app.include_router(shop_router)
app.include_router(phone_router)
app.include_router(live_router)
app.include_router(track_router)

@app.get("/api/paypal/payment-success")
async def paypal_payment_success(token: str):
    """
    PayPal redirects the buyer here after checkout approval.
    The token query parameter contains the PayPal order ID.
    """
    try:
        await shop_service.complete_checkout(token)
        return _result_page(
            "Payment complete",
            "Thank you! Your PayPal payment is done. You can go back to PayGuard now.",
        )
    except shop_service.ShopError:
        return _result_page(
            "Payment not finished",
            "PayPal could not complete this payment. Nothing was charged twice. "
            "Please go back to PayGuard and try again.",
        )


@app.get("/api/paypal/payment-cancel")
async def paypal_payment_cancel():
    return _result_page("Payment cancelled", "No money was taken. You can go back to PayGuard.")


def _result_page(title: str, message: str) -> HTMLResponse:
    """A small page the phone browser shows after PayPal checkout."""
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title></head>
<body style="font-family:sans-serif;padding:24px;font-size:20px;line-height:1.5">
<h1 style="font-size:26px">{escape(title)}</h1><p>{escape(message)}</p></body></html>""",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/")
async def root():
    return {
        "message": "Welcome to Accessible Commerce AI Backend!",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "accessible-commerce-backend",
        "version": "0.1.0"
    }

@app.get("/api/paypal/connection-test")
async def paypal_connection_test():
    try:
        token_data = await get_access_token()

        return {
            "status": "connected",
            "environment": settings.paypal_env,
            "message": "PayPal OAuth authentication successful",
            "token_type": token_data.get("token_type"),
            "expires_in": token_data.get("expires_in"),
        }

    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )

@app.post("/api/paypal/create-order")
async def create_order(
    amount: Decimal = Query(
        default=Decimal("5.00"),
        ge=Decimal("1.00"),
        le=Decimal("100.00"),
        decimal_places=2,
    ),
):
    try:
        order = await create_paypal_order(
            amount=f"{amount:.2f}",
            currency="USD",
        )

        return order

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Unable to create PayPal Sandbox order.",
        )


@app.get("/api/paypal/order/{order_id}")
async def inspect_paypal_order(order_id: str):
    try:
        return await get_paypal_order(order_id)

    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )

