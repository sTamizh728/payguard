"""
PayGuard chat: Gemini understands the owner, our code does everything else.

Layer 1: understand the request (Gemini) and find the payment (our code).
Layer 2: the owner confirms with the Confirm button (or says exactly 'yes, confirm').
Money moves only in confirm(), after every check is run again.
"""
import math
import secrets
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.agents import guardrails
from app.agents.guardrails import MAX_TEXT
from app.core.config import settings
from app.models.user import User
from app.services import contacts, payout_service, refund_service, scam_guard, security_service

MAX_STRIKES = 2             # unsafe requests before refunds are locked
LOCK_SECONDS = 10 * 60      # how long refunds stay locked
ACTION_TTL_SECONDS = 2 * 60  # time allowed to press Confirm
TAMIL_LATEST = ("கடைசி", "சமீப")  # "last", "recent"
DEFAULT_LIST = 5
MAX_LIST = 10

CANCELLED = "Okay, cancelled. No money was refunded."
# Tricks and out-of-place "yes, confirm" get this short reply - we don't explain the rules.
NOT_UNDERSTOOD = "I'm sorry, I don't understand you."
OWNER_ONLY = "Only the shop owner can view payments and make refunds."
PAYPAL_LOGIN_NEEDED = (
    "Please log in with PayPal to see your purchases and ask for refunds."
)
REQUEST_STATUS_TEXT = {
    "OPEN": "refund requested, waiting for the shop",
    "CHECKING": "refund being checked",
    "DECLINED": "refund request declined",
    "APPROVED": "refund approved",
}


@dataclass
class PendingRefund:
    id: str
    transaction_number: int
    amount: Decimal
    currency: str
    expires_at: float
    # Set when this refund answers a customer's refund request.
    request_number: int | None = None


@dataclass
class PendingPayout:
    id: str
    name: str
    email: str
    amount: Decimal
    expires_at: float
    # Scam guard: warning signs, and the earliest moment Confirm is accepted.
    warnings: list[str] = field(default_factory=list)
    not_before: float = 0.0


@dataclass
class ChatSession:
    strikes: int = 0          # unsafe requests seen (NOT cleared by cancel)
    locked_until: float = 0.0
    pending: PendingRefund | PendingPayout | None = None


@dataclass
class ChatReply:
    reply: str
    pending_action: dict | None = None
    transactions: list[dict] = field(default_factory=list)
    # What happened, so the app can play the right sound:
    # payment_sent, refund_done, request_sent, failed.
    event: str | None = None


_sessions: dict[int, ChatSession] = {}


def _session(user_id: int) -> ChatSession:
    return _sessions.setdefault(user_id, ChatSession())


def is_merchant_admin(user: User) -> bool:
    # Only a Log in with PayPal account counts: PayPal proved that email.
    # Anyone can type the owner's email at email/password sign-up.
    return (
        bool(getattr(user, "paypal_user_id", None))
        and user.email.strip().lower() in settings.merchant_admins
    )


def _money(amount: Decimal) -> str:
    return f"${amount:.2f}"


def _describe(transaction: dict) -> str:
    when = transaction["created_at"].strftime("%d %b")
    text = (
        f"Payment {transaction['number']}: {_money(transaction['amount'])} "
        f"{transaction['currency']} on {when}"
    )

    if transaction["refundable"] <= 0:
        return text + ", fully refunded."
    if transaction["refundable"] < transaction["amount"]:
        return text + f", {_money(transaction['refundable'])} left to refund."
    return text + "."


def _public(transaction: dict) -> dict:
    return {
        "number": transaction["number"],
        "amount": f"{transaction['amount']:.2f}",
        "currency": transaction["currency"],
        "refundable": f"{transaction['refundable']:.2f}",
        "status": transaction["status"],
        "created_at": transaction["created_at"].isoformat(),
    }


def _block(session: ChatSession) -> ChatReply:
    """An attempt to change the rules: cancel anything pending, count a strike."""
    session.pending = None
    session.strikes += 1

    if session.strikes >= MAX_STRIKES:
        session.locked_until = time.monotonic() + LOCK_SECONDS
        return ChatReply(
            "For your safety, refunds are locked for 10 minutes "
            "because of repeated unsafe requests. No money was refunded."
        )

    return ChatReply(NOT_UNDERSTOOD)


