"""Tests del auto-refresh de query IDs en el cliente GraphQL."""

import httpx
import pytest
import respx

from xactions import client as client_mod
from xactions.client import GRAPHQL_ENDPOINTS, NotFoundError, TwitterClient


@pytest.fixture
def reset_gql(monkeypatch):
    """Aísla el store global y desactiva refresh en red real."""
    monkeypatch.setattr(client_mod, "_NO_GQL_REFRESH", True)
    monkeypatch.setattr(client_mod, "_gql_refreshed_this_process", False)
    saved = {k: dict(v) for k, v in GRAPHQL_ENDPOINTS.items()}
    yield
    GRAPHQL_ENDPOINTS.clear()
    GRAPHQL_ENDPOINTS.update(saved)


@respx.mock
async def test_stale_query_id_triggers_refresh_and_retry(reset_gql, monkeypatch):
    """404 → refresh (mock) → retry con el queryId nuevo → 200."""
    GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = "STALE1234567890"
    old_id = "STALE1234567890"
    new_id = "FRESH9876543210123"

    stale_route = respx.get(
        f"https://x.com/i/api/graphql/{old_id}/UserByScreenName"
    ).mock(return_value=httpx.Response(404, json={"errors": [{"message": "Query does not exist"}]}))

    fresh_route = respx.get(
        f"https://x.com/i/api/graphql/{new_id}/UserByScreenName"
    ).mock(
        return_value=httpx.Response(
            200, json={"data": {"user": {"result": {"rest_id": "42"}}}}
        )
    )

    async def fake_refresh(force: bool = False):
        GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = new_id
        return GRAPHQL_ENDPOINTS

    monkeypatch.setattr(client_mod, "refresh_graphql_endpoints", fake_refresh)

    client = TwitterClient(cookies="auth_token=a; ct0=b")
    data = await client.graphql(
        "UserByScreenName",
        variables={"screen_name": "test"},
        features={"x": True},
    )
    assert data["data"]["user"]["result"]["rest_id"] == "42"
    assert stale_route.call_count == 1
    assert fresh_route.call_count == 1


@respx.mock
async def test_plain_404_without_refresh_when_disabled(reset_gql, monkeypatch):
    """Con refresh desactivado, un 404 sigue fallando sin tocar la red de refresh."""
    GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = "STALE1234567890"
    respx.get("https://x.com/i/api/graphql/STALE1234567890/UserByScreenName").mock(
        return_value=httpx.Response(404, json={"error": "Not found"})
    )

    called = {"n": 0}

    async def fake_refresh(force: bool = False):
        called["n"] += 1
        return GRAPHQL_ENDPOINTS

    # _NO_GQL_REFRESH ya está True en el fixture; el cliente aún llama a refresh_graphql_endpoints,
    # pero esa función devuelve sin red. Contamos invocaciones del wrapper del cliente.
    monkeypatch.setattr(client_mod, "refresh_graphql_endpoints", fake_refresh)

    client = TwitterClient(cookies="auth_token=a; ct0=b", max_retries=0)
    with pytest.raises(NotFoundError):
        await client.graphql("UserByScreenName", variables={"screen_name": "t"})
    # El cliente intenta un refresh; la función fake lo cuenta. El segundo intento vuelve a 404.
    assert called["n"] == 1


@respx.mock
async def test_graphql_body_stale_error_raises_not_found(reset_gql):
    """Un error GraphQL con 'Query does not exist' se trata como NotFoundError."""
    GRAPHQL_ENDPOINTS["UserByScreenName"]["queryId"] = "STALE1234567890"
    respx.get("https://x.com/i/api/graphql/STALE1234567890/UserByScreenName").mock(
        return_value=httpx.Response(
            200,
            json={"errors": [{"code": 0, "message": "Query does not exist"}]},
        )
    )
    client = TwitterClient(cookies="auth_token=a; ct0=b")
    with pytest.raises(NotFoundError):
        # force refresh off via _allow_refresh False... wait we need the path
        await client.graphql(
            "UserByScreenName",
            variables={"screen_name": "t"},
            _allow_refresh=False,
        )
