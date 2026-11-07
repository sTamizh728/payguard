"""
The people PayGuard can send money to: the PayPal sandbox test accounts, plus
anyone the person picked from their phone's contact book or typed in.
"""
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.saved_contact import SavedContact

CONTACTS = [
    {"name": "Sam Kumar", "email": "sb-8pugp53567304@personal.example.com"},
    {"name": "Sam Sun", "email": "sb-x9t43k53569337@personal.example.com"},
    {"name": "Priya Raj", "email": "sb-oaavd53471227@business.example.com"},
]
MAX_SAVED = 200


class ContactError(Exception):
    pass


def _saved(user_id: int | None) -> list[dict]:
    if user_id is None:
        return []
    with SessionLocal() as db:
        rows = db.scalars(
            select(SavedContact).where(SavedContact.user_id == user_id).order_by(SavedContact.name)
        ).all()
        return [{"name": r.name, "email": r.email, "saved": True} for r in rows]


def all_for(user_id: int | None, my_email: str = "") -> list[dict]:
    """Test accounts first, then the person's own contacts. Never yourself, never twice."""
    me = my_email.strip().lower()
    seen, people = set(), []
    for contact in [*CONTACTS, *_saved(user_id)]:
        if contact["email"] != me and contact["email"] not in seen:
            seen.add(contact["email"])
            people.append(contact)
    return people


def clean_email(email: str) -> str:
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise ContactError("That is not a valid PayPal email address.") from None


def save(user_id: int, name: str, email: str) -> dict:
    """Add (or rename) a contact from the phone's contact book or typed in."""
    email = clean_email(email)
    name = " ".join(str(name or "").split())[:100] or email.split("@")[0]
    known = find_by_email(email, user_id)
    if known is not None and not known.get("saved"):
        return known  # a test account: keep its name
    with SessionLocal() as db:
        row = db.scalar(select(SavedContact).where(SavedContact.user_id == user_id, SavedContact.email == email))
        if row is None:
            count = len(db.scalars(select(SavedContact.id).where(SavedContact.user_id == user_id)).all())
            if count >= MAX_SAVED:
                raise ContactError("You have too many contacts saved.")
            db.add(SavedContact(user_id=user_id, name=name, email=email))
        else:
            row.name = name
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return {"name": name, "email": email, "saved": True}


def find_contacts(name: str, user_id: int | None = None) -> list[dict]:
    """Return every contact whose name matches what the user said, word by word.

    'sam' -> Sam Kumar + Sam Sun, 'sam sun' -> Sam Sun. Each word must match the
    START of a name word, so 'am' or an empty name never match anybody.
    """
    said = name.strip().lower().split()
    if not said:
        return []
    matches = []
    for contact in all_for(user_id):
        parts = contact["name"].lower().split()
        if all(any(part.startswith(word) for part in parts) for word in said):
            matches.append(contact)
    return matches


def find_by_email(email: str, user_id: int | None = None) -> dict | None:
    email = email.strip().lower()
    return next((c for c in all_for(user_id) if c["email"] == email), None)
