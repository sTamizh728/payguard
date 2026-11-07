"""
Autopay: real PayPal subscriptions started in PayGuard, plus autopays set up
elsewhere that people add by hand so PayGuard can track and remind them.

PayPal does not let any app see a person's subscriptions with other companies,
so outside autopays can only be tracked by hand. Reminders are made when the app
asks for alerts or opens Track (the free server has no clock job).
"""
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.integrations.paypal_client import get_access_token
from app.models.autopay import Autopay, PayPalCatalog

INTERVALS = {"DAY": "day", "WEEK": "week", "MONTH": "month", "YEAR": "year"}
REMIND_DAYS = 2
MAX_MANUAL_AMOUNT = Decimal("10000")

# Demo billers for the sandbox. Every subscription is a real PayPal sandbox
# subscription paid to the PayGuard demo merchant account. The names are made up.
BILLERS = {
    "streambox": {"name": "StreamBox video", "amount": Decimal("7.99"), "interval": "MONTH"},
    "fitlife": {"name": "FitLife gym", "amount": Decimal("25.00"), "interval": "MONTH"},
    "cloudsafe": {"name": "CloudSafe storage", "amount": Decimal("2.99"), "interval": "MONTH"},
    # Charges every day, so a renewal (and its alert) can be seen quickly.
    "dailynews": {"name": "Daily News digest", "amount": Decimal("1.00"), "interval": "DAY"},
}

PAYPAL_STATUSES = {"APPROVAL_PENDING", "APPROVED", "ACTIVE", "SUSPENDED", "CANCELLED", "EXPIRED"}


class AutopayError(Exception):
    pass


# ---------- small helpers ----------

def _today() -> date:
    return datetime.now(timezone.utc).date()


def _add_interval(day: date, interval: str) -> date:
    if interval == "DAY":
        return day + timedelta(days=1)
    if interval == "WEEK":
        return day + timedelta(weeks=1)
    months = 12 if interval == "YEAR" else 1
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def find_biller(text: str) -> str | None:
    """'streambox', 'Stream box', 'the gym' -> a biller key, from the person's own words."""
    said = "".join(ch for ch in text.lower() if ch.isalnum() or ch == " ")
    squashed = said.replace(" ", "")
    for key, biller in BILLERS.items():
        first = biller["name"].split()[0].lower()
        if key in squashed or first in squashed or biller["name"].lower() in said:
            return key
    if "gym" in said.split():
        return "fitlife"
    if "news" in said.split():
        return "dailynews"
    return None


def _view(row: Autopay, number: int) -> dict:
    return {
        "number": number,
        "id": row.id,
        "source": row.source,
        "name": row.name,
        "amount": f"{Decimal(str(row.amount)):.2f}",
        "currency": row.currency,
        "interval": row.interval,
        "every": INTERVALS.get(row.interval, row.interval.lower()),
        "status": row.status,
        "next_date": row.next_date,
        "last_paid_at": row.last_paid_at.isoformat() if row.last_paid_at else None,
        "last_amount": f"{Decimal(str(row.last_amount)):.2f}" if row.last_amount is not None else None,
        "failed_count": row.failed_count,
        "approval_url": row.approval_url if row.status == "APPROVAL_PENDING" else None,
    }


def describe(item: dict) -> str:
    text = f"Autopay {item['number']}: {item['name']}, ${item['amount']} every {item['every']}"
    status = item["status"]
    if status == "ACTIVE":
        text += f", next on {item['next_date']}" if item["next_date"] else ", active"
    elif status == "APPROVAL_PENDING":
        text += ", waiting for your approval in PayPal"
    elif status == "SUSPENDED":
        text += ", paused"
    else:
        text += f", {status.lower()}"
    if item["failed_count"]:
        text += f". {item['failed_count']} payment(s) failed"
    if item["source"] == "manual":
        text += " (added by you)"
    return text + "."


def list_autopays(user_id: int, include_ended: bool = True) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(Autopay).where(Autopay.user_id == user_id).order_by(Autopay.id)
        ).all()
        items = [_view(row, n) for n, row in enumerate(rows, start=1)]
    if not include_ended:
        items = [i for i in items if i["status"] not in ("CANCELLED", "EXPIRED")]
    return items


def find_by_number(user_id: int, number: int) -> dict | None:
    return next((i for i in list_autopays(user_id) if i["number"] == number), None)


