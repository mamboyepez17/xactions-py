"""
XActions-PY — Scrapers
Python ports of XActions' HTTP scrapers.

v1.2.0:
  - New scrapers: replies, favoriters, retweeters, bookmarks, user likes,
    home timeline and trending topics.
  - Better error handling (ForbiddenError, RateLimitError).
  - Sync wrappers that close the HTTP client automatically.
  - In-memory user_id cache to avoid repeated lookups.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .client import (
    DEFAULT_FEATURES,
    ForbiddenError,
    NotFoundError,
    TwitterClient,
    TwitterError,
    XClient,
)

_log = logging.getLogger(__name__)

# GraphQL page sizes (X accepts more than 20 on several endpoints;
# search is usually still capped at 20).
PAGE_SIZE_USERS = 100       # Followers / Following
PAGE_SIZE_ENGAGEMENT = 50   # Favoriters / Retweeters
PAGE_SIZE_TWEETS = 40       # UserTweets / replies / likes / home
PAGE_SIZE_BOOKMARKS = 40
PAGE_SIZE_SEARCH = 20       # SearchTimeline: the API caps it at ~20

# ─── user_id cache (avoids repeated profile lookups) ──────────────────────────

_USER_ID_CACHE: dict[str, str] = {}


def clear_user_id_cache() -> None:
    """Clear the username -> user_id cache."""
    _USER_ID_CACHE.clear()


# ─── Parsing helpers ──────────────────────────────────────────────────────────

def _upgrade_avatar(url: str | None) -> str | None:
    if not url:
        return None
    return url.replace("_normal", "_400x400")


def _safe_int(val: Any, default: int = 0) -> int:
    """Convert any value to int safely."""
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def parse_user(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a GraphQL user result to the XActions format."""
    if not raw or raw.get("__typename") == "UserUnavailable":
        return None
    legacy = raw.get("legacy", {})
    return {
        "id": raw.get("rest_id"),
        "username": legacy.get("screen_name"),
        "name": legacy.get("name"),
        "bio": legacy.get("description"),
        "verified": raw.get("is_blue_verified", legacy.get("verified", False)),
        "avatar": _upgrade_avatar(legacy.get("profile_image_url_https")),
        "followers": _safe_int(legacy.get("followers_count", 0)),
        "following": _safe_int(legacy.get("friends_count", 0)),
        "tweets_count": _safe_int(legacy.get("statuses_count", 0)),
        "protected": legacy.get("protected", False),
        "created_at": legacy.get("created_at"),
        "location": legacy.get("location"),
        "website": (legacy.get("entities", {})
                        .get("url", {})
                        .get("urls", [{}])[0]
                        .get("expanded_url")),
        "platform": "twitter",
    }


