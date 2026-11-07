"""The person's delivery address for shop orders."""
import re
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.delivery_address import DeliveryAddress

FIELDS = ("full_name", "line1", "line2", "city", "state", "postal_code", "country_code", "phone")
# Same limits as the database columns.
MAX_LENGTH = {"full_name": 100, "line1": 150, "line2": 150, "city": 80, "state": 80,
              "postal_code": 20, "country_code": 2, "phone": 20}
REQUIRED = {"full_name": "your name", "line1": "the street address", "city": "the city",
            "postal_code": "the postal code (PIN code)", "country_code": "the country"}
# PayPal needs the state for these countries.
STATE_NEEDED = {"IN", "US", "CA", "AU", "BR", "MX", "CN", "JP"}


class AddressError(Exception):
    pass


def _view(row: DeliveryAddress) -> dict:
    return {f: getattr(row, f) for f in FIELDS}


def get(user_id: int) -> dict | None:
    with SessionLocal() as db:
        row = db.scalar(select(DeliveryAddress).where(DeliveryAddress.user_id == user_id))
        return _view(row) if row else None


def one_line(address: dict | None) -> str:
    if not address:
        return ""
    parts = [address["full_name"], address["line1"], address.get("line2"), address["city"],
             address.get("state"), address["postal_code"], address["country_code"]]
    return ", ".join(p for p in parts if p)


def save(user_id: int, data: dict) -> dict:
    clean = {f: " ".join(str(data.get(f) or "").split())[:MAX_LENGTH[f]] or None for f in FIELDS}
    for field, words in REQUIRED.items():
        if not clean[field]:
            raise AddressError(f"Please add {words}.")
    clean["country_code"] = clean["country_code"].upper()
    if not re.fullmatch(r"[A-Z]{2}", clean["country_code"]):
        raise AddressError("Please give the country as 2 letters, for example IN or US.")
    if clean["country_code"] in STATE_NEEDED and not clean["state"]:
        raise AddressError("Please add the state.")
    if not re.fullmatch(r"[A-Za-z0-9 -]{3,10}", clean["postal_code"]):
        raise AddressError("That postal code doesn't look right.")
    if clean["country_code"] == "IN" and not re.fullmatch(r"\d{6}", clean["postal_code"]):
        raise AddressError("An Indian PIN code has 6 digits.")
    if clean["phone"] and not re.fullmatch(r"\+?[0-9 ]{6,16}", clean["phone"]):
        raise AddressError("That phone number doesn't look right.")

    with SessionLocal() as db:
        row = db.scalar(select(DeliveryAddress).where(DeliveryAddress.user_id == user_id))
        if row is None:
            row = DeliveryAddress(user_id=user_id, **clean)
            db.add(row)
        else:
            for field, value in clean.items():
                setattr(row, field, value)
            row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return _view(row)


def paypal_shipping(address: dict) -> dict:
    """The address in PayPal's Orders v2 shipping format."""
    shipping = {
        "address_line_1": address["line1"][:300],
        "admin_area_2": address["city"][:120],
        "postal_code": address["postal_code"],
        "country_code": address["country_code"],
    }
    if address.get("line2"):
        shipping["address_line_2"] = address["line2"][:300]
    if address.get("state"):
        shipping["admin_area_1"] = address["state"][:300]
    return {"type": "SHIPPING", "name": {"full_name": address["full_name"][:300]}, "address": shipping}
