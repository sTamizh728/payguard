from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import SessionLocal
from datetime import datetime, timezone

from app.models.payment_refund import PaymentRefund
from app.models.payment_transaction import PaymentTransaction
from app.models.refund_request import RefundRequest
from app.models.user import User
from app.services import payment_service

# Refunds in these states hold money back from being refunded again.
# UNKNOWN and REQUESTED count too: PayPal may still complete them.
HELD_STATUSES = ("REQUESTED", "UNKNOWN", "PENDING", "COMPLETED")
SETTLED_STATUSES = ("PENDING", "COMPLETED")


class RefundNotAllowed(Exception):
    """The refund was refused by our own checks. Nothing was sent to PayPal."""


def _held_amount(db, transaction_id: int) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(PaymentRefund.amount), 0)).where(
            PaymentRefund.transaction_id == transaction_id,
            PaymentRefund.status.in_(HELD_STATUSES),
        )
    )
    return Decimal(str(total))


def _view(db, transaction: PaymentTransaction) -> dict:
    amount = Decimal(str(transaction.amount))
    refundable = amount - _held_amount(db, transaction.id)

    return {
        "number": transaction.id,
        "amount": amount,
        "currency": transaction.currency,
        "refundable": max(refundable, Decimal("0")),
        "status": transaction.status,
        "created_at": transaction.created_at,
    }


def list_transactions(limit: int = 5) -> list[dict]:
    with SessionLocal() as db:
        transactions = db.scalars(
            select(PaymentTransaction)
            .order_by(PaymentTransaction.created_at.desc(), PaymentTransaction.id.desc())
            .limit(limit)
        ).all()

        return [_view(db, transaction) for transaction in transactions]


def find_transaction(number: int | None = None, latest: bool = False) -> dict | None:
    with SessionLocal() as db:
        if number is not None:
            transaction = db.get(PaymentTransaction, number)
        elif latest:
            transaction = db.scalar(
                select(PaymentTransaction)
                .order_by(PaymentTransaction.created_at.desc(), PaymentTransaction.id.desc())
                .limit(1)
            )
        else:
            transaction = None

        return _view(db, transaction) if transaction else None


def _reserve(transaction_id: int, amount: Decimal, request_id: str, user_id: int):
    """
    Lock the payment, re-check what is left, and record the refund as
    REQUESTED before PayPal is called. A second refund for the same money
    then fails here, even if two confirms arrive at the same moment.
    """

    with SessionLocal() as db:
        transaction = db.scalar(
            select(PaymentTransaction)
            .where(PaymentTransaction.id == transaction_id)
            .with_for_update()
        )

        if transaction is None:
            raise RefundNotAllowed("That payment no longer exists.")

        refundable = Decimal(str(transaction.amount)) - _held_amount(db, transaction.id)

        if refundable <= 0:
            raise RefundNotAllowed("This payment is already fully refunded.")

        if amount > refundable:
            raise RefundNotAllowed(
                f"Only ${refundable:.2f} of this payment can still be refunded."
            )

        refund = PaymentRefund(
            transaction_id=transaction.id,
            request_id=request_id,
            amount=amount,
            currency=transaction.currency,
            status="REQUESTED",
            requested_by=user_id,
        )
        db.add(refund)
        db.commit()

        return refund.id, transaction.capture_id, transaction.currency


def _finish(refund_row_id: int, status: str, refund_id: str | None = None) -> None:
    with SessionLocal() as db:
        refund = db.get(PaymentRefund, refund_row_id)
        refund.status = status
        if refund_id:
            refund.refund_id = refund_id

        transaction = db.get(PaymentTransaction, refund.transaction_id)
        db.flush()

        settled = Decimal(str(db.scalar(
            select(func.coalesce(func.sum(PaymentRefund.amount), 0)).where(
                PaymentRefund.transaction_id == transaction.id,
                PaymentRefund.status.in_(SETTLED_STATUSES),
            )
        )))

        if settled >= Decimal(str(transaction.amount)):
            transaction.status = "REFUNDED"
        elif settled > 0:
            transaction.status = "PARTIALLY_REFUNDED"

        db.commit()


async def refund_transaction(
    transaction_id: int,
    amount: Decimal,
    request_id: str,
    user_id: int,
) -> dict:
    """
    Refund money for real. Returns {"outcome": "done" | "pending" | "unknown"}.
    Raises RefundNotAllowed when our checks or PayPal refuse it.
    """

    refund_row_id, capture_id, currency = _reserve(
        transaction_id, amount, request_id, user_id
    )

    try:
        result = await payment_service.refund_paypal_capture(
            capture_id=capture_id,
            amount=f"{amount:.2f}",
            currency=currency,
            request_id=request_id,
        )

    except payment_service.RefundUncertain:
        # Keep the money held: PayPal may still finish this refund.
        _finish(refund_row_id, "UNKNOWN")
        return {"outcome": "unknown"}

    except payment_service.RefundRejected as error:
        # For the developer: PayPal's issue name (e.g. REFUND_AMOUNT_EXCEEDED). No secrets.
        print(f"[Refund rejected] transaction {transaction_id}: {error}")
        _finish(refund_row_id, "FAILED")
        raise RefundNotAllowed("PayPal did not accept this refund.") from None

    status = (result.get("status") or "").upper()

    if status == "COMPLETED":
        _finish(refund_row_id, "COMPLETED", result.get("refund_id"))
        return {"outcome": "done", "refund_id": result.get("refund_id")}

    if status == "PENDING":
        _finish(refund_row_id, "PENDING", result.get("refund_id"))
        return {"outcome": "pending", "refund_id": result.get("refund_id")}

    if status in ("FAILED", "CANCELLED"):
        _finish(refund_row_id, "FAILED", result.get("refund_id"))
        raise RefundNotAllowed("PayPal did not complete this refund.")

    # A status we do not know: keep the money held and let a person check.
    _finish(refund_row_id, "UNKNOWN", result.get("refund_id"))
    return {"outcome": "unknown"}


