"""
Scam guard: warning signs before money leaves, decided by plain code (never the AI).

Scammers win by rushing people: "urgent, send now". With two or more warning
signs PayGuard explains them and the server refuses to confirm for a short
cooling-off time, so nobody can be hurried into a payment.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models.payout import Payout

BIG_AMOUNT = Decimal("50.00")
RAPID_COUNT = 3              # this many payouts...
RAPID_MINUTES = 10           # ...within this many minutes is a warning sign
SIGNS_FOR_WARNING = 2
COOLING_OFF_SECONDS = 30

# Words scammers use to create pressure, in English and Tamil.
PRESSURE_PATTERNS = [
    r"\burgent(ly)?\b", r"\bemergency\b", r"\bimmediately\b", r"\bright now\b",
    r"\bas soon as possible\b", r"\basap\b", r"\bquick(ly)?\b", r"\bhurry\b",
    r"\bgift ?cards?\b", r"\blottery\b", r"\bprize\b", r"\byou (have )?won\b",
    r"\bpolice\b", r"\barrest", r"\bbail\b", r"\bcustoms\b", r"\btax (officer|department)\b",
    r"\bverify (your|my) account\b", r"\bblocked account\b", r"\bkyc\b",
    r"\bdon'?t tell\b", r"\bsecret(ly)?\b",
    "அவசரம்", "உடனே", "உடனடியாக", "பரிசு", "லாட்டரி", "காவல்",
]

# Successful or still-moving payouts count as "paid this person before".
KNOWN_STATUSES = ("SUCCESS", "PENDING", "PROCESSING", "UNCLAIMED", "NEW")


@dataclass
class Assessment:
    reasons: list[str] = field(default_factory=list)

    @property
    def risky(self) -> bool:
        return len(self.reasons) >= SIGNS_FOR_WARNING

    @property
    def wait_seconds(self) -> int:
        return COOLING_OFF_SECONDS if self.risky else 0


def pressure_words(text: str | None) -> list[str]:
    if not text:
        return []
    lower = text.lower()
    found = []
    for pattern in PRESSURE_PATTERNS:
        match = re.search(pattern, lower)
        if match:
            found.append(match.group(0))
    return found


def assess(user_id: int, email: str, amount: Decimal, text: str | None = None) -> Assessment:
    result = Assessment()
    since = datetime.now(timezone.utc) - timedelta(minutes=RAPID_MINUTES)

    with SessionLocal() as db:
        paid_before = db.scalar(
            select(func.count(Payout.id)).where(
                Payout.requested_by == user_id,
                func.lower(Payout.recipient_email) == email.strip().lower(),
                Payout.status.in_(KNOWN_STATUSES),
            )
        )
        recent = db.scalar(
            select(func.count(Payout.id)).where(
                Payout.requested_by == user_id,
                Payout.created_at >= since,
            )
        )

    if not paid_before:
        result.reasons.append("You have never paid this person before.")

    words = pressure_words(text)
    if words:
        quoted = ", ".join(f'"{w}"' for w in words[:3])
        result.reasons.append(f"The request uses pressure words ({quoted}), a common scam sign.")

    if amount >= BIG_AMOUNT:
        result.reasons.append(f"It is a large amount (${amount:.2f}).")

    if recent >= RAPID_COUNT:
        result.reasons.append(f"You sent {recent} payments in the last {RAPID_MINUTES} minutes.")

    return result
