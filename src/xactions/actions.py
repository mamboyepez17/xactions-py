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
import mimetypes
import os
from collections.abc import Callable
from typing import Any

from .caps import CapsFileError, WriteCapExceeded, check_write, load_caps, record_write, save_caps
from .client import UPLOAD_BASE, AuthError, TwitterError, XClient

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

MEDIA_UPLOAD_URL = f"{UPLOAD_BASE}/1.1/media/upload.json"
SIMPLE_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
CHUNK_SIZE = 4 * 1024 * 1024  # X accepts up to 5MB per APPEND segment
MAX_PROCESSING_WAIT = 300.0  # seconds to wait for X to transcode a video


def _media_type(file_path: str) -> str:
    mime, _ = mimetypes.guess_type(file_path)
    return mime or "application/octet-stream"


def _media_category(mime: str) -> str:
    if mime.startswith("video/"):
        return "tweet_video"
    if mime == "image/gif":
        return "tweet_gif"
    return "tweet_image"


def _needs_chunked(file_path: str, mime: str) -> bool:
    return (
        mime.startswith("video/")
        or mime == "image/gif"
        or os.path.getsize(file_path) > SIMPLE_UPLOAD_MAX_BYTES
    )


async def _upload_chunked(client: Any, file_path: str, mime: str) -> dict[str, Any]:
    """INIT → APPEND (4MB segments) → FINALIZE → poll STATUS until processed."""
    total = os.path.getsize(file_path)
    init = await client.upload_request(
        MEDIA_UPLOAD_URL,
        data={
            "command": "INIT",
            "total_bytes": str(total),
            "media_type": mime,
            "media_category": _media_category(mime),
        },
    )
    media_id = init.get("media_id_string") or str(init.get("media_id") or "")
    if not media_id:
        raise TwitterError(f"Chunked upload INIT returned no media_id: {init}")

    with open(file_path, "rb") as f:
        segment = 0
        while chunk := f.read(CHUNK_SIZE):
            await client.upload_request(
                MEDIA_UPLOAD_URL,
                data={"command": "APPEND", "media_id": media_id, "segment_index": str(segment)},
                files={"media": ("blob", chunk, "application/octet-stream")},
            )
            segment += 1

    result = await client.upload_request(MEDIA_UPLOAD_URL, data={"command": "FINALIZE", "media_id": media_id})
    waited = 0.0
    while (info := result.get("processing_info")) and info.get("state") in ("pending", "in_progress"):
        delay = float(info.get("check_after_secs") or 1)
        if waited + delay > MAX_PROCESSING_WAIT:
            raise TwitterError(f"Media {media_id} still processing after {waited:.0f}s")
        await asyncio.sleep(delay)
        waited += delay
        result = await client.upload_request(
            MEDIA_UPLOAD_URL, method="GET", params={"command": "STATUS", "media_id": media_id}
        )
    if info and info.get("state") == "failed":
        error = info.get("error") or {}
        raise TwitterError(f"X failed to process media {media_id}: {error.get('message') or error or info}")
    return {"success": True, "media_id": media_id, "size": total, "chunked": True, "segments": segment}


def check_media_set(paths: list[str] | tuple[str, ...]) -> None:
    """
    Enforce X's per-tweet media rule: up to 4 images, or exactly one video/GIF.
    Raises ValueError otherwise.
    """
    kinds = [_media_category(_media_type(p)) for p in paths]
    if len(kinds) > 4:
        raise ValueError(f"A tweet can carry at most 4 images (got {len(kinds)} files)")
    if len(kinds) > 1 and any(k != "tweet_image" for k in kinds):
        raise ValueError("A video or GIF must be the only media in a tweet")


async def upload_media(client: XClient, file_path: str) -> dict[str, Any]:
    """
    Upload an image, GIF or video to X and return its media_id. Requires auth.

    Images up to 5MB use a single request. Videos, GIFs and larger files use
    the chunked INIT/APPEND/FINALIZE flow and wait for X to finish processing.
    """
    _require_auth(client)
    mime = _media_type(file_path)
    if _needs_chunked(file_path, mime):
        # Every chunk must go to the account that ran INIT, so pin one client.
        return await _upload_chunked(getattr(client, "current", client), file_path, mime)
    data = await client.rest_upload(MEDIA_UPLOAD_URL, file_path)
    media_id = data.get("media_id_string") or str(data.get("media_id", ""))
    if not media_id:
        raise AuthError(f"No media_id returned: {data}")
    return {"success": True, "media_id": media_id, "size": data.get("size"), "chunked": False}


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


# ─── Lists ────────────────────────────────────────────────────────────────────

async def create_list(
    client: XClient, name: str, description: str = "", private: bool = False
) -> dict[str, Any]:
    """Create an X List owned by the authenticated account."""
    _require_auth(client)
    name = (name or "").strip()
    if not name:
        raise ValueError("List name cannot be empty")
    _before_write(client, "list_create")
    data = await client.graphql(
        "CreateList",
        variables={"isPrivate": private, "name": name, "description": description},
        mutation=True,
    )
    lst = data.get("data", {}).get("list") or {}
    list_id = lst.get("id_str") or lst.get("rest_id")
    if list_id:
        _after_write(client, "list_create")
    return {"success": bool(list_id), "list_id": list_id, "name": lst.get("name", name)}


async def _list_member_mutation(client: XClient, endpoint: str, op: str, list_id: str, user_id: str) -> dict[str, Any]:
    _require_auth(client)
    _before_write(client, op)
    data = await client.graphql(
        endpoint,
        variables={"listId": str(list_id), "userId": str(user_id)},
        mutation=True,
    )
    ok = bool(data.get("data", {}).get("list"))
    if ok:
        _after_write(client, op)
    return {"success": ok}


async def list_add_member(client: XClient, list_id: str, user_id: str) -> dict[str, Any]:
    """Add a user (by user_id) to a List you own."""
    return await _list_member_mutation(client, "ListAddMember", "list_add", list_id, user_id)


async def list_remove_member(client: XClient, list_id: str, user_id: str) -> dict[str, Any]:
    """Remove a user (by user_id) from a List you own."""
    return await _list_member_mutation(client, "ListRemoveMember", "list_remove", list_id, user_id)


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