# ---------- Customer side ----------
# A customer's purchases are the payments whose PayPal buyer email matches the
# email PayPal gave us at Log in with PayPal. Email/password accounts are NOT
# matched: anyone can type any email at sign-up, PayPal login proves it.

def can_see_purchases(user) -> bool:
    return bool(getattr(user, "paypal_user_id", None))


def _customer_email(user) -> str:
    return user.email.strip().lower()


def _latest_request_status(db, transaction_id: int) -> str | None:
    return db.scalar(
        select(RefundRequest.status)
        .where(RefundRequest.transaction_id == transaction_id)
        .order_by(RefundRequest.id.desc())
        .limit(1)
    )


def list_purchases(user, limit: int = 5) -> list[dict]:
    with SessionLocal() as db:
        transactions = db.scalars(
            select(PaymentTransaction)
            .where(PaymentTransaction.payer_email == _customer_email(user))
            .order_by(PaymentTransaction.created_at.desc(), PaymentTransaction.id.desc())
            .limit(limit)
        ).all()

        views = []
        for transaction in transactions:
            view = _view(db, transaction)
            view["request_status"] = _latest_request_status(db, transaction.id)
            views.append(view)

        return views


def find_purchase(user, number: int | None = None, latest: bool = False) -> dict | None:
    """Like find_transaction, but only ever returns this customer's own payment."""
    with SessionLocal() as db:
        query = select(PaymentTransaction).where(
            PaymentTransaction.payer_email == _customer_email(user)
        )

        if number is not None:
            query = query.where(PaymentTransaction.id == number)
        elif not latest:
            return None

        transaction = db.scalar(
            query.order_by(
                PaymentTransaction.created_at.desc(), PaymentTransaction.id.desc()
            ).limit(1)
        )

        if transaction is None:
            return None

        view = _view(db, transaction)
        view["request_status"] = _latest_request_status(db, transaction.id)
        return view


def create_refund_request(user, transaction_number: int, reason: str) -> int:
    with SessionLocal() as db:
        transaction = db.scalar(
            select(PaymentTransaction)
            .where(
                PaymentTransaction.id == transaction_number,
                PaymentTransaction.payer_email == _customer_email(user),
            )
            .with_for_update()
        )

        if transaction is None:
            raise RefundNotAllowed("I couldn't find that purchase.")

        if Decimal(str(transaction.amount)) - _held_amount(db, transaction.id) <= 0:
            raise RefundNotAllowed("This purchase is already fully refunded.")

        open_request = db.scalar(
            select(RefundRequest.id).where(
                RefundRequest.transaction_id == transaction.id,
                RefundRequest.status.in_(("OPEN", "CHECKING")),
            )
        )

        if open_request:
            raise RefundNotAllowed(
                f"You already asked for a refund of payment {transaction.id}. "
                "The shop owner will review it."
            )

        request = RefundRequest(
            transaction_id=transaction.id,
            customer_id=user.id,
            reason=reason[:300],
            status="OPEN",
        )
        db.add(request)
        db.commit()
        return request.id


def list_open_requests(limit: int = 5) -> list[dict]:
    with SessionLocal() as db:
        rows = db.execute(
            select(RefundRequest, User.email)
            .join(User, User.id == RefundRequest.customer_id)
            .where(RefundRequest.status == "OPEN")
            .order_by(RefundRequest.id)
            .limit(limit)
        ).all()

        return [
            {
                "number": request.id,
                "payment": _view(db, db.get(PaymentTransaction, request.transaction_id)),
                "customer": email,
                "reason": request.reason,
            }
            for request, email in rows
        ]


def get_open_request(request_number: int) -> dict | None:
    with SessionLocal() as db:
        request = db.get(RefundRequest, request_number)

        if request is None or request.status != "OPEN":
            return None

        return {
            "number": request.id,
            "payment": _view(db, db.get(PaymentTransaction, request.transaction_id)),
            "reason": request.reason,
        }


def decide_request(request_number: int, status: str, owner_id: int) -> bool:
    """Close an OPEN (or CHECKING) request. Returns False if it was already decided."""
    with SessionLocal() as db:
        request = db.scalar(
            select(RefundRequest)
            .where(RefundRequest.id == request_number)
            .with_for_update()
        )

        if request is None or request.status not in ("OPEN", "CHECKING"):
            return False

        request.status = status
        request.decided_by = owner_id
        request.decided_at = datetime.now(timezone.utc)
        db.commit()
        return True
