"""
XActions-PY — MCP Server
MCP server for AI agents.
No npm. Uses MCPServer (mcp>=2) or FastMCP (mcp 1.x) + plain httpx.

v1.2.0:
  - New tools: replies, favoriters, retweeters, user likes, bookmarks,
    home timeline, trending topics, cookie validation, bookmark/unbookmark.
  - Better error handling (ForbiddenError).

v1.5.0:
  - Compatible with mcp 2.x (MCPServer) and mcp 1.x (FastMCP).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from dotenv import load_dotenv

load_dotenv()

try:
    # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _MCPServer
except ImportError:  # pragma: no cover - compat mcp 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer  # type: ignore[no-redef,attr-defined]

from .actions import (
    bulk_unfollow,
    create_bookmark,
    delete_bookmark,
    delete_tweet,
    follow_user,
    like_tweet,
    post_thread,
    post_tweet,
    retweet,
    unfollow_user,
    unlike_tweet,
)
from .analyzer import analyze_tweets, compare_accounts
from .client import (
    AuthError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    TwitterClient,
    TwitterError,
)
from .drafts import approval_required, create_draft
from .pool import ClientPool
from .scrapers import (
    get_bookmarks,
    get_home_timeline,
    get_trends,
    get_tweet_favoriters,
    get_tweet_replies,
    get_tweet_retweeters,
    get_user_id,
    get_user_likes,
    scrape_followers,
    scrape_following,
    scrape_non_followers,
    scrape_profile,
    scrape_tweets,
    search_tweets,
)
from .search_query import build_search_query

# ─── Setup ───────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

mcp = _MCPServer(
    "xactions-py",
    instructions="X/Twitter automation toolkit — Python port of XActions. No npm.",
)

_cookies = os.getenv("TWITTER_COOKIES", "")
_proxy = os.getenv("TWITTER_PROXY")
_client: TwitterClient | ClientPool | None = None
_client_key: str | None = None


def get_client(cookies: str | None = None) -> TwitterClient | ClientPool:
    """
    Return the singleton client, rebuilding it when new cookies are passed.
    Several cookie strings (separated by '|||' or newlines) create a pool.
    """
    global _client, _client_key
    effective = cookies or _cookies
    if _client is None or effective != _client_key:
        old = _client
        parts = [c.strip() for c in effective.replace("\n", "|||").split("|||") if c.strip()]
        _client = ClientPool(parts, proxy=_proxy) if len(parts) > 1 else TwitterClient(
            cookies=parts[0] if parts else "", proxy=_proxy
        )
        _client_key = effective
        # Close the previous client (frees sockets) without blocking the loop.
        if old is not None:
            asyncio.get_running_loop().create_task(old.aclose())
    return _client


def _fmt_error(e: Exception) -> str:
    if isinstance(e, AuthError):
        return f"❌ Authentication error: {e}. Check your auth_token and ct0."
    if isinstance(e, ForbiddenError):
        return f"🚫 Access denied: {e}. X may restrict this account/query."
    if isinstance(e, RateLimitError):
        return f"⏳ Rate limited: {e}. Wait a few minutes."
    if isinstance(e, NotFoundError):
        return f"🔍 Not found: {e}"
    if isinstance(e, TwitterError):
        return f"🐦 X error: {e}"
    return f"💥 Unexpected error: {type(e).__name__}: {e}"


def _draft_if_required(action: str, params: dict) -> str | None:
    """
    Approval gate for write tools. When XACTIONS_REQUIRE_APPROVAL is set the
    write is saved as a draft instead of reaching X, and the returned message
    tells the agent that a human has to release it from the CLI.
    """
    if not approval_required():
        return None
    draft = create_draft(action, params)
    return (
        f"📝 Approval required: saved draft {draft['id']} ({action}); nothing was sent to X. "
        f"A human must review and run it with: xactions drafts approve {draft['id']}"
    )


# ─── MCP tools ───────────────────────────────────────────────────────────────

@mcp.tool()
async def x_set_cookies(cookies: str) -> str:
    """
    Set the X session cookies for this session.
    Get auth_token and ct0 from: x.com → DevTools (F12) → Application → Cookies.
    cookies: string in the form 'auth_token=xxx; ct0=yyy'
    """
    get_client(cookies)
    return "✅ Cookies set."


@mcp.tool()
async def x_validate_cookies() -> str:
    """Check that the current cookies are valid."""
    try:
        client = get_client()
        result = await client.validate_cookies()
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_profile(username: str) -> str:
    """
    Fetch an X user's full profile.
    username: handle without @ (e.g. 'elonmusk')
    """
    try:
        client = get_client()
        profile = await scrape_profile(client, username)
        return json.dumps(profile, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_followers(username: str, limit: int = 100) -> str:
    """
    Fetch a user's followers.
    username: handle without @
    limit: maximum users to fetch (default 100, recommended max 500)
    """
    try:
        client = get_client()
        followers = await scrape_followers(client, username, limit=limit)
        return json.dumps({
            "count": len(followers),
            "followers": followers,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_following(username: str, limit: int = 100) -> str:
    """
    Fetch the accounts a user follows.
    username: handle without @
    limit: maximum users to fetch
    """
    try:
        client = get_client()
        following = await scrape_following(client, username, limit=limit)
        return json.dumps({
            "count": len(following),
            "following": following,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_non_followers(username: str, limit: int = 200) -> str:
    """
    Find accounts you follow that do NOT follow you back.
    Useful to clean up your following list.
    username: your handle without @
    limit: how many followed accounts to check (default 200)
    """
    try:
        client = get_client()
        non_followers = await scrape_non_followers(client, username, limit=limit)
        return json.dumps({
            "count": len(non_followers),
            "non_followers": non_followers,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_tweets(
    username: str,
    limit: int = 50,
    include_replies: bool = False,
) -> str:
    """
    Fetch a user's recent tweets.
    username: handle without @
    limit: number of tweets (default 50)
    include_replies: incluir respuestas (default False)
    """
    try:
        client = get_client()
        tweets = await scrape_tweets(client, username, limit=limit, include_replies=include_replies)
        return json.dumps({
            "count": len(tweets),
            "tweets": tweets,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_user_likes(username: str, limit: int = 50) -> str:
    """Fetch the tweets a user liked."""
    try:
        client = get_client()
        tweets = await get_user_likes(client, username, limit=limit)
        return json.dumps({
            "count": len(tweets),
            "tweets": tweets,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_search_tweets(
    query: str,
    limit: int = 50,
    mode: str = "Top",
) -> str:
    """
    Search tweets by query.
    query: search terms
    limit: number of results (default 50)
    mode: 'Latest' or 'Top'
    """
    try:
        client = get_client()
        tweets = await search_tweets(client, query, limit=limit, mode=mode)
        return json.dumps({
            "query": query,
            "count": len(tweets),
            "tweets": tweets,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_tweet_replies(tweet_id: str, limit: int = 50) -> str:
    """Fetch a tweet's replies/conversation."""
    try:
        client = get_client()
        tweets = await get_tweet_replies(client, tweet_id, limit=limit)
        return json.dumps({
            "tweet_id": tweet_id,
            "count": len(tweets),
            "tweets": tweets,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_tweet_favoriters(tweet_id: str, limit: int = 100) -> str:
    """Fetch the users who liked a tweet."""
    try:
        client = get_client()
        users = await get_tweet_favoriters(client, tweet_id, limit=limit)
        return json.dumps({
            "tweet_id": tweet_id,
            "count": len(users),
            "users": users,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_tweet_retweeters(tweet_id: str, limit: int = 100) -> str:
    """Fetch the users who retweeted a tweet."""
    try:
        client = get_client()
        users = await get_tweet_retweeters(client, tweet_id, limit=limit)
        return json.dumps({
            "tweet_id": tweet_id,
            "count": len(users),
            "users": users,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_bookmarks(limit: int = 50) -> str:
    """Fetch the authenticated user's bookmarks. Requires auth."""
    try:
        client = get_client()
        tweets = await get_bookmarks(client, limit=limit)
        return json.dumps({
            "count": len(tweets),
            "tweets": tweets,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_home_timeline(limit: int = 50, latest: bool = False) -> str:
    """Fetch the authenticated user's home timeline. Requires auth."""
    try:
        client = get_client()
        tweets = await get_home_timeline(client, limit=limit, latest=latest)
        return json.dumps({
            "count": len(tweets),
            "tweets": tweets,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_analyze_user(username: str, limit: int = 100) -> str:
    """
    Analyze a user's engagement: averages, engagement rate,
    top tweets, best hours and days to post.
    username: handle without @
    limit: how many recent tweets to analyze (default 100)
    """
    try:
        client = get_client()
        profile = await scrape_profile(client, username)
        tweets = await scrape_tweets(client, username, limit=limit)
        report = analyze_tweets(tweets, profile=profile)
        report["username"] = username
        return json.dumps(report, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_get_trends(woeid: int = 1) -> str:
    """Fetch trending topics. woeid=1 is worldwide."""
    try:
        client = get_client()
        trends = await get_trends(client, woeid=woeid)
        return json.dumps({
            "count": len(trends),
            "trends": trends,
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_post_tweet(
    text: str,
    reply_to_id: str | None = None,
) -> str:
    """
    Post a tweet. Requires authentication (auth_token).
    text: tweet text (max 280 characters)
    reply_to_id: ID of the tweet to reply to (optional)
    """
    try:
        if gated := _draft_if_required("post_tweet", {"text": text, "reply_to_id": reply_to_id}):
            return gated
        client = get_client()
        result = await post_tweet(client, text, reply_to_id=reply_to_id)
        if result["success"]:
            return f"✅ Tweet posted. ID: {result['tweet_id']}"
        return "❌ Could not post the tweet."
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_post_thread(tweets: list[str], delay: float = 1.5) -> str:
    """
    Post a thread (each tweet replies to the previous one). Requires auth.
    tweets: texts in order
    delay: seconds between tweets (default 1.5)
    """
    try:
        if gated := _draft_if_required("post_thread", {"tweets": tweets, "delay_seconds": delay}):
            return gated
        client = get_client()
        result = await post_thread(client, tweets, delay_seconds=delay)
        if result["success"]:
            return (
                f"✅ Thread posted ({result['count']} tweets).\n"
                f"  Root: {result['root_id']}\n"
                f"  IDs: {', '.join(result['tweet_ids'])}"
            )
        return f"❌ {result.get('error', 'Error posting thread')}"
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_compare_accounts(user_a: str, user_b: str, limit: int = 50) -> str:
    """
    Compare two accounts: followers, engagement rate and averages.
    user_a / user_b: handles without @
    limit: recent tweets to analyze per account (default 50)
    """
    try:
        client = get_client()
        prof_a, tw_a, prof_b, tw_b = await asyncio.gather(
            scrape_profile(client, user_a),
            scrape_tweets(client, user_a, limit=limit),
            scrape_profile(client, user_b),
            scrape_tweets(client, user_b, limit=limit),
        )
        report = compare_accounts(prof_a, tw_a, prof_b, tw_b)
        return json.dumps(report, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_build_search_query(
    base: str = "",
    from_user: str | None = None,
    since: str | None = None,
    until: str | None = None,
    min_faves: int | None = None,
    lang: str | None = None,
    exclude_retweets: bool = False,
) -> str:
    """
    Build an X advanced-search query (from/since/min_faves… operators).
    Use it with x_search_tweets.
    """
    q = build_search_query(
        base,
        from_user=from_user,
        since=since,
        until=until,
        min_faves=min_faves,
        lang=lang,
        exclude_retweets=exclude_retweets,
    )
    return json.dumps({"query": q}, ensure_ascii=False)


@mcp.tool()
async def x_delete_tweet(tweet_id: str) -> str:
    """
    Delete a tweet by ID. Requires authentication.
    tweet_id: numeric tweet ID
    """
    try:
        if gated := _draft_if_required("delete", {"tweet_id": tweet_id}):
            return gated
        client = get_client()
        result = await delete_tweet(client, tweet_id)
        return "✅ Tweet deleted." if result["success"] else "❌ Could not delete the tweet."
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_like_tweet(tweet_id: str) -> str:
    """Like a tweet. Requires authentication."""
    try:
        if gated := _draft_if_required("like", {"tweet_id": tweet_id}):
            return gated
        result = await like_tweet(get_client(), tweet_id)
        return "✅ Liked." if result["success"] else "❌ Could not like the tweet."
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_unlike_tweet(tweet_id: str) -> str:
    """Remove a like from a tweet. Requires authentication."""
    try:
        if gated := _draft_if_required("unlike", {"tweet_id": tweet_id}):
            return gated
        result = await unlike_tweet(get_client(), tweet_id)
        return "✅ Like removed." if result["success"] else "❌ Could not remove the like."
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_retweet(tweet_id: str) -> str:
    """Retweet a tweet. Requires authentication."""
    try:
        if gated := _draft_if_required("retweet", {"tweet_id": tweet_id}):
            return gated
        result = await retweet(get_client(), tweet_id)
        return "✅ Retweeted." if result["success"] else "❌ Could not retweet."
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_follow_user(username: str) -> str:
    """
    Follow a user. Requires authentication.
    username: handle without @
    """
    try:
        if gated := _draft_if_required("follow", {"username": username}):
            return gated
        client = get_client()
        user_id = await get_user_id(client, username)
        result = await follow_user(client, user_id)
        return f"✅ Following @{username}." if result["success"] else f"❌ Could not follow @{username}."
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_unfollow_user(username: str) -> str:
    """
    Unfollow a user. Requires authentication.
    username: handle without @
    """
    try:
        if gated := _draft_if_required("unfollow", {"username": username}):
            return gated
        client = get_client()
        user_id = await get_user_id(client, username)
        result = await unfollow_user(client, user_id)
        return f"✅ Unfollowed @{username}." if result["success"] else f"❌ Could not unfollow @{username}."
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_bookmark_tweet(tweet_id: str) -> str:
    """Bookmark a tweet. Requires authentication."""
    try:
        if gated := _draft_if_required("bookmark", {"tweet_id": tweet_id}):
            return gated
        client = get_client()
        result = await create_bookmark(client, tweet_id)
        return "✅ Bookmarked." if result["success"] else "❌ Could not bookmark the tweet."
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_unbookmark_tweet(tweet_id: str) -> str:
    """Remove a tweet from bookmarks. Requires authentication."""
    try:
        if gated := _draft_if_required("unbookmark", {"tweet_id": tweet_id}):
            return gated
        client = get_client()
        result = await delete_bookmark(client, tweet_id)
        return "✅ Bookmark removed." if result["success"] else "❌ Could not remove the bookmark."
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_bulk_unfollow_non_followers(
    username: str,
    limit: int = 200,
    delay: float = 2.0,
    dry_run: bool = False,
) -> str:
    """
    Unfollow everyone who does not follow you back.
    USE WITH CARE — this makes real changes to your account.
    username: your handle without @
    limit: how many followed accounts to check (default 200)
    delay: seconds between unfollows (default 2.0, don't go below 1.0)
    dry_run: if True, only show who would be unfollowed without doing anything
    """
    try:
        client = get_client()
        non_followers = await scrape_non_followers(client, username, limit=limit)

        if not non_followers:
            return "✅ Everyone you follow follows you back. Nothing to do."

        user_ids = [u["id"] for u in non_followers if u.get("id")]
        names = [f"@{u['username']}" for u in non_followers[:5]]
        preview = ", ".join(names)
        if len(non_followers) > 5:
            preview += f" and {len(non_followers) - 5} more..."

        if dry_run:
            return (
                f"🔍 DRY-RUN — nothing was unfollowed.\n"
                f"  Would unfollow: {len(user_ids)} users\n"
                f"  First: {preview}"
            )

        if approval_required():
            ids = [
                create_draft("unfollow", {"user_id": u["id"], "username": u.get("username")})["id"]
                for u in non_followers
                if u.get("id")
            ]
            return (
                f"📝 Approval required: saved {len(ids)} unfollow draft(s); nothing was sent to X.\n"
                f"  Users: {preview}\n"
                "  A human must review them with: xactions drafts list"
            )

        result = await bulk_unfollow(client, user_ids, delay_seconds=delay)

        return (
            f"✅ Bulk unfollow finished.\n"
            f"  Total:   {result['total']}\n"
            f"  Succeeded: {result['success']}\n"
            f"  Failed:  {result['failed']}\n"
            f"  Users: {preview}"
        )
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_list_drafts(status: str = "pending") -> str:
    """List write drafts. status: pending|approved|discarded|executed or empty for all."""
    try:
        from .drafts import list_drafts

        items = list_drafts(status=status or None)
        return json.dumps({"count": len(items), "drafts": items}, ensure_ascii=False, indent=2)
    except Exception as e:
        return _fmt_error(e)


@mcp.tool()
async def x_discard_draft(draft_id: str) -> str:
    """Discard a pending draft."""
    try:
        from .drafts import discard

        d = discard(draft_id)
        if not d:
            return f"Draft not found: {draft_id}"
        return f"🗑️ Draft {draft_id} discarded."
    except Exception as e:
        return _fmt_error(e)


# ─── Entry point ──────────────────────────────────────────────────────────────

# Applied at import time so the filter holds however the server is launched
# (`python -m`, `mcp run`, the `xactions-mcp` script, or an embedding host).
from .mcp_groups import apply_env_filter_to_mcp

ADVERTISED_TOOLS = apply_env_filter_to_mcp(mcp)


def main() -> None:
    logging.getLogger(__name__).info("MCP tools advertised: %d", len(ADVERTISED_TOOLS))
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
