from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import get_current_user
from app.models.user import User
from app.services import shop_service

router = APIRouter(prefix="/api/shop", tags=["Shop"])


class OrderRequest(BaseModel):
    product_id: str = Field(min_length=1, max_length=30)
    quantity: int = Field(ge=1, le=shop_service.MAX_QUANTITY)


class ClaimRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@router.get("/products")
def products(current_user: User = Depends(get_current_user)):
    return {
        "products": [shop_service.public(p) for p in shop_service.PRODUCTS],
        # Phone ordering only works once a Twilio number is set up.
        "phone_orders": bool(settings.twilio_auth_token and settings.twilio_phone_number),
        "phone_number": settings.twilio_phone_number if settings.twilio_auth_token else None,
    }


@router.post("/orders")
async def create_order(data: OrderRequest, current_user: User = Depends(get_current_user)):
    """No money moves here: the buyer pays in PayPal's own checkout."""
    try:
        order = await shop_service.create_order(
            data.product_id, data.quantity, channel="app", user_id=current_user.id
        )
    except shop_service.ShopError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"code": order["code"], "total": f"{order['total']:.2f}", "approval_url": order["approval_url"]}


@router.get("/orders")
def my_orders(current_user: User = Depends(get_current_user)):
    return {"orders": shop_service.list_orders(current_user.id)}


@router.post("/claim")
def claim(data: ClaimRequest, current_user: User = Depends(get_current_user)):
    """Open an order made by phone call, using the code read out on the call."""
    try:
        return shop_service.claim_phone_order(data.code, current_user.id)
    except shop_service.ShopError as error:
        raise HTTPException(status_code=400, detail=str(error))
