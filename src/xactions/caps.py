"""
XActions-PY — Daily write caps (on-disk, survives restart).

Rolling 24h budget per account + operation. Refuses a write that would
exceed the cap *before* it reaches X.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

DEFAULT_CAPS_DIR = Path(os.getenv("XACTIONS_HOME", str(Path.home() / ".xactions")))
DEFAULT_CAPS_PATH = DEFAULT_CAPS_DIR / "write_caps.json"
WINDOW_SECONDS = 24 * 60 * 60

# Conservative defaults (not X's exact published numbers — safety first)
DEFAULT_LIMITS: dict[str, int] = {
    "tweet": 50,
    "like": 100,
    "unlike": 100,
    "retweet": 50,
    "unretweet": 50,
    "follow": 50,
    "unfollow": 50,
    "bookmark": 100,
    "unbookmark": 100,
    "delete": 50,
    "thread_tweet": 50,  # each tweet in a thread counts
    "list_create": 10,
    "list_add": 100,
    "list_remove": 100,
}


class WriteCapExceeded(Exception):
    """Raised when a write would exceed the rolling 24h budget."""


class CapsFileError(WriteCapExceeded):
    """
    The caps file exists but cannot be read. Writes are refused (fail closed)
    rather than silently starting from an empty budget.
    """


def _utc_day_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def load_caps(path: Path | str | None = None, *, strict: bool = False) -> dict[str, Any]:
    """
    Load the caps file. A missing file means an empty budget. An unreadable or
    malformed file raises CapsFileError when strict (used before writes);
    otherwise it is logged and treated as empty (reporting only).
    """
    p = Path(path) if path else DEFAULT_CAPS_PATH
    if not p.exists():
        return {"events": [], "limits": dict(DEFAULT_LIMITS)}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("top-level JSON value is not an object")
    except (OSError, ValueError) as e:
        if strict:
            raise CapsFileError(
                f"Write caps file {p} is unreadable ({e}). Refusing writes until it is "
                "fixed or deleted (deleting resets the 24h budget)."
            ) from e
        _log.warning("write_caps unreadable (%s): %s", p, e)
        return {"events": [], "limits": dict(DEFAULT_LIMITS)}
    data.setdefault("events", [])
    limits = dict(DEFAULT_LIMITS)
    limits.update(data.get("limits") or {})
    data["limits"] = limits
    return data


def save_caps(data: dict[str, Any], path: Path | str | None = None) -> Path:
    p = Path(path) if path else DEFAULT_CAPS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename so a crash mid-write never leaves a truncated file.
    fd, tmp = tempfile.mkstemp(prefix=p.name, suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return p


def _prune(events: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    cutoff = now - WINDOW_SECONDS
    return [e for e in events if float(e.get("ts", 0)) >= cutoff]


def count_in_window(
    data: dict[str, Any],
    operation: str,
    account: str,
    now: float | None = None,
) -> int:
    now = now if now is not None else time.time()
    events = _prune(data.get("events") or [], now)
    return sum(
        1
        for e in events
        if e.get("op") == operation and e.get("account") == account
    )


def remaining(
    data: dict[str, Any],
    operation: str,
    account: str,
    now: float | None = None,
) -> int:
    limit = int((data.get("limits") or DEFAULT_LIMITS).get(operation, 0))
    if limit <= 0:
        return 0
    used = count_in_window(data, operation, account, now=now)
    return max(0, limit - used)


def check_write(
    data: dict[str, Any],
    operation: str,
    account: str,
    now: float | None = None,
) -> None:
    """Raise WriteCapExceeded if this write would go over the budget."""
    if remaining(data, operation, account, now=now) <= 0:
        limit = (data.get("limits") or DEFAULT_LIMITS).get(operation)
        raise WriteCapExceeded(
            f"Daily cap reached for {operation!r} (account={account}, limit={limit}/24h). "
            "Wait for the rolling window or raise limits in write_caps.json."
        )


def record_write(
    data: dict[str, Any],
    operation: str,
    account: str,
    now: float | None = None,
) -> dict[str, Any]:
    """Charge one write against the budget (call only after X accepted it)."""
    now = now if now is not None else time.time()
    events = _prune(data.get("events") or [], now)
    events.append({"op": operation, "account": account, "ts": now})
    data["events"] = events
    return data


def try_charge(
    operation: str,
    account: str,
    path: Path | str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """
    Check + record atomically at the file level.
    Returns {allowed, used, limit, remaining}.
    Raises WriteCapExceeded if not allowed (does not record).
    """
    p = Path(path) if path else DEFAULT_CAPS_PATH
    data = load_caps(p, strict=True)
    check_write(data, operation, account, now=now)
    data = record_write(data, operation, account, now=now)
    save_caps(data, p)
    limit = int((data.get("limits") or DEFAULT_LIMITS).get(operation, 0))
    used = count_in_window(data, operation, account, now=now)
    return {
        "allowed": True,
        "operation": operation,
        "account": account,
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
    }


def status_report(path: Path | str | None = None) -> dict[str, Any]:
    """Snapshot for `xactions doctor`."""
    data = load_caps(path)
    now = time.time()
    events = _prune(data.get("events") or [], now)
    by_op: dict[str, int] = {}
    accounts: set[str] = set()
    for e in events:
        by_op[e.get("op", "?")] = by_op.get(e.get("op", "?"), 0) + 1
        if e.get("account"):
            accounts.add(str(e["account"]))
    return {
        "path": str(Path(path) if path else DEFAULT_CAPS_PATH),
        "events_24h": len(events),
        "by_operation": by_op,
        "accounts": sorted(accounts),
        "limits": data.get("limits") or DEFAULT_LIMITS,
    }
