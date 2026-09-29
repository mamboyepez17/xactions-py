"""Regression tests for the write-safety fixes (caps key, non-followers, MCP gate/filter)."""

import subprocess
import sys

import pytest

from xactions import actions, caps, drafts
from xactions.actions import _account_key, bulk_unfollow
from xactions.caps import WriteCapExceeded
from xactions.client import TwitterClient, TwitterError
from xactions.mcp_groups import apply_env_filter_to_mcp
from xactions.pool import ClientPool
from xactions.scrapers import clear_user_id_cache, scrape_non_followers

# ─── Write caps account key ───────────────────────────────────────────────────


def test_account_key_stable_across_processes():
    code = (
        "from xactions.client import TwitterClient;"
        "from xactions.actions import _account_key;"
        "print(_account_key(TwitterClient(cookies='auth_token=abc; ct0=x')))"
    )
    keys = {
        subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
        for _ in range(3)
    }
    assert len(keys) == 1
    assert keys == {_account_key(TwitterClient(cookies="auth_token=abc; ct0=x"))}


def test_account_key_does_not_leak_token():
    key = _account_key(TwitterClient(cookies="auth_token=supersecret; ct0=x"))
    assert "supersecret" not in key


def test_account_key_pool_uses_current_account():
    pool = ClientPool(["auth_token=a1; ct0=x", "auth_token=a2; ct0=y"])
    first = _account_key(pool)
    assert first == _account_key(TwitterClient(cookies="auth_token=a1; ct0=x"))
    pool._rotate()
    assert _account_key(pool) == _account_key(TwitterClient(cookies="auth_token=a2; ct0=y"))
    assert _account_key(pool) != first


async def test_bulk_unfollow_stops_when_cap_reached(monkeypatch):
    calls = []

    async def fake_unfollow(client, uid):
        calls.append(uid)
        if len(calls) > 2:
            raise WriteCapExceeded("cap")
        return {"success": True}

    monkeypatch.setattr(actions, "unfollow_user", fake_unfollow)
    client = TwitterClient(cookies="auth_token=a; ct0=b")
    result = await bulk_unfollow(client, ["1", "2", "3", "4", "5"], delay_seconds=0)
    assert calls == ["1", "2", "3"]
    assert result["success"] == 2
    assert result["stopped"] == "cap"


# ─── Non-followers ────────────────────────────────────────────────────────────


def _user(uid: str) -> dict:
    return {
        "entryId": f"user-{uid}",
        "content": {
            "itemContent": {
                "itemType": "TimelineUser",
                "user_results": {"result": {"rest_id": uid, "legacy": {"screen_name": f"u{uid}"}}},
            }
        },
    }


def _page(uids: list[str], cursor: str | None) -> dict:
    entries = [_user(u) for u in uids]
    if cursor:
        entries.append({"entryId": "cursor-bottom-1", "content": {"value": cursor}})
    return {
        "data": {
            "user": {
                "result": {
                    "timeline": {"timeline": {"instructions": [{"type": "TimelineAddEntries", "entries": entries}]}}
                }
            }
        }
    }


class FakeGraphClient:
    """Serves UserByScreenName + paginated Followers/Following from fixed lists."""

    def __init__(self, following: list[str], followers: list[str], followers_count: int | None = None):
        self.lists = {"Following": following, "Followers": followers}
        self.followers_count = len(followers) if followers_count is None else followers_count

    def is_authenticated(self) -> bool:
        return True

    async def graphql(self, endpoint, variables, features=None, mutation=False):
        if endpoint == "UserByScreenName":
            return {
                "data": {
                    "user": {
                        "result": {
                            "rest_id": "42",
                            "legacy": {"screen_name": "me", "followers_count": self.followers_count},
                        }
                    }
                }
            }
        items = self.lists[endpoint]
        start = int(variables.get("cursor") or 0)
        end = start + variables["count"]
        return _page(items[start:end], str(end) if end < len(items) else None)


async def test_non_followers_uses_full_follower_list():
    clear_user_id_cache()
    following = [str(i) for i in range(10)]
    # Everyone followed back, but the follower list is much longer than `limit`
    # and the people we follow sit at its end.
    followers = [str(i) for i in range(1000, 1500)] + following
    client = FakeGraphClient(following, followers)
    result = await scrape_non_followers(client, "me", limit=10)
    assert result == []


