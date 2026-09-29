"""Analytics, tracking and reporting commands."""

from __future__ import annotations

import asyncio
import json
import os
import sys

import click

from ..analyzer import analyze_tweets, compare_accounts
from ..db import TrackerDB, compute_profile_delta
from ..scrapers import (
    scrape_profile,
    scrape_tweets,
    search_tweets,
)
from ._app import cli
from ._common import (
    COOKIES_ENV,
    _flatten_tweets,
    export_options,
    export_rows,
    print_analysis,
    print_json,
    run,
    with_client,
)

# ─── Analytics & tracking ─────────────────────────────────────────────────────

@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True, help="Tweets to analyze")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@click.option("--output", "-o", default=None, help="Output JSON file")
@with_client
def analyze(client, username, limit, output):
    """Analyze a user's engagement (averages, top tweets, best hours)."""

    async def _analyze():
        prof = await scrape_profile(client, username)
        tw = await scrape_tweets(client, username, limit=limit)
        return prof, tw

    prof, tw = run(_analyze())
    report = analyze_tweets(tw, profile=prof)
    report["username"] = username
    report["followers"] = prof.get("followers")

    if output:
        print_json(report, output)
    else:
        print_analysis(report, username)


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=50, show_default=True, help="Tweets to snapshot")
@click.option("--db", "db_path", default=None, help="SQLite database path (default ~/.xactions/xactions.db)")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def track(client, username, limit, db_path):
    """Store a snapshot of a user's metrics in SQLite and show the delta."""
    db = TrackerDB(db_path)

    async def _collect():
        prof = await scrape_profile(client, username)
        tw = await scrape_tweets(client, username, limit=limit)
        return prof, tw

    prof, tw = run(_collect())

    previous = db.get_last_profile_snapshot(username)
    delta = compute_profile_delta(previous, prof)

    db.save_profile_snapshot(username, prof)
    saved = db.save_tweet_snapshots(tw)

    click.echo(f"\n📸 Snapshot saved for @{username} ({saved} tweets)")
    click.echo(f"  Followers: {prof.get('followers', 0):,}")
    if delta["followers_delta"] is not None:
        sign = "+" if delta["followers_delta"] >= 0 else ""
        click.echo(f"  Δ followers: {sign}{delta['followers_delta']:,} (since {delta.get('since')})")
        click.echo(f"  Δ tweets:    {'+' if delta['tweets_delta'] >= 0 else ''}{delta['tweets_delta']:,}")
    else:
        click.echo("  (first snapshot — run the command again to see deltas)")
    click.echo(f"  DB: {db.path}\n")


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=30, show_default=True, help="Snapshots to show")
@click.option("--db", "db_path", default=None, help="SQLite database path")
@click.option("--output", "-o", default=None, help="Output JSON file")
@export_options
def history(username, limit, db_path, output, csv_path, ndjson_path):
    """Show the snapshot history of a tracked user."""
    try:
        db = TrackerDB(db_path)
        rows = db.get_profile_history(username, limit=limit)

        if export_rows(rows, csv_path, ndjson_path):
            return
        if output:
            print_json({"username": username, "count": len(rows), "history": rows}, output)
            return

        if not rows:
            click.echo(f"⚠️  No snapshots for @{username}. Run: xactions track {username}")
            return

        click.echo(f"\n{'─'*60}")
        click.echo(f"  📈 History of @{username} ({len(rows)} snapshots)")
        click.echo(f"{'─'*60}")
        click.echo(f"  {'Date':<22} {'Followers':>12} {'Following':>12} {'Tweets':>10}")
        for r in reversed(rows):
            click.echo(
                f"  {r['captured_at']:<22} {r['followers']:>12,} "
                f"{r['following']:>12,} {r['tweets_count']:>10,}"
            )
        click.echo(f"{'─'*60}\n")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)

@cli.command()
@click.argument("user_a")
@click.argument("user_b")
@click.option("--limit", "-l", default=50, show_default=True, help="Tweets to analyze per account")
@click.option("--output", "-o", default=None, help="Output JSON file")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@click.option("--table", is_flag=True, help="Show as a table")
@export_options
@with_client
def compare(client, user_a, user_b, limit, output, table, csv_path, ndjson_path):
    """Compare two accounts: followers, engagement rate and averages."""

    async def _collect():
        prof_a, tw_a, prof_b, tw_b = await asyncio.gather(
            scrape_profile(client, user_a),
            scrape_tweets(client, user_a, limit=limit),
            scrape_profile(client, user_b),
            scrape_tweets(client, user_b, limit=limit),
        )
        return prof_a, tw_a, prof_b, tw_b

    prof_a, tw_a, prof_b, tw_b = run(_collect())
    report = compare_accounts(prof_a, tw_a, prof_b, tw_b)

    rows = [
        {
            "username": side.get("username"),
            "followers": side.get("followers"),
            "following": side.get("following"),
            "tweets_count": side.get("tweets_count"),
            "avg_likes": (side.get("averages") or {}).get("likes"),
            "avg_retweets": (side.get("averages") or {}).get("retweets"),
            "avg_views": (side.get("averages") or {}).get("views"),
            "engagement_rate_followers": side.get("engagement_rate_followers"),
        }
        for side in (report["a"], report["b"])
    ]
    if export_rows(rows, csv_path, ndjson_path):
        return
    if output:
        print_json(report, output)
        return

    a, b = report["a"], report["b"]
    click.echo(f"\n{'═'*60}")
    click.echo(f"  @{a['username']} vs @{b['username']}")
    click.echo(f"{'═'*60}")
    click.echo(f"  {'Metric':<28} {'@' + str(a['username']):>14} {'@' + str(b['username']):>14}")
    click.echo(f"  {'-'*56}")
    rows = [
        ("Followers", a.get("followers"), b.get("followers")),
        ("Following", a.get("following"), b.get("following")),
        ("Tweets (total)", a.get("tweets_count"), b.get("tweets_count")),
        ("Avg likes", (a.get("averages") or {}).get("likes"), (b.get("averages") or {}).get("likes")),
        ("Avg RTs", (a.get("averages") or {}).get("retweets"), (b.get("averages") or {}).get("retweets")),
        ("Avg views", (a.get("averages") or {}).get("views"), (b.get("averages") or {}).get("views")),
        ("ER followers %", a.get("engagement_rate_followers"), b.get("engagement_rate_followers")),
    ]
    for label, va, vb in rows:
        fa = f"{va:,}" if isinstance(va, (int, float)) else "—"
        fb = f"{vb:,}" if isinstance(vb, (int, float)) else "—"
        click.echo(f"  {label:<28} {fa:>14} {fb:>14}")
    winners = report.get("winner") or {}
    click.echo(f"\n  Winners: followers={winners.get('followers')} · "
               f"ER={winners.get('engagement_rate_followers')} · "
               f"likes={winners.get('avg_likes')}")
    click.echo(f"{'═'*60}\n")

