"""Tests de features B5: query builder, thread, compare."""

import pytest
import respx

from xactions.actions import post_thread
from xactions.analyzer import compare_accounts
from xactions.client import AuthError, TwitterClient
from xactions.search_query import build_search_query


def test_build_search_query_basic():
    q = build_search_query("crypto", from_user="elonmusk", min_faves=100, lang="es")
    assert "crypto" in q
    assert "from:elonmusk" in q
    assert "min_faves:100" in q
    assert "lang:es" in q


def test_build_search_query_strips_at_and_hash():
    q = build_search_query("", from_user="@jack", hashtag="#AI", exclude_retweets=True)
    assert "from:jack" in q
    assert "#AI" in q
    assert "-filter:retweets" in q


def test_build_search_query_phrase_quoted():
    q = build_search_query(phrase="hello world")
    assert '"hello world"' in q


def test_build_search_query_dates():
    q = build_search_query("ai", since="2026-01-01", until="2026-02-01")
    assert "since:2026-01-01" in q
    assert "until:2026-02-01" in q


def test_build_search_query_empty_base_only_flags():
    q = build_search_query("", filter_media=True, lang="en")
    assert set(q.strip().split()) == {"filter:media", "lang:en"}


@respx.mock
async def test_post_thread_chains_replies(monkeypatch):
    client = TwitterClient(cookies="auth_token=a; ct0=b")
    ids = ["111", "222", "333"]
    calls = []

    async def fake_post(c, text, reply_to_id=None, media_ids=None):
        idx = len(calls)
        calls.append({"text": text, "reply_to_id": reply_to_id})
        return {"success": True, "tweet_id": ids[idx]}

    monkeypatch.setattr("xactions.actions.post_tweet", fake_post)
    slept = []

    async def fake_sleep(t):
        slept.append(t)

    monkeypatch.setattr("xactions.actions.asyncio.sleep", fake_sleep)

    result = await post_thread(client, ["uno", "dos", "tres"], delay_seconds=0.01)
    assert result["success"] is True
    assert result["tweet_ids"] == ids
    assert result["root_id"] == "111"
    assert calls[0]["reply_to_id"] is None
    assert calls[1]["reply_to_id"] == "111"
    assert calls[2]["reply_to_id"] == "222"
    assert len(slept) == 2


async def test_post_thread_requires_auth():
    client = TwitterClient(cookies="")
    with pytest.raises(AuthError):
        await post_thread(client, ["hola"])


def test_compare_accounts_side_by_side():
    profile_a = {
        "username": "alice",
        "name": "Alice",
        "followers": 1000,
        "following": 10,
        "tweets_count": 50,
        "verified": False,
    }
    profile_b = {
        "username": "bob",
        "name": "Bob",
        "followers": 500,
        "following": 20,
        "tweets_count": 80,
        "verified": True,
    }
    tweets_a = [
        {
            "id": "1",
            "text": "hi",
            "likes": 10,
            "retweets": 2,
            "replies": 1,
            "quotes": 0,
            "views": 100,
            "created_at": "Mon Jun 21 12:00:00 +0000 2026",
        }
    ]
    tweets_b = [
        {
            "id": "2",
            "text": "yo",
            "likes": 50,
            "retweets": 10,
            "replies": 5,
            "quotes": 1,
            "views": 500,
            "created_at": "Mon Jun 21 12:00:00 +0000 2026",
        }
    ]
    report = compare_accounts(profile_a, tweets_a, profile_b, tweets_b)
    assert report["a"]["username"] == "alice"
    assert report["b"]["username"] == "bob"
    assert report["winner"]["followers"] == "alice"
    assert report["winner"]["avg_likes"] == "bob"
    assert report["a"]["engagement_rate_followers"] is not None


def test_cli_search_flags_importable():
    from click.testing import CliRunner

    from xactions.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["search", "--help"])
    assert result.exit_code == 0
    assert "--min-faves" in result.output
    assert "--from" in result.output
    assert "--exclude-retweets" in result.output


def test_cli_thread_and_compare_registered():
    from xactions.cli import cli

    assert "thread" in cli.commands
    assert "compare" in cli.commands