def _own_row(db, user_id: int, autopay_id: int) -> Autopay:
    row = db.get(Autopay, autopay_id)
    if row is None or row.user_id != user_id:
        raise AutopayError("That autopay was not found.")
    return row


# ---------- PayPal ----------

async def _paypal(method: str, path: str, body: dict | None = None) -> dict:
    """One PayPal REST call. Tests replace this."""
    token = (await get_access_token())["access_token"]
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.request(
                method,
                f"{settings.paypal_base_url.rstrip('/')}{path}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AutopayError(f"PayPal refused the autopay request (HTTP {exc.response.status_code}).") from None
        except httpx.RequestError:
            raise AutopayError("Could not reach PayPal. Please try again.") from None
    return response.json() if response.content else {}


async def _catalog_id(key: str, create) -> str:
    with SessionLocal() as db:
        found = db.get(PayPalCatalog, key)
        if found is not None:
            return found.value
    value = await create()
    with SessionLocal() as db:
        if db.get(PayPalCatalog, key) is None:
            db.add(PayPalCatalog(key=key, value=value))
            db.commit()
    return value


async def _plan_id(biller_key: str) -> str:
    biller = BILLERS[biller_key]

    async def new_product():
        data = await _paypal("POST", "/v1/catalogs/products", {
            "name": "PayGuard Autopay", "type": "SERVICE",
        })
        return data["id"]

    product = await _catalog_id(f"{settings.paypal_env}:product", new_product)

    async def new_plan():
        data = await _paypal("POST", "/v1/billing/plans", {
            "product_id": product,
            "name": biller["name"],
            "status": "ACTIVE",
            "billing_cycles": [{
                "frequency": {"interval_unit": biller["interval"], "interval_count": 1},
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,
                "pricing_scheme": {"fixed_price": {
                    "value": f"{biller['amount']:.2f}", "currency_code": "USD",
                }},
            }],
            "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 3},
        })
        return data["id"]

    return await _catalog_id(
        f"{settings.paypal_env}:plan:{biller_key}:{biller['amount']}:{biller['interval']}", new_plan,
    )


async def start_paypal_autopay(user_id: int, biller_key: str) -> dict:
    """Create the PayPal subscription. It starts only after approval in PayPal."""
    if biller_key not in BILLERS:
        raise AutopayError("I don't know that biller.")
    biller = BILLERS[biller_key]

    with SessionLocal() as db:
        running = db.scalar(select(Autopay).where(
            Autopay.user_id == user_id, Autopay.name == biller["name"], Autopay.source == "paypal",
            Autopay.status.in_(("ACTIVE", "SUSPENDED")),
        ))
        if running is not None:
            raise AutopayError(f"You already have an autopay for {biller['name']}.")
        waiting = db.scalar(select(Autopay).where(
            Autopay.user_id == user_id, Autopay.name == biller["name"], Autopay.source == "paypal",
            Autopay.status == "APPROVAL_PENDING",
        ))
        if waiting is not None:
            # Two taps must never make two subscriptions: send them to the same approval page.
            number = next(i["number"] for i in list_autopays(user_id) if i["id"] == waiting.id)
            return _view(waiting, number)

    plan = await _plan_id(biller_key)
    data = await _paypal("POST", "/v1/billing/subscriptions", {
        "plan_id": plan,
        "custom_id": f"payguard-user-{user_id}",
        "application_context": {
            "brand_name": "PayGuard",
            "user_action": "SUBSCRIBE_NOW",
            "shipping_preference": "NO_SHIPPING",
            # Straight back into the app. This link proves nothing by itself:
            # the status is always read from PayPal afterwards.
            "return_url": settings.app_autopay_return_uri,
            "cancel_url": settings.app_autopay_cancel_uri,
        },
    })
    approval = next((link["href"] for link in data.get("links", []) if link.get("rel") == "approve"), None)
    if not data.get("id") or not approval:
        raise AutopayError("PayPal did not return an approval link.")

    with SessionLocal() as db:
        row = Autopay(
            user_id=user_id, source="paypal", name=biller["name"], amount=biller["amount"],
            currency="USD", interval=biller["interval"], status="APPROVAL_PENDING",
            paypal_subscription_id=data["id"], approval_url=approval,
        )
        db.add(row)
        db.commit()
        number = len(list_autopays(user_id))
        return _view(row, number)


def _apply_paypal(row: Autopay, data: dict) -> None:
    status = str(data.get("status") or "").upper()
    if status in PAYPAL_STATUSES:
        row.status = "ACTIVE" if status == "APPROVED" else status
    info = data.get("billing_info") or {}
    next_time = info.get("next_billing_time")
    if next_time:
        row.next_date = str(next_time)[:10]
    last = info.get("last_payment") or {}
    if last.get("time"):
        row.last_paid_at = datetime.fromisoformat(str(last["time"]).replace("Z", "+00:00"))
        try:
            row.last_amount = Decimal(str((last.get("amount") or {}).get("value")))
        except (InvalidOperation, TypeError):
            pass
    if info.get("failed_payments_count") is not None:
        row.failed_count = int(info["failed_payments_count"])


async def refresh(user_id: int, autopay_id: int) -> dict:
    """Read the real status from PayPal (after approval, or any time)."""
    with SessionLocal() as db:
        row = _own_row(db, user_id, autopay_id)
        sub_id = row.paypal_subscription_id
    if not sub_id:
        return next(i for i in list_autopays(user_id) if i["id"] == autopay_id)

    data = await _paypal("GET", f"/v1/billing/subscriptions/{sub_id}")
    with SessionLocal() as db:
        row = _own_row(db, user_id, autopay_id)
        _apply_paypal(row, data)
        db.commit()
    return next(i for i in list_autopays(user_id) if i["id"] == autopay_id)


async def refresh_by_subscription(user_id: int, subscription_id: str) -> dict:
    with SessionLocal() as db:
        row = db.scalar(select(Autopay).where(Autopay.paypal_subscription_id == subscription_id))
        if row is None or row.user_id != user_id:
            raise AutopayError("That autopay was not found.")
        autopay_id = row.id
    return await refresh(user_id, autopay_id)


async def refresh_open(user_id: int) -> None:
    """Before showing Track: update PayPal autopays still waiting or due."""
    today = _today().isoformat()
    with SessionLocal() as db:
        rows = db.scalars(select(Autopay).where(
            Autopay.user_id == user_id, Autopay.source == "paypal",
            Autopay.status.in_(("APPROVAL_PENDING", "ACTIVE")),
        )).all()
        due = [r.id for r in rows if r.status == "APPROVAL_PENDING" or not r.next_date or r.next_date <= today]
    for autopay_id in due[:5]:
        try:
            await refresh(user_id, autopay_id)
        except AutopayError:
            pass


async def change(user_id: int, autopay_id: int, what: str) -> dict:
    """what: cancel / pause / resume."""
    with SessionLocal() as db:
        row = _own_row(db, user_id, autopay_id)
        if row.status in ("CANCELLED", "EXPIRED"):
            raise AutopayError(f"{row.name} autopay has already ended.")
        sub_id, source, status = row.paypal_subscription_id, row.source, row.status

    if status == "APPROVAL_PENDING" and what != "cancel":
        raise AutopayError(f"{row.name} autopay is not approved in PayPal yet.")

    target = {"cancel": "CANCELLED", "pause": "SUSPENDED", "resume": "ACTIVE"}[what]
    # Never approved: PayPal can't cancel it (and will never charge it), so just drop it here.
    if source == "paypal" and sub_id and status != "APPROVAL_PENDING":
        if what == "cancel":
            await _paypal("POST", f"/v1/billing/subscriptions/{sub_id}/cancel", {"reason": "Cancelled in PayGuard"})
        elif what == "pause":
            await _paypal("POST", f"/v1/billing/subscriptions/{sub_id}/suspend", {"reason": "Paused in PayGuard"})
        else:
            await _paypal("POST", f"/v1/billing/subscriptions/{sub_id}/activate", {"reason": "Resumed in PayGuard"})

    with SessionLocal() as db:
        row = _own_row(db, user_id, autopay_id)
        row.status = target
        db.commit()
    return next(i for i in list_autopays(user_id) if i["id"] == autopay_id)


# ---------- autopays added by hand ----------

def add_manual(user_id: int, name: str, amount, interval: str, next_date: str) -> dict:
    name = " ".join(str(name).split())[:60]
    if len(name) < 2:
        raise AutopayError("Please give the autopay a name, like 'Phone bill'.")
    try:
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise AutopayError("Please give the amount as a number.") from None
    if not (Decimal("0") < amount <= MAX_MANUAL_AMOUNT):
        raise AutopayError("The amount must be between $0.01 and $10,000.")
    interval = str(interval).upper()
    if interval not in INTERVALS:
        raise AutopayError("How often: every day, week, month or year.")
    try:
        when = date.fromisoformat(next_date)
    except (TypeError, ValueError):
        raise AutopayError("Please give the next payment date as YYYY-MM-DD.") from None
    if not (_today() - timedelta(days=366) <= when <= _today() + timedelta(days=366)):
        raise AutopayError("The next payment date must be within a year.")

    with SessionLocal() as db:
        row = Autopay(
            user_id=user_id, source="manual", name=name, amount=amount, currency="USD",
            interval=interval, status="ACTIVE", next_date=when.isoformat(),
        )
        db.add(row)
        db.commit()
        autopay_id = row.id
    _roll_forward(user_id)
    return next(i for i in list_autopays(user_id) if i["id"] == autopay_id)


def _roll_forward(user_id: int) -> None:
    """A hand-added autopay whose date has passed has charged: move to the next one."""
    today = _today()
    with SessionLocal() as db:
        rows = db.scalars(select(Autopay).where(
            Autopay.user_id == user_id, Autopay.source == "manual", Autopay.status == "ACTIVE",
        )).all()
        for row in rows:
            when = date.fromisoformat(row.next_date) if row.next_date else today
            while when < today:
                when = _add_interval(when, row.interval)
            row.next_date = when.isoformat()
        db.commit()


def make_reminders(user_id: int) -> int:
    """One alert per upcoming charge, when it is 2 days away or less."""
    from app.services import webhook_service

    _roll_forward(user_id)
    soon = (_today() + timedelta(days=REMIND_DAYS)).isoformat()
    made = 0
    with SessionLocal() as db:
        rows = db.scalars(select(Autopay).where(
            Autopay.user_id == user_id, Autopay.status == "ACTIVE", Autopay.next_date.is_not(None),
        )).all()
        due = []
        for row in rows:
            if row.next_date <= soon and row.reminded_for != row.next_date:
                row.reminded_for = row.next_date
                due.append((row.name, Decimal(str(row.amount)), row.next_date))
        db.commit()
    for name, amount, when in due:
        day = "today" if when == _today().isoformat() else f"on {when}"
        webhook_service.add_notification(
            user_id, "autopay", f"Reminder: {name} autopay of ${amount:.2f} charges {day}.",
        )
        made += 1
    return made


# ---------- verified PayPal webhooks ----------

def apply_webhook(kind: str, resource: dict) -> tuple[int, str] | None:
    """
    Update the autopay a verified webhook is about.
    -> (user_id, alert text), or None if it is not one of ours.
    """
    if kind.startswith("BILLING.SUBSCRIPTION."):
        sub_id = resource.get("id")
    elif kind == "PAYMENT.SALE.COMPLETED":
        sub_id = resource.get("billing_agreement_id")
    else:
        return None
    if not sub_id:
        return None

    with SessionLocal() as db:
        row = db.scalar(select(Autopay).where(Autopay.paypal_subscription_id == str(sub_id)))
        if row is None:
            return None

        name = row.name
        if kind == "PAYMENT.SALE.COMPLETED":
            amount = (resource.get("amount") or {}).get("total") or f"{Decimal(str(row.amount)):.2f}"
            row.last_paid_at = datetime.now(timezone.utc)
            try:
                row.last_amount = Decimal(str(amount))
            except InvalidOperation:
                pass
            if row.next_date:
                row.next_date = _add_interval(_today(), row.interval).isoformat()
            text = f"Autopay paid: ${amount} to {name}."
        elif kind.endswith("PAYMENT.FAILED"):
            row.failed_count += 1
            text = f"Autopay failed: your {name} payment did not go through. Please check your PayPal."
        else:
            _apply_paypal(row, resource)
            what = {
                "ACTIVATED": "is now active", "CANCELLED": "was cancelled",
                "SUSPENDED": "was paused", "EXPIRED": "has ended", "RE-ACTIVATED": "is active again",
            }.get(kind.split(".")[-1], "was updated")
            text = f"Your {name} autopay {what}."
        user_id = row.user_id
        db.commit()
    return user_id, text