async def test_non_followers_detects_real_non_followers():
    clear_user_id_cache()
    client = FakeGraphClient(["1", "2", "3"], ["2", "9"])
    result = await scrape_non_followers(client, "me", limit=10)
    assert [u["id"] for u in result] == ["1", "3"]


async def test_non_followers_refuses_incomplete_follower_list():
    clear_user_id_cache()
    client = FakeGraphClient(["1", "2"], ["2"], followers_count=500)
    with pytest.raises(TwitterError, match="Incomplete follower list"):
        await scrape_non_followers(client, "me", limit=10)


# ─── Drafts executor ──────────────────────────────────────────────────────────


async def test_execute_draft_routes_actions(monkeypatch):
    seen = []

    async def fake_like(client, tweet_id):
        seen.append(("like", tweet_id))
        return {"success": True}

    monkeypatch.setattr(actions, "like_tweet", fake_like)
    result = await drafts.execute_draft(object(), {"action": "like", "params": {"tweet_id": "7"}})
    assert result == {"success": True}
    assert seen == [("like", "7")]

    with pytest.raises(ValueError):
        await drafts.execute_draft(object(), {"action": "nope", "params": {}})


# ─── MCP approval gate + tool filter ──────────────────────────────────────────


@pytest.fixture
def mcp_server(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    monkeypatch.delenv("XACTIONS_MCP_TOOLS", raising=False)
    monkeypatch.delenv("XACTIONS_MCP_TOOLS_EXCLUDE", raising=False)
    from xactions import mcp_server

    monkeypatch.setattr(drafts, "DEFAULT_DRAFTS_DIR", tmp_path / "drafts")
    monkeypatch.setattr(caps, "DEFAULT_CAPS_PATH", tmp_path / "caps.json")
    return mcp_server


async def test_mcp_write_tools_draft_when_approval_required(mcp_server, monkeypatch):
    monkeypatch.setenv("XACTIONS_REQUIRE_APPROVAL", "1")

    def no_client(*a, **k):
        raise AssertionError("write reached the client despite approval gate")

    monkeypatch.setattr(mcp_server, "get_client", no_client)

    for call in (
        mcp_server.x_post_tweet("hi"),
        mcp_server.x_post_thread(["a", "b"]),
        mcp_server.x_like_tweet("1"),
        mcp_server.x_unlike_tweet("1"),
        mcp_server.x_retweet("1"),
        mcp_server.x_delete_tweet("1"),
        mcp_server.x_follow_user("jack"),
        mcp_server.x_unfollow_user("jack"),
        mcp_server.x_bookmark_tweet("1"),
        mcp_server.x_unbookmark_tweet("1"),
        mcp_server.x_create_list("news"),
        mcp_server.x_add_list_member("5", "jack"),
        mcp_server.x_remove_list_member("5", "jack"),
    ):
        out = await call
        assert "Approval required" in out

    pending = drafts.list_drafts()
    assert {d["action"] for d in pending} == drafts.DRAFT_ACTIONS


def test_mcp_does_not_expose_self_approval(mcp_server):
    assert not hasattr(mcp_server, "x_approve_draft")
    assert "x_approve_draft" not in mcp_server.ADVERTISED_TOOLS
    assert "x_discard_draft" in mcp_server.ADVERTISED_TOOLS


def test_filter_fails_closed_without_registry(monkeypatch):
    monkeypatch.setenv("XACTIONS_MCP_TOOLS_EXCLUDE", "write")

    class OpaqueMCP:
        pass

    with pytest.raises(RuntimeError):
        apply_env_filter_to_mcp(OpaqueMCP())


def test_filter_uses_public_remove_tool(monkeypatch):
    monkeypatch.setenv("XACTIONS_MCP_TOOLS_EXCLUDE", "write")

    class TM:
        def __init__(self):
            self._tools = {"x_get_profile": 1, "x_post_tweet": 2}

    class MCP:
        def __init__(self):
            self._tool_manager = TM()

        def remove_tool(self, name):
            del self._tool_manager._tools[name]

    m = MCP()
    assert apply_env_filter_to_mcp(m) == ["x_get_profile"]
    assert list(m._tool_manager._tools) == ["x_get_profile"]
