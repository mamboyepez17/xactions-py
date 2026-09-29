"""
XActions-PY — Actions
Like, unlike, follow, unfollow, tweet, retweet, delete, bookmark.
All via the internal GraphQL API or legacy REST. Requires auth_token + ct0 cookies.

v1.2.0:
  - Added create_bookmark / delete_bookmark.
  - Better error handling and client shutdown.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from typing import Any

from .caps import CapsFileError, WriteCapExceeded, check_write, load_caps, record_write, save_caps
from .client import UPLOAD_BASE, AuthError, XClient

_log = logging.getLogger(__name__)

# Set to False to bypass on-disk daily caps (not recommended)
CAPS_ENABLED = True


def _require_auth(client: XClient) -> None:
    if not client.is_authenticated():
        raise AuthError("Authentication required. Set auth_token and ct0.")


def _account_key(client: Any) -> str:
    """
    Stable, non-reversible per-account key for the on-disk write caps.

    Must be identical across processes (the builtin hash() is salted per
    process), and a ClientPool is keyed by the account currently in use.
    """
    client = getattr(client, "current", client)
    cookies = getattr(client, "_cookies", None) or {}
    token = cookies.get("auth_token") or getattr(client, "_cookie_str", "") or ""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"acct:{digest[:16]}"


def _before_write(client: Any, operation: str) -> None:
    """Raise WriteCapExceeded before hitting X (does not record yet)."""
    if not CAPS_ENABLED:
        return
    data = load_caps(strict=True)
    check_write(data, operation, _account_key(client))


def _after_write(client: Any, operation: str) -> None:
    """Record a successful write against the daily budget."""
    if not CAPS_ENABLED:
        return
    try:
        data = load_caps(strict=True)
        data = record_write(data, operation, _account_key(client))
        save_caps(data)
    except (OSError, CapsFileError) as e:
        _log.warning("Could not record write cap: %s", e)


# ─── Media upload ─────────────────────────────────────────────────────────────

async def upload_media(client: XClient, file_path: str) -> dict[str, Any]:
    """
    Upload an image (jpg/png/gif/webp) to X and return its media_id.
    Requires auth. Simple upload limit: ~5MB per image.
    (Video needs chunked INIT/APPEND/FINALIZE upload — not supported yet.)
    """
    _require_auth(client)
    data = await client.rest_upload(f"{UPLOAD_BASE}/1.1/media/upload.json", file_path)
    media_id = data.get("media_id_string") or str(data.get("media_id", ""))
    if not media_id:
        raise AuthError(f"No media_id returned: {data}")
    return {"success": True, "media_id": media_id, "size": data.get("size")}


# ─── Tweets ───────────────────────────────────────────────────────────────────

async def post_tweet(
    client: XClient,
    text: str,
    reply_to_id: str | None = None,
    media_ids: list | None = None,
) -> dict[str, Any]:
    """Post a tweet (optionally with media). Requires auth."""
    _require_auth(client)
    _before_write(client, "tweet")

    media_entities = [{"media_id": mid, "tagged_users": []} for mid in (media_ids or [])]
    variables = {
        "tweet_text": text,
        "dark_request": False,
        "media": {"media_entities": media_entities, "possibly_sensitive": False},
        "semantic_annotation_ids": [],
    }
    if reply_to_id:
        variables["reply"] = {
            "in_reply_to_tweet_id": reply_to_id,
            "exclude_reply_user_ids": [],
        }

    data = await client.graphql("CreateTweet", variables=variables, mutation=True)
    result = (
        data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
    )
    # TweetWithVisibilityResults nests the real tweet under .tweet
    if isinstance(result, dict) and result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet") or {}

    tweet_id = None
    if isinstance(result, dict):
        tweet_id = (
            result.get("rest_id")
            or (result.get("legacy") or {}).get("id_str")
            or (result.get("tweet") or {}).get("rest_id")
        )

    # GraphQL errors inside the payload (no HTTP error)
    errors = data.get("errors") or []
    error_msg = None
    if errors:
        error_msg = errors[0].get("message") if isinstance(errors[0], dict) else str(errors[0])

    if tweet_id:
        _after_write(client, "tweet")

    return {
        "success": bool(tweet_id),
        "tweet_id": tweet_id,
        "error": error_msg,
        "raw_keys": list(data.keys()) if not tweet_id else None,
    }


async def post_thread(
    client: XClient,
    tweets: list[str],
    delay_seconds: float = 1.5,
) -> dict[str, Any]:
    """
    Post a thread: each tweet replies to the previous one.
    Requires auth. `delay_seconds` between tweets to avoid rate limits.
    """
    _require_auth(client)
    if not tweets:
        return {"success": False, "tweet_ids": [], "error": "empty list"}

    tweet_ids: list[str] = []
    reply_to: str | None = None
    for i, text in enumerate(tweets):
        text = (text or "").strip()
        if not text:
            continue
        _before_write(client, "thread_tweet")
        result = await post_tweet(client, text, reply_to_id=reply_to)
        if not result.get("success") or not result.get("tweet_id"):
            return {
                "success": False,
                "tweet_ids": tweet_ids,
                "failed_at": i,
                "error": (
                    result.get("error")
                    or f"Could not post tweet {i + 1}/{len(tweets)}"
                ),
            }
        _after_write(client, "thread_tweet")
        tweet_ids.append(result["tweet_id"])
        reply_to = result["tweet_id"]
        if i < len(tweets) - 1:
            await asyncio.sleep(delay_seconds)

    return {
        "success": True,
        "tweet_ids": tweet_ids,
        "root_id": tweet_ids[0] if tweet_ids else None,
        "count": len(tweet_ids),
    }


async def delete_tweet(client: XClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    _before_write(client, "delete")
    data = await client.graphql(
        "DeleteTweet",
        variables={"tweet_id": tweet_id, "dark_request": False},
        mutation=True,
    )
    ok = "data" in data
    if ok:
        _after_write(client, "delete")
    return {"success": ok}


# ─── Engagement ─────────────────────────────────────────────────────────────

async def like_tweet(client: XClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    _before_write(client, "like")
    data = await client.graphql(
        "FavoriteTweet",
        variables={"tweet_id": tweet_id},
        mutation=True,
    )
    ok = data.get("data", {}).get("favorite_tweet") == "Done"
    if ok:
        _after_write(client, "like")
    return {"success": ok}


async def unlike_tweet(client: XClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    _before_write(client, "unlike")
    data = await client.graphql(
        "UnfavoriteTweet",
        variables={"tweet_id": tweet_id},
        mutation=True,
    )
    ok = data.get("data", {}).get("unfavorite_tweet") == "Done"
    if ok:
        _after_write(client, "unlike")
    return {"success": ok}


async def retweet(client: XClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    _before_write(client, "retweet")
    data = await client.graphql(
        "CreateRetweet",
        variables={"tweet_id": tweet_id, "dark_request": False},
        mutation=True,
    )
    result = data.get("data", {}).get("create_retweet", {}).get("retweet_results", {})
    ok = bool(result)
    if ok:
        _after_write(client, "retweet")
    return {"success": ok}


async def unretweet(client: XClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    _before_write(client, "unretweet")
    data = await client.graphql(
        "DeleteRetweet",
        variables={"source_tweet_id": tweet_id, "dark_request": False},
        mutation=True,
    )
    ok = bool(data.get("data"))
    if ok:
        _after_write(client, "unretweet")
    return {"success": ok}


# ─── Bookmarks ───────────────────────────────────────────────────────────────

async def create_bookmark(client: XClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    _before_write(client, "bookmark")
    data = await client.graphql(
        "CreateBookmark",
        variables={"tweet_id": tweet_id},
        mutation=True,
    )
    ok = "data" in data
    if ok:
        _after_write(client, "bookmark")
    return {"success": ok}


async def delete_bookmark(client: XClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    _before_write(client, "unbookmark")
    data = await client.graphql(
        "DeleteBookmark",
        variables={"tweet_id": tweet_id},
        mutation=True,
    )
    ok = "data" in data
    if ok:
        _after_write(client, "unbookmark")
    return {"success": ok}


# ─── Follow / Unfollow ─────────────────────────────────────────────────────────

async def follow_user(client: XClient, user_id: str) -> dict[str, Any]:
    """Follow by user_id. Uses the REST endpoint (no GraphQL mutation available)."""
    _require_auth(client)
    _before_write(client, "follow")
    data = await client.rest_post(
        "/1.1/friendships/create.json",
        {"user_id": user_id, "skip_status": "true"},
    )
    ok = bool(data.get("id_str") or data.get("id"))
    if ok:
        _after_write(client, "follow")
    return {"success": ok}


async def unfollow_user(client: XClient, user_id: str) -> dict[str, Any]:
    """Unfollow by user_id."""
    _require_auth(client)
    _before_write(client, "unfollow")
    data = await client.rest_post(
        "/1.1/friendships/destroy.json",
        {"user_id": user_id, "skip_status": "true"},
    )
    ok = bool(data.get("id_str") or data.get("id"))
    if ok:
        _after_write(client, "unfollow")
    return {"success": ok}


# ─── Bulk unfollow ─────────────────────────────────────────────────────────────

async def bulk_unfollow(
    client: XClient,
    user_ids: list,
    delay_seconds: float = 2.0,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """
    Unfollow many users with a delay between each to avoid rate limits.
    on_progress: optional callback(current, total, user_id).
    """
    _require_auth(client)
    success = 0
    failed = 0
    stopped: str | None = None

    for i, uid in enumerate(user_ids):
        try:
            result = await unfollow_user(client, uid)
            if result["success"]:
                success += 1
            else:
                failed += 1
        except (WriteCapExceeded, AuthError) as e:
            # Every remaining unfollow would fail the same way: stop now.
            _log.warning("bulk_unfollow: stopping at %d/%d (%s)", i, len(user_ids), e)
            stopped = str(e)
            break
        except Exception as e:
            failed += 1
            _log.warning("bulk_unfollow: failed user_id=%s (%s)", uid, e)

        if on_progress:
            on_progress(i + 1, len(user_ids), uid)

        await asyncio.sleep(delay_seconds)

    return {
        "total": len(user_ids),
        "success": success,
        "failed": failed,
        "stopped": stopped,
    }
