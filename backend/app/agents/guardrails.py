"""
Safety checks that run in plain code, before and after the AI.
Taken from the VoicePay Agent send flow (flow.py) and its tests.
"""
import re
import unicodedata

MAX_TEXT = 300  # one spoken or typed request is never longer than this

INVISIBLE = dict.fromkeys(map(ord, "­​‌‍‎‏⁠﻿"))
# Letters that look Latin but are Cyrillic/Greek - a classic trick to sneak past filters.
LOOKALIKES = str.maketrans(
    "асеорхуіјѕԁɡοαεικνρτυχАВСЕНІЈКМОРЅТХУΑΒΕΗΙΚΜΝΟΡΤΥΧ",
    "aceopxyijsdgoaeikvptuxABCEHIJKMOPSTXYABEHIKMNOPTYX",
)


def normalize(text: str | None) -> str:
    """Make tricky text plain: full-width letters and invisible characters."""
    return unicodedata.normalize("NFKC", text or "").translate(INVISIBLE)


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def is_exact_confirm(text: str) -> bool:
    """True ONLY for 'yes, confirm' (any case, any punctuation). Nothing more, nothing less."""
    return re.findall(r"[a-z0-9]+", text.lower()) == ["yes", "confirm"]


# Phrases that try to change the rules. Checked by plain code BEFORE the AI
# sees anything, so no clever wording can talk it out of this.
UNSAFE_PATTERNS = [
    r"\bignore\b.*\b(rules?|instructions?|previous|above|safety|limits?)\b",
    r"\bforget\b.*\b(rules?|instructions?|everything|previous)\b",
    r"\b(skip|bypass|disable|turn off|without|no need|don'?t need|do not need|don'?t ask|do not ask)\b"
    r".*\b(confirm\w*|verif\w*|fingerprint|pin|password|asking|ask|check\w*|security|safety|limits?)\b",
    r"\balready\b.*\b(confirmed|verified|approved|authori[sz]ed)\b",
    r"(^|\s|\[|<)(system|developer|admin|assistant)\s*[:\]>]",
    r"^\W*(system|developer|admin|assistant)\s*[,;.\-]",
    r"\b(system|developer|admin)\s+(message|prompt|override|mode|instruction)s?\b",
    r"\b(jailbreak|override|god mode|dan mode|pretend|role ?play|act as|you are now|new instructions?)\b",
    r"\b(raise|increase|remove|change|lift)\b.*\blimits?\b",
    r"\bauto(matic(ally)?)?[- ]?(confirm|approve)\w*\b",
]


def is_unsafe(text: str) -> bool:
    # Look-alike letters are turned into Latin ONLY for this check, so real
    # Russian or Greek names still work everywhere else.
    t = text.translate(LOOKALIKES).lower()
    return any(re.search(p, t) for p in UNSAFE_PATTERNS)


UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split(), start=2)}


def spoken_numbers(text: str) -> list[float]:
    """Every number said in words: 'twenty five' -> 25, 'one hundred fifty' -> 150."""
    found, current = [], None
    for w in re.findall(r"[a-z]+", text.lower()) + ["<end>"]:
        if w in UNITS or w in TENS:
            current = (current or 0) + UNITS.get(w, TENS.get(w, 0))
        elif w == "hundred":
            current = (current or 1) * 100
        elif w == "thousand":
            current = (current or 1) * 1000
        elif w == "and" and current is not None:
            continue
        elif current is not None:
            found.append(float(current))
            current = None
    return found


def said_numbers(text: str) -> list[float]:
    """Every number the user said, in digits or in words."""
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))]
    return numbers + spoken_numbers(text)


def user_said_number(value: float, text: str) -> bool:
    """The AI may only use a number the user really said - never an invented one."""
    return any(abs(n - value) < 0.005 for n in said_numbers(text))


ID_KEYWORDS = r"(?:payment|request|order|purchase|number|no\.?|#)"


def user_said_id(value: int, text: str) -> bool:
    """
    A payment or request number the user really said. Digits count anywhere
    ("refund 3"); number WORDS count only after a keyword ("request one"),
    so "approve that one" is not read as request 1.
    """
    digits = [int(n) for n in re.findall(r"(?<![\d.])\d+(?![\d.])", text)]
    if value in digits:
        return True

    for match in re.finditer(ID_KEYWORDS + r"\s*(?:number\s*)?((?:[a-z]+\s*){1,3})", text.lower()):
        spoken = spoken_numbers(match.group(1))
        if spoken and int(spoken[0]) == value:
            return True

    return False
