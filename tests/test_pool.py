"""Tests para el ClientPool (rotación multi-cuenta)."""

import pytest

from xactions.client import AuthError, RateLimitError, TwitterError
from xactions.pool import ClientPool


class StubClient:
    """Cliente falso con comportamiento programable."""

    def __init__(self, name, behavior):
        self.name = name
        self.behavior = behavior  # lista de excepciones o valores de retorno
        self.calls = 0
        self.closed = False

    async def graphql(self, *args, **kwargs):
        result = self.behavior[min(self.calls, len(self.behavior) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result

    def is_authenticated(self):
        return True

    async def aclose(self):
        self.closed = True

    async def validate_cookies(self):
        if isinstance(self.behavior[0], Exception):
            return {"valid": False, "error": str(self.behavior[0])}
        return {"valid": True, "username": self.name, "user_id": "1"}


def test_pool_requires_clients():
    with pytest.raises(ValueError):
        ClientPool(cookies_list=[])


async def test_pool_rotates_on_rate_limit():
    c0 = StubClient("c0", [RateLimitError("limited"), RateLimitError("limited")])
    c1 = StubClient("c1", [{"data": "ok"}])
    pool = ClientPool(clients=[c0, c1])

    result = await pool.graphql("UserByScreenName", variables={})
    assert result == {"data": "ok"}
    assert c0.calls == 1
    assert c1.calls == 1
    assert pool.current is c1


async def test_pool_marks_dead_on_auth_error():
    c0 = StubClient("c0", [AuthError("bad cookies")])
    c1 = StubClient("c1", [{"data": "ok"}])
    pool = ClientPool(clients=[c0, c1])

    result = await pool.graphql("UserByScreenName", variables={})
    assert result == {"data": "ok"}
    assert 0 in pool._dead
    assert pool.alive == 1


async def test_pool_raises_when_all_dead():
    c0 = StubClient("c0", [AuthError("bad")])
    pool = ClientPool(clients=[c0])

    with pytest.raises(TwitterError):
        await pool.graphql("UserByScreenName", variables={})


async def test_pool_validate_all_accounts():
    c0 = StubClient("good", [{"data": "ok"}])
    c1 = StubClient("bad", [AuthError("bad")])
    pool = ClientPool(clients=[c0, c1])

    result = await pool.validate_cookies()
    assert result["total"] == 2
    assert result["alive"] == 1
    assert result["accounts"][0]["valid"] is True
    assert result["accounts"][1]["valid"] is False


async def test_pool_aclose_closes_all():
    c0 = StubClient("c0", [{}])
    c1 = StubClient("c1", [{}])
    pool = ClientPool(clients=[c0, c1])
    await pool.aclose()
    assert c0.closed and c1.closed
