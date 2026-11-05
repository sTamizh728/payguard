import json

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.chat_flow import is_merchant_admin
from app.core.security import get_current_user
from app.models.user import User
from app.services import webhook_service

router = APIRouter(tags=["Notifications"])


@router.post("/api/webhooks/paypal")
async def paypal_webhook(request: Request):
    """PayPal calls this. Nothing is trusted until PayPal confirms the signature."""
    body = await request.body()
    if len(body) > 200_000:
        raise HTTPException(status_code=413, detail="Too large.")

    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not JSON.")

    headers = {key.lower(): value for key, value in request.headers.items()}

    if not await webhook_service.verify(headers, event):
        # Unverified or not configured: ignore it, but don't tell an attacker why.
        raise HTTPException(status_code=401, detail="Not verified.")

    webhook_service.store(event)
    return {"ok": True}


@router.get("/api/notifications")
def notifications(after_id: int = 0, current_user: User = Depends(get_current_user)):
    return {
        "notifications": webhook_service.list_for(
            current_user.id, is_merchant_admin(current_user), after_id
        )
    }
