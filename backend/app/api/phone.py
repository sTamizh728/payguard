"""
PayGuard Shop by phone call (Twilio). Keypad menus in English or Tamil:
language -> product -> quantity -> confirm -> a 6-digit order code that the
caller opens in the app to pay with PayPal. No money moves on the call itself.

Every step carries its choices in the URL (?l=ta&p=2&q=3) and Twilio signs
the full URL, so the server keeps no call state and nobody can fake a step.
"""
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse

from app.core.config import settings
from app.services import shop_service

router = APIRouter(prefix="/api/phone", tags=["Phone"])

VOICES = {
    "en": {"voice": "Google.en-US-Standard-C", "language": "en-US"},
    "ta": {"voice": "Google.ta-IN-Standard-A", "language": "ta-IN"},
}

TEXT = {
    "en": {
        "menu_intro": "Choose a product.",
        "menu_item": "For {name}, {price} dollars, press {n}.",
        "how_many": "{name}. How many would you like? Press a number from 1 to 9.",
        "confirm": "{q} {name}, total {total} dollars. To place the order, press 1. To cancel, press 2.",
        "too_much": "One order can be up to 100 dollars. Please choose fewer.",
        "done": (
            "Your order code is {code}. Again, {code}. Open the PayGuard app, go to Shop, "
            "choose Claim phone order, enter this code, and pay with PayPal. "
            "The code works for 30 minutes. Thank you. Goodbye."
        ),
        "cancelled": "Order cancelled. Nothing was charged. Goodbye.",
        "no_input": "Sorry, I did not get that.",
        "bye": "Please call again. Goodbye.",
        "error": "Sorry, PayPal is not reachable right now. Nothing was charged. Please try again later. Goodbye.",
    },
    "ta": {
        "menu_intro": "ஒரு பொருளைத் தேர்ந்தெடுங்கள்.",
        "menu_item": "{name}, {price} டாலர், {n} அழுத்தவும்.",
        "how_many": "{name}. எத்தனை வேண்டும்? 1 முதல் 9 வரை ஒரு எண்ணை அழுத்தவும்.",
        "confirm": "{q} {name}, மொத்தம் {total} டாலர். ஆர்டர் செய்ய 1 அழுத்தவும். ரத்து செய்ய 2 அழுத்தவும்.",
        "too_much": "ஒரு ஆர்டர் 100 டாலர் வரை மட்டுமே. குறைவாகத் தேர்ந்தெடுங்கள்.",
        "done": (
            "உங்கள் ஆர்டர் எண் {code}. மீண்டும், {code}. PayGuard செயலியைத் திறந்து, "
            "Shop-இல் Claim phone order தேர்ந்தெடுத்து, இந்த எண்ணை உள்ளிட்டு PayPal மூலம் செலுத்துங்கள். "
            "இந்த எண் 30 நிமிடங்கள் செல்லும். நன்றி. வணக்கம்."
        ),
        "cancelled": "ஆர்டர் ரத்து செய்யப்பட்டது. பணம் எடுக்கப்படவில்லை. வணக்கம்.",
        "no_input": "மன்னிக்கவும், புரியவில்லை.",
        "bye": "மீண்டும் அழையுங்கள். வணக்கம்.",
        "error": "மன்னிக்கவும், PayPal இப்போது கிடைக்கவில்லை. பணம் எடுக்கப்படவில்லை. வணக்கம்.",
    },
}


def _xml(response: VoiceResponse) -> Response:
    return Response(content=str(response), media_type="application/xml")


async def _verified_form(request: Request) -> dict:
    """Only Twilio may drive the menu: check its signature on the PUBLIC url."""
    if not settings.twilio_auth_token:
        raise HTTPException(status_code=503, detail="Phone calls are not set up.")

    form = {key: value for key, value in (await request.form()).items()}
    # Render ends HTTPS before the app, so request.url says http://...;
    # Twilio signed the public https address.
    url = settings.public_base_url + request.url.path
    if request.url.query:
        url += "?" + request.url.query

    signature = request.headers.get("X-Twilio-Signature", "")
    if not RequestValidator(settings.twilio_auth_token).validate(url, form, signature):
        raise HTTPException(status_code=403, detail="Not from Twilio.")
    return form


