"""Tests del throttle proactivo de rate limits."""

import time

import httpx
import pytest
import respx

from xactions.client import RateLimitError, TwitterClient


@pytest.fixture
def client():
    return TwitterClient(cookies="auth_token=a; ct0=b", max_retries=0)


def test_record_rate_limit_from_headers(client):
    url = "https://x.com/i/api/graphql/abc/UserByScreenName"
    resp = httpx.Response(
        200,
        json={"data": {}},
        headers={
            "x-rate-limit-remaining": "3",
            "x-rate-limit-reset": str(int(time.time()) + 900),
        },
    )
    client._record_rate_limit(url, resp)
    status = client.rate_limit_status()
    key = client._rate_limit_key(url)
    assert key in status
    assert status[key]["remaining"] == 3
    assert status[key]["reset"] > time.time()


def test_rate_limit_key_normalizes_query_id():
    c = TwitterClient(cookies="a=b")
    k1 = c._rate_limit_key("https://x.com/i/api/graphql/ID1/UserTweets?foo=1")
    k2 = c._rate_limit_key("https://x.com/i/api/graphql/ID2/UserTweets")
    assert k1 == k2
    assert "UserTweets" in k1


@respx.mock
async def test_proactive_throttle_waits_before_request(monkeypatch):
    """Si remaining=0 y reset en el futuro, espera antes de pegar a la red."""
    client = TwitterClient(
        cookies="auth_token=a; ct0=b",
        max_retries=0,
        max_rate_limit_wait=5.0,
    )
    real_url = "https://x.com/i/api/graphql/NimuplG1OB7Fd2btCLdBOw/UserByScreenName"
    reset_at = int(time.time()) + 2
    client._rate_limits[client._rate_limit_key(real_url)] = {
        "remaining": 0,
        "reset": reset_at,
    }

    slept = {"s": 0.0}

    async def fake_sleep(t):
        slept["s"] += t

    monkeypatch.setattr("xactions.client.asyncio.sleep", fake_sleep)

    respx.get(real_url).mock(
        return_value=httpx.Response(200, json={"data": {"ok": True}})
    )

    data = await client.graphql(
        "UserByScreenName",
        variables={"screen_name": "t"},
        features={"x": True},
    )
    assert data["data"]["ok"] is True
    assert slept["s"] > 0


@respx.mock
async def test_proactive_throttle_skipped_when_remaining_ok():
    client = TwitterClient(cookies="auth_token=a; ct0=b", max_retries=0)
    # remaining > 0 → no debe intentar dormir
    url = "https://x.com/i/api/graphql/NimuplG1OB7Fd2btCLdBOw/UserByScreenName"
    client._rate_limits[client._rate_limit_key(url)] = {
        "remaining": 10,
        "reset": int(time.time()) + 100,
    }
    respx.get(url).mock(return_value=httpx.Response(200, json={"data": {"ok": 1}}))
    data = await client.graphql("UserByScreenName", variables={"screen_name": "t"})
    assert data["data"]["ok"] == 1


@respx.mock
async def test_429_respects_max_rate_limit_wait(monkeypatch):
    client = TwitterClient(
        cookies="auth_token=a; ct0=b",
        max_retries=1,
        max_rate_limit_wait=1.5,
    )
    url = "https://x.com/i/api/graphql/NimuplG1OB7Fd2btCLdBOw/UserByScreenName"
    respx.get(url).mock(
        return_value=httpx.Response(
            429,
            json={},
            headers={"x-rate-limit-reset": str(int(time.time()) + 3600)},
        )
    )
    slept = []

    async def fake_sleep(t):
        slept.append(t)

    monkeypatch.setattr("xactions.client.asyncio.sleep", fake_sleep)

    with pytest.raises(RateLimitError):
        await client.graphql("UserByScreenName", variables={"screen_name": "t"})
    # El wait del 429 debe estar capado a max_rate_limit_wait
    assert slept
    assert all(s <= 1.5 for s in slept)


def test_scrapers_use_larger_page_sizes():
    from xactions.scrapers import (
        PAGE_SIZE_ENGAGEMENT,
        PAGE_SIZE_SEARCH,
        PAGE_SIZE_TWEETS,
        PAGE_SIZE_USERS,
    )

    assert PAGE_SIZE_USERS >= 100
    assert PAGE_SIZE_ENGAGEMENT >= 50
    assert PAGE_SIZE_TWEETS >= 40
    assert PAGE_SIZE_SEARCH == 20  # Search sigue capado por la API