async def handle_message(user: User, text: str, understand) -> ChatReply:
    """
    One message from the owner. `understand` is the Gemini intent function,
    passed in so tests can fake it.
    """
    session = _session(user.id)
    text = guardrails.normalize(text).strip()

    if not text:
        return ChatReply("I didn't hear anything. Please say it again.")

    if len(text) > MAX_TEXT:
        session.pending = None
        return ChatReply("That's too long. Please say one short request.")

    if time.monotonic() < session.locked_until:
        minutes = math.ceil((session.locked_until - time.monotonic()) / 60)
        return ChatReply(
            f"Refunds are locked for {minutes} more minutes because of unsafe requests."
        )

    if guardrails.is_unsafe(text):
        return _block(session)

    if guardrails.words(text) & {"cancel", "stop"}:
        session.pending = None
        return ChatReply(CANCELLED)

    if guardrails.is_exact_confirm(text):
        if session.pending and settings.require_device_signature:
            # A spoken "yes" never moves money: the fingerprint / PIN does.
            return ChatReply(
                "Please tap Confirm and use your fingerprint or PIN.",
                pending_action=_pending_public(session.pending),
            )
        if session.pending:
            return await confirm(user, session.pending.id)
        return ChatReply(NOT_UNDERSTOOD)

    # Anything else starts a new request and drops an unconfirmed one.
    session.pending = None

    role = "owner" if is_merchant_admin(user) else "customer"

    if role == "customer" and not refund_service.can_see_purchases(user):
        return ChatReply(PAYPAL_LOGIN_NEEDED)

    try:
        intent = await understand(text, role)
    except Exception as error:
        print("[Gemini error]", type(error).__name__, str(error)[:200])  # for the developer
        if "429" in str(error) or "RESOURCE_EXHAUSTED" in str(error):
            return ChatReply("The AI service limit is reached right now. Please try again later.")
        return ChatReply("Sorry, I couldn't reach the AI service. Please try again.")

    action = intent.get("action")

    if action == "unsafe_request":   # the AI spotted a trick
        return _block(session)

    if action == "ask_user":
        return ChatReply(intent.get("message") or "Sorry, can you say that again?")

    if action == "multiple":
        return ChatReply("Please ask for one refund at a time.")

    if role == "customer":
        # Customer tools only. Owner actions are never run for a customer,
        # whatever the AI answers.
        if action == "show_my_purchases":
            return _show_purchases(user)
        if action == "request_refund":
            return _request_refund(user, intent, text)
        return ChatReply(
            "I can show your purchases and send a refund request to the shop owner."
        )

    if action == "send_money":
        return _prepare_payout_from_chat(user, session, intent, text)

    if action == "show_sent_payments":
        return await _show_sent(user, intent.get("only_failed") is True)

    if action == "show_transactions":
        return _show(intent, text)

    if action == "refund_payment":
        return _prepare_refund(session, intent, text)

    if action == "show_refund_requests":
        return _show_requests()

    if action == "approve_refund_request":
        return _approve_request(session, intent, text)

    if action == "decline_refund_request":
        return _decline_request(user, intent, text)

    return ChatReply("I can show your shop's payments, refund requests and make refunds.")


def _said_latest(text: str) -> bool:
    return bool(
        guardrails.words(text) & {"latest", "last", "recent", "newest"}
        or any(word in text for word in TAMIL_LATEST)
    )


