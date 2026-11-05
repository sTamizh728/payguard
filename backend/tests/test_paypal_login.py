"""
Tests for Log in with PayPal. PayPal and the database are faked,
so these run offline.
"""
import asyncio
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.core.config import settings
from app.services import paypal_login_service as service

NONCE = "a" * 43
OTHER_NONCE = "b" * 43


@pytest.fixture(autouse=True)
def clean_stores():
    service._pending_states.clear()
    service._login_codes.clear()
    yield
    service._pending_states.clear()
    service._login_codes.clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(auth_api.router)
    return TestClient(app, follow_redirects=False)


def start_login(client, nonce=NONCE) -> str:
    response = client.get("/api/auth/paypal/start", params={"app_nonce": nonce})
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0]


def app_link_from(page: str) -> dict:
    match = re.search(r'href="([^"]+)"', page)
    assert match, page
    link = match.group(1).replace("&amp;", "&")
    assert link.startswith(settings.app_auth_redirect_uri + "?")
    return {k: v[0] for k, v in parse_qs(urlparse(link).query).items()}


def fake_paypal_ok(monkeypatch, user_id=7):
    async def fake_profile(code):
        assert code == "paypal-code"
        return {
            "paypal_user_id": "https://www.paypal.com/webapps/auth/identity/user/XYZ",
            "email": "sam@personal.example.com",
            "full_name": "Sam Kumar",
        }

    monkeypatch.setattr(service, "fetch_paypal_profile", fake_profile)
    monkeypatch.setattr(
        auth_api,
        "authenticate_paypal_user",
        lambda **kwargs: SimpleNamespace(id=user_id),
    )


# ---- start ----

def test_start_redirects_to_paypal_with_exact_return_url(client):
    response = client.get("/api/auth/paypal/start", params={"app_nonce": NONCE})

    assert response.status_code == 302
    url = urlparse(response.headers["location"])
    query = parse_qs(url.query)

    assert f"{url.scheme}://{url.netloc}" == settings.paypal_web_base_url
    assert url.path == "/connect/"
    assert query["flowEntry"] == ["static"]
    assert query["client_id"] == [settings.paypal_client_id]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile email"]
    assert query["redirect_uri"] == [settings.paypal_login_redirect_uri]
    assert len(query["state"][0]) >= 32


@pytest.mark.parametrize("bad", ["short", "x" * 31, "has spaces" * 5, "a" * 129, "é" * 40])
def test_start_rejects_bad_nonce(client, bad):
    response = client.get("/api/auth/paypal/start", params={"app_nonce": bad})
    assert response.status_code in (400, 422)


def test_each_start_gets_a_new_state(client):
    assert start_login(client) != start_login(client)


# ---- full flow ----

