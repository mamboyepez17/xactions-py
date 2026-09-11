"""Tests B0: daily write caps + doctor."""

import json
import time
from pathlib import Path

import pytest

from xactions.caps import (
    DEFAULT_LIMITS,
    WriteCapExceeded,
    check_write,
    count_in_window,
    load_caps,
    record_write,
    remaining,
    save_caps,
    status_report,
    try_charge,
)
from xactions.doctor import run_doctor


def test_load_empty_defaults(tmp_path: Path):
    data = load_caps(tmp_path / "caps.json")
    assert data["events"] == []
    assert data["limits"]["tweet"] == DEFAULT_LIMITS["tweet"]


def test_record_and_count(tmp_path: Path):
    p = tmp_path / "caps.json"
    data = load_caps(p)
    now = 1_000_000.0
    data = record_write(data, "tweet", "acct:a", now=now)
    data = record_write(data, "tweet", "acct:a", now=now + 10)
    data = record_write(data, "like", "acct:a", now=now + 20)
    save_caps(data, p)
    reloaded = load_caps(p)
    assert count_in_window(reloaded, "tweet", "acct:a", now=now + 30) == 2
    assert count_in_window(reloaded, "like", "acct:a", now=now + 30) == 1
    assert remaining(reloaded, "tweet", "acct:a", now=now + 30) == DEFAULT_LIMITS["tweet"] - 2


def test_prune_old_events(tmp_path: Path):
    now = 2_000_000.0
    data = {"events": [], "limits": dict(DEFAULT_LIMITS)}
    data = record_write(data, "tweet", "a", now=now - 25 * 3600)  # older than 24h
    data = record_write(data, "tweet", "a", now=now - 60)
    assert count_in_window(data, "tweet", "a", now=now) == 1


def test_check_write_raises_at_limit(tmp_path: Path):
    limits = dict(DEFAULT_LIMITS)
    limits["tweet"] = 2
    data = {"events": [], "limits": limits}
    now = time.time()
    data = record_write(data, "tweet", "a", now=now)
    data = record_write(data, "tweet", "a", now=now + 1)
    with pytest.raises(WriteCapExceeded):
        check_write(data, "tweet", "a", now=now + 2)
    assert remaining(data, "tweet", "a", now=now + 2) == 0


def test_try_charge_persists(tmp_path: Path):
    p = tmp_path / "caps.json"
    r1 = try_charge("like", "acct:x", path=p, now=100.0)
    assert r1["allowed"] is True
    assert r1["used"] == 1
    r2 = try_charge("like", "acct:x", path=p, now=101.0)
    assert r2["used"] == 2
    assert Path(p).exists()
    payload = json.loads(Path(p).read_text(encoding="utf-8"))
    assert len(payload["events"]) == 2


def test_try_charge_refuses_when_full(tmp_path: Path):
    p = tmp_path / "caps.json"
    data = load_caps(p)
    data["limits"] = {**DEFAULT_LIMITS, "tweet": 1}
    save_caps(data, p)
    try_charge("tweet", "a", path=p, now=1.0)
    with pytest.raises(WriteCapExceeded):
        try_charge("tweet", "a", path=p, now=2.0)
    # still only one event
    assert count_in_window(load_caps(p), "tweet", "a", now=3.0) == 1


def test_status_report(tmp_path: Path):
    p = tmp_path / "caps.json"
    now = time.time()
    try_charge("tweet", "acct:1", path=p, now=now)
    try_charge("tweet", "acct:1", path=p, now=now + 1)
    try_charge("like", "acct:2", path=p, now=now + 2)
    rep = status_report(p)
    assert rep["events_24h"] == 3
    assert rep["by_operation"]["tweet"] == 2
    assert "acct:1" in rep["accounts"]


def test_doctor_runs_and_reports():
    report = run_doctor(cookies="")
    assert "checks" in report
    assert report["ok"] is True  # missing cookies is warn, not error
    names = [c["check"] for c in report["checks"]]
    assert "python" in names
    assert "graphql" in names
    assert "write_caps" in names
    assert "cookies" in names


def test_doctor_with_fake_cookies():
    report = run_doctor(cookies="auth_token=SECRET; ct0=ABC")
    cookie_checks = [c for c in report["checks"] if c["check"] == "cookies"]
    assert cookie_checks and cookie_checks[0]["status"] == "ok"
    assert "SECRET" not in json.dumps(report)


def test_cli_doctor_registered():
    from xactions.cli import cli

    assert "doctor" in cli.commands