def _said_int(value, text: str) -> int | None:
    """An integer the AI picked, kept only if the user really said it."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if guardrails.user_said_id(number, text) else None


# ---------- customer ----------

def _describe_purchase(purchase: dict) -> str:
    text = _describe(purchase)
    status = REQUEST_STATUS_TEXT.get(purchase.get("request_status"))
    if status and purchase["refundable"] > 0:
        text = text.rstrip(".") + f", {status}."
    return text


def _show_purchases(user: User) -> ChatReply:
    purchases = refund_service.list_purchases(user, DEFAULT_LIST)

    if not purchases:
        return ChatReply("I couldn't find any purchases from this shop for your PayPal account.")

    lines = " ".join(_describe_purchase(p) for p in purchases)
    return ChatReply(
        f"Here are your last {len(purchases)} purchases. {lines}",
        transactions=[_public(p) for p in purchases],
    )


def _request_refund(user: User, intent: dict, text: str) -> ChatReply:
    number = _said_int(intent.get("payment_number"), text)
    latest = intent.get("latest") is True and _said_latest(text)

    if number is None and not latest:
        return ChatReply(
            "Which purchase? Say its number from your purchases list, or say 'the latest'."
        )

    purchase = refund_service.find_purchase(user, number=number, latest=number is None)

    if purchase is None:
        if number is not None:
            return ChatReply(f"I couldn't find payment {number} in your purchases.")
        return ChatReply("I couldn't find any purchases from this shop for your PayPal account.")

    try:
        refund_service.create_refund_request(user, purchase["number"], reason=text)
    except refund_service.RefundNotAllowed as error:
        return ChatReply(str(error))

    return ChatReply(
        f"I sent your refund request for payment {purchase['number']} "
        f"({_money(purchase['refundable'])}) to the shop owner. "
        "You'll see the answer in your purchases.",
        transactions=[_public(purchase)],
        event="request_sent",
    )


# ---------- owner: customer requests ----------

def _show_requests() -> ChatReply:
    requests = refund_service.list_open_requests(DEFAULT_LIST)

    if not requests:
        return ChatReply("There are no open refund requests.")

    lines = " ".join(
        f"Request {r['number']}: {r['customer']} asks for "
        f"{_money(r['payment']['refundable'])} back on payment {r['payment']['number']}. "
        f"They said: \"{r['reason']}\"."
        for r in requests
    )
    return ChatReply(f"You have {len(requests)} open refund requests. {lines}")


def _approve_request(session: ChatSession, intent: dict, text: str) -> ChatReply:
    number = _said_int(intent.get("request_number"), text)

    if number is None:
        return ChatReply("Which request? Say its number, for example 'approve request 1'.")

    request = refund_service.get_open_request(number)

    if request is None:
        return ChatReply(f"There is no open refund request {number}.")

    payment = request["payment"]

    if payment["refundable"] <= 0:
        return ChatReply(f"Payment {payment['number']} is already fully refunded.")

    session.pending = PendingRefund(
        id=secrets.token_urlsafe(24),
        transaction_number=payment["number"],
        amount=payment["refundable"],
        currency=payment["currency"],
        expires_at=time.monotonic() + ACTION_TTL_SECONDS,
        request_number=number,
    )
    summary = (
        f"Approve request {number}: refund {_money(payment['refundable'])} "
        f"{payment['currency']} of payment {payment['number']}"
    )

    return ChatReply(
        f"{summary}? Tap Confirm, or say 'yes, confirm'. Say 'cancel' to stop.",
        pending_action={
            "id": session.pending.id,
            "type": "refund",
            "summary": summary,
            "expires_in": ACTION_TTL_SECONDS,
        },
        transactions=[_public(payment)],
    )


def _decline_request(user: User, intent: dict, text: str) -> ChatReply:
    number = _said_int(intent.get("request_number"), text)

    if number is None:
        return ChatReply("Which request? Say its number, for example 'decline request 1'.")

    if not refund_service.decide_request(number, "DECLINED", user.id):
        return ChatReply(f"There is no open refund request {number}.")

    return ChatReply(f"Request {number} is declined. No money was refunded.")


def _show(intent: dict, text: str) -> ChatReply:
    count = DEFAULT_LIST

    try:
        asked = int(intent.get("count"))
        if guardrails.user_said_number(asked, text):
            count = min(max(asked, 1), MAX_LIST)
    except (TypeError, ValueError):
        pass

    transactions = refund_service.list_transactions(count)

    if not transactions:
        return ChatReply("There are no payments yet.")

    lines = " ".join(_describe(t) for t in transactions)
    return ChatReply(
        f"Here are your last {len(transactions)} payments. {lines}",
        transactions=[_public(t) for t in transactions],
    )


def _prepare_refund(session: ChatSession, intent: dict, text: str) -> ChatReply:
    number = intent.get("payment_number")
    latest = intent.get("latest") is True

    # The payment must come from the owner's own words, never from the AI.
    if number is not None:
        try:
            number = int(number)
        except (TypeError, ValueError):
            number = None

    if number is not None and not guardrails.user_said_id(number, text):
        number = None

    if latest and not (
        guardrails.words(text) & {"latest", "last", "recent", "newest"}
        or any(word in text for word in TAMIL_LATEST)
    ):
        latest = False

    if number is None and not latest:
        return ChatReply(
            "Which payment? Say its number from your payment list, or say 'the latest'."
        )

    transaction = refund_service.find_transaction(number=number, latest=number is None)

    if transaction is None:
        if number is not None:
            return ChatReply(f"I couldn't find payment {number}.")
        return ChatReply("There are no payments yet.")

    refundable = transaction["refundable"]

    if refundable <= 0:
        return ChatReply(f"Payment {transaction['number']} is already fully refunded.")

    amount = refundable
    raw_amount = intent.get("amount")

    if raw_amount is not None:
        try:
            asked = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return ChatReply("How much would you like to refund?")

        said = guardrails.said_numbers(text)
        matches = [n for n in said if abs(n - float(asked)) < 0.005]

        # "refund payment 3" must not turn into a $3 refund: when the amount equals
        # the payment number, the owner has to say that number twice.
        if not matches or (number is not None and asked == number and len(matches) < 2):
            return ChatReply("How much would you like to refund?")

        if not asked.is_finite() or asked < Decimal("0.01"):
            return ChatReply("The refund amount must be more than zero.")

        if asked > refundable:
            return ChatReply(
                f"Only {_money(refundable)} of payment {transaction['number']} "
                "can still be refunded."
            )

        amount = asked

    session.pending = PendingRefund(
        id=secrets.token_urlsafe(24),
        transaction_number=transaction["number"],
        amount=amount,
        currency=transaction["currency"],
        expires_at=time.monotonic() + ACTION_TTL_SECONDS,
    )

    full = amount == transaction["amount"]
    summary = (
        f"Refund {_money(amount)} {transaction['currency']} "
        f"{'(the full amount) ' if full else ''}"
        f"of payment {transaction['number']}"
    )

    return ChatReply(
        f"{summary}? Tap Confirm, or say 'yes, confirm'. Say 'cancel' to stop.",
        pending_action={
            "id": session.pending.id,
            "type": "refund",
            "summary": summary,
            "expires_in": ACTION_TTL_SECONDS,
        },
        transactions=[_public(transaction)],
    )


# ---------- owner: send money (PayPal Payouts) ----------

PAYOUT_STATUS_TEXT = {
    "REQUESTED": "being sent",
    "UNKNOWN": "not confirmed by PayPal yet, check before trying again",
    "PENDING": "pending",
    "PROCESSING": "processing",
    "NEW": "pending",
    "SUCCESS": "received",
    "UNCLAIMED": "not claimed yet: the person has no PayPal account with that email",
    "ONHOLD": "on hold by PayPal",
    "FAILED": "failed",
    "DENIED": "denied by PayPal",
    "RETURNED": "returned to you",
    "BLOCKED": "blocked by PayPal",
    "REFUNDED": "refunded",
    "REVERSED": "reversed",
    "CANCELED": "cancelled",
}


def _prepare_payout_from_chat(user: User, session: ChatSession, intent: dict, text: str) -> ChatReply:
    if str(intent.get("currency") or "USD").upper() != "USD":
        return ChatReply("Right now I can only send US dollars.")

    try:
        amount = Decimal(str(intent.get("amount"))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return ChatReply("How much would you like to send?")

    # The amount and the name must be the owner's own words, never the AI's.
    if not amount.is_finite() or not guardrails.user_said_number(float(amount), text):
        return ChatReply("Sorry, how much would you like to send?")

    name = str(intent.get("recipient_name") or "").strip()
    said = guardrails.words(text)
    if len(name) < 2 or not all(w in said for w in guardrails.words(name)):
        return ChatReply("Who would you like to send money to?")

    matches = contacts.find_contacts(name)

    if not matches:
        return ChatReply(f"I couldn't find {name} in your contacts.")

    if len(matches) > 1:
        options = " or ".join(c["name"] for c in matches)
        return ChatReply(f"I found {len(matches)} people: {options}. Please say the full name.")

    return prepare_payout(user, session, matches[0], amount, text)


def prepare_payout(
    user: User,
    session: ChatSession,
    contact: dict,
    amount: Decimal,
    text: str | None = None,
) -> ChatReply:
    """Shared by the chat and the Send screen. No money moves here."""
    if contact["email"].lower() == user.email.strip().lower():
        return ChatReply("That's your own account. Please choose someone else.")

    try:
        payout_service.check_limits(user.id, amount)
    except payout_service.PayoutNotAllowed as error:
        return ChatReply(str(error))

    check = scam_guard.assess(user.id, contact["email"], amount, text)
    now = time.monotonic()

    session.pending = PendingPayout(
        id=secrets.token_urlsafe(24),
        name=contact["name"],
        email=contact["email"],
        amount=amount,
        # A risky payment gets extra time, so the wait never eats the window.
        expires_at=now + ACTION_TTL_SECONDS + check.wait_seconds,
        warnings=check.reasons if check.risky else [],
        not_before=now + check.wait_seconds,
    )
    summary = f"Send {_money(amount)} USD to {contact['name']}"

    if check.risky:
        reply = (
            f"Careful: this payment shows {len(check.reasons)} warning signs. "
            + " ".join(check.reasons)
            + f" If anyone is rushing you, stop. You can confirm in {check.wait_seconds} seconds, "
            "or say 'cancel'."
        )
    else:
        reply = f"{summary}? Confirm with your fingerprint or PIN, or say 'cancel'."

    return ChatReply(reply, pending_action=_pending_public(session.pending))


async def prepare_payout_from_form(user: User, email: str, amount: Decimal) -> ChatReply:
    """The Send screen: a contact picked from the list and a typed amount."""
    session = _session(user.id)
    session.pending = None

    if time.monotonic() < session.locked_until:
        return ChatReply("Payments are locked right now because of unsafe requests.")

    if not is_merchant_admin(user):
        return ChatReply(OWNER_ONLY)

    contact = contacts.find_by_email(email)
    if contact is None:
        return ChatReply("Please choose a person from your contacts.")

    return prepare_payout(user, session, contact, amount)


def _payout_public(payout: dict) -> dict:
    return {
        "number": payout["number"],
        "name": payout["name"],
        "amount": f"{payout['amount']:.2f}",
        "currency": payout["currency"],
        "status": payout["status"],
        "status_text": PAYOUT_STATUS_TEXT.get(payout["status"], payout["status"].lower()),
        "created_at": payout["created_at"].isoformat(),
    }


async def _show_sent(user: User, only_failed: bool) -> ChatReply:
    await payout_service.refresh_open_payouts(user.id)
    payouts = payout_service.list_payouts(user.id, only_failed=only_failed, limit=DEFAULT_LIST)

    if not payouts:
        if only_failed:
            return ChatReply("Good news: none of your payments failed.")
        return ChatReply("You haven't sent any money yet.")

    lines = " ".join(
        f"{_money(p['amount'])} to {p['name']} on {p['created_at'].strftime('%d %b')}: "
        f"{PAYOUT_STATUS_TEXT.get(p['status'], p['status'].lower())}."
        for p in payouts
    )
    title = "Payments that need attention" if only_failed else "Your last payments"
    return ChatReply(
        f"{title}. {lines}",
        transactions=[_payout_public(p) for p in payouts],
    )


async def _confirm_payout(user: User, pending: PendingPayout) -> ChatReply:
    try:
        result = await payout_service.send_payout(
            user_id=user.id,
            sender_batch_id=pending.id,
            name=pending.name,
            email=pending.email,
            amount=pending.amount,
        )
    except payout_service.PayoutNotAllowed as error:
        return ChatReply(f"{error} No money was sent.", event="failed")

    if result["outcome"] == "unknown":
        # A timeout does NOT mean it failed - never retry blindly.
        return ChatReply(
            "I couldn't confirm the payment with PayPal. Please check your "
            "history before trying again.",
            event="failed",
        )

    return ChatReply(
        f"Done. {_money(pending.amount)} sent to {pending.name}. "
        f"Reference: {result.get('payout_batch_id')}.",
        event="payment_sent",
    )


def _pending_public(pending: PendingRefund | PendingPayout) -> dict:
    if isinstance(pending, PendingPayout):
        kind, summary = "payout", f"Send {_money(pending.amount)} USD to {pending.name}"
    else:
        kind, summary = "refund", (
            f"Refund {_money(pending.amount)} {pending.currency} "
            f"of payment {pending.transaction_number}"
        )
    public = {
        "id": pending.id,
        "type": kind,
        "summary": summary,
        "expires_in": max(0, int(pending.expires_at - time.monotonic())),
    }
    if isinstance(pending, PendingPayout) and pending.warnings:
        public["warnings"] = pending.warnings
        public["wait_seconds"] = max(0, math.ceil(pending.not_before - time.monotonic()))
    return public


async def confirm(user: User, action_id: str, signature: str | None = None) -> ChatReply:
    """The owner pressed Confirm. Every check runs again before money moves."""
    session = _session(user.id)
    pending = session.pending

    # Single use: whatever happens next, this action is gone.
    if pending is None or not secrets.compare_digest(pending.id, action_id):
        return ChatReply("There is nothing to confirm. Please ask again.")

    # Scam guard cooling-off: too early does NOT use up the payment.
    if isinstance(pending, PendingPayout) and time.monotonic() < pending.not_before:
        seconds = math.ceil(pending.not_before - time.monotonic())
        return ChatReply(
            f"Please wait {seconds} more seconds before confirming. "
            "Take a moment: is this really someone you know?",
            pending_action=_pending_public(pending),
        )

    session.pending = None

    if settings.require_device_signature and not security_service.verify_confirmation(
        user.id, action_id, signature
    ):
        return ChatReply(
            "Your fingerprint or PIN check did not match this phone, so nothing "
            "was sent. Please ask again.",
            event="failed",
        )

    if time.monotonic() > pending.expires_at:
        return ChatReply("That request expired, so nothing was refunded. Please ask again.")

    if time.monotonic() < session.locked_until:
        return ChatReply("Refunds are locked right now. Nothing was refunded.")

    if not is_merchant_admin(user):
        return ChatReply(OWNER_ONLY)

    if isinstance(pending, PendingPayout):
        return await _confirm_payout(user, pending)

    if pending.request_number is not None and (
        refund_service.get_open_request(pending.request_number) is None
    ):
        return ChatReply(
            f"Request {pending.request_number} was already decided. Nothing was refunded."
        )

    try:
        result = await refund_service.refund_transaction(
            transaction_id=pending.transaction_number,
            amount=pending.amount,
            request_id=pending.id,
            user_id=user.id,
        )
    except refund_service.RefundNotAllowed as error:
        return ChatReply(f"{error} Nothing was refunded.", event="failed")

    if pending.request_number is not None:
        refund_service.decide_request(
            pending.request_number,
            "CHECKING" if result["outcome"] == "unknown" else "APPROVED",
            user.id,
        )

    amount = _money(pending.amount)

    if result["outcome"] == "done":
        return ChatReply(
            f"Done. {amount} refunded for payment {pending.transaction_number}. "
            f"Reference: {result.get('refund_id')}.",
            event="refund_done",
        )

    if result["outcome"] == "pending":
        return ChatReply(
            f"PayPal accepted the {amount} refund for payment "
            f"{pending.transaction_number}. It is still processing.",
            event="refund_done",
        )

    # A timeout does NOT mean it failed - never retry blindly.
    return ChatReply(
        "I couldn't confirm the refund with PayPal. Please check the payment "
        "history before trying again.",
        event="failed",
    )


def cancel(user: User) -> ChatReply:
    _session(user.id).pending = None
    return ChatReply(CANCELLED)
