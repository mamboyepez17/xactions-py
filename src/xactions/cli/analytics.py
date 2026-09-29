"""Analytics, tracking and reporting commands."""

from __future__ import annotations

import asyncio
import json
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
    print_analysis,
    print_json,
    run,
    with_client,
)

# ─── Analytics & tracking ─────────────────────────────────────────────────────

@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True, help="Tweets a analizar")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@click.option("--output", "-o", default=None, help="Archivo JSON de salida")
@with_client
def analyze(client, username, limit, output):
    """Analiza el engagement de un usuario (promedios, top tweets, mejores horas)."""

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
@click.option("--limit", "-l", default=50, show_default=True, help="Tweets a trackear")
@click.option("--db", "db_path", default=None, help="Path de la base SQLite (default ~/.xactions/xactions.db)")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def track(client, username, limit, db_path):
    """Guarda un snapshot de métricas de un usuario en SQLite y muestra el delta."""
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

    click.echo(f"\n📸 Snapshot guardado para @{username} ({saved} tweets)")
    click.echo(f"  Followers: {prof.get('followers', 0):,}")
    if delta["followers_delta"] is not None:
        sign = "+" if delta["followers_delta"] >= 0 else ""
        click.echo(f"  Δ followers: {sign}{delta['followers_delta']:,} (desde {delta.get('since')})")
        click.echo(f"  Δ tweets:    {'+' if delta['tweets_delta'] >= 0 else ''}{delta['tweets_delta']:,}")
    else:
        click.echo("  (primer snapshot — corre el comando de nuevo para ver deltas)")
    click.echo(f"  DB: {db.path}\n")


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=30, show_default=True, help="Snapshots a mostrar")
@click.option("--db", "db_path", default=None, help="Path de la base SQLite")
@click.option("--output", "-o", default=None, help="Archivo JSON de salida")
def history(username, limit, db_path, output):
    """Muestra el histórico de snapshots de un usuario trackeado."""
    try:
        db = TrackerDB(db_path)
        rows = db.get_profile_history(username, limit=limit)

        if output:
            print_json({"username": username, "count": len(rows), "history": rows}, output)
            return

        if not rows:
            click.echo(f"⚠️  No hay snapshots de @{username}. Usa: xactions track {username}")
            return

        click.echo(f"\n{'─'*60}")
        click.echo(f"  📈 Histórico de @{username} ({len(rows)} snapshots)")
        click.echo(f"{'─'*60}")
        click.echo(f"  {'Fecha':<22} {'Followers':>12} {'Following':>12} {'Tweets':>10}")
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
@click.option("--limit", "-l", default=50, show_default=True, help="Tweets a analizar por cuenta")
@click.option("--output", "-o", default=None, help="Archivo JSON de salida")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@click.option("--table", is_flag=True, help="Mostrar como tabla")
@with_client
def compare(client, user_a, user_b, limit, output, table):
    """Compara dos cuentas: followers, engagement rate y promedios."""

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

    if output:
        print_json(report, output)
        return

    a, b = report["a"], report["b"]
    click.echo(f"\n{'═'*60}")
    click.echo(f"  Comparativa @{a['username']} vs @{b['username']}")
    click.echo(f"{'═'*60}")
    click.echo(f"  {'Métrica':<28} {'@' + str(a['username']):>14} {'@' + str(b['username']):>14}")
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
    click.echo(f"\n  Ganadores: followers={winners.get('followers')} · "
               f"ER={winners.get('engagement_rate_followers')} · "
               f"likes={winners.get('avg_likes')}")
    click.echo(f"{'═'*60}\n")

@cli.command()
@click.argument("target")
@click.argument("target_b", required=False)
@click.option("--limit", "-l", default=50, show_default=True, help="Tweets to sample")
@click.option("--format", "fmt", type=click.Choice(["md", "html"]), default="md")
@click.option("--out", "out_path", default=None, help="Write report to file (default stdout)")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
@with_client
def report(client, target, target_b, limit, fmt, out_path):
    """
    Generate a shareable engagement report.

    xactions report USERNAME
    xactions report USER_A USER_B --format html --out compare.html
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
        content = (
            render_account_report_html(prof, tw)
            if fmt == "html"
            else render_account_report_md(prof, tw)
        )

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
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
@with_client
def sentiment(client, query, file_path, limit, output):
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
