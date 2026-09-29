"""Tests for scheduled tweets."""

from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from xactions import actions
from xactions.caps import WriteCapExceeded
from xactions.cli import cli
from xactions.schedule import ScheduleStore, parse_when, run_due

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_parse_when_relative_and_iso():
    assert parse_when("+30m", NOW) == NOW + timedelta(minutes=30)
    assert parse_when("+2h", NOW) == NOW + timedelta(hours=2)
    assert parse_when("+1d", NOW) == NOW + timedelta(days=1)
    assert parse_when("2026-10-01T09:00:00+02:00") == datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc)
    assert parse_when("2026-10-01T09:00Z") == datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    naive = parse_when("2026-10-01T09:00")
    assert naive.tzinfo is not None
    assert naive == datetime(2026, 10, 1, 9, 0).astimezone().astimezone(timezone.utc)
    with pytest.raises(ValueError):
        parse_when("tomorrow-ish")


@pytest.fixture
def store(tmp_path):
    return ScheduleStore(tmp_path / "x.db")


def test_add_due_cancel(store):
    a = store.add("past", NOW - timedelta(minutes=1))
    b = store.add("future", NOW + timedelta(hours=1))
    assert [p["id"] for p in store.due(NOW)] == [a["id"]]
    assert store.cancel(b["id"])
    assert not store.cancel(b["id"])  # already cancelled
    assert store.get(b["id"])["status"] == "cancelled"
    with pytest.raises(ValueError):
        store.add("   ", NOW)


class _Client:
    _cookies = {"auth_token": "t"}

    def is_authenticated(self):
        return True


@pytest.fixture
def fake_post(monkeypatch):
    calls = []

    async def post_tweet(client, text, reply_to_id=None, media_ids=None):
        calls.append((text, reply_to_id))
        if text == "boom":
            raise RuntimeError("network down")
        if text == "rejected":
            return {"success": False, "tweet_id": None, "error": "duplicate"}
        if text == "capped":
            raise WriteCapExceeded("cap")
        return {"success": True, "tweet_id": f"id-{text}"}

    monkeypatch.setattr(actions, "post_tweet", post_tweet)
    return calls


async def test_run_due_publishes_and_records(store, fake_post):
    ok = store.add("hello", NOW - timedelta(minutes=5), reply_to_id="9")
    bad = store.add("boom", NOW - timedelta(minutes=4))
    rej = store.add("rejected", NOW - timedelta(minutes=3))
    later = store.add("later", NOW + timedelta(hours=1))

    result = await run_due(_Client(), store, now=NOW)
    assert [p["id"] for p in result["posted"]] == [ok["id"]]
    assert {p["id"] for p in result["failed"]} == {bad["id"], rej["id"]}
    assert store.get(ok["id"])["status"] == "posted"
    assert store.get(ok["id"])["tweet_id"] == "id-hello"
    assert store.get(bad["id"])["error"] == "network down"
    assert store.get(rej["id"])["error"] == "duplicate"
    assert store.get(later["id"])["status"] == "pending"
    assert ("hello", "9") in fake_post

    # a second run posts nothing again
    again = await run_due(_Client(), store, now=NOW)
    assert again["posted"] == [] and again["failed"] == []


async def test_run_due_stops_at_cap_and_keeps_rest_pending(store, fake_post):
    first = store.add("capped", NOW - timedelta(minutes=2))
    second = store.add("after", NOW - timedelta(minutes=1))
    result = await run_due(_Client(), store, now=NOW)
    assert result["stopped"] == "cap"
    assert store.get(first["id"])["status"] == "pending"
    assert store.get(second["id"])["status"] == "pending"
    assert fake_post == [("capped", None)]


async def test_claimed_post_is_not_published_twice(store, fake_post):
    item = store.add("hello", NOW - timedelta(minutes=1))
    assert store._transition(item["id"], "pending", "posting")  # another run claimed it
    result = await run_due(_Client(), store, now=NOW)
    assert result["posted"] == [] and fake_post == []


async def test_dry_run_posts_nothing(store, fake_post):
    store.add("hello", NOW - timedelta(minutes=1))
    result = await run_due(_Client(), store, now=NOW, dry_run=True)
    assert len(result["due"]) == 1 and fake_post == []


def test_cli_add_list_cancel(tmp_path):
    db = str(tmp_path / "x.db")
    runner = CliRunner()
    r = runner.invoke(cli, ["schedule", "add", "hi there", "--at", "+1h", "--db", db])
    assert r.exit_code == 0, r.output
    assert "Scheduled #1" in r.output
    r = runner.invoke(cli, ["schedule", "list", "--db", db])
    assert "hi there" in r.output and "[pending]" in r.output
    r = runner.invoke(cli, ["schedule", "cancel", "1", "--db", db])
    assert r.exit_code == 0 and "Cancelled #1" in r.output
    r = runner.invoke(cli, ["schedule", "cancel", "1", "--db", db])
    assert r.exit_code != 0
    r = runner.invoke(cli, ["schedule", "add", "x", "--at", "someday", "--db", db])
    assert r.exit_code != 0 and "Unrecognized time" in r.output
