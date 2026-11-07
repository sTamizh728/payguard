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
from app.services import (
    autopay_service, catalog_service, contacts, friend_pay_service, payout_service, pin_service,
    refund_service, scam_guard, security_service, shop_service, track_service,
)

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
class PendingAutopay:
    id: str
    autopay_id: int
    number: int
    name: str
    change: str  # cancel / pause / resume
    expires_at: float


@dataclass
class PendingShopPay:
    """Pay the cart with the buyer's saved PayPal after the PIN + fingerprint."""
    id: str
    total: Decimal
    summary: str
    expires_at: float


@dataclass
class ChatSession:
    strikes: int = 0          # unsafe requests seen (NOT cleared by cancel)
    locked_until: float = 0.0
    pending: PendingRefund | PendingPayout | PendingAutopay | PendingShopPay | None = None
    # Asking the delivery address one question at a time (voice checkout).
    address_step: str | None = None
    address: dict = field(default_factory=dict)
    address_fix_one: bool = False
    # Shopping memory: product ids of the last search, and the product last described.
    last_results: list[int] = field(default_factory=list)
    current_product: int | None = None


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

    if guardrails.words(text) & {"cancel", "stop"} and not _about_autopay(text):
        session.pending = None
        if session.address_step:
            session.address_step = None
            return ChatReply("Okay, I stopped. Nothing was saved or paid.")
        return ChatReply(CANCELLED)

    # Answering one of the delivery-address questions: the person's own words are
    # the answer. The AI never fills in an address.
    if session.address_step:
        return await _address_answer(user, session, text)

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

    if action in SHOP_ACTIONS:
        return await _shop(user, session, action, intent, text)

    if action in TRACK_ACTIONS:
        return await _track(user, session, action, intent, text)

    if role == "customer":
        # Customer tools only. Owner actions are never run for a customer,
        # whatever the AI answers.
        # Purchases are matched by the PayPal-proven email: an email/password
        # sign-up could type anyone's email, so it never sees purchases.
        if action in ("show_my_purchases", "request_refund") and not refund_service.can_see_purchases(user):
            return ChatReply(PAYPAL_LOGIN_NEEDED)
        if action == "show_my_purchases":
            return _show_purchases(user)
        if action == "request_refund":
            return _request_refund(user, intent, text)
        if action == "send_money":
            return await _prepare_friend_pay(user, intent, text)
        return ChatReply(
            "I can help with your payments, autopays, shopping and refund requests."
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


# ---------- shop (anyone logged in; PayPal checkout is the payment check) ----------

SHOP_ACTIONS = {"search_products", "product_details", "add_to_cart", "remove_from_cart", "show_cart", "checkout_cart",
                "show_orders", "find_best_products"}
THIS_WORDS = {"it", "this", "that", "one"}


async def _find_best(user: User, query: str) -> ChatReply:
    """Top-rated products on the web, with store links. Nothing is ordered here."""
    from app.services import address_service, web_shop_service

    address = address_service.get(user.id)
    try:
        items = await web_shop_service.find_best(query, (address or {}).get("country_code") or "us")
    except web_shop_service.WebShopError as error:
        return ChatReply(str(error))
    if not items:
        return ChatReply(f"I found no well-rated products for {query}. Try other words.")
    lines = " ".join(web_shop_service.describe(i) for i in items[:3])
    return ChatReply(
        f"The best rated for {query}, from Google Shopping: {lines} "
        "Tap a link to open the store and buy there.",
        transactions=[{**i, "type": "web_product"} for i in items],
    )


def _stars(rating: float) -> str:
    return f"rated {rating:.1f} out of 5"


async def _shop(user: User, session: ChatSession, action: str, intent: dict, text: str) -> ChatReply:
    if action == "find_best_products":
        return await _find_best(user, str(intent.get("query") or "").strip() or text)
    try:
        if action == "search_products":
            query = str(intent.get("query") or "").strip()
            if not query:
                return ChatReply("What would you like to search for?")
            results = await catalog_service.search(query)
            session.last_results = [r["id"] for r in results]
            session.current_product = None
            if not results:
                return ChatReply(f"I found nothing for {query}. Try other words.")
            lines = " ".join(
                f"{n}: {r['title']}, ${r['price']:.2f}, {_stars(r['rating'])}."
                for n, r in enumerate(results[:5], start=1)
            )
            return ChatReply(
                f"I found {len(results)} products for {query}. {lines} "
                "Say a number to hear more, or add one to your cart.",
                transactions=[catalog_service.public(r) for r in results],
            )

        if action == "product_details":
            product_id = _result_id(session, intent.get("result_number"), text)
            if product_id is None:
                return ChatReply("Which result? Say its number, for example 'tell me about number 2'.")
            p = await catalog_service.get_product(product_id)
            session.current_product = product_id
            reviews = " ".join(
                f"{r['name']} gave {r['rating']} stars: {r['comment']}" for r in p["reviews"][:3]
            ) or "No reviews yet."
            first_sentence = p["description"].split(". ")[0].rstrip(".")
            return ChatReply(
                f"{p['title']}, ${p['price']:.2f}, {_stars(p['rating'])}. {first_sentence}. "
                f"{p['stock']} in stock. {p['shipping'] or ''}. Reviews: {reviews} "
                "Say 'add it to my cart' to buy.",
                transactions=[catalog_service.public(p)],
            )

        if action == "add_to_cart":
            product_id = _result_id(session, intent.get("result_number"), text)
            if product_id is None and session.current_product and guardrails.words(text) & THIS_WORDS:
                product_id = session.current_product
            if product_id is None:
                return ChatReply("Which product? Say its number from the search results.")
            quantity = 1
            if intent.get("quantity") is not None:
                quantity = _said_int(intent.get("quantity"), text) or 0
                if quantity < 1:
                    return ChatReply("How many would you like?")
            cart = await shop_service.get_cart(user.id)
            already = next((i["quantity"] for i in cart["items"] if i["product_id"] == product_id), 0)
            await shop_service.set_cart_quantity(user.id, product_id, already + quantity)
            p = await catalog_service.get_product(product_id)
            return await _cart_reply(user, f"Added {quantity} {p['title']} to your cart.")

        if action == "remove_from_cart":
            cart = await shop_service.get_cart(user.id)
            number = _said_int(intent.get("item_number"), text)
            if number is None or not 1 <= number <= len(cart["items"]):
                return ChatReply("Which item? Say its number in your cart.")
            item = cart["items"][number - 1]
            await shop_service.set_cart_quantity(user.id, item["product_id"], 0)
            return await _cart_reply(user, f"Removed {item['title']}.")

        if action == "show_cart":
            return await _cart_reply(user, "")

        if action == "show_orders":
            orders = shop_service.list_orders(user.id, limit=3)
            if not orders:
                return ChatReply("You have no shop orders yet.")
            lines = " ".join(
                f"Order {o['code']}: {o['name']}, ${o['total']}, "
                + (f"paid, expected delivery by {shop_service.delivery_words(o['delivery_by'])}."
                   if o["status"] == "PAID" else "waiting for payment.")
                for o in orders
            )
            return ChatReply(f"Your latest orders. {lines}")

        # checkout_cart
        return await start_checkout(user, session)

    except (shop_service.ShopError, catalog_service.CatalogError) as error:
        return ChatReply(str(error), event="failed")


def _result_id(session: ChatSession, value, text: str) -> int | None:
    number = _said_int(value, text)
    if number is None or not 1 <= number <= len(session.last_results):
        return None
    return session.last_results[number - 1]


async def _cart_reply(user: User, prefix: str) -> ChatReply:
    cart = await shop_service.get_cart(user.id)
    if not cart["items"]:
        return ChatReply((prefix + " Your cart is empty.").strip())
    lines = " ".join(
        f"{n}: {i['quantity']} x {i['title']}, ${i['line_total']:.2f}."
        for n, i in enumerate(cart["items"], start=1)
    )
    return ChatReply(
        f"{prefix} Your cart: {lines} Total ${cart['total']:.2f}. Say 'checkout' to pay with PayPal.".strip()
    )


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


def _recipient_and_amount(intent: dict, text: str, user_id: int) -> tuple[dict, Decimal] | ChatReply:
    """The person and amount, from the user's own words only."""
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

    matches = contacts.find_contacts(name, user_id)

    if not matches:
        return ChatReply(f"I couldn't find {name} in your contacts.")

    if len(matches) > 1:
        options = " or ".join(c["name"] for c in matches)
        return ChatReply(f"I found {len(matches)} people: {options}. Please say the full name.")

    return matches[0], amount


def _prepare_payout_from_chat(user: User, session: ChatSession, intent: dict, text: str) -> ChatReply:
    found = _recipient_and_amount(intent, text, user.id)
    if isinstance(found, ChatReply):
        return found
    contact, amount = found
    return prepare_payout(user, session, contact, amount, text)


async def _prepare_friend_pay(user: User, intent: dict, text: str) -> ChatReply:
    """Send from the person's OWN PayPal: they approve it on PayPal's page."""
    found = _recipient_and_amount(intent, text, user.id)
    if isinstance(found, ChatReply):
        return found
    contact, amount = found
    try:
        payment = await friend_pay_service.start(user, contact["email"], amount)
    except friend_pay_service.FriendPayError as error:
        return ChatReply(str(error), event="failed")
    summary = f"Send {_money(amount)} USD to {contact['name']} from your PayPal"
    return ChatReply(
        f"{summary}? Tap Pay with PayPal and approve it in PayPal.",
        pending_action={"id": payment["id"], "type": "checkout", "kind": "friend",
                        "summary": summary, "url": payment["approval_url"]},
        event="confirm_needed",
    )


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

    contact = contacts.find_by_email(email, user.id)
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


def _pending_public(pending: PendingRefund | PendingPayout | PendingAutopay | PendingShopPay) -> dict:
    if isinstance(pending, PendingShopPay):
        kind, summary = "shop_pay", f"Pay ${pending.total:.2f} with your saved PayPal: {pending.summary}"
    elif isinstance(pending, PendingAutopay):
        kind, summary = "autopay", f"{pending.change.capitalize()} autopay {pending.number}: {pending.name}"
    elif isinstance(pending, PendingPayout):
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


async def confirm(
    user: User, action_id: str, signature: str | None = None, pin: str | None = None
) -> ChatReply:
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

    # PayGuard PIN. A wrong PIN keeps the request so the person can type it again;
    # too many wrong tries lock the PIN and drop the request.
    if settings.require_app_pin:
        checked = pin_service.check_pin(user.id, pin)
        if not checked.ok:
            if checked.locked:
                session.pending = None
                return ChatReply(f"{checked.message} Nothing was sent.", event="failed")
            return ChatReply(checked.message, pending_action=_pending_public(pending), event="failed")

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

    if isinstance(pending, PendingAutopay):
        return await _confirm_autopay(user, pending)

    if isinstance(pending, PendingShopPay):
        return await _confirm_shop_pay(user, pending)

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


# ---------- tracking: payment history and autopays (anyone logged in) ----------

TRACK_ACTIONS = {"show_payment_history", "show_autopays", "start_autopay", "change_autopay"}
AUTOPAY_WORDS = {"autopay", "autopays", "subscription", "subscriptions", "membership", "சந்தா"}
CHANGE_WORDS = {
    "cancel": {"cancel", "end", "stop", "ரத்து"},
    "pause": {"pause", "hold", "suspend"},
    "resume": {"resume", "restart", "unpause", "reactivate"},
}


def _about_autopay(text: str) -> bool:
    """'Cancel my StreamBox autopay' is a request, not 'cancel what is pending'."""
    return bool(guardrails.words(text) & AUTOPAY_WORDS) or autopay_service.find_biller(text) is not None


def _billers_text() -> str:
    return ", ".join(
        f"{b['name']} (${b['amount']:.2f} every {autopay_service.INTERVALS[b['interval']]})"
        for b in autopay_service.BILLERS.values()
    )


async def _track(user: User, session: ChatSession, action: str, intent: dict, text: str) -> ChatReply:
    if action == "show_payment_history":
        items = track_service.payment_history(user)[:DEFAULT_LIST]
        if not items:
            return ChatReply("You have no payments yet.")
        lines = " ".join(f"{i['title']}, {i['date'][:10]}: {i['status_text']}." for i in items)
        return ChatReply(f"Your latest payments. {lines}", transactions=items)

    if action == "show_autopays":
        items = autopay_service.list_autopays(user.id, include_ended=False)
        if not items:
            return ChatReply(
                "You have no autopays yet. You can set one up on the Track tab, "
                f"or say 'set up autopay for' one of: {_billers_text()}."
            )
        return ChatReply(" ".join(autopay_service.describe(i) for i in items), transactions=items)

    if action == "start_autopay":
        # The biller must come from the person's own words, not the AI's.
        key = autopay_service.find_biller(text)
        if key is None:
            return ChatReply(f"Which autopay would you like? I can set up: {_billers_text()}.")
        try:
            item = await autopay_service.start_paypal_autopay(user.id, key)
        except autopay_service.AutopayError as error:
            return ChatReply(str(error), event="failed")
        summary = f"Autopay: {item['name']}, ${item['amount']} every {item['every']}"
        return ChatReply(
            f"{summary}. Tap Approve in PayPal to start it. PayPal will charge it until you cancel.",
            pending_action={"id": str(item["id"]), "type": "checkout", "kind": "autopay",
                            "summary": summary, "url": item["approval_url"]},
            event="confirm_needed",
        )

    # change_autopay: which change, and which autopay, from the person's own words.
    said = guardrails.words(text)
    change = next((c for c, words in CHANGE_WORDS.items() if said & words), None)
    if change is None:
        return ChatReply("Would you like to cancel, pause or resume an autopay?")

    items = autopay_service.list_autopays(user.id, include_ended=False)
    chosen = None
    number = _said_int(intent.get("autopay_number"), text)
    if number is not None:
        chosen = next((i for i in items if i["number"] == number), None)
    else:
        key = autopay_service.find_biller(text)
        name = autopay_service.BILLERS[key]["name"] if key else None
        named = [i for i in items if name and i["name"] == name] or [
            i for i in items if i["source"] == "manual" and set(guardrails.words(i["name"])) & said - AUTOPAY_WORDS
        ]
        if len(named) == 1:
            chosen = named[0]
    if chosen is None:
        if not items:
            return ChatReply("You have no autopays to change.")
        return ChatReply("Which autopay? " + " ".join(autopay_service.describe(i) for i in items))

    session.pending = PendingAutopay(
        id=secrets.token_urlsafe(16), autopay_id=chosen["id"], number=chosen["number"],
        name=chosen["name"], change=change, expires_at=time.monotonic() + ACTION_TTL_SECONDS,
    )
    return ChatReply(
        f"{change.capitalize()} autopay {chosen['number']}: {chosen['name']} "
        f"(${chosen['amount']} every {chosen['every']})? Tap Confirm.",
        pending_action=_pending_public(session.pending),
        event="confirm_needed",
    )


async def _confirm_autopay(user: User, pending: PendingAutopay) -> ChatReply:
    try:
        item = await autopay_service.change(user.id, pending.autopay_id, pending.change)
    except autopay_service.AutopayError as error:
        return ChatReply(f"{error} Nothing was changed.", event="failed")
    done = {"cancel": "cancelled", "pause": "paused", "resume": "resumed"}[pending.change]
    return ChatReply(f"Done. Your {item['name']} autopay is {done}.", event="request_sent")


# ---------- checkout: delivery address by voice, then pay ----------

ADDRESS_STEPS = [
    ("full_name", "What is the full name for the delivery?"),
    ("line1", "What is the house number and street?"),
    ("line2", "Any area or landmark? Say skip if there is none."),
    ("city", "Which city?"),
    ("postal_code", "What is the PIN code or postal code? Say it digit by digit."),
    ("country_code", "Which country? For example India."),
    ("state", "Which state?"),
    ("phone", "A phone number for the delivery person? Say skip if you don't want to give one."),
]
ADDRESS_QUESTIONS = dict(ADDRESS_STEPS)
OPTIONAL_FIELDS = {"line2", "phone"}
SKIP_WORDS = {"skip", "none", "no", "nothing", "nil", "illai", "இல்லை", "வேண்டாம்"}
YES_WORDS = {"yes", "yeah", "yep", "correct", "right", "save", "ok", "okay", "sure", "ஆம்", "சரி", "ஆமாம்"}
FIELD_WORDS = {
    "full_name": {"name"}, "line1": {"street", "house", "door"}, "line2": {"area", "landmark"},
    "city": {"city", "town"}, "postal_code": {"pin", "postal", "zip", "pincode"},
    "country_code": {"country"}, "state": {"state"}, "phone": {"phone", "mobile"},
}
COUNTRIES = {
    "india": "IN", "bharat": "IN", "இந்தியா": "IN", "united states": "US", "usa": "US", "america": "US",
    "us": "US", "united kingdom": "GB", "uk": "GB", "england": "GB", "britain": "GB", "canada": "CA",
    "australia": "AU", "singapore": "SG", "malaysia": "MY", "sri lanka": "LK", "uae": "AE",
    "united arab emirates": "AE", "dubai": "AE", "germany": "DE", "france": "FR", "japan": "JP",
}
DIGIT_WORDS = {"zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4",
               "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def _digits(text: str) -> str:
    """'six zero zero, double zero one' -> '600001'. Digits typed as digits also work."""
    out, double = [], False
    for token in text.lower().replace("-", " ").replace(",", " ").split():
        if token in ("double", "triple"):
            double = 2 if token == "double" else 3
            continue
        digit = DIGIT_WORDS.get(token) or ("".join(ch for ch in token if ch.isdigit()) or None)
        if digit:
            out.append(digit * (double or 1) if len(digit) == 1 else digit)
        double = False
    return "".join(out)


def _country(text: str) -> str | None:
    said = " ".join(text.lower().replace(".", " ").split())
    for name, code in COUNTRIES.items():
        if f" {name} " in f" {said} ":
            return code
    letters = said.replace(" ", "")
    return letters.upper() if len(letters) == 2 and letters.isalpha() else None


def _address_readback(session: ChatSession) -> ChatReply:
    from app.services import address_service

    session.address_step = "confirm"
    return ChatReply(
        f"I have: {address_service.one_line(session.address)}. "
        "Say yes to save it, or say change and the part, like change city."
    )


def _ask(session: ChatSession, step: str, prefix: str = "") -> ChatReply:
    session.address_step = step
    return ChatReply(f"{prefix}{ADDRESS_QUESTIONS[step]}".strip())


def _next_step(after: str) -> str | None:
    names = [name for name, _ in ADDRESS_STEPS]
    index = names.index(after) + 1
    return names[index] if index < len(names) else None


async def _address_answer(user: User, session: ChatSession, text: str) -> ChatReply:
    from app.services import address_service

    step = session.address_step
    said = guardrails.words(text)

    if step == "confirm":
        wanted = next((f for f, words in FIELD_WORDS.items() if said & words), None)
        if wanted and said & {"change", "wrong", "fix", "edit", "மாற்று"}:
            session.address_fix_one = True
            return _ask(session, wanted)
        if said & YES_WORDS and not said & {"no", "not", "wrong", "dont", "don't", "isn't", "illai", "இல்லை"}:
            try:
                address_service.save(user.id, session.address)
            except address_service.AddressError as error:
                message = str(error)
                bad = next((f for f, words in FIELD_WORDS.items()
                            if any(w in message.lower() for w in words)), "line1")
                session.address_fix_one = True
                return _ask(session, bad, f"{message} ")
            session.address_step = None
            session.address = {}
            try:
                reply = await start_checkout(user, session)
            except shop_service.ShopError as error:
                reply = ChatReply(str(error))
            return ChatReply(f"Address saved. {reply.reply}", pending_action=reply.pending_action,
                             event=reply.event)
        return ChatReply("Please say yes to save the address, or say change and the part, like change city.")

    # One answer, one field.
    if step in OPTIONAL_FIELDS and said & SKIP_WORDS and len(said) <= 3:
        value = None
    elif step == "postal_code":
        value = _digits(text) if any(ch.isdigit() for ch in _digits(text)) else ""
        if not (3 <= len(value) <= 10):
            return ChatReply("Sorry, I didn't get the PIN code. Please say it digit by digit, like six zero zero zero zero one.")
    elif step == "phone":
        value = _digits(text)
        if not (6 <= len(value) <= 15):
            return ChatReply("Sorry, please say the phone number digit by digit, or say skip.")
    elif step == "country_code":
        value = _country(text)
        if value is None:
            return ChatReply("Sorry, which country? For example India or United States.")
    elif step == "state":
        if said & SKIP_WORDS and len(said) <= 3:
            value = None
        else:
            value = text.strip(" .")[:80]
    else:
        value = text.strip(" .")[:150]
        if len(value) < 2:
            return ChatReply(f"Sorry, I didn't catch that. {ADDRESS_QUESTIONS[step]}")

    session.address[step] = value
    nxt = None if session.address_fix_one else _next_step(step)
    session.address_fix_one = False if nxt is None else session.address_fix_one
    if nxt is None:
        return _address_readback(session)
    return _ask(session, nxt)


async def start_checkout(user: User, session: ChatSession) -> ChatReply:
    """
    Voice / chat / Shop button checkout:
    no delivery address yet -> ask it one question at a time;
    saved PayPal -> PIN + fingerprint pays right here;
    otherwise -> PayPal's page once (it can save PayPal for next time).
    """
    from app.services import address_service

    address = address_service.get(user.id)
    if address is None:
        session.address = {}
        return _ask(session, "full_name", "Before you pay, I need your delivery address. I'll ask one thing at a time. ")

    cart = await shop_service.get_cart(user.id)
    if not cart["items"]:
        return ChatReply("Your cart is empty.")
    where = f"{address['city']}, {address['postal_code']}"
    summary = ", ".join(f"{i['quantity']} x {i['title']}" for i in cart["items"])[:200]

    if shop_service.saved_paypal(user.id):
        session.pending = PendingShopPay(
            id=secrets.token_urlsafe(16), total=cart["total"], summary=summary,
            expires_at=time.monotonic() + ACTION_TTL_SECONDS,
        )
        return ChatReply(
            f"Your order: {summary}. Total ${cart['total']:.2f}, delivered to {where}. "
            "Type your PayGuard PIN and confirm with your fingerprint to pay with your saved PayPal.",
            pending_action=_pending_public(session.pending),
            event="confirm_needed",
        )

    order = await shop_service.checkout_cart(user.id)
    return ChatReply(
        f"Your order {order['code']} is ready: total ${order['total']:.2f}, delivered to {where}. "
        "Tap Pay with PayPal to finish. PayPal can save your account so next time "
        "your PIN and fingerprint are enough.",
        pending_action={
            "id": order["code"],
            "type": "checkout",
            "summary": f"{order['summary']}, ${order['total']:.2f}",
            "url": order["approval_url"],
        },
        event="request_sent",
    )


async def _confirm_shop_pay(user: User, pending: PendingShopPay) -> ChatReply:
    try:
        done = await shop_service.checkout_cart(user.id, use_saved_paypal=True, expected_total=pending.total)
    except shop_service.ShopError as error:
        return ChatReply(str(error), event="failed")
    order = done["order"]
    when = shop_service.delivery_words(order.get("delivery_by"))
    return ChatReply(
        f"Paid. Order {order['code']}: ${order['total']} with your saved PayPal. "
        f"Expected delivery by {when}. Your receipt is in Shop, My orders.",
        event="payment_sent",
    )
