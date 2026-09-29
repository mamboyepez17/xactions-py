"""Regression tests for pool 403 handling, caps hardening and non-blocking notify."""

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from xactions import actions, caps
from xactions.caps import CapsFileError, load_caps, save_caps, try_charge
from xactions.client import ForbiddenError
from xactions.notify import make_notifier
from xactions.pool import ClientPool

# ─── Pool ─────────────────────────────────────────────────────────────────────


class _Stub:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def is_authenticated(self):
        return True

    async def graphql(self, *a, **k):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def aclose(self):
        pass


async def test_pool_forbidden_does_not_kill_account():
    c0, c1 = _Stub(ForbiddenError("protected")), _Stub({"data": "ok"})
    pool = ClientPool(clients=[c0, c1])
    with pytest.raises(ForbiddenError):
        await pool.graphql("TweetDetail", variables={})
    assert pool._dead == set()
    assert pool.current is c0
    assert c1.calls == 0


# ─── Caps file ────────────────────────────────────────────────────────────────


def test_corrupt_caps_file_fails_closed(tmp_path: Path):
    p = tmp_path / "caps.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(CapsFileError):
        load_caps(p, strict=True)
    with pytest.raises(CapsFileError):
        try_charge("tweet", "acct:a", path=p)
    # reporting paths stay lenient
    assert load_caps(p)["events"] == []


def test_non_object_caps_file_fails_closed(tmp_path: Path):
    p = tmp_path / "caps.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(CapsFileError):
        load_caps(p, strict=True)


def test_save_caps_is_atomic(tmp_path: Path):
    p = tmp_path / "caps.json"
    save_caps({"events": [], "limits": {}}, p)
    save_caps({"events": [{"op": "tweet", "account": "a", "ts": 1.0}], "limits": {}}, p)
    assert json.loads(p.read_text(encoding="utf-8"))["events"][0]["op"] == "tweet"
    assert [f.name for f in tmp_path.iterdir()] == ["caps.json"]


# ─── Every write is charged ───────────────────────────────────────────────────


class _WriteClient:
    """Answers every mutation with a success payload for its action."""

    _cookies = {"auth_token": "tok"}

    def __init__(self):
        self.calls: list[str] = []
        self._n = 0

    def is_authenticated(self):
        return True

    async def graphql(self, endpoint, variables, features=None, mutation=False):
        self.calls.append(endpoint)
        self._n += 1
        return {
            "data": {
                "unfavorite_tweet": "Done",
                "create_retweet": {"retweet_results": {"result": {"rest_id": "1"}}},
                "create_tweet": {"tweet_results": {"result": {"rest_id": str(self._n)}}},
            }
        }


@pytest.fixture
def caps_path(tmp_path, monkeypatch):
    p = tmp_path / "caps.json"
    monkeypatch.setattr(caps, "DEFAULT_CAPS_PATH", p)
    return p


@pytest.mark.parametrize(
    ("fn", "op"),
    [
        (actions.unlike_tweet, "unlike"),
        (actions.retweet, "retweet"),
        (actions.unretweet, "unretweet"),
        (actions.delete_tweet, "delete"),
        (actions.create_bookmark, "bookmark"),
        (actions.delete_bookmark, "unbookmark"),
    ],
)
async def test_write_is_charged_and_capped(caps_path, fn, op):
    client = _WriteClient()
    save_caps({"events": [], "limits": {op: 1}}, caps_path)

    assert (await fn(client, "1"))["success"]
    data = load_caps(caps_path)
    assert caps.count_in_window(data, op, actions._account_key(client)) == 1

    with pytest.raises(caps.WriteCapExceeded):
        await fn(client, "2")
    assert len(client.calls) == 1  # the capped call never reached X


async def test_thread_tweets_are_charged(caps_path):
    client = _WriteClient()
    save_caps({"events": [], "limits": {"thread_tweet": 2}}, caps_path)
    result = await actions.post_thread(client, ["a", "b"], delay_seconds=0)
    assert result["success"]
    data = load_caps(caps_path)
    key = actions._account_key(client)
    assert caps.count_in_window(data, "thread_tweet", key) == 2
    assert caps.count_in_window(data, "tweet", key) == 2

    with pytest.raises(caps.WriteCapExceeded):
        await actions.post_thread(client, ["c"], delay_seconds=0)


# ─── Notify ───────────────────────────────────────────────────────────────────


async def test_notifier_does_not_block_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow_post(*a, **k):
        started.set()
        release.wait(5)

    monkeypatch.setattr("xactions.notify.httpx.post", slow_post)
    notify = make_notifier("https://example.test/hook")

    t0 = time.monotonic()
    notify("hello")
    assert time.monotonic() - t0 < 0.5  # returned without waiting for the POST
    await asyncio.to_thread(started.wait, 5)
    assert started.is_set()
    release.set()
