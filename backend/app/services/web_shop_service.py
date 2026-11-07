"""
Find the best-rated products on the web (Google Shopping, through SerpAPI) and
give links to the stores that sell them. PayGuard never orders these: the person
opens the store's own page and buys there.

Prices, ratings, review counts and links all come from Google Shopping results,
never from the AI. Results are cached for 6 hours to save the free search quota.
"""
import re
import time
from urllib.parse import quote_plus
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import settings

SERPAPI_URL = "https://serpapi.com/search.json"
CACHE_SECONDS = 6 * 60 * 60
TOP = 5
# A rating only counts with enough reviews behind it.
MIN_REVIEWS = 20
PRIOR_RATING, PRIOR_WEIGHT = 4.0, 50

_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}

GOOGLE_DOMAINS = {"in": "google.co.in", "gb": "google.co.uk", "au": "google.com.au", "ca": "google.ca"}


class WebShopError(Exception):
    pass


# Google Shopping gives a link to its own product page (all sellers), not to the
# store. For well-known stores PayGuard builds the store's own search link for the
# product name - a fixed address pattern, so the link can only go to that store.
STORE_SEARCH = {
    "amazon.in": "https://www.amazon.in/s?k={q}",
    "amazon.com": "https://www.amazon.com/s?k={q}",
    "amazon.co.uk": "https://www.amazon.co.uk/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "myntra": "https://www.myntra.com/{q}",
    "croma": "https://www.croma.com/searchB?q={q}",
    "reliance digital": "https://www.reliancedigital.in/products?q={q}",
    "tatacliq": "https://www.tatacliq.com/search/?searchCategory=all&text={q}",
    "tata cliq": "https://www.tatacliq.com/search/?searchCategory=all&text={q}",
    "meesho": "https://www.meesho.com/search?q={q}",
    "ajio": "https://www.ajio.com/search/?text={q}",
    "noise": "https://www.gonoise.com/search?q={q}",
    "boat": "https://www.boat-lifestyle.com/search?q={q}",
    "vijay sales": "https://www.vijaysales.com/search/{q}",
    "walmart": "https://www.walmart.com/search?q={q}",
    "best buy": "https://www.bestbuy.com/site/searchpage.jsp?st={q}",
    "ebay": "https://www.ebay.com/sch/i.html?_nkw={q}",
    "target": "https://www.target.com/s?searchTerm={q}",
}


def store_link(store: str, title: str) -> str | None:
    name = store.lower().replace("www.", "").strip()
    for key, pattern in STORE_SEARCH.items():
        if name == key or name.startswith(key) or (key.startswith("amazon") and name == key.replace(".", " ")):
            return pattern.format(q=quote_plus(title[:80]))
    return None


def max_price(query: str) -> Decimal | None:
    """'earbuds under 3000' -> 3000. Commas allowed ('under 3,000')."""
    m = re.search(r"\b(?:under|below|less than|within|upto|up to|max)\s*(?:rs\.?|₹|\$|inr|usd)?\s*([\d,]+(?:\.\d+)?)",
                  query.lower())
    if not m:
        return None
    try:
        return Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None


def _score(item: dict) -> float:
    """Bayesian average: 5 stars from 3 reviews must not beat 4.6 from 10,000."""
    rating, reviews = item["rating"], item["reviews"]
    return (rating * reviews + PRIOR_RATING * PRIOR_WEIGHT) / (reviews + PRIOR_WEIGHT)


def _clean(raw: dict) -> dict | None:
    link = raw.get("link") or raw.get("product_link")
    if not link or not str(link).startswith(("https://", "http://")):
        return None
    try:
        rating = float(raw.get("rating") or 0)
        reviews = int(str(raw.get("reviews") or 0).replace(",", ""))
    except ValueError:
        return None
    try:
        price_value = Decimal(str(raw.get("extracted_price"))) if raw.get("extracted_price") is not None else None
    except InvalidOperation:
        price_value = None
    return {
        "title": str(raw.get("title") or "")[:150],
        "price": str(raw.get("price") or "")[:30],
        "price_value": price_value,
        "rating": rating,
        "reviews": reviews,
        "store": str(raw.get("source") or "the store")[:60],
        # The store's own page when we know the store, else Google's page listing all sellers.
        "link": store_link(str(raw.get("source") or ""), str(raw.get("title") or "")) or str(link),
        "store_link": store_link(str(raw.get("source") or ""), str(raw.get("title") or "")) is not None,
        "compare_link": str(link),
        "thumbnail": raw.get("thumbnail"),
        "delivery": str(raw.get("delivery") or "")[:80] or None,
    }


async def _search(query: str, country: str) -> list[dict]:
    """One Google Shopping search. Tests replace this."""
    if not settings.serpapi_key:
        raise WebShopError("Web product search is not set up yet.")
    params = {
        "engine": "google_shopping", "q": query, "gl": country, "hl": "en",
        "google_domain": GOOGLE_DOMAINS.get(country, "google.com"), "api_key": settings.serpapi_key,
    }
    async with httpx.AsyncClient(timeout=25.0) as client:
        try:
            response = await client.get(SERPAPI_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 429):
                raise WebShopError("The web search limit is reached for now. Please try later.") from None
            raise WebShopError("Web search is not working right now.") from None
        except httpx.RequestError:
            raise WebShopError("Could not reach web search. Please try again.") from None
    return response.json().get("shopping_results") or []


async def find_best(query: str, country: str = "us") -> list[dict]:
    """The top-rated products for this search, best first."""
    query = " ".join(query.split())[:100]
    if len(query) < 2:
        raise WebShopError("What would you like me to find?")
    country = (country or "us").lower()[:2]
    key = (query.lower(), country)

    cached = _cache.get(key)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]

    items = [i for i in (_clean(r) for r in await _search(query, country)) if i and i["title"]]
    limit = max_price(query)
    if limit is not None:
        items = [i for i in items if i["price_value"] is not None and i["price_value"] <= limit]

    rated = [i for i in items if i["rating"] > 0 and i["reviews"] >= MIN_REVIEWS]
    if len(rated) < 3:  # few well-reviewed results: fall back to anything rated
        rated = [i for i in items if i["rating"] > 0]
    best = sorted(rated, key=_score, reverse=True)[:TOP]

    result = [{**i, "price_value": None, "rank": n} for n, i in enumerate(best, start=1)]
    for item in result:
        item.pop("price_value")
    _cache[key] = (time.time(), result)
    return result


def describe(item: dict) -> str:
    text = f"{item['rank']}: {item['title']}"
    if item["price"]:
        text += f", {item['price']}"
    text += f" at {item['store']}, rated {item['rating']:.1f} out of 5"
    if item["reviews"]:
        text += f" from {item['reviews']:,} reviews"
    return text + "."
