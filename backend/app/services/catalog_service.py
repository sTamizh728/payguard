"""
Product catalog for the PayGuard Shop: search, details, ratings and reviews.
Uses DummyJSON, a free public demo store (https://dummyjson.com). A real shop
would plug its own catalog in here. Prices always come from here, never from
the app, so nobody can change a price.
"""
import time
from decimal import Decimal

import httpx

BASE_URL = "https://dummyjson.com"
CACHE_SECONDS = 10 * 60
SEARCH_LIMIT = 8

_cache: dict[str, tuple[float, object]] = {}


class CatalogError(Exception):
    pass


async def _get(path: str, params: dict | None = None):
    key = path + repr(sorted((params or {}).items()))
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(BASE_URL + path, params=params)
        except httpx.RequestError:
            raise CatalogError("The product catalog is not reachable right now.") from None

    if response.status_code == 404:
        raise CatalogError("That product does not exist.")
    if response.is_error:
        raise CatalogError("The product catalog is not reachable right now.")

    data = response.json()
    _cache[key] = (time.time() + CACHE_SECONDS, data)
    return data


def _summary(p: dict) -> dict:
    return {
        "id": p["id"],
        "title": p["title"],
        "brand": p.get("brand"),
        "price": Decimal(str(p["price"])).quantize(Decimal("0.01")),
        "rating": round(float(p.get("rating") or 0), 1),
        "stock": int(p.get("stock") or 0),
        "thumbnail": p.get("thumbnail"),
    }


async def search(query: str) -> list[dict]:
    query = query.strip()[:60]
    if not query:
        return []
    data = await _get("/products/search", {"q": query, "limit": SEARCH_LIMIT})
    return [_summary(p) for p in data.get("products", [])]


async def get_product(product_id: int) -> dict:
    p = await _get(f"/products/{int(product_id)}")
    product = _summary(p)
    reviews = sorted(p.get("reviews") or [], key=lambda r: r.get("date") or "", reverse=True)
    product.update({
        "description": p.get("description") or "",
        "category": p.get("category"),
        "shipping": p.get("shippingInformation"),
        "returns": p.get("returnPolicy"),
        "warranty": p.get("warrantyInformation"),
        "reviews": [
            {
                "name": r.get("reviewerName") or "A buyer",
                "rating": int(r.get("rating") or 0),
                "comment": (r.get("comment") or "")[:200],
            }
            for r in reviews[:5]
        ],
    })
    return product


def public(product: dict) -> dict:
    """JSON-safe copy (Decimal -> string)."""
    return {**product, "price": f"{product['price']:.2f}"}
