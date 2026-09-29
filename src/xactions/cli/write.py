"""Commands that write to X (posts, likes, follows, engage)."""

from __future__ import annotations

import re
import sys

import click

from ..actions import (
    bulk_unfollow,
    create_bookmark,
    delete_bookmark,
    delete_tweet,
    follow_user,
    like_tweet,
    post_thread,
    post_tweet,
    unfollow_user,
    unlike_tweet,
    upload_media,
)
from ..scrapers import (
    get_user_id,
    scrape_non_followers,
)
from ._app import cli
from ._common import (
    COOKIES_ENV,
    print_users_table,
    run,
    with_client,
)

# ─── Write actions ────────────────────────────────────────────────────────────

@cli.command()
@click.argument("text")
@click.option("--reply-to", default=None, help="ID of the tweet to reply to")
@click.option("--media", "media_files", multiple=True, type=click.Path(exists=True),
              help="Image to attach (repeatable, max 4)")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def post(client, text, reply_to, media_files):
    """Post a tweet. Requires auth_token."""
    from ..drafts import approval_required, create_draft

    if approval_required():
        if media_files:
            raise click.ClickException(
                "Approval is required (XACTIONS_REQUIRE_APPROVAL) and drafts cannot carry media yet. "
                "Post without --media or disable approval."
            )
        draft = create_draft(
            "post_tweet",
            {"text": text, "reply_to_id": reply_to},
        )
        click.echo(f"📝 Draft saved (approval required): {draft['id']}")
        click.echo("   Review: xactions drafts list → xactions drafts approve <id>")
        return

    async def _post():
        media_ids = []
        for path in media_files[:4]:
            up = await upload_media(client, path)
            media_ids.append(up["media_id"])
            click.echo(f"📎 Media uploaded: {path} (id {up['media_id']})")
        return await post_tweet(client, text, reply_to_id=reply_to, media_ids=media_ids)

    result = run(_post())
    if result["success"]:
        click.echo(f"✅ Tweet posted! ID: {result['tweet_id']}")
    else:
        click.echo(f"❌ Could not post. {result.get('error') or ''}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("tweets", nargs=-1)
@click.option("--from-file", type=click.Path(exists=True), default=None,
              help="Text file: one tweet per line, or tweets separated by ---")
@click.option("--delay", default=1.5, show_default=True, help="Seconds between thread tweets")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def thread(client, tweets, from_file, delay):
    """Post a thread. Each argument is a tweet, or use --from-file."""
    parts: list[str] = []
    if from_file:
        raw = open(from_file, encoding="utf-8").read()
        # split on ---, or on blank lines if there is no ---
        if "\n---\n" in raw or raw.strip().startswith("---"):
            chunks = [c.strip() for c in re.split(r"\n?---\n?", raw) if c.strip()]
        else:
            chunks = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        parts.extend(chunks)
    parts.extend(t.strip() for t in tweets if t and t.strip())

    if not parts:
        raise click.ClickException("Pass tweets as arguments or use --from-file")

    click.echo(f"🧵 Posting a {len(parts)}-tweet thread…")
    result = run(post_thread(client, parts, delay_seconds=delay))
    if result["success"]:
        click.echo(f"✅ Thread posted. Root: {result['root_id']} ({result['count']} tweets)")
    else:
        click.echo(f"❌ {result.get('error', 'Error')}", err=True)
        if result.get("tweet_ids"):
            click.echo(f"   Partially posted: {', '.join(result['tweet_ids'])}", err=True)
        sys.exit(1)

@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def delete(client, tweet_id):
    """Delete a tweet by ID. Requires auth_token."""
    result = run(delete_tweet(client, tweet_id))
    click.echo("✅ Tweet deleted." if result["success"] else "❌ Could not delete.")


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def like(client, tweet_id):
    """Like a tweet. Requires auth_token."""
    from ..drafts import approval_required, create_draft

    if approval_required():
        draft = create_draft("like", {"tweet_id": tweet_id})
        click.echo(f"📝 Draft saved: {draft['id']} — approve with: xactions drafts approve {draft['id']}")
        return
    result = run(like_tweet(client, tweet_id))
    click.echo("✅ Liked." if result["success"] else "❌ Could not like.")


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def unlike(client, tweet_id):
    """Remove a like. Requires auth_token."""
    result = run(unlike_tweet(client, tweet_id))
    click.echo("✅ Like removed." if result["success"] else "❌ Could not remove the like.")


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def bookmark(client, tweet_id):
    """Bookmark a tweet. Requires auth_token."""
    result = run(create_bookmark(client, tweet_id))
    click.echo("✅ Bookmarked." if result["success"] else "❌ Could not bookmark.")


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def unbookmark(client, tweet_id):
    """Remove a bookmark. Requires auth_token."""
    result = run(delete_bookmark(client, tweet_id))
    click.echo("✅ Bookmark removed." if result["success"] else "❌ Could not remove the bookmark.")


@cli.command()
@click.argument("username")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def follow(client, username):
    """Follow a user. Requires auth_token."""
    user_id = run(get_user_id(client, username))
    result = run(follow_user(client, user_id))
    click.echo(f"✅ Following @{username}." if result["success"] else f"❌ Could not follow @{username}.")


@cli.command()
@click.argument("username")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def unfollow(client, username):
    """Unfollow a user. Requires auth_token."""
    user_id = run(get_user_id(client, username))
    result = run(unfollow_user(client, user_id))
    click.echo(f"✅ Unfollowed @{username}." if result["success"] else f"❌ Could not unfollow @{username}.")


@cli.command("bulk-unfollow")
@click.argument("username")
@click.option("--limit", "-l", default=200, show_default=True, help="How many followed accounts to check")
@click.option("--delay", default=2.0, show_default=True, help="Seconds between unfollows")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@click.option("--dry-run", is_flag=True, help="Only show who would be unfollowed; change nothing")
@with_client
def bulk_unfollow_cmd(client, username, limit, delay, dry_run):
    """
    Unfollow every account that does not follow you back.
    ⚠️  Run with --dry-run first to see what would happen.
    """
    try:
        non_followers = run(scrape_non_followers(client, username, limit=limit))

        if not non_followers:
            click.echo("✅ Everyone you follow follows you back!")
            return

        click.echo(f"\n📋 Found {len(non_followers)} non-followers:")
        print_users_table(non_followers[:10])
        if len(non_followers) > 10:
            click.echo(f"  ... and {len(non_followers) - 10} more")

        if dry_run:
            click.echo("\n🔍 Dry-run: nothing was changed. Drop --dry-run to execute.")
            return

        click.confirm(f"\n⚠️  Unfollow {len(non_followers)} users?", abort=True)

        user_ids = [u["id"] for u in non_followers if u.get("id")]

        with click.progressbar(length=len(user_ids), label="Unfollowing") as bar:
            def on_progress(current, total, uid):
                bar.update(1)

            result = run(bulk_unfollow(client, user_ids, delay_seconds=delay, on_progress=on_progress))

        click.echo(
            f"\n✅ Done: {result['success']} succeeded, {result['failed']} failed, {result['total']} total."
        )

    except click.Abort:
        click.echo("\nCancelled.")

@cli.command()
@click.argument("query")
@click.option("--like", is_flag=True, help="Like matching tweets")
@click.option("--retweet", is_flag=True, help="Retweet matching tweets")
@click.option("--limit", "-l", default=10, show_default=True, help="Max tweets to consider")
@click.option("--delay", default=3.0, show_default=True, help="Seconds between write actions")
@click.option("--min-likes", type=int, default=None, help="Skip tweets below this like count")
@click.option("--dry-run", is_flag=True, default=True, help="Preview only (default)")
@click.option("--execute", is_flag=True, help="Actually perform likes/RTs (uses daily caps)")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
@with_client
def engage(client, query, like, retweet, limit, delay, min_likes, dry_run, execute):
    """
    Engage with search results (like / retweet) with delay and daily caps.

    Always preview with --dry-run; add --execute to write.
    """
    from ..actions import like_tweet
    from ..actions import retweet as rt_action
    from ..caps import WriteCapExceeded
    from ..scrapers import search_tweets

    if not like and not retweet:
        raise click.ClickException("Pass --like and/or --retweet")
    if execute:
        dry_run = False

    tweets = run(search_tweets(client, query, limit=limit, mode="Latest"))
    if min_likes is not None:
        tweets = [t for t in tweets if (t.get("likes") or 0) >= min_likes]

    click.echo(f"Found {len(tweets)} tweets for “{query}”")
    planned = []
    for t in tweets:
        planned.append(
            {
                "id": t.get("id"),
                "like": like,
                "retweet": retweet,
                "likes": t.get("likes"),
                "text": (t.get("text") or "")[:60],
            }
        )

    if dry_run:
        click.echo("🔍 DRY-RUN — nothing will be written. Use --execute to run.")
        for p in planned:
            acts = "+".join([a for a, on in (("like", p["like"]), ("rt", p["retweet"])) if on])
            click.echo(f"  [{acts}] {p['id']} ❤{p['likes']} {p['text']}")
        return

    done = {"like": 0, "retweet": 0, "skipped": 0, "failed": 0}
    import time as _time

    for p in planned:
        tid = p["id"]
        if not tid:
            continue
        try:
            if p["like"]:
                r = run(like_tweet(client, str(tid)))
                if r.get("success"):
                    done["like"] += 1
                else:
                    done["failed"] += 1
                _time.sleep(delay)
            if p["retweet"]:
                r = run(rt_action(client, str(tid)))
                if r.get("success"):
                    done["retweet"] += 1
                else:
                    done["failed"] += 1
                _time.sleep(delay)
        except WriteCapExceeded as e:
            click.echo(f"🛑 Cap reached: {e}", err=True)
            done["skipped"] += 1
            break
    click.echo(
        f"Engage done: likes={done['like']} rts={done['retweet']} "
        f"failed={done['failed']} stopped_cap={done['skipped']}"
    )
