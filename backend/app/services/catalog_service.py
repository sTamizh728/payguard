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


# The demo catalog only matches exact words, so help it the way a shop would.
STOP_WORDS = {
    "show", "me", "find", "search", "for", "some", "a", "an", "the", "i", "want", "need",
    "buy", "please", "get", "looking", "any", "cheap", "good", "best", "new", "with",
    "and", "of", "to", "my", "can", "you", "is", "are", "there", "do", "have",
}
# word -> other words to search, and catalog categories to show
SYNONYMS = {
    "mobile": (["phone"], ["smartphones"]), "cellphone": (["phone"], ["smartphones"]),
    "smartphone": (["phone"], ["smartphones"]), "phone": ([], ["smartphones"]),
    "perfume": (["fragrance"], ["fragrances"]), "scent": ([], ["fragrances"]),
    "earphone": (["airpods"], ["mobile-accessories"]), "earbud": (["airpods"], ["mobile-accessories"]),
    "headphone": (["airpods"], ["mobile-accessories"]), "headset": (["airpods"], ["mobile-accessories"]),
    "charger": ([], ["mobile-accessories"]), "shoe": ([], ["mens-shoes", "womens-shoes"]),
    "sneaker": ([], ["mens-shoes", "womens-shoes"]), "watch": ([], ["mens-watches", "womens-watches"]),
    "bag": ([], ["womens-bags"]), "handbag": ([], ["womens-bags"]), "dress": ([], ["womens-dresses"]),
    "jewellery": ([], ["womens-jewellery"]), "jewelry": ([], ["womens-jewellery"]),
    "shirt": ([], ["mens-shirts", "tops"]), "tshirt": (["shirt"], ["mens-shirts", "tops"]),
    "laptop": ([], ["laptops"]), "computer": (["laptop"], ["laptops"]), "notebook": (["laptop"], ["laptops"]),
    "tablet": ([], ["tablets"]), "ipad": ([], ["tablets"]), "sunglass": ([], ["sunglasses"]),
    "glasses": ([], ["sunglasses"]), "sofa": ([], ["furniture"]), "chair": ([], ["furniture"]),
    "bed": ([], ["furniture"]), "makeup": ([], ["beauty"]), "lipstick": ([], ["beauty"]),
    "cream": ([], ["skin-care"]), "lotion": ([], ["skin-care"]), "kitchen": ([], ["kitchen-accessories"]),
    "food": ([], ["groceries"]), "grocery": ([], ["groceries"]), "fruit": ([], ["groceries"]),
    "bike": ([], ["motorcycle"]), "car": ([], ["vehicle"]), "ball": ([], ["sports-accessories"]),
    "sport": ([], ["sports-accessories"]), "lamp": ([], ["home-decoration"]), "decor": ([], ["home-decoration"]),
}


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("es") and word[:-2].endswith(("sh", "ch", "ss")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


async def search(query: str) -> list[dict]:
    """Exact words first; if that finds little, each word, similar words and categories."""
    query = query.strip()[:60]
    if not query:
        return []

    found: dict[int, dict] = {}

    async def add(path: str, params: dict) -> None:
        data = await _get(path, {**params, "limit": SEARCH_LIMIT})
        for p in data.get("products", []):
            found.setdefault(p["id"], p)

    await add("/products/search", {"q": query})

    if len(found) < 3:
        words = [_singular(w) for w in query.lower().replace("-", " ").split()]
        words = [w for w in words if len(w) > 2 and w not in STOP_WORDS]
        for word in words:
            more_words, categories = SYNONYMS.get(word, ([], []))
            # The word itself, then its categories (what people mostly mean),
            # then similar words.
            steps = [("/products/search", {"q": word})]
            steps += [(f"/products/category/{c}", {}) for c in categories]
            steps += [("/products/search", {"q": w}) for w in more_words]
            for path, params in steps:
                if len(found) >= SEARCH_LIMIT:
                    break
                await add(path, params)

    return [_summary(p) for p in list(found.values())[:SEARCH_LIMIT]]


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
