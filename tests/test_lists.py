"""Tests for X Lists: scrapers, actions, drafts and CLI."""

import pytest
from click.testing import CliRunner

from xactions import actions, caps, drafts
from xactions.actions import create_list, list_add_member, list_remove_member
from xactions.cli import cli
from xactions.scrapers import get_list_members, get_list_tweets


def _tweet_entry(tid):
    return {
        "entryId": f"tweet-{tid}",
        "content": {
            "itemContent": {
                "itemType": "TimelineTweet",
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": tid,
                        "core": {"user_results": {"result": {"rest_id": "1", "legacy": {"screen_name": "a"}}}},
                        "legacy": {"full_text": f"t{tid}", "id_str": tid},
                    }
                }
            }
        },
    }


def _user_entry(uid):
    return {
        "entryId": f"user-{uid}",
        "content": {
            "itemContent": {
                "itemType": "TimelineUser",
                "user_results": {"result": {"rest_id": uid, "legacy": {"screen_name": f"u{uid}"}}},
            }
        },
    }


def _wrap(kind, entries, cursor):
    if cursor:
        entries = entries + [{"entryId": "cursor-bottom-1", "content": {"value": cursor}}]
    return {"data": {"list": {kind: {"timeline": {"instructions": [{"type": "TimelineAddEntries", "entries": entries}]}}}}}


class FakeClient:
    _cookies = {"auth_token": "tok"}

    def __init__(self, pages=None, mutation_result=None):
        self.pages = list(pages or [])
        self.mutation_result = mutation_result
        self.calls = []

    def is_authenticated(self):
        return True

    async def graphql(self, endpoint, variables, features=None, mutation=False):
        self.calls.append((endpoint, dict(variables), mutation))
        if mutation:
            return self.mutation_result
        return self.pages.pop(0)


async def test_get_list_tweets_paginates():
    client = FakeClient(pages=[
        _wrap("tweets_timeline", [_tweet_entry("1"), _tweet_entry("2")], "C1"),
        _wrap("tweets_timeline", [_tweet_entry("3")], None),
    ])
    tweets = await get_list_tweets(client, "99", limit=10)
    assert [t["id"] for t in tweets] == ["1", "2", "3"]
    assert client.calls[0][0] == "ListLatestTweetsTimeline"
    assert client.calls[0][1]["listId"] == "99"
    assert client.calls[1][1]["cursor"] == "C1"


async def test_get_list_members_respects_limit():
    client = FakeClient(pages=[_wrap("members_timeline", [_user_entry("7"), _user_entry("8")], "C1")])
    users = await get_list_members(client, "99", limit=2)
    assert [u["id"] for u in users] == ["7", "8"]
    assert client.calls[0][0] == "ListMembers"
    assert len(client.calls) == 1


@pytest.fixture
def caps_path(tmp_path, monkeypatch):
    p = tmp_path / "caps.json"
    monkeypatch.setattr(caps, "DEFAULT_CAPS_PATH", p)
    return p


async def test_create_list_and_members_are_charged(caps_path):
    client = FakeClient(mutation_result={"data": {"list": {"id_str": "123", "name": "News"}}})
    res = await create_list(client, "News", "desc", private=True)
    assert res == {"success": True, "list_id": "123", "name": "News"}
    assert client.calls[-1] == ("CreateList", {"isPrivate": True, "name": "News", "description": "desc"}, True)

    assert (await list_add_member(client, "123", "42"))["success"]
    assert (await list_remove_member(client, "123", "42"))["success"]
    assert client.calls[-1][:2] == ("ListRemoveMember", {"listId": "123", "userId": "42"})

    data = caps.load_caps(caps_path)
    key = actions._account_key(client)
    for op in ("list_create", "list_add", "list_remove"):
        assert caps.count_in_window(data, op, key) == 1


async def test_create_list_rejects_empty_name(caps_path):
    with pytest.raises(ValueError):
        await create_list(FakeClient(), "  ")


async def test_list_create_cap_blocks_before_x(caps_path):
    caps.save_caps({"events": [], "limits": {"list_create": 0}}, caps_path)
    client = FakeClient(mutation_result={"data": {"list": {"id_str": "1"}}})
    with pytest.raises(caps.WriteCapExceeded):
        await create_list(client, "x")
    assert client.calls == []


async def test_draft_executor_runs_list_actions(monkeypatch):
    seen = []

    async def fake_add(client, list_id, user_id):
        seen.append((list_id, user_id))
        return {"success": True}

    async def fake_user_id(client, username):
        return f"id-{username}"

    monkeypatch.setattr(actions, "list_add_member", fake_add)
    monkeypatch.setattr("xactions.scrapers.get_user_id", fake_user_id)
    res = await drafts.execute_draft(object(), {"action": "list_add", "params": {"list_id": "5", "username": "jack"}})
    assert res == {"success": True} and seen == [("5", "id-jack")]


def test_cli_list_write_saves_draft_when_approval_required(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "DEFAULT_DRAFTS_DIR", tmp_path / "drafts")
    env = {"XACTIONS_REQUIRE_APPROVAL": "1", "TWITTER_COOKIES": "auth_token=a; ct0=b"}
    r = CliRunner().invoke(cli, ["lists", "add", "5", "@jack"], env=env)
    assert r.exit_code == 0, r.output
    assert "Draft saved" in r.output
    (draft,) = drafts.list_drafts()
    assert draft["action"] == "list_add" and draft["params"] == {"list_id": "5", "username": "jack"}