def _say(response, lang: str, key: str, **values) -> None:
    response.say(TEXT[lang][key].format(**values), **VOICES[lang])


def _gather(response: VoiceResponse, action: str, params: dict, lang: str, *keys_and_values):
    """Ask for one key press. With no answer, ask once more, then say goodbye."""
    gather = response.gather(num_digits=1, action=f"{action}?{urlencode(params)}", method="POST", timeout=6)
    for key, values in keys_and_values:
        gather.say(TEXT[lang][key].format(**values), **VOICES[lang])

    if params.get("r") != "1":
        _say(response, lang, "no_input")
        retry = {**params, "r": "1"}
        response.redirect(f"{_step_url(action)}?{urlencode(retry)}", method="POST")
    else:
        _say(response, lang, "bye")
        response.hangup()


def _step_url(action: str) -> str:
    # A "no key pressed" retry replays the step that asked the question.
    return {
        "/api/phone/lang": "/api/phone/voice",
        "/api/phone/product": "/api/phone/products",
        "/api/phone/quantity": "/api/phone/how-many",
        "/api/phone/confirm": "/api/phone/review",
    }[action]


def _lang(value: str | None) -> str:
    return value if value in TEXT else "en"


def _spoken_code(code: str) -> str:
    return " ".join(code)  # read digit by digit


@router.post("/voice")
async def voice(request: Request, r: str | None = None):
    """Twilio calls this when the phone rings: choose a language."""
    await _verified_form(request)
    response = VoiceResponse()
    gather = response.gather(
        num_digits=1, action=f"/api/phone/lang?{urlencode({'r': r or ''})}", method="POST", timeout=6
    )
    gather.say("Welcome to PayGuard Shop. For English, press 1.", **VOICES["en"])
    gather.say("தமிழுக்கு 2 அழுத்தவும்.", **VOICES["ta"])
    if r != "1":
        response.redirect("/api/phone/voice?r=1", method="POST")
    else:
        response.hangup()
    return _xml(response)


@router.post("/lang")
async def lang(request: Request):
    form = await _verified_form(request)
    chosen = {"1": "en", "2": "ta"}.get(form.get("Digits", ""))
    response = VoiceResponse()
    if chosen is None:
        response.redirect("/api/phone/voice?r=1", method="POST")
        return _xml(response)
    response.redirect(f"/api/phone/products?{urlencode({'l': chosen})}", method="POST")
    return _xml(response)


@router.post("/products")
async def products(request: Request, l: str = "en", r: str | None = None):  # noqa: E741
    await _verified_form(request)
    lang_ = _lang(l)
    items = [
        ("menu_item", {
            "name": p["name_ta"] if lang_ == "ta" else p["name"],
            "price": f"{p['price']:.0f}",
            "n": n,
        })
        for n, p in enumerate(shop_service.PRODUCTS, start=1)
    ]
    response = VoiceResponse()
    _gather(response, "/api/phone/product", {"l": lang_, "r": r or ""}, lang_, ("menu_intro", {}), *items)
    return _xml(response)


def _product_name(index: int, lang_: str) -> str:
    product = shop_service.PRODUCTS[index]
    return product["name_ta"] if lang_ == "ta" else product["name"]


@router.post("/product")
async def product(request: Request, l: str = "en"):  # noqa: E741
    form = await _verified_form(request)
    lang_ = _lang(l)
    digit = form.get("Digits", "")
    response = VoiceResponse()
    if not digit.isdigit() or not 1 <= int(digit) <= len(shop_service.PRODUCTS):
        response.redirect(f"/api/phone/products?{urlencode({'l': lang_, 'r': '1'})}", method="POST")
        return _xml(response)
    response.redirect(f"/api/phone/how-many?{urlencode({'l': lang_, 'p': digit})}", method="POST")
    return _xml(response)


