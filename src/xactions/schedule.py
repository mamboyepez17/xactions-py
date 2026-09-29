"""
XActions-PY — Scheduled tweets.

Posts are queued in the tracking SQLite database (same file as TrackerDB)
and published by `run_due()`, which is meant to be called periodically
(`xactions schedule run` from cron / Task Scheduler, or `--every`).

Each post moves pending → posting → posted | failed. The pending → posting
step is an atomic UPDATE, so two overlapping runs can never publish the same
post twice. A run that dies mid-publish leaves the post in `posting`; it is
never retried automatically (it may already be live) and shows up in
`schedule list --all` for a human to check.

Queuing a post is a human action (CLI), so the approval gate does not apply
to publishing it; daily write caps still do.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .caps import WriteCapExceeded
from .db import DEFAULT_DB_PATH

STATUSES = ("pending", "posting", "posted", "failed", "cancelled")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    reply_to_id TEXT,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    tweet_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_due ON scheduled_posts(status, run_at);
"""

_RELATIVE = re.compile(r"^\+(\d+)\s*([smhd])$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_when(value: str, now: datetime | None = None) -> datetime:
    """
    Parse a schedule time into an aware UTC datetime.

    Accepts relative offsets (`+30m`, `+2h`, `+1d`, `+45s`) and ISO 8601
    (`2026-10-01T09:00`, `2026-10-01 09:00:00+02:00`). A time without an
    offset is taken as local time.
    """
    now = now or datetime.now(timezone.utc)
    value = value.strip()
    m = _RELATIVE.match(value)
    if m:
        return now + timedelta(**{_UNITS[m.group(2)]: int(m.group(1))})
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError(f"Unrecognized time {value!r}: use ISO 8601 or +30m/+2h/+1d") from e
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive → local time
    return dt.astimezone(timezone.utc)


class ScheduleStore:
    """Queue of scheduled posts in SQLite."""

    def __init__(self, path: str | Path | None = None):
        self.path = str(path or DEFAULT_DB_PATH)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def add(self, text: str, run_at: datetime, reply_to_id: str | None = None) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("Cannot schedule an empty post")
        now = _iso(datetime.now(timezone.utc))
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO scheduled_posts (text, reply_to_id, run_at, status, created_at, updated_at) "
                "VALUES (?, ?, ?, 'pending', ?, ?)",
                (text, reply_to_id, _iso(run_at), now, now),
            )
            post_id = cur.lastrowid
        return self.get(post_id)  # type: ignore[arg-type,return-value]

    def get(self, post_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM scheduled_posts WHERE id = ?", (post_id,)).fetchone()
        return dict(row) if row else None

    def list_posts(self, status: str | None = "pending") -> list[dict[str, Any]]:
        query, args = "SELECT * FROM scheduled_posts", []
        if status:
            query, args = query + " WHERE status = ?", [status]
        with self._connect() as conn:
            rows = conn.execute(query + " ORDER BY run_at, id", args).fetchall()
        return [dict(r) for r in rows]

    def due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now_iso = _iso(now or datetime.now(timezone.utc))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_posts WHERE status = 'pending' AND run_at <= ? ORDER BY run_at, id",
                (now_iso,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _transition(self, post_id: int, from_status: str, to_status: str, **fields: Any) -> bool:
        """Atomically move a post between states. False if it was not in `from_status`."""
        assignments = ", ".join(f"{k} = ?" for k in fields)
        sql = "UPDATE scheduled_posts SET status = ?, updated_at = ?"
        if assignments:
            sql += ", " + assignments
        sql += " WHERE id = ? AND status = ?"
        args = (to_status, _iso(datetime.now(timezone.utc)), *fields.values(), post_id, from_status)
        with self._connect() as conn:
            return conn.execute(sql, args).rowcount == 1

    def cancel(self, post_id: int) -> bool:
        return self._transition(post_id, "pending", "cancelled")


async def run_due(
    client: Any,
    store: ScheduleStore,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Publish every due post. Stops early (leaving the rest pending) when the
    daily write cap is reached, so they go out on a later run.
    """
    from .actions import post_tweet

    due = store.due(now)
    posted: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    stopped: str | None = None
    if dry_run:
        return {"due": due, "posted": posted, "failed": failed, "stopped": None, "dry_run": True}

    for item in due:
        if not store._transition(item["id"], "pending", "posting"):
            continue  # another run claimed it
        try:
            result = await post_tweet(client, item["text"], reply_to_id=item.get("reply_to_id"))
        except WriteCapExceeded as e:
            store._transition(item["id"], "posting", "pending")
            stopped = str(e)
            break
        except Exception as e:  # noqa: BLE001 — record any failure on the post itself
            store._transition(item["id"], "posting", "failed", error=str(e)[:500])
            failed.append({**item, "error": str(e)})
            continue
        if result.get("success"):
            store._transition(item["id"], "posting", "posted", tweet_id=result["tweet_id"])
            posted.append({**item, "tweet_id": result["tweet_id"]})
        else:
            error = result.get("error") or "X did not return a tweet id"
            store._transition(item["id"], "posting", "failed", error=error[:500])
            failed.append({**item, "error": error})
    return {"due": due, "posted": posted, "failed": failed, "stopped": stopped, "dry_run": False}
