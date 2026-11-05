
from app.integrations.paypal_client import get_access_token
from app.services.payment_service import (
    capture_paypal_order,
    create_paypal_order,
    get_paypal_order,
)
from app.core.database import Base, engine
from app.services.transaction_service import save_completed_capture
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.security import router as security_router
from app.api.webhooks import router as webhooks_router
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query
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

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(security_router)
app.include_router(webhooks_router)

@app.get("/api/paypal/payment-success")
async def paypal_payment_success(token: str):
    """
    PayPal redirects the buyer here after checkout approval.
    The token query parameter contains the PayPal order ID.
    """
    try:
        result = await capture_paypal_order(token)

        if result["status"] != "COMPLETED":
            return {
                "payment": "not_completed",
                "order_id": result["order_id"],
                "paypal_status": result["status"],
                "captures": result["captures"],
            }

        # Record each completed capture so it shows in history and can be refunded.
        # Saving is idempotent, so reloading this page never creates duplicates.
        for capture in result["captures"]:
            if capture.get("status") == "COMPLETED":
                save_completed_capture(
                    result["order_id"],
                    capture,
                    payer_email=result.get("payer_email"),
                    payer_id=result.get("payer_id"),
                )

        return {
            "payment": "successful",
            "order_id": result["order_id"],
            "paypal_status": result["status"],
            "captures": result["captures"],
            "message": "PayPal payment captured successfully!",
        }

    except RuntimeError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )


@app.get("/api/paypal/payment-cancel")
async def paypal_payment_cancel():
    return {
        "payment": "cancelled",
        "message": "The buyer cancelled the PayPal checkout.",
    }

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
            "environment": "sandbox",
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

