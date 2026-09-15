"""Tests B1: declarative pipeline."""

from pathlib import Path

import pytest

from xactions.pipeline import apply_filter, load_pipeline, run_pipeline


def test_load_valid_pipeline():
    p = load_pipeline({"name": "t", "steps": [{"type": "search", "query": "ai"}]})
    assert p["name"] == "t"
    assert p["steps"][0]["type"] == "search"


def test_load_rejects_bad_steps():
    with pytest.raises(ValueError):
        load_pipeline({"steps": []})
    with pytest.raises(ValueError):
        load_pipeline({"steps": [{"type": "nope"}]})
    with pytest.raises(ValueError):
        load_pipeline({"name": "x"})


def test_load_from_file(tmp_path: Path):
    f = tmp_path / "p.json"
    f.write_text('{"steps": [{"type": "print"}]}', encoding="utf-8")
    p = load_pipeline(f)
    assert p["steps"][0]["type"] == "print"


def test_apply_filter_rules():
    tweets = [
        {"id": "1", "likes": 10, "retweets": 0, "is_retweet": False, "is_reply": False, "lang": "es", "text": "hola crypto"},
        {"id": "2", "likes": 0, "retweets": 5, "is_retweet": True, "is_reply": False, "lang": "en", "text": "rt"},
        {"id": "3", "likes": 50, "retweets": 1, "is_retweet": False, "is_reply": True, "lang": "es", "text": "reply crypto"},
        {"id": "4", "likes": 100, "retweets": 2, "is_retweet": False, "is_reply": False, "lang": "en", "text": "other"},
    ]
    out = apply_filter(tweets, {"min_likes": 10, "exclude_retweets": True, "exclude_replies": True})
    assert [t["id"] for t in out] == ["1", "4"]
    out2 = apply_filter(tweets, {"lang": "en"})
    assert [t["id"] for t in out2] == ["2", "4"]
    out3 = apply_filter(tweets, {"contains": "crypto"})
    assert [t["id"] for t in out3] == ["1", "3"]


async def test_run_pipeline_search_filter_notify(monkeypatch):
    fake_tweets = [
        {"id": "a", "likes": 20, "retweets": 0, "is_retweet": False, "is_reply": False, "text": "hot"},
        {"id": "b", "likes": 1, "retweets": 0, "is_retweet": False, "is_reply": False, "text": "cold"},
    ]

    async def fake_search(client, query, limit=20, mode="Latest"):
        assert query == "hot topic"
        return list(fake_tweets)

    monkeypatch.setattr("xactions.scrapers.search_tweets", fake_search)
    # pipeline imports search from .scrapers inside run_pipeline — patch there

    # re-import binding inside function: patch scrapers module used at call time
    import xactions.scrapers as scrapers

    monkeypatch.setattr(scrapers, "search_tweets", fake_search)

    messages = []
    result = await run_pipeline(
        object(),
        {
            "name": "test",
            "steps": [
                {"type": "search", "query": "hot topic", "limit": 10},
                {"type": "filter", "min_likes": 10},
                {"type": "notify", "message": "hits={count}"},
            ],
        },
        dry_run=True,
        notify_fn=messages.append,
    )
    assert result["final_count"] == 1
    assert result["tweets"][0]["id"] == "a"
    assert messages == ["hits=1"]
    assert result["log"][0]["type"] == "search"


async def test_like_step_dry_run(monkeypatch):
    async def fake_search(client, query, limit=20, mode="Latest"):
        return [{"id": "1", "likes": 1}]

    import xactions.scrapers as scrapers

    monkeypatch.setattr(scrapers, "search_tweets", fake_search)
    result = await run_pipeline(
        object(),
        {
            "steps": [
                {"type": "search", "query": "x"},
                {"type": "like"},
            ]
        },
        dry_run=True,
    )
    assert result["log"][-1]["dry_run"] is True
    assert result["log"][-1]["would_like"] == 1


def test_cli_pipeline_registered():
    from xactions.cli import cli

    assert "pipeline" in cli.commands
