
from app.core.config import settings
from app.core.database import Base, engine
from app.models import app_pin, autopay, delivery_address, friend_payment, saved_contact, saved_paypal  # noqa: F401  (new tables: import before create_all)
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.security import router as security_router
from app.api.webhooks import router as webhooks_router
from app.api.shop import router as shop_router
from app.api.phone import router as phone_router
from app.api.live import router as live_router
from app.api.track import router as track_router

from fastapi import FastAPI
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
