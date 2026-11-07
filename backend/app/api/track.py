"""
Track: one place for payment history, autopays, shop orders and deliveries,
plus autopay set-up and paying a friend from your own PayPal.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agents import chat_flow
from app.core.config import settings
from app.core.security import get_current_user
from app.models.user import User
from app.services import (
    autopay_service, friend_pay_service, payout_service, pin_service, security_service, shop_service,
    track_service,
)

router = APIRouter(prefix="/api", tags=["Track"])


@router.get("/track")
async def track(current_user: User = Depends(get_current_user)):
    await autopay_service.refresh_open(current_user.id)
    autopay_service.make_reminders(current_user.id)
    if chat_flow.is_merchant_admin(current_user):
        await payout_service.refresh_open_payouts(current_user.id)

    orders = shop_service.list_orders(current_user.id, 20)
    return {
        "payments": track_service.payment_history(current_user, orders),
        "autopays": autopay_service.list_autopays(current_user.id),
        "orders": orders,
        "deliveries": track_service.deliveries(orders),
        "billers": [
            {"key": key, "name": b["name"], "amount": f"{b['amount']:.2f}",
             "every": autopay_service.INTERVALS[b["interval"]]}
            for key, b in autopay_service.BILLERS.items()
        ],
    }


# ---------- autopay ----------

class StartAutopay(BaseModel):
    biller: str = Field(min_length=2, max_length=20)


class AutopayReturn(BaseModel):
    subscription_id: str = Field(min_length=5, max_length=40)


class ManualAutopay(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    amount: Decimal = Field(gt=0, le=Decimal("10000"), decimal_places=2)
    interval: str = Field(min_length=3, max_length=5)
    next_date: str = Field(min_length=10, max_length=10)


def _fail(error: Exception):
    raise HTTPException(status_code=400, detail=str(error))


@router.post("/autopay/start")
async def start_autopay(data: StartAutopay, current_user: User = Depends(get_current_user)):
    try:
        return await autopay_service.start_paypal_autopay(current_user.id, data.biller)
    except autopay_service.AutopayError as error:
        _fail(error)


@router.post("/autopay/return")
async def autopay_return(data: AutopayReturn, current_user: User = Depends(get_current_user)):
    """PayPal sent the person back. The status is read from PayPal, never from the link."""
    try:
        return await autopay_service.refresh_by_subscription(current_user.id, data.subscription_id)
    except autopay_service.AutopayError as error:
        _fail(error)


@router.post("/autopay/manual")
def add_manual_autopay(data: ManualAutopay, current_user: User = Depends(get_current_user)):
    try:
        return autopay_service.add_manual(current_user.id, data.name, data.amount, data.interval, data.next_date)
    except autopay_service.AutopayError as error:
        _fail(error)


class AutopayChange(BaseModel):
    pin: str | None = Field(default=None, max_length=6)
    # /api/security/challenge, signed by the phone after the fingerprint.
    challenge: str | None = Field(default=None, max_length=64)
    signature: str | None = Field(default=None, max_length=200)


@router.post("/autopay/{autopay_id}/{what}")
async def change_autopay(
    autopay_id: int, what: str, data: AutopayChange | None = None,
    current_user: User = Depends(get_current_user),
):
    if what not in ("cancel", "pause", "resume", "refresh"):
        raise HTTPException(status_code=404, detail="Not found.")
    try:
        if what == "refresh":
            return await autopay_service.refresh(current_user.id, autopay_id)
        # Resume restarts charges; cancel / pause change money too: PayGuard PIN first.
        if settings.require_app_pin:
            checked = pin_service.check_pin(current_user.id, data.pin if data else None)
            if not checked.ok:
                raise HTTPException(status_code=403, detail=checked.message)
        if settings.require_device_signature and not security_service.verify_challenge(
            current_user.id, data.challenge if data else None, data.signature if data else None, "action",
        ):
            raise HTTPException(status_code=403, detail="Your fingerprint check did not match this phone. Nothing was changed.")
        return await autopay_service.change(current_user.id, autopay_id, what)
    except autopay_service.AutopayError as error:
        _fail(error)


# ---------- pay a friend from your own PayPal ----------

class FriendPay(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    amount: Decimal = Field(gt=0, le=friend_pay_service.MAX_AMOUNT, decimal_places=2)


class FriendPayDone(BaseModel):
    order_id: str = Field(min_length=5, max_length=50)


@router.post("/pay/start")
async def pay_start(data: FriendPay, current_user: User = Depends(get_current_user)):
    try:
        return await friend_pay_service.start(current_user, data.email, data.amount)
    except friend_pay_service.FriendPayError as error:
        _fail(error)


@router.post("/pay/complete")
async def pay_complete(data: FriendPayDone, current_user: User = Depends(get_current_user)):
    try:
        return await friend_pay_service.complete(current_user.id, data.order_id)
    except friend_pay_service.FriendPayError as error:
        _fail(error)


@router.get("/pay/contacts")
def pay_contacts(current_user: User = Depends(get_current_user)):
    from app.services import contacts

    me = current_user.email.strip().lower()
    return {
        "contacts": contacts.all_for(current_user.id, me),
        "max_payment": f"{friend_pay_service.MAX_AMOUNT:.2f}",
    }


class NewContact(BaseModel):
    name: str = Field(default="", max_length=100)
    email: str = Field(min_length=3, max_length=255)


@router.post("/contacts/save")
def save_contact(data: NewContact, current_user: User = Depends(get_current_user)):
    """Someone picked from the phone's contact book, or a PayPal email typed in."""
    from app.services import contacts

    try:
        email = contacts.clean_email(data.email)
    except contacts.ContactError as error:
        _fail(error)
    if email == current_user.email.strip().lower():
        raise HTTPException(status_code=400, detail="You can't send money to yourself.")
    try:
        return contacts.save(current_user.id, data.name, email)
    except contacts.ContactError as error:
        _fail(error)
