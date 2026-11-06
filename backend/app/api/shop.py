from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import get_current_user
from app.models.user import User
from app.services import catalog_service, shop_service

router = APIRouter(prefix="/api/shop", tags=["Shop"])


class CartRequest(BaseModel):
    product_id: int = Field(ge=1)
    quantity: int = Field(ge=0, le=shop_service.MAX_QUANTITY)  # 0 removes


class CompleteRequest(BaseModel):
    order_id: str = Field(min_length=5, max_length=50)


class ClaimRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)


def _cart_json(cart: dict) -> dict:
    return {
        "items": [
            {**i, "price": f"{i['price']:.2f}", "line_total": f"{i['line_total']:.2f}"}
            for i in cart["items"]
        ],
        "total": f"{cart['total']:.2f}",
    }


@router.get("/products")
def products(current_user: User = Depends(get_current_user)):
    """The phone menu's products, and whether phone ordering is switched on."""
    return {
        "products": [shop_service.public(p) for p in shop_service.PRODUCTS],
        # Phone ordering only works once a Twilio number is set up.
        "phone_orders": bool(settings.twilio_auth_token and settings.twilio_phone_number),
        "phone_number": settings.twilio_phone_number if settings.twilio_auth_token else None,
    }


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=60), current_user: User = Depends(get_current_user)):
    try:
        return {"results": [catalog_service.public(p) for p in await catalog_service.search(q)]}
    except catalog_service.CatalogError as error:
        raise HTTPException(status_code=502, detail=str(error))


@router.get("/products/{product_id}")
async def product(product_id: int, current_user: User = Depends(get_current_user)):
    try:
        return catalog_service.public(await catalog_service.get_product(product_id))
    except catalog_service.CatalogError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.get("/cart")
async def cart(current_user: User = Depends(get_current_user)):
    try:
        return _cart_json(await shop_service.get_cart(current_user.id))
    except shop_service.ShopError as error:
        raise HTTPException(status_code=502, detail=str(error))


@router.post("/cart")
async def set_cart(data: CartRequest, current_user: User = Depends(get_current_user)):
    try:
        await shop_service.set_cart_quantity(current_user.id, data.product_id, data.quantity)
        return _cart_json(await shop_service.get_cart(current_user.id))
    except shop_service.ShopError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/checkout")
async def checkout(current_user: User = Depends(get_current_user)):
    """No money moves here: the buyer pays in PayPal's own checkout."""
    try:
        order = await shop_service.checkout_cart(current_user.id)
    except shop_service.ShopError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"code": order["code"], "total": f"{order['total']:.2f}", "approval_url": order["approval_url"]}


@router.post("/complete")
async def complete(data: CompleteRequest, current_user: User = Depends(get_current_user)):
    """PayPal sent the buyer back into the app: collect the payment now."""
    if shop_service.order_owner(data.order_id) != current_user.id:
        raise HTTPException(status_code=404, detail="That order was not found.")
    try:
        return await shop_service.complete_checkout(data.order_id)
    except shop_service.ShopError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/orders")
def my_orders(current_user: User = Depends(get_current_user)):
    return {"orders": shop_service.list_orders(current_user.id)}


@router.get("/orders/{code}")
def order_receipt(code: str, current_user: User = Depends(get_current_user)):
    """The receipt: items, total, PayPal transaction and expected delivery."""
    found = shop_service.receipt(code, current_user.id)
    if found is None:
        raise HTTPException(status_code=404, detail="That order was not found.")
    return found


@router.post("/claim")
def claim(data: ClaimRequest, current_user: User = Depends(get_current_user)):
    """Open an order made by phone call, using the code read out on the call."""
    try:
        return shop_service.claim_phone_order(data.code, current_user.id)
    except shop_service.ShopError as error:
        raise HTTPException(status_code=400, detail=str(error))
