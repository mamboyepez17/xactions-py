"""Monitoring commands: watch, media download, follower snapshots."""

from __future__ import annotations

import click

from ..scrapers import (
    scrape_followers,
    scrape_tweets,
)
from ._app import cli
from ._common import (
    COOKIES_ENV,
    _flatten_tweets,
    _handle_output,
    common_options,
    print_json,
    print_tweets_table,
    run,
    with_client,
)


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=20, show_default=True)
@click.option("--mode", default="Latest", type=click.Choice(["Latest", "Top"]))
@click.option("--loop", "loop_interval", type=float, default=0, help="Seconds between polls (0 = once)")
@click.option("--max-polls", type=int, default=0, help="Stop after N polls when --loop > 0 (0 = forever)")
@common_options
@with_client
def watch(client, query, limit, mode, loop_interval, max_polls, output, csv_path, ndjson_path, table):
    """Poll a search and print only new tweets (delta)."""
    from ..notify import format_tweet_alert, make_notifier
    from ..watch import watch_search_once

    notify = make_notifier()
    polls = 0
    while True:
        result = run(watch_search_once(client, query, limit=limit, mode=mode))
        polls += 1
        new = result["new_tweets"]
        if new:
            alert = format_tweet_alert(new, query)
            notify(alert)
            _handle_output(
                {"query": query, "new_count": result["new_count"], "tweets": new},
                output, csv_path, ndjson_path,
                csv_data=_flatten_tweets(new),
                table_fn=print_tweets_table if table else None,
                table_title=f"New for “{query}”",
            )
        else:
            click.echo(f"… no new tweets for “{query}” (poll {polls})")
        if loop_interval <= 0:
            break
        if max_polls and polls >= max_polls:
            break
        import time as _time
        _time.sleep(loop_interval)


@cli.command("download-media")
@click.argument("username")
@click.option("--limit", "-l", default=30, show_default=True, help="Tweets to scan for media")
@click.option("--dest", default="media", show_default=True, help="Output directory")
@click.option("--max-files", default=50, show_default=True)
@common_options
@with_client
def download_media_cmd(client, username, limit, dest, max_files, output, csv_path, ndjson_path, table):
    """Download photos/videos from a user's recent tweets."""
    from ..media import collect_media_urls, download_media

    tweets = run(scrape_tweets(client, username, limit=limit))
    urls = collect_media_urls(tweets)
    result = run(download_media(urls, dest, max_files=max_files))
    result["media_found"] = len(urls)
    if output:
        print_json(result, output)
        return
    click.echo(
        f"📁 {len(result['downloaded'])} downloaded, "
        f"{len(result['skipped'])} skipped, {len(result['failed'])} failed → {result['dest']}"
    )


@cli.command("snapshot-followers")
@click.argument("username")
@click.option("--limit", "-l", default=200, show_default=True)
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
@with_client
def snapshot_followers(client, username, limit):
    """Save a follower snapshot for later unfollower diff."""
    from ..media import save_follower_snapshot

    followers = run(scrape_followers(client, username, limit=limit))
    ids = [str(u["id"]) for u in followers if u.get("id")]
    save_follower_snapshot(username, ids)
    click.echo(f"💾 Saved {len(ids)} followers for @{username}")


@cli.command("unfollowers")
@click.argument("username")
@click.option("--limit", "-l", default=200, show_default=True)
@click.option("--save", "do_save", is_flag=True, help="Also save this run as new snapshot")
@click.option("--output", "-o", default=None)
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
@with_client
def unfollowers_cmd(client, username, limit, do_save, output):
    """Diff current followers vs last snapshot (who unfollowed)."""
    from ..media import diff_followers, load_follower_snapshot, save_follower_snapshot

    prev = load_follower_snapshot(username)
    if prev is None:
        raise click.ClickException(
            f"No snapshot for @{username}. Run: xactions snapshot-followers {username}"
        )
    followers = run(scrape_followers(client, username, limit=limit))
    ids = [str(u["id"]) for u in followers if u.get("id")]
    diff = diff_followers(prev, ids)
    report = {
        "username": username,
        "previous_count": len(prev),
        "current_count": len(ids),
        "unfollowed_count": len(diff["unfollowed"]),
        "new_followers_count": len(diff["new_followers"]),
        **diff,
    }
    if do_save:
        save_follower_snapshot(username, ids)
    if output:
        print_json(report, output)
        return
    click.echo(
        f"📉 @{username}: {report['unfollowed_count']} unfollowed, "
        f"{report['new_followers_count']} new (prev {report['previous_count']} → now {report['current_count']})"
    )
    for uid in diff["unfollowed"][:20]:
        click.echo(f"  - {uid}")
    if report["unfollowed_count"] > 20:
        click.echo(f"  … and {report['unfollowed_count'] - 20} more")
