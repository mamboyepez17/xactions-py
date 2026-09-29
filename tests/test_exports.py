"""Tests for --csv/--ndjson on history, schedule list, drafts list and the CSV writer."""

import csv
import json
from datetime import datetime, timezone

from click.testing import CliRunner

from xactions import drafts
from xactions.cli import cli
from xactions.cli._common import _write_csv
from xactions.db import TrackerDB
from xactions.schedule import ScheduleStore


def test_csv_writer_handles_rows_with_different_keys(tmp_path):
    path = tmp_path / "rows.csv"
    _write_csv(str(path), [{"a": 1}, {"a": 2, "b": 3}])
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows == [{"a": "1", "b": ""}, {"a": "2", "b": "3"}]


def test_history_csv_and_ndjson(tmp_path):
    db = str(tmp_path / "x.db")
    TrackerDB(db).save_profile_snapshot("nasa", {"followers": 10, "following": 2, "tweets_count": 5})
    out_csv, out_nd = tmp_path / "h.csv", tmp_path / "h.ndjson"
    r = CliRunner().invoke(cli, ["history", "nasa", "--db", db, "--csv", str(out_csv), "--ndjson", str(out_nd)])
    assert r.exit_code == 0, r.output
    (row,) = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    assert row["username"] == "nasa" and row["followers"] == "10"
    assert json.loads(out_nd.read_text(encoding="utf-8").strip())["followers"] == 10


def test_schedule_list_csv(tmp_path):
    db = str(tmp_path / "x.db")
    ScheduleStore(db).add("hello", datetime(2030, 1, 1, tzinfo=timezone.utc))
    out = tmp_path / "s.csv"
    r = CliRunner().invoke(cli, ["schedule", "list", "--db", db, "--csv", str(out)])
    assert r.exit_code == 0, r.output
    (row,) = list(csv.DictReader(out.open(encoding="utf-8")))
    assert row["text"] == "hello" and row["status"] == "pending"


def test_drafts_list_ndjson_serializes_params(tmp_path, monkeypatch):
    monkeypatch.setattr(drafts, "DEFAULT_DRAFTS_DIR", tmp_path / "drafts")
    drafts.create_draft("like", {"tweet_id": "7"})
    out = tmp_path / "d.ndjson"
    r = CliRunner().invoke(cli, ["drafts", "list", "--ndjson", str(out)])
    assert r.exit_code == 0, r.output
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["action"] == "like" and json.loads(row["params"]) == {"tweet_id": "7"}
