"""Best-rated products from Google Shopping (SerpAPI faked), with store links."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.agents import chat_flow
from app.core.config import settings
from app.services import address_service, web_shop_service
from tests.conftest import HOME

ANNA = SimpleNamespace(id=1, email="anna@buyer.test", paypal_user_id="pp-anna")

RESULTS = [
    {"title": "Budget Buds", "price": "₹999", "extracted_price": 999, "rating": 5.0, "reviews": 3,
     "source": "Tiny Shop", "link": "https://tiny.example/buds"},
    {"title": "Sound Pro", "price": "₹2,499", "extracted_price": 2499, "rating": 4.4, "reviews": "12,345",
     "source": "Amazon.in", "product_link": "https://www.google.com/shopping/product/1"},
    {"title": "Bass King", "price": "₹2,999", "extracted_price": 2999, "rating": 4.6, "reviews": 800,
     "source": "Flipkart", "link": "https://www.flipkart.com/bass"},
    {"title": "Luxury Pods", "price": "₹15,900", "extracted_price": 15900, "rating": 4.8, "reviews": 5000,
     "source": "Croma", "link": "https://croma.example/pods"},
    {"title": "No Link", "price": "₹500", "extracted_price": 500, "rating": 4.9, "reviews": 900, "source": "X"},
    {"title": "Evil", "price": "₹1", "extracted_price": 1, "rating": 4.9, "reviews": 900, "source": "X",
     "link": "javascript:alert(1)"},
    {"title": "Unrated", "price": "₹1,500", "extracted_price": 1500, "source": "Y", "link": "https://y.example"},
]


@pytest.fixture(autouse=True)
def fake_search(monkeypatch):
    web_shop_service._cache.clear()
    calls = []

    async def search(query, country):
        calls.append((query, country))
        return [dict(r) for r in RESULTS]

    monkeypatch.setattr(web_shop_service, "_search", search)
    return calls


def best(query, country="in"):
    return asyncio.run(web_shop_service.find_best(query, country))


def test_ranked_by_rating_with_enough_reviews():
    items = best("wireless earbuds")
    assert [i["title"] for i in items] == ["Luxury Pods", "Bass King", "Sound Pro"]
    assert items[0]["rank"] == 1 and items[0]["link"] == "https://www.croma.com/searchB?q=Luxury+Pods"


def test_budget_from_the_words():
    items = best("wireless earbuds under 3,000 rupees")
    assert [i["title"] for i in items] == ["Bass King", "Sound Pro", "Budget Buds"]
    assert all("price_value" not in i for i in items)


def test_store_links_go_to_the_store():
    items = {i["title"]: i for i in best("earbuds")}
    assert items["Bass King"]["link"] == "https://www.flipkart.com/search?q=Bass+King"
    assert items["Bass King"]["store_link"] is True
    assert items["Sound Pro"]["link"].startswith("https://www.amazon.in/s?k=Sound+Pro")
    assert items["Sound Pro"]["compare_link"] == "https://www.google.com/shopping/product/1"
    # Unknown store: Google's page with all sellers.
    assert items["Luxury Pods"]["link"] == "https://croma.example/pods" or items["Luxury Pods"]["store_link"]


@pytest.mark.parametrize("store,ok", [("Amazon.in", True), ("amazon.in - Seller", True), ("Flipkart", True),
                                      ("Myntra", True), ("Some Shop", False), ("", False)])
def test_known_stores(store, ok):
    assert (web_shop_service.store_link(store, "X Y") is not None) == ok


def test_only_real_web_links():
    links = [i["link"] for i in best("earbuds")]
    assert all(link.startswith("https://") for link in links)


def test_results_are_cached(fake_search):
    best("earbuds")
    best("Earbuds ")
    assert len(fake_search) == 1


@pytest.mark.parametrize("text,limit", [("under 3000", 3000), ("below ₹1,500", 1500), ("less than $50", 50),
                                        ("best phone", None)])
def test_max_price(text, limit):
    assert web_shop_service.max_price(text) == limit


def test_no_key_says_so(monkeypatch):
    monkeypatch.undo()
    web_shop_service._cache.clear()
    monkeypatch.setattr(settings, "serpapi_key", None)
    with pytest.raises(web_shop_service.WebShopError, match="not set up"):
        best("earbuds")


def test_real_search_sends_country_and_key(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(settings, "serpapi_key", "test-key")
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"shopping_results": RESULTS})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(web_shop_service.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    web_shop_service._cache.clear()
    assert best("earbuds", "IN")[0]["title"] == "Luxury Pods"
    assert seen["engine"] == "google_shopping" and seen["gl"] == "in" and seen["google_domain"] == "google.co.in"


def test_chat_finds_best_with_links(fake_search):
    address_service.save(1, HOME)
    chat_flow._sessions.clear()

    async def understand(t, role="customer"):
        return {"action": "find_best_products", "query": "wireless earbuds"}

    r = asyncio.run(chat_flow.handle_message(ANNA, "find the best wireless earbuds", understand))
    assert r.reply.startswith("The best rated for wireless earbuds, from Google Shopping: 1: Luxury Pods, ₹15,900")
    assert r.transactions[0]["type"] == "web_product" and r.transactions[0]["link"]
    assert fake_search == [("wireless earbuds", "in")]  # country from the delivery address
    assert r.pending_action is None  # nothing is ordered