def parse_tweet(raw: dict[str, Any], author: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """
    Convert a GraphQL tweet result to the XActions format.
    Handles the structure variants X returns:
    - TweetWithVisibilityResults
    - Tweet
    - TweetTombstone (dropped)
    """
    if not raw:
        return None

    # The tweet may come directly or inside tweet_results.result
    result = raw.get("tweet_results", {}).get("result") if "tweet_results" in raw else raw
    if not result:
        # Sometimes it comes as itemContent with nested tweet_results
        result = raw.get("itemContent", {}).get("tweet_results", {}).get("result", raw)

    if not result or result.get("__typename") == "TweetTombstone":
        return None

    # TweetWithVisibilityResults keeps the real tweet under .tweet
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", result)

    core = result.get("core", {})
    legacy = result.get("legacy", {})
    metrics = result.get("public_metrics") or {}

    # The id can live in several places
    tweet_id = result.get("rest_id") or legacy.get("id_str") or raw.get("rest_id")
    if not tweet_id:
        return None

    # Author: prefer the one passed in, else extract it from core
    tweet_author = author
    if not tweet_author:
        user_result = core.get("user_results", {}).get("result", {})
        if user_result:
            tweet_author = parse_user(user_result)

    # Text: full_text is complete, text is truncated
    text = legacy.get("full_text") or legacy.get("text") or ""

    # Metrics: may be in legacy or in public_metrics (API v2)
    likes = _safe_int(legacy.get("favorite_count", 0)) or _safe_int(metrics.get("like_count", 0))
    retweets = _safe_int(legacy.get("retweet_count", 0)) or _safe_int(metrics.get("retweet_count", 0))
    replies = _safe_int(legacy.get("reply_count", 0)) or _safe_int(metrics.get("reply_count", 0))
    quotes = _safe_int(legacy.get("quote_count", 0)) or _safe_int(metrics.get("quote_count", 0))
    views = _safe_int(result.get("views", {}).get("count", 0))
    bookmarks = _safe_int(legacy.get("bookmark_count", 0))

    return {
        "id": tweet_id,
        "text": text,
        "author": tweet_author or {},
        "created_at": legacy.get("created_at"),
        "likes": likes,
        "retweets": retweets,
        "replies": replies,
        "quotes": quotes,
        "views": views,
        "bookmarks": bookmarks,
        "lang": legacy.get("lang"),
        "is_reply": bool(legacy.get("in_reply_to_status_id_str")),
        "is_retweet": "retweeted_status_result" in legacy,
        "is_quote": "quoted_status_id_str" in legacy,
        "media": _parse_media(legacy),
        "url": f"https://x.com/i/web/status/{tweet_id}",
        "platform": "twitter",
    }


def _parse_media(legacy: dict[str, Any]) -> list[dict[str, Any]]:
    entities = legacy.get("extended_entities", legacy.get("entities", {}))
    media_list = entities.get("media", [])
    result = []
    for m in media_list:
        entry: dict[str, Any] = {
            "type": m.get("type"),
            "url": m.get("media_url_https"),
        }
        if m.get("type") == "video":
            variants = (m.get("video_info", {}).get("variants", []))
            mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
            if mp4s:
                best = max(mp4s, key=lambda v: v.get("bitrate", 0))
                entry["video_url"] = best["url"]
        result.append(entry)
    return result


def _parse_user_list(instructions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """Extract users and the cursor from a GraphQL timeline's instructions."""
    users: list[dict[str, Any]] = []
    cursor: str | None = None

    for instruction in instructions:
        itype = instruction.get("type") or instruction.get("__typename", "")
        if "AddEntries" in itype or "TimelineAddEntries" in itype:
            for entry in instruction.get("entries", []):
                entry_id = entry.get("entryId", "")
                content = entry.get("content", {})

                if entry_id.startswith("cursor-bottom"):
                    cursor = (
                        content.get("value")
                        or content.get("itemContent", {}).get("value")
                    )
                    continue

                item_content = content.get("itemContent", {})
                if item_content.get("itemType") == "TimelineUser":
                    raw_user = item_content.get("user_results", {}).get("result")
                    parsed = parse_user(raw_user)
                    if parsed:
                        users.append(parsed)

    return users, cursor


def _parse_tweet_list(instructions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """Extract tweets and the cursor from a GraphQL timeline's instructions."""
    tweets: list[dict[str, Any]] = []
    cursor: str | None = None

    for instruction in instructions:
        itype = instruction.get("type") or instruction.get("__typename", "")
        if "AddEntries" not in itype and "TimelineAddEntries" not in itype:
            continue

        for entry in instruction.get("entries", []):
            entry_id = entry.get("entryId", "")
            content = entry.get("content", {})

            # Pagination cursor
            if "cursor-bottom" in entry_id or "cursor-top" in entry_id:
                cursor = content.get("value") or content.get("itemContent", {}).get("value")
                continue

            # Tweet normal
            item_content = content.get("itemContent", {})
            if item_content.get("itemType") == "TimelineTweet":
                tweet = parse_tweet(item_content)
                if tweet:
                    tweets.append(tweet)
                continue

            # Thread: puede tener multiples tweets dentro
            if "TimelineTimelineModule" in str(content.get("itemType", "")):
                for sub_item in content.get("items", []):
                    sub_content = sub_item.get("item", {}).get("itemContent", {})
                    if sub_content.get("itemType") == "TimelineTweet":
                        tweet = parse_tweet(sub_content)
                        if tweet:
                            tweets.append(tweet)

    return tweets, cursor


def _instructions_from_data(data: dict[str, Any], path: list[str]) -> list[dict[str, Any]]:
    """Walk the GraphQL response and return its instructions."""
    node = data.get("data", {})
    for key in path:
        if not isinstance(node, dict):
            return []
        node = node.get(key, {})
    if not isinstance(node, dict):
        return []
    return node.get("instructions", [])


# ─── Profile scrapers ─────────────────────────────────────────────────────────

async def scrape_profile(client: XClient, username: str) -> dict[str, Any]:
    """Fetch a user's profile by @username."""
    data = await client.graphql(
        "UserByScreenName",
        variables={
            "screen_name": username,
            "withSafetyModeUserFields": True,
        },
        features={
            **DEFAULT_FEATURES,
            "hidden_profile_likes_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
        },
    )
    raw = (
        data.get("data", {})
            .get("user", {})
            .get("result", {})
    )
    if not raw:
        raise NotFoundError(f"User @{username} not found")
    profile = parse_user(raw)
    if not profile:
        raise NotFoundError(f"User @{username} unavailable (account suspended or blocked)")
    return profile


# ─── Relationship scrapers ────────────────────────────────────────────────────

async def _paginate_users(
    client: XClient,
    endpoint: str,
    user_id: str,
    limit: int | None = 100,
    checkpoint_key: str | None = None,
) -> list[dict[str, Any]]:
    """Generic paginator for followers/following/favoriters/retweeters.

    limit=None fetches every page until the cursor is exhausted.
    """
    from .watch import load_cursor, mark_scrape_complete, save_cursor

    all_users: list[dict[str, Any]] = []
    cursor: str | None = None
    exhausted = False  # True once X has no further pages
    if checkpoint_key:
        cursor = load_cursor(checkpoint_key)
        if cursor:
            _log.info("Resuming scrape %s from checkpoint cursor", checkpoint_key)

    while limit is None or len(all_users) < limit:
        page_size = PAGE_SIZE_USERS if limit is None else min(PAGE_SIZE_USERS, limit - len(all_users))
        variables: dict[str, Any] = {
            "userId": user_id,
            "count": page_size,
            "includePromotedContent": False,
        }
        if cursor:
            variables["cursor"] = cursor

        data = await client.graphql(endpoint, variables=variables)

        timeline = (
            data.get("data", {})
                .get("user", {})
                .get("result", {})
                .get("timeline", {})
                .get("timeline", {})
        )
        instructions = timeline.get("instructions", [])
        batch, new_cursor = _parse_user_list(instructions)

        if not batch:
            exhausted = True
            break

        all_users.extend(batch)

        if checkpoint_key and new_cursor:
            save_cursor(checkpoint_key, new_cursor)

        if not new_cursor or new_cursor == cursor:
            exhausted = True
            break
        cursor = new_cursor

    # Stopping at `limit` keeps the saved cursor so the next call continues;
    # reaching the end of the list clears it so the next run starts fresh.
    if checkpoint_key and exhausted:
        mark_scrape_complete(checkpoint_key)

    return all_users if limit is None else all_users[:limit]


async def get_user_id(client: XClient, username: str) -> str:
    """Fetch a user's numeric ID (cached in memory)."""
    key = username.lower()
    if key in _USER_ID_CACHE:
        return _USER_ID_CACHE[key]
    profile = await scrape_profile(client, username)
    uid = profile.get("id")
    if not uid:
        raise NotFoundError(f"Could not resolve the user ID of @{username}")
    _USER_ID_CACHE[key] = uid
    return uid


async def scrape_followers(
    client: XClient,
    username: str,
    limit: int = 100,
    checkpoint: bool = False,
) -> list[dict[str, Any]]:
    user_id = await get_user_id(client, username)
    key = f"followers:{username.lower()}" if checkpoint else None
    return await _paginate_users(client, "Followers", user_id, limit, checkpoint_key=key)


async def scrape_following(
    client: XClient,
    username: str,
    limit: int = 100,
    checkpoint: bool = False,
) -> list[dict[str, Any]]:
    user_id = await get_user_id(client, username)
    key = f"following:{username.lower()}" if checkpoint else None
    return await _paginate_users(client, "Following", user_id, limit, checkpoint_key=key)


# Minimum fraction of the profile's follower count that must be fetched before
# we trust the follower set (suspended/deactivated accounts are still counted
# by X but never returned, so an exact match is not expected).
MIN_FOLLOWER_COVERAGE = 0.9


async def scrape_non_followers(
    client: XClient,
    username: str,
    limit: int = 200,
    min_follower_coverage: float = MIN_FOLLOWER_COVERAGE,
) -> list[dict[str, Any]]:
    """Return accounts `username` follows that do not follow back.

    `limit` bounds how many *following* accounts are checked. The follower
    list is always fetched in full: truncating it would report real
    followers as non-followers (and bulk-unfollow would then drop them).
    Raises TwitterError if the follower list comes back noticeably
    incomplete, rather than returning a result that is unsafe to act on.
    """
    profile = await scrape_profile(client, username)
    user_id = profile.get("id")
    if not user_id:
        raise NotFoundError(f"Could not resolve the user ID of @{username}")
    _USER_ID_CACHE[username.lower()] = user_id

    following, followers = await asyncio.gather(
        _paginate_users(client, "Following", user_id, limit),
        _paginate_users(client, "Followers", user_id, None),
    )
    expected = _safe_int(profile.get("followers"))
    if expected and len(followers) < expected * min_follower_coverage:
        raise TwitterError(
            f"Incomplete follower list for @{username}: fetched {len(followers)} of "
            f"{expected}. Refusing to compute non-followers (results would include "
            "accounts that do follow back). Retry later."
        )
    follower_ids = {u["id"] for u in followers if u.get("id")}
    return [u for u in following if u.get("id") not in follower_ids]


# ─── Tweet scrapers ──────────────────────────────────────────────────────────

async def scrape_tweets(
    client: XClient,
    username: str,
    limit: int = 50,
    include_replies: bool = False,
) -> list[dict[str, Any]]:
    user_id = await get_user_id(client, username)
    endpoint = "UserTweetsAndReplies" if include_replies else "UserTweets"
    all_tweets: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_tweets) < limit:
        variables: dict[str, Any] = {
            "userId": user_id,
            "count": min(PAGE_SIZE_TWEETS, limit - len(all_tweets)),
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor

        data = await client.graphql(endpoint, variables=variables)

        timeline = (
            data.get("data", {})
                .get("user", {})
                .get("result", {})
                .get("timeline_v2", {})
                .get("timeline", {})
        )
        instructions = timeline.get("instructions", [])
        batch, new_cursor = _parse_tweet_list(instructions)

        all_tweets.extend(batch)

        if not new_cursor or new_cursor == cursor or not batch:
            break
        cursor = new_cursor

    return all_tweets[:limit]


async def get_user_likes(
    client: XClient,
    username: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch the tweets a user liked (public likes only)."""
    user_id = await get_user_id(client, username)
    all_tweets: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_tweets) < limit:
        variables: dict[str, Any] = {
            "userId": user_id,
            "count": min(PAGE_SIZE_TWEETS, limit - len(all_tweets)),
            "includePromotedContent": False,
            "withClientEventToken": False,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor

        data = await client.graphql("UserLikes", variables=variables)
        timeline = (
            data.get("data", {})
                .get("user", {})
                .get("result", {})
                .get("timeline_v2", {})
                .get("timeline", {})
        )
        instructions = timeline.get("instructions", [])
        batch, new_cursor = _parse_tweet_list(instructions)

        all_tweets.extend(batch)
        if not new_cursor or new_cursor == cursor or not batch:
            break
        cursor = new_cursor

    return all_tweets[:limit]


# ─── Replies and thread ─────────────────────────────────────────────────────────

async def get_tweet_replies(
    client: XClient,
    tweet_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch a tweet's replies/conversation via TweetDetail."""
    all_tweets: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_tweets) < limit:
        variables: dict[str, Any] = {
            "focalTweetId": tweet_id,
            "with_rux_injections": False,
            "includePromotedContent": True,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor

        data = await client.graphql(
            "TweetDetail",
            variables=variables,
            features={
                **DEFAULT_FEATURES,
                "rweb_lists_timeline_redesign_enabled": True,
                "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                "tweet_gql_enabled": True,
                "responsive_web_enhance_cards_enabled": False,
            },
        )

        instructions = _instructions_from_data(
            data,
            ["threaded_conversation_with_injections_v2", "instructions"],
        )
        if not instructions:
            # Fallback a otros paths posibles
            instructions = _instructions_from_data(
                data,
                ["tweet", "result", "timeline_response", "timeline", "instructions"],
            )

        batch, new_cursor = _parse_tweet_list(instructions)
        all_tweets.extend(batch)

        if not new_cursor or new_cursor == cursor or not batch:
            break
        cursor = new_cursor

    return all_tweets[:limit]


# ─── Engagement: favoriters and retweeters ────────────────────────────────────

async def get_tweet_favoriters(
    client: XClient,
    tweet_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch the users who liked a tweet."""
    all_users: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_users) < limit:
        variables: dict[str, Any] = {
            "tweetId": tweet_id,
            "count": min(PAGE_SIZE_ENGAGEMENT, limit - len(all_users)),
            "includePromotedContent": False,
        }
        if cursor:
            variables["cursor"] = cursor

        data = await client.graphql("Favoriters", variables=variables)
        timeline = (
            data.get("data", {})
                .get("favoriters_timeline", {})
                .get("timeline", {})
                .get("instructions", [])
        )
        batch, new_cursor = _parse_user_list(timeline)
        all_users.extend(batch)

        if not new_cursor or new_cursor == cursor or not batch:
            break
        cursor = new_cursor

    return all_users[:limit]


async def get_tweet_retweeters(
    client: XClient,
    tweet_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch the users who retweeted a tweet."""
    all_users: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_users) < limit:
        variables: dict[str, Any] = {
            "tweetId": tweet_id,
            "count": min(PAGE_SIZE_ENGAGEMENT, limit - len(all_users)),
            "includePromotedContent": False,
        }
        if cursor:
            variables["cursor"] = cursor

        data = await client.graphql("Retweeters", variables=variables)
        timeline = (
            data.get("data", {})
                .get("retweeters_timeline", {})
                .get("timeline", {})
                .get("instructions", [])
        )
        batch, new_cursor = _parse_user_list(timeline)
        all_users.extend(batch)

        if not new_cursor or new_cursor == cursor or not batch:
            break
        cursor = new_cursor

    return all_users[:limit]


# ─── Bookmarks ──────────────────────────────────────────────────────────────────

async def get_bookmarks(
    client: XClient,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch the authenticated user's bookmarks. Requires auth."""
    if not client.is_authenticated():
        raise TwitterError("Bookmarks require authentication")

    all_tweets: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_tweets) < limit:
        variables: dict[str, Any] = {
            "count": min(PAGE_SIZE_BOOKMARKS, limit - len(all_tweets)),
            "includePromotedContent": False,
        }
        if cursor:
            variables["cursor"] = cursor

        data = await client.graphql(
            "Bookmarks",
            variables=variables,
            features={
                **DEFAULT_FEATURES,
                "graphql_timeline_v2_bookmark_timeline": True,
            },
        )
        timeline = (
            data.get("data", {})
                .get("bookmark_timeline_v2", {})
                .get("timeline", {})
                .get("instructions", [])
        )
        batch, new_cursor = _parse_tweet_list(timeline)
        all_tweets.extend(batch)

        if not new_cursor or new_cursor == cursor or not batch:
            break
        cursor = new_cursor

    return all_tweets[:limit]


# ─── Home timeline ────────────────────────────────────────────────────────────

async def get_home_timeline(
    client: XClient,
    limit: int = 50,
    latest: bool = False,
) -> list[dict[str, Any]]:
    """Fetch the authenticated user's home timeline. Requires auth."""
    if not client.is_authenticated():
        raise TwitterError("Home timeline requires authentication")

    endpoint = "HomeLatestTimeline" if latest else "HomeTimeline"
    all_tweets: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_tweets) < limit:
        variables: dict[str, Any] = {
            "count": min(PAGE_SIZE_TWEETS, limit - len(all_tweets)),
            "includePromotedContent": True,
            "latestControlAvailable": True,
            "requestContext": "launch",
            "withCommunity": True,
        }
        if cursor:
            variables["cursor"] = cursor

        data = await client.graphql(endpoint, variables=variables)
        timeline = (
            data.get("data", {})
                .get("home", {})
                .get("home_timeline_urt", {})
                .get("instructions", [])
        )
        batch, new_cursor = _parse_tweet_list(timeline)
        all_tweets.extend(batch)

        if not new_cursor or new_cursor == cursor or not batch:
            break
        cursor = new_cursor

    return all_tweets[:limit]


# ─── Trends ───────────────────────────────────────────────────────────────────

async def get_trends(client: XClient, woeid: int = 1) -> list[dict[str, Any]]:
    """
    Fetch X trending topics via the REST API.
    woeid: 1 = worldwide, 23424977 = USA, 44418 = London, etc.
    """
    data = await client.rest_get("/1.1/trends/place.json", params={"id": str(woeid)})
    if not isinstance(data, list) or not data:
        return []

    trends = data[0].get("trends", [])
    return [
        {
            "name": t.get("name"),
            "query": t.get("query"),
            "url": t.get("url"),
            "tweet_volume": t.get("tweet_volume"),
            "promoted": t.get("promoted_content") is not None,
        }
        for t in trends
    ]


# ─── Search ───────────────────────────────────────────────────────────────────

async def search_tweets(
    client: XClient,
    query: str,
    limit: int = 50,
    mode: str = "Top",
) -> list[dict[str, Any]]:
    """
    Search tweets by query.
    mode="Top" returns the most engaged tweets (likes, RTs).
    mode="Latest" returns the most recent ones (usually less engagement).
    """
    all_tweets: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(all_tweets) < limit:
        variables: dict[str, Any] = {
            "rawQuery": query,
            "count": min(PAGE_SIZE_SEARCH, limit - len(all_tweets)),
            "querySource": "typed_query",
            "product": mode,
        }
        if cursor:
            variables["cursor"] = cursor

        try:
            data = await client.graphql("SearchTimeline", variables=variables)
        except ForbiddenError as e:
            # X sometimes blocks certain queries. If we already have
            # results, return them (with a warning); otherwise re-raise so
            # the caller knows the query was blocked.
            if all_tweets:
                _log.warning("Search blocked (403) after %d tweets: %s", len(all_tweets), e)
                break
            raise

        timeline = (
            data.get("data", {})
                .get("search_by_raw_query", {})
                .get("search_timeline", {})
                .get("timeline", {})
        )
        if not timeline:
            break

        instructions = timeline.get("instructions", [])
        batch, new_cursor = _parse_tweet_list(instructions)

        all_tweets.extend(batch)

        if not new_cursor or new_cursor == cursor or not batch:
            break
        cursor = new_cursor

    return all_tweets[:limit]


# ─── Sync wrappers (easy use from other projects) ─────────────────────────────

def _run_sync(coro):
    """Run a coroutine on a fresh event loop and close it properly."""
    return asyncio.run(coro)


async def _with_client(cookies: str, coro):
    async with TwitterClient(cookies=cookies) as client:
        return await coro(client)


def search_tweets_sync(
    cookies: str,
    query: str,
    limit: int = 50,
    mode: str = "Top",
) -> list[dict[str, Any]]:
    """Sync wrapper to search tweets. No asyncio needed."""
    return _run_sync(_with_client(cookies, lambda c: search_tweets(c, query=query, limit=limit, mode=mode)))


def scrape_profile_sync(cookies: str, username: str) -> dict[str, Any]:
    """Sync wrapper to fetch a user profile."""
    return _run_sync(_with_client(cookies, lambda c: scrape_profile(c, username)))


def scrape_tweets_sync(
    cookies: str,
    username: str,
    limit: int = 50,
    include_replies: bool = False,
) -> list[dict[str, Any]]:
    """Sync wrapper to fetch a user's tweets."""
    return _run_sync(_with_client(cookies, lambda c: scrape_tweets(c, username, limit, include_replies)))


def get_user_likes_sync(cookies: str, username: str, limit: int = 50) -> list[dict[str, Any]]:
    """Sync wrapper to fetch a user's public likes."""
    return _run_sync(_with_client(cookies, lambda c: get_user_likes(c, username, limit)))


def get_tweet_replies_sync(cookies: str, tweet_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Sync wrapper to fetch a tweet's replies."""
    return _run_sync(_with_client(cookies, lambda c: get_tweet_replies(c, tweet_id, limit)))


def get_tweet_favoriters_sync(cookies: str, tweet_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Sync wrapper to fetch the users who liked a tweet."""
    return _run_sync(_with_client(cookies, lambda c: get_tweet_favoriters(c, tweet_id, limit)))


def get_tweet_retweeters_sync(cookies: str, tweet_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Sync wrapper to fetch the users who retweeted a tweet."""
    return _run_sync(_with_client(cookies, lambda c: get_tweet_retweeters(c, tweet_id, limit)))


def get_bookmarks_sync(cookies: str, limit: int = 50) -> list[dict[str, Any]]:
    """Sync wrapper to fetch the authenticated user's bookmarks."""
    return _run_sync(_with_client(cookies, lambda c: get_bookmarks(c, limit)))


def get_home_timeline_sync(cookies: str, limit: int = 50, latest: bool = False) -> list[dict[str, Any]]:
    """Sync wrapper to fetch the home timeline."""
    return _run_sync(_with_client(cookies, lambda c: get_home_timeline(c, limit, latest)))


def get_trends_sync(cookies: str, woeid: int = 1) -> list[dict[str, Any]]:
    """Sync wrapper to fetch trending topics."""
    return _run_sync(_with_client(cookies, lambda c: get_trends(c, woeid)))


def validate_cookies_sync(cookies: str) -> dict[str, Any]:
    """Sync wrapper to check that the cookies work."""
    return _run_sync(_with_client(cookies, lambda c: c.validate_cookies()))
