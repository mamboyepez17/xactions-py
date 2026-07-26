"""Tests para el cliente HTTP de xactions-py."""

import httpx
import pytest
import respx

from src.scraper.client import (
    TwitterClient,
    TwitterError,
    RateLimitError,
    AuthError,
    ForbiddenError,
    NotFoundError,
    BEARER_TOKEN,
)


@pytest.fixture
def client():
    return TwitterClient(cookies="auth_token=abc; ct0=xyz")


@respx.mock
async def test_graphql_success(client):
    route = respx.get("https://x.com/i/api/graphql/123/UserByScreenName").mock(
        return_value=httpx.Response(200, json={"data": {"user": {"result": {"rest_id": "42"}}}})
    )

    # Sobrescribimos endpoint para el test
    from src.scraper.client import GRAPHQL_ENDPOINTS
    old = GRAPHQL_ENDPOINTS["UserByScreenName"].copy()
    GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = "123"
    try:
        data = await client.graphql(
            "UserByScreenName",
            variables={"screen_name": "test"},
            features={"test_feature": True},
        )
    finally:
        GRAPHQL_ENDPOINTS["UserByScreenName"].update(old)

    assert data["data"]["user"]["result"]["rest_id"] == "42"
    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {BEARER_TOKEN}"
    assert request.headers["x-csrf-token"] == "xyz"


@respx.mock
async def test_rate_limit_raises(client):
    respx.get("https://x.com/i/api/graphql/123/UserByScreenName").mock(
        return_value=httpx.Response(
            429,
            json={"errors": [{"code": 88, "message": "Rate limit exceeded"}]},
            headers={"retry-after": "0.5"},
        )
    )

    from src.scraper.client import GRAPHQL_ENDPOINTS
    old = GRAPHQL_ENDPOINTS["UserByScreenName"].copy()
    GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = "123"
    try:
        with pytest.raises(RateLimitError):
            await client.graphql("UserByScreenName", variables={"screen_name": "test"})
    finally:
        GRAPHQL_ENDPOINTS["UserByScreenName"].update(old)


@respx.mock
async def test_auth_error(client):
    respx.get("https://x.com/i/api/graphql/123/UserByScreenName").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )

    from src.scraper.client import GRAPHQL_ENDPOINTS
    old = GRAPHQL_ENDPOINTS["UserByScreenName"].copy()
    GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = "123"
    try:
        with pytest.raises(AuthError):
            await client.graphql("UserByScreenName", variables={"screen_name": "test"})
    finally:
        GRAPHQL_ENDPOINTS["UserByScreenName"].update(old)


@respx.mock
async def test_forbidden_error(client):
    respx.post("https://x.com/i/api/graphql/123/SearchTimeline").mock(
        return_value=httpx.Response(403, json={"error": "Forbidden"})
    )

    from src.scraper.client import GRAPHQL_ENDPOINTS
    old = GRAPHQL_ENDPOINTS["SearchTimeline"].copy()
    GRAPHQL_ENDPOINTS["SearchTimeline"]["queryId"] = "123"
    try:
        with pytest.raises(ForbiddenError):
            await client.graphql("SearchTimeline", variables={"rawQuery": "test"})
    finally:
        GRAPHQL_ENDPOINTS["SearchTimeline"].update(old)


@respx.mock
async def test_network_retry():
    client = TwitterClient(cookies="auth_token=abc; ct0=xyz", max_retries=1)
    route = respx.get("https://x.com/i/api/graphql/123/UserByScreenName").mock(
        side_effect=[httpx.ConnectError("Connection failed"), httpx.Response(200, json={"data": {}})]
    )

    from src.scraper.client import GRAPHQL_ENDPOINTS
    old = GRAPHQL_ENDPOINTS["UserByScreenName"].copy()
    GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = "123"
    try:
        data = await client.graphql("UserByScreenName", variables={"screen_name": "test"})
        assert data == {"data": {}}
        assert route.call_count == 2
    finally:
        GRAPHQL_ENDPOINTS["UserByScreenName"].update(old)


@respx.mock
async def test_rest_get_verify_credentials(client):
    route = respx.get("https://x.com/i/api/1.1/account/verify_credentials.json").mock(
        return_value=httpx.Response(200, json={"id_str": "42", "screen_name": "test", "name": "Test"})
    )

    result = await client.validate_cookies()
    assert result["valid"] is True
    assert result["username"] == "test"
    assert route.called


async def test_parse_cookies_url_encoding():
    client = TwitterClient(cookies="auth_token=abc%3D123; ct0=xyz%2B")
    assert client._cookies["auth_token"] == "abc=123"
    assert client._cookies["ct0"] == "xyz+"
