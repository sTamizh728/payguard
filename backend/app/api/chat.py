from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.agents import chat_flow
from app.core.security import get_current_user
from app.models.user import User
from app.services import contacts, payout_service, refund_service

router = APIRouter(prefix="/api", tags=["Assistant"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class ConfirmRequest(BaseModel):
    action_id: str = Field(min_length=10, max_length=64)
    # Base64 signature from the phone's fingerprint/PIN key.
    signature: str | None = Field(default=None, max_length=200)
    # The person's own PayGuard PIN.
    pin: str | None = Field(default=None, max_length=6)


class PayoutRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    amount: Decimal = Field(gt=0, le=Decimal("100.00"), decimal_places=2)


class ChatResponse(BaseModel):
    reply: str
    pending_action: dict | None = None
    transactions: list[dict] = []
    event: str | None = None


async def understand(text: str, role: str) -> dict:
    # Imported here so the app still starts if the Gemini library is missing.
    from app.agents.intent import understand as gemini_understand

    # The Gemini SDK call blocks, so keep it off the event loop.
    return await run_in_threadpool(gemini_understand, text, role)


def _response(result: chat_flow.ChatReply) -> ChatResponse:
    return ChatResponse(
        reply=result.reply,
        pending_action=result.pending_action,
        transactions=result.transactions,
        event=result.event,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    result = await chat_flow.handle_message(current_user, data.message, understand)
    return _response(result)


@router.post("/chat/confirm", response_model=ChatResponse)
async def confirm(
    data: ConfirmRequest,
    current_user: User = Depends(get_current_user),
):
    result = await chat_flow.confirm(current_user, data.action_id, data.signature, data.pin)
    return _response(result)


@router.post("/chat/cancel", response_model=ChatResponse)
def cancel(current_user: User = Depends(get_current_user)):
    return _response(chat_flow.cancel(current_user))


# ---------- Send screen ----------

def _owner(current_user: User) -> User:
    if not chat_flow.is_merchant_admin(current_user):
        raise HTTPException(status_code=403, detail=chat_flow.OWNER_ONLY)
    return current_user


@router.get("/contacts")
def list_contacts(current_user: User = Depends(get_current_user)):
    _owner(current_user)
    me = current_user.email.strip().lower()
    return {
        # Never offer to send money to yourself.
        "contacts": contacts.all_for(current_user.id, me),
        "left_today": f"{payout_service.left_today(current_user.id):.2f}",
        "max_payment": f"{payout_service.MAX_PAYOUT:.2f}",
    }


@router.post("/payouts/prepare", response_model=ChatResponse)
async def prepare_payout(
    data: PayoutRequest,
    current_user: User = Depends(get_current_user),
):
    """Prepare a payment from the Send screen. It moves only after /chat/confirm."""
    result = await chat_flow.prepare_payout_from_form(current_user, data.email, data.amount)
    return _response(result)


# ---------- History screen ----------

def _iso(value):
    return value.isoformat() if value else None


@router.get("/history")
async def history(current_user: User = Depends(get_current_user)):
    if chat_flow.is_merchant_admin(current_user):
        await payout_service.refresh_open_payouts(current_user.id)
        sent = [
            chat_flow._payout_public(p)
            for p in payout_service.list_payouts(current_user.id, limit=20)
        ]
        received = [
            chat_flow._public(t) for t in refund_service.list_transactions(20)
        ]
        requests = [
            {
                "number": r["number"],
                "customer": r["customer"],
                "reason": r["reason"],
                "payment": r["payment"]["number"],
                "amount": f"{r['payment']['refundable']:.2f}",
            }
            for r in refund_service.list_open_requests(20)
        ]
        return {"role": "owner", "sent": sent, "received": received, "requests": requests}

    if not refund_service.can_see_purchases(current_user):
        return {"role": "customer", "purchases": [], "message": chat_flow.PAYPAL_LOGIN_NEEDED}

    purchases = []
    for p in refund_service.list_purchases(current_user, 20):
        item = chat_flow._public(p)
        item["request_status"] = p.get("request_status")
        purchases.append(item)
    return {"role": "customer", "purchases": purchases}
