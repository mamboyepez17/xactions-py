"""Tests para el cliente HTTP de xactions-py."""

import asyncio

import httpx
import pytest
import respx

from xactions.client import (
    BEARER_TOKEN,
    AuthError,
    ForbiddenError,
    RateLimitError,
    TwitterClient,
    TwitterError,
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
    from xactions.client import GRAPHQL_ENDPOINTS
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

    from xactions.client import GRAPHQL_ENDPOINTS
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

    from xactions.client import GRAPHQL_ENDPOINTS
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

    from xactions.client import GRAPHQL_ENDPOINTS
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

    from xactions.client import GRAPHQL_ENDPOINTS
    old = GRAPHQL_ENDPOINTS["UserByScreenName"].copy()
    GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = "123"
    try:
        data = await client.graphql("UserByScreenName", variables={"screen_name": "test"})
        assert data == {"data": {}}
        assert route.call_count == 2
    finally:
        GRAPHQL_ENDPOINTS["UserByScreenName"].update(old)


@respx.mock
async def test_validate_cookies_via_graphql_home(client):
    from xactions.client import GRAPHQL_ENDPOINTS

    qid = GRAPHQL_ENDPOINTS["HomeLatestTimeline"]["queryId"]
    respx.post(f"https://x.com/i/api/graphql/{qid}/HomeLatestTimeline").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "home": {
                        "home_timeline_urt": {
                            "instructions": [
                                {
                                    "type": "TimelineAddEntries",
                                    "entries": [
                                        {
                                            "entryId": "tweet-1",
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "core": {
                                                                "user_results": {
                                                                    "result": {
                                                                        "rest_id": "42",
                                                                        "legacy": {
                                                                            "screen_name": "test"
                                                                        },
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            },
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            },
        )
    )

    result = await client.validate_cookies()
    assert result["valid"] is True
    assert result["username"] == "test"
    assert result["user_id"] == "42"


async def test_parse_cookies_url_encoding():
    client = TwitterClient(cookies="auth_token=abc%3D123; ct0=xyz%2B")
    assert client._cookies["auth_token"] == "abc=123"
    assert client._cookies["ct0"] == "xyz+"


@respx.mock
async def test_mutation_not_retried_on_network_error():
    client = TwitterClient(cookies="auth_token=abc; ct0=xyz", max_retries=2)
    route = respx.post("https://x.com/i/api/graphql/123/FavoriteTweet").mock(
        side_effect=httpx.ConnectError("Connection failed")
    )

    from xactions.client import GRAPHQL_ENDPOINTS
    old = GRAPHQL_ENDPOINTS["FavoriteTweet"].copy()
    GRAPHQL_ENDPOINTS["FavoriteTweet"]["queryId"] = "123"
    try:
        with pytest.raises(TwitterError):
            await client.graphql("FavoriteTweet", variables={"tweet_id": "1"}, mutation=True)
    finally:
        GRAPHQL_ENDPOINTS["FavoriteTweet"].update(old)

    # Las mutations no se reintentan para evitar acciones duplicadas.
    assert route.call_count == 1


@respx.mock
async def test_csrf_token_updated_from_response(client):
    respx.get("https://x.com/i/api/graphql/123/UserByScreenName").mock(
        return_value=httpx.Response(
            200,
            json={"data": {}},
            headers={"Set-Cookie": "ct0=newtoken; Path=/; Domain=.x.com"},
        )
    )

    from xactions.client import GRAPHQL_ENDPOINTS
    old = GRAPHQL_ENDPOINTS["UserByScreenName"].copy()
    GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = "123"
    try:
        await client.graphql("UserByScreenName", variables={"screen_name": "test"})
    finally:
        GRAPHQL_ENDPOINTS["UserByScreenName"].update(old)

    assert client._csrf_token == "newtoken"
    assert "ct0=newtoken" in client._cookie_str


async def test_close_inside_running_loop_does_not_crash():
    client = TwitterClient(cookies="auth_token=a; ct0=b")
    client.close()  # antes esto lanzaba RuntimeError desde un loop corriendo
    await asyncio.sleep(0.01)  # deja correr la tarea de cierre programada
    assert client._closed is True


def test_close_sync_without_loop():
    client = TwitterClient(cookies="auth_token=a; ct0=b")
    client.close()
    assert client._closed is True