def _valid_product(p: str | None) -> int | None:
    if p and p.isdigit() and 1 <= int(p) <= len(shop_service.PRODUCTS):
        return int(p) - 1
    return None


@router.post("/how-many")
async def how_many(request: Request, l: str = "en", p: str | None = None, r: str | None = None):  # noqa: E741
    await _verified_form(request)
    lang_ = _lang(l)
    index = _valid_product(p)
    response = VoiceResponse()
    if index is None:
        response.redirect(f"/api/phone/products?{urlencode({'l': lang_})}", method="POST")
        return _xml(response)
    _gather(response, "/api/phone/quantity", {"l": lang_, "p": p, "r": r or ""}, lang_,
            ("how_many", {"name": _product_name(index, lang_)}))
    return _xml(response)


@router.post("/quantity")
async def quantity(request: Request, l: str = "en", p: str | None = None):  # noqa: E741
    form = await _verified_form(request)
    lang_ = _lang(l)
    index = _valid_product(p)
    digit = form.get("Digits", "")
    response = VoiceResponse()
    if index is None:
        response.redirect(f"/api/phone/products?{urlencode({'l': lang_})}", method="POST")
        return _xml(response)
    if not digit.isdigit() or not 1 <= int(digit) <= 9:
        response.redirect(f"/api/phone/how-many?{urlencode({'l': lang_, 'p': p, 'r': '1'})}", method="POST")
        return _xml(response)
    if shop_service.PRODUCTS[index]["price"] * int(digit) > shop_service.MAX_TOTAL:
        _say(response, lang_, "too_much")
        response.redirect(f"/api/phone/how-many?{urlencode({'l': lang_, 'p': p})}", method="POST")
        return _xml(response)
    response.redirect(f"/api/phone/review?{urlencode({'l': lang_, 'p': p, 'q': digit})}", method="POST")
    return _xml(response)


def _valid_quantity(index: int | None, q: str | None) -> int | None:
    if index is None or not q or not q.isdigit() or not 1 <= int(q) <= 9:
        return None
    if shop_service.PRODUCTS[index]["price"] * int(q) > shop_service.MAX_TOTAL:
        return None
    return int(q)


@router.post("/review")
async def review(request: Request, l: str = "en", p: str | None = None, q: str | None = None,  # noqa: E741
                 r: str | None = None):
    await _verified_form(request)
    lang_ = _lang(l)
    index = _valid_product(p)
    count = _valid_quantity(index, q)
    response = VoiceResponse()
    if count is None:
        response.redirect(f"/api/phone/products?{urlencode({'l': lang_})}", method="POST")
        return _xml(response)
    total = shop_service.PRODUCTS[index]["price"] * count
    _gather(response, "/api/phone/confirm", {"l": lang_, "p": p, "q": q, "r": r or ""}, lang_,
            ("confirm", {"q": count, "name": _product_name(index, lang_), "total": f"{total:.0f}"}))
    return _xml(response)


@router.post("/confirm")
async def confirm(request: Request, l: str = "en", p: str | None = None, q: str | None = None):  # noqa: E741
    form = await _verified_form(request)
    lang_ = _lang(l)
    index = _valid_product(p)
    count = _valid_quantity(index, q)
    digit = form.get("Digits", "")
    response = VoiceResponse()

    if count is None:
        response.redirect(f"/api/phone/products?{urlencode({'l': lang_})}", method="POST")
        return _xml(response)

    if digit == "2":
        _say(response, lang_, "cancelled")
        response.hangup()
        return _xml(response)

    if digit != "1":
        response.redirect(f"/api/phone/review?{urlencode({'l': lang_, 'p': p, 'q': q, 'r': '1'})}", method="POST")
        return _xml(response)

    try:
        order = await shop_service.create_order(shop_service.PRODUCTS[index]["id"], count, channel="phone")
    except shop_service.ShopError:
        _say(response, lang_, "error")
        response.hangup()
        return _xml(response)

    _say(response, lang_, "done", code=_spoken_code(order["code"]))
    response.hangup()
    return _xml(response)
