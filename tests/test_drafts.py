"""Tests B2: write drafts + approval gate."""

from pathlib import Path

from xactions.drafts import (
    approve,
    create_draft,
    discard,
    list_drafts,
    load_draft,
    mark_executed,
    maybe_draft_or_run,
)


def test_create_and_list(tmp_path: Path):
    d1 = create_draft("post_tweet", {"text": "hola"}, path=tmp_path)
    d2 = create_draft("like", {"tweet_id": "1"}, path=tmp_path)
    pending = list_drafts(path=tmp_path)
    assert len(pending) == 2
    assert pending[0]["action"] == "post_tweet"
    assert load_draft(d1["id"], tmp_path)["params"]["text"] == "hola"
    assert d2["status"] == "pending"


def test_approve_discard(tmp_path: Path):
    d = create_draft("like", {"tweet_id": "9"}, path=tmp_path)
    approve(d["id"], tmp_path)
    assert load_draft(d["id"], tmp_path)["status"] == "approved"
    d2 = create_draft("like", {"tweet_id": "8"}, path=tmp_path)
    discard(d2["id"], tmp_path)
    assert load_draft(d2["id"], tmp_path)["status"] == "discarded"
    assert len(list_drafts(path=tmp_path)) == 0  # no pending left


def test_mark_executed(tmp_path: Path):
    d = create_draft("post_tweet", {"text": "x"}, path=tmp_path)
    approve(d["id"], tmp_path)
    mark_executed(d["id"], {"success": True, "tweet_id": "1"}, path=tmp_path)
    loaded = load_draft(d["id"], tmp_path)
    assert loaded["status"] == "executed"
    assert loaded["result"]["tweet_id"] == "1"


async def test_maybe_draft_when_approval_on(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XACTIONS_REQUIRE_APPROVAL", "1")
    called = {"n": 0}

    async def runner(**kwargs):
        called["n"] += 1
        return {"success": True}

    out = await maybe_draft_or_run("post_tweet", {"text": "hi"}, runner, drafts_path=tmp_path)
    assert out["drafted"] is True
    assert called["n"] == 0
    assert out["draft"]["action"] == "post_tweet"


async def test_maybe_runs_when_approval_off(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("XACTIONS_REQUIRE_APPROVAL", raising=False)
    called = {"n": 0}

    async def runner(**kwargs):
        called["n"] += 1
        return {"success": True, "tweet_id": "42"}

    out = await maybe_draft_or_run("post_tweet", {"text": "hi"}, runner, drafts_path=tmp_path)
    assert out["drafted"] is False
    assert out["tweet_id"] == "42"
    assert called["n"] == 1


def test_cli_drafts_group():
    from xactions.cli import cli

    assert "drafts" in cli.commands
    assert "list" in cli.commands["drafts"].commands
    assert "approve" in cli.commands["drafts"].commands
    assert "discard" in cli.commands["drafts"].commands