def test_full_login_flow_gives_a_token(client, monkeypatch):
    fake_paypal_ok(monkeypatch, user_id=7)
    state = start_login(client)

    page = client.get(
        "/api/auth/paypal/callback",
        params={"state": state, "code": "paypal-code"},
    )
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    params = app_link_from(page.text)
    assert set(params) == {"code"}
    # The JWT itself never travels in the link.
    assert "access_token" not in page.text

    response = client.post(
        "/api/auth/paypal/exchange",
        json={"code": params["code"], "app_nonce": NONCE},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"

    import jwt
    claims = jwt.decode(
        body["access_token"],
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert claims["sub"] == "7"


def test_login_code_works_only_once(client, monkeypatch):
    fake_paypal_ok(monkeypatch)
    state = start_login(client)
    code = app_link_from(client.get(
        "/api/auth/paypal/callback",
        params={"state": state, "code": "paypal-code"},
    ).text)["code"]

    payload = {"code": code, "app_nonce": NONCE}
    assert client.post("/api/auth/paypal/exchange", json=payload).status_code == 200
    assert client.post("/api/auth/paypal/exchange", json=payload).status_code == 401


def test_code_with_wrong_nonce_is_refused_and_burned(client, monkeypatch):
    """A code stolen from the redirect is useless without the app's nonce."""
    fake_paypal_ok(monkeypatch)
    state = start_login(client)
    code = app_link_from(client.get(
        "/api/auth/paypal/callback",
        params={"state": state, "code": "paypal-code"},
    ).text)["code"]

    wrong = client.post(
        "/api/auth/paypal/exchange",
        json={"code": code, "app_nonce": OTHER_NONCE},
    )
    assert wrong.status_code == 401

    right = client.post(
        "/api/auth/paypal/exchange",
        json={"code": code, "app_nonce": NONCE},
    )
    assert right.status_code == 401


def test_expired_login_code_is_refused(client, monkeypatch):
    code = service.issue_login_code(7, service._hash_nonce(NONCE))
    real_time = service.time.time
    monkeypatch.setattr(
        service.time,
        "time",
        lambda: real_time() + service.LOGIN_CODE_TTL_SECONDS + 1,
    )

    response = client.post(
        "/api/auth/paypal/exchange",
        json={"code": code, "app_nonce": NONCE},
    )
    assert response.status_code == 401


def test_made_up_code_is_refused(client):
    response = client.post(
        "/api/auth/paypal/exchange",
        json={"code": "z" * 43, "app_nonce": NONCE},
    )
    assert response.status_code == 401


# ---- callback errors ----

def test_callback_without_state(client):
    page = client.get("/api/auth/paypal/callback", params={"code": "paypal-code"})
    assert app_link_from(page.text) == {"error": "missing_state"}


def test_callback_with_unknown_state(client, monkeypatch):
    fake_paypal_ok(monkeypatch)
    page = client.get(
        "/api/auth/paypal/callback",
        params={"state": "forged", "code": "paypal-code"},
    )
    assert app_link_from(page.text) == {"error": "expired"}


def test_state_works_only_once(client, monkeypatch):
    fake_paypal_ok(monkeypatch)
    state = start_login(client)
    params = {"state": state, "code": "paypal-code"}

    assert "code" in app_link_from(client.get("/api/auth/paypal/callback", params=params).text)
    assert app_link_from(
        client.get("/api/auth/paypal/callback", params=params).text
    ) == {"error": "expired"}


def test_expired_state_is_refused(client, monkeypatch):
    fake_paypal_ok(monkeypatch)
    state = start_login(client)
    real_time = service.time.time
    monkeypatch.setattr(
        service.time,
        "time",
        lambda: real_time() + service.STATE_TTL_SECONDS + 1,
    )

    page = client.get(
        "/api/auth/paypal/callback",
        params={"state": state, "code": "paypal-code"},
    )
    assert app_link_from(page.text) == {"error": "expired"}


def test_user_cancelled_on_paypal(client):
    state = start_login(client)
    page = client.get(
        "/api/auth/paypal/callback",
        params={"state": state, "error": "access_denied"},
    )
    assert app_link_from(page.text) == {"error": "cancelled"}


def test_paypal_down(client, monkeypatch):
    async def broken(code):
        raise RuntimeError("PayPal login failed (HTTP 500).")

    monkeypatch.setattr(service, "fetch_paypal_profile", broken)
    state = start_login(client)
    page = client.get(
        "/api/auth/paypal/callback",
        params={"state": state, "code": "paypal-code"},
    )
    assert app_link_from(page.text) == {"error": "paypal_unavailable"}


def test_email_already_used_by_password_account(client, monkeypatch):
    fake_paypal_ok(monkeypatch)

    def conflict(**kwargs):
        raise ValueError("An account with this email already exists.")

    monkeypatch.setattr(auth_api, "authenticate_paypal_user", conflict)
    state = start_login(client)
    page = client.get(
        "/api/auth/paypal/callback",
        params={"state": state, "code": "paypal-code"},
    )
    assert app_link_from(page.text) == {"error": "account_conflict"}


def test_callback_page_escapes_html():
    page = auth_api._back_to_app(error='"><script>alert(1)</script>').body.decode()
    assert "<script>alert(1)" not in page


# ---- talking to PayPal (faked HTTP) ----

def run_fetch(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(service.httpx, "AsyncClient", fake_client)
    return asyncio.run(service.fetch_paypal_profile("paypal-code"))


def test_fetch_profile_reads_paypal_v11_profile(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "user-token"})
        return httpx.Response(200, json={
            "user_id": "https://www.paypal.com/webapps/auth/identity/user/ABC",
            "name": "Sam Kumar",
            "emails": [
                {"value": "other@example.com", "primary": False},
                {"value": "Sam@Personal.Example.com", "primary": True},
            ],
        })

    profile = run_fetch(monkeypatch, handler)

    assert profile == {
        "paypal_user_id": "https://www.paypal.com/webapps/auth/identity/user/ABC",
        "email": "sam@personal.example.com",
        "full_name": "Sam Kumar",
    }
    token_request, profile_request = seen
    assert b"grant_type=authorization_code" in token_request.content
    assert b"code=paypal-code" in token_request.content
    assert token_request.headers["authorization"].startswith("Basic ")
    assert profile_request.url.params["schema"] == "paypalv1.1"
    assert profile_request.headers["authorization"] == "Bearer user-token"


def test_fetch_profile_reads_openid_shape(monkeypatch):
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json={
            "user_id": "U1",
            "name": "Priya Raj",
            "email": "priya@example.com",
        })

    assert run_fetch(monkeypatch, handler)["email"] == "priya@example.com"


def test_fetch_profile_without_email_is_a_clear_error(monkeypatch):
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(200, json={"user_id": "U1", "name": "No Mail"})

    with pytest.raises(ValueError, match="email"):
        run_fetch(monkeypatch, handler)


def test_fetch_profile_hides_paypal_error_details(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "invalid_client", "secret": "leak"})

    with pytest.raises(RuntimeError) as error:
        run_fetch(monkeypatch, handler)

    assert "leak" not in str(error.value)
    assert "401" in str(error.value)


def test_fetch_profile_falls_back_to_openid_endpoint(monkeypatch):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path == "/v1/identity/oauth2/userinfo":
            return httpx.Response(400, json={"error": "invalid_request"})
        return httpx.Response(200, json={
            "user_id": "https://www.paypal.com/webapps/auth/identity/user/OWNER",
            "name": "Voice Pay Agent",
            "email": "Owner@Business.example.com",
        })

    profile = run_fetch(monkeypatch, handler)

    assert paths[-1] == "/v1/identity/openidconnect/userinfo"
    assert profile["email"] == "owner@business.example.com"


def test_fetch_profile_reports_step_and_error_name(monkeypatch):
    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(400, json={"error": "invalid_request", "error_description": "secret detail"})

    with pytest.raises(RuntimeError) as error:
        run_fetch(monkeypatch, handler)

    assert "userinfo (HTTP 400, invalid_request)" in str(error.value)
    assert "secret detail" not in str(error.value)
