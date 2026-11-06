from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.payment_transaction import PaymentTransaction


def save_completed_capture(
    order_id: str,
    capture: dict,
    payer_email: str | None = None,
    payer_id: str | None = None,
) -> dict:
    """
    Save a completed PayPal capture.
    Repeated requests for the same capture won't create duplicate records.
    """

    capture_id = capture.get("capture_id")
    status = capture.get("status")
    amount = capture.get("amount")
    currency = capture.get("currency")

    if status != "COMPLETED":
        raise ValueError("Only completed PayPal captures can be saved.")

    if not all([order_id, capture_id, amount, currency]):
        raise ValueError("Required PayPal capture information is missing.")

    try:
        decimal_amount = Decimal(str(amount))
    except InvalidOperation:
        raise ValueError("Invalid payment amount.") from None

    if decimal_amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    db = SessionLocal()

    try:
        existing_capture = db.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.capture_id == capture_id
            )
        )

        if existing_capture:
            if existing_capture.order_id != order_id:
                raise ValueError("Capture ID is already associated with another order.")

            return {
                "saved": True,
                "duplicate": True,
                "transaction_id": existing_capture.id,
            }

        existing_order = db.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.order_id == order_id
            )
        )

        if existing_order:
            raise ValueError("This order already has a recorded capture.")

        transaction = PaymentTransaction(
            order_id=order_id,
            capture_id=capture_id,
            amount=decimal_amount,
            currency=currency,
            status=status,
            payer_email=payer_email.strip().lower() if payer_email else None,
            payer_id=payer_id,
            environment=settings.paypal_env,
        )

        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        return {
            "saved": True,
            "duplicate": False,
            "transaction_id": transaction.id,
        }

    except IntegrityError:
        db.rollback()
        raise ValueError(
            "This PayPal transaction may already have been recorded."
        ) from None

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()