@cli.command()
@click.argument("target")
@click.argument("target_b", required=False)
@click.option("--limit", "-l", default=50, show_default=True, help="Tweets to sample")
@click.option("--format", "fmt", type=click.Choice(["md", "html"]), default="md")
@click.option("--out", "out_path", default=None, help="Write report to file (default stdout)")
@click.option("--db", "db_path", default=None, help="Tracking DB for the follower-history chart (html)")
@click.option("--no-history", is_flag=True, help="Skip the follower-history chart")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
@with_client
def report(client, target, target_b, limit, fmt, out_path, db_path, no_history):
    """
    Generate a shareable engagement report.

    xactions report USERNAME
    xactions report USER_A USER_B --format html --out compare.html

    Single-account HTML reports include a follower-history chart when the
    account has been snapshotted with `xactions track` (2+ snapshots).
    """
    from ..report import (
        render_account_report_html,
        render_account_report_md,
        render_compare_report_html,
        render_compare_report_md,
    )

    if target_b:
        async def _cmp():
            return await asyncio.gather(
                scrape_profile(client, target),
                scrape_tweets(client, target, limit=limit),
                scrape_profile(client, target_b),
                scrape_tweets(client, target_b, limit=limit),
            )

        pa, ta, pb, tb = run(_cmp())
        content = (
            render_compare_report_html(pa, ta, pb, tb)
            if fmt == "html"
            else render_compare_report_md(pa, ta, pb, tb)
        )
    else:
        async def _one():
            return await asyncio.gather(
                scrape_profile(client, target),
                scrape_tweets(client, target, limit=limit),
            )

        prof, tw = run(_one())
        if fmt == "html":
            history = []
            if not no_history:
                from ..db import DEFAULT_DB_PATH

                path = db_path or str(DEFAULT_DB_PATH)
                if os.path.exists(path):  # never create an empty DB just to read it
                    history = TrackerDB(path).get_profile_history(target, limit=365)
            content = render_account_report_html(prof, tw, history=history)
        else:
            content = render_account_report_md(prof, tw)

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        click.echo(f"✅ Report written to {out_path}")
    else:
        click.echo(content)


@cli.command()
@click.argument("query", required=False, default="")
@click.option("--file", "file_path", type=click.Path(exists=True), default=None, help="JSON list of tweets")
@click.option("--limit", "-l", default=30, show_default=True)
@click.option("--output", "-o", default=None)
@export_options
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
@with_client
def sentiment(client, query, file_path, limit, output, csv_path, ndjson_path):
    """Score sentiment of a search query or a JSON tweet file (lightweight lexicon)."""
    from ..sentiment import score_tweets, summarize_sentiment

    if file_path:
        data = json.loads(open(file_path, encoding="utf-8").read())
        tweets = data if isinstance(data, list) else data.get("tweets") or []
    elif query:
        tweets = run(search_tweets(client, query, limit=limit, mode="Latest"))
    else:
        raise click.ClickException("Pass a search query or --file tweets.json")

    scored = score_tweets(tweets)
    summary = summarize_sentiment(scored)
    payload = {"summary": summary, "tweets": scored}
    rows = [
        {**flat, "sentiment_label": t["sentiment"]["label"], "sentiment_score": t["sentiment"]["score"]}
        for t, flat in zip(scored, _flatten_tweets(scored))
    ]
    if export_rows(rows, csv_path, ndjson_path):
        return
    if output:
        print_json(payload, output)
        return
    s = summary
    click.echo(
        f"Sentiment n={s['count']} avg={s['avg_score']:+.3f} "
        f"pos={s['positive']} neu={s['neutral']} neg={s['negative']}"
    )
    for t in scored[:10]:
        sent = t["sentiment"]
        click.echo(f"  [{sent['label'][:3]} {sent['score']:+.2f}] {(t.get('text') or '')[:70]}")
