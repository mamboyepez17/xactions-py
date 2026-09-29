"""
XActions-PY — Local notifications / webhooks for watch & pipeline.

Default: log. Optional HTTP POST webhook with a JSON body.

If XACTIONS_WEBHOOK_SECRET is set, every delivery is signed so the receiver
can reject forged or replayed calls:

    X-Xactions-Timestamp: <unix seconds>
    X-Xactions-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<raw body>">

Receivers can use `verify_signature()` (or reimplement those two lines).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

import httpx

_log = logging.getLogger(__name__)

WEBHOOK_ENV = "XACTIONS_WEBHOOK_URL"
SECRET_ENV = "XACTIONS_WEBHOOK_SECRET"
SIGNATURE_HEADER = "X-Xactions-Signature"
TIMESTAMP_HEADER = "X-Xactions-Timestamp"


def webhook_url() -> str | None:
    return os.getenv(WEBHOOK_ENV) or None


def webhook_secret() -> str | None:
    return os.getenv(SECRET_ENV) or None


def sign_payload(secret: str, body: bytes, timestamp: int) -> str:
    """Signature header value for `body` sent at `timestamp`."""
    mac = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_signature(
    secret: str,
    body: bytes,
    timestamp: str | int,
    signature: str,
    *,
    tolerance: float = 300.0,
    now: float | None = None,
) -> bool:
    """
    Receiver-side check: the signature matches and the timestamp is within
    `tolerance` seconds (rejects replays of old deliveries).
    """
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    now = time.time() if now is None else now
    if abs(now - ts) > tolerance:
        return False
    return hmac.compare_digest(sign_payload(secret, body, ts), signature or "")


def build_request(
    payload: dict[str, Any], secret: str | None = None, *, now: float | None = None
) -> tuple[bytes, dict[str, str]]:
    """Serialize `payload` and return (body, headers), signed when a secret is given."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        ts = int(time.time() if now is None else now)
        headers[TIMESTAMP_HEADER] = str(ts)
        headers[SIGNATURE_HEADER] = sign_payload(secret, body, ts)
    return body, headers


def make_notifier(
    url: str | None = None,
    *,
    extra: dict[str, Any] | None = None,
    http: httpx.AsyncClient | None = None,
) -> Callable[[str], None]:
    """
    Returns a sync callable(message) that logs and, if url set, best-effort POSTs.
    (Fire-and-forget style for pipeline notify_fn.)
    """
    url = url or webhook_url()
    extra = extra or {}
    secret = webhook_secret()

    def _post(payload: dict[str, Any]) -> None:
        assert url is not None
        body, headers = build_request(payload, secret)
        try:
            # short timeout; notify should never hang the pipeline
            httpx.post(url, content=body, headers=headers, timeout=5.0)
        except httpx.HTTPError as e:
            _log.warning("webhook failed: %s", e)

    def _notify(message: str) -> None:
        _log.info("notify: %s", message)
        if not url:
            return
        payload = {"text": message, "message": message, **extra}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            _post(payload)
            return
        # Called from async code (pipeline/watch): a blocking POST would freeze
        # the event loop for up to the timeout, so run it on the default
        # executor. asyncio.run() waits for executor jobs before returning.
        loop.run_in_executor(None, _post, payload)

    return _notify


def format_tweet_alert(tweets: list[dict[str, Any]], query: str | None = None) -> str:
    if not tweets:
        return "No new tweets"
    head = f"{len(tweets)} new tweet(s)"
    if query:
        head += f" for “{query}”"
    lines = [head]
    for t in tweets[:5]:
        author = (t.get("author") or {}).get("username") or "?"
        text = (t.get("text") or "").replace("\n", " ")[:80]
        lines.append(f"  @{author}: {text}")
    if len(tweets) > 5:
        lines.append(f"  … +{len(tweets) - 5} more")
    return "\n".join(lines)


async def post_webhook(
    url: str, payload: dict[str, Any], secret: str | None = None
) -> dict[str, Any]:
    """Explicit async POST for callers that want the response (signed if a secret is set)."""
    body, headers = build_request(payload, secret or webhook_secret())
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, content=body, headers=headers)
        return {"status_code": resp.status_code, "ok": resp.is_success}
