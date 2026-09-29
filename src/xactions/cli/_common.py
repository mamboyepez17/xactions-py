"""Shared CLI helpers: client construction, output writers and tables."""

from __future__ import annotations

import asyncio
import csv
import functools
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import click

from ..client import TwitterClient
from ..pool import ClientPool
from ..security import (
    check_cookies_file_permissions,
    redact_in_text,
    warn_cli_cookies,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

COOKIES_ENV = "TWITTER_COOKIES"
PROXY_ENV = "TWITTER_PROXY"

AnyClient = TwitterClient | ClientPool

try:
    __version__ = version("xactions-py")
except PackageNotFoundError:
    __version__ = "1.5.0"


def _load_cookies_list(cookies: str, cookies_file: str | None, from_browser: str | None = None) -> list[str]:
    """
    Return the available cookie strings.
    - --from-browser: read auth_token/ct0 from an installed browser
    - --cookies-file: cookie string, Netscape, Cookie-Editor JSON or Playwright
    - --cookies / TWITTER_COOKIES: one cookie string, or several separated by '|||'
    """
    from ..browser_cookies import import_from_browser, load_cookies_from_file

    if from_browser:
        imported = import_from_browser(from_browser)
        if not imported:
            raise click.ClickException(
                f"Could not import cookies from {from_browser}. "
                "Export them with Cookie-Editor and use --cookies-file."
            )
        return [imported]

    raw: list[str] = []
    if cookies_file:
        if not os.path.exists(cookies_file):
            raise click.ClickException(f"File not found: {cookies_file}")
        perm_warn = check_cookies_file_permissions(cookies_file)
        if perm_warn:
            click.echo(f"⚠️  {perm_warn}", err=True)
        raw = load_cookies_from_file(cookies_file)
        if not raw:
            # fallback simple lines
            with open(cookies_file, encoding="utf-8") as f:
                raw = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    else:
        value = cookies or os.getenv(COOKIES_ENV, "")
        if value:
            raw = [c.strip() for c in value.split("|||") if c.strip()]
    return raw


def get_client(
    cookies: str = "",
    cookies_file: str | None = None,
    from_browser: str | None = None,
) -> AnyClient:
    """Return a TwitterClient (one cookie) or a ClientPool (several)."""
    cookie_list = _load_cookies_list(cookies, cookies_file, from_browser=from_browser)
    cli_warn = warn_cli_cookies(cookies)
    if cli_warn:
        click.echo(f"⚠️  {cli_warn}", err=True)
    proxy = os.getenv(PROXY_ENV)
    if len(cookie_list) > 1:
        return ClientPool(cookie_list, proxy=proxy)
    return TwitterClient(cookies=cookie_list[0] if cookie_list else "", proxy=proxy)


def _safe_error_message(e: Exception) -> str:
    """Error message with any cookie values redacted."""
    return redact_in_text(str(e))


def with_client(func):
    """
    Command decorator: pops --cookies/--cookies-file from kwargs, builds the
    client (or pool), injects it as the first argument, reports errors and
    always closes the connections.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        cookies = kwargs.pop("cookies", "")
        cookies_file = kwargs.pop("cookies_file", None)
        from_browser = kwargs.pop("from_browser", None)
        client = get_client(cookies, cookies_file, from_browser=from_browser)
        exit_code = 0
        try:
            return func(client, *args, **kwargs)
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 1
            raise
        except Exception as e:
            click.echo(f"❌ {_safe_error_message(e)}", err=True)
            exit_code = 1
        finally:
            try:
                run(client.aclose())
            except Exception:
                pass
            if exit_code:
                sys.exit(exit_code)

    return wrapper


def run(coro):
    return asyncio.run(coro)


def print_json(data: Any, output: str | None = None):
    out = json.dumps(data, ensure_ascii=False, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(out)
        click.echo(f"✅ Saved to {output}")
    else:
        click.echo(out)


def _write_csv(path: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None):
    if not rows:
        click.echo("⚠️  No data to export to CSV.")
        return
    if fieldnames is None:
        # Union of keys in first-seen order: rows don't always share a shape.
        fieldnames = list(dict.fromkeys(k for row in rows for k in row))
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(rows)
    click.echo(f"✅ CSV saved to {path}")


def _write_ndjson(path: str, rows: list[dict[str, Any]]):
    if not rows:
        click.echo("⚠️  No data to export to NDJSON.")
        return
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    click.echo(f"✅ NDJSON saved to {path}")


def _flatten_users(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": u.get("id"),
            "username": u.get("username"),
            "name": u.get("name"),
            "followers": u.get("followers"),
            "following": u.get("following"),
            "verified": u.get("verified"),
            "bio": (u.get("bio") or "").replace("\n", " "),
        }
        for u in users
    ]


def _flatten_tweets(tweets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": t.get("id"),
            "url": t.get("url"),
            "author": (t.get("author") or {}).get("username"),
            "text": (t.get("text") or "").replace("\n", " "),
            "likes": t.get("likes"),
            "retweets": t.get("retweets"),
            "replies": t.get("replies"),
            "quotes": t.get("quotes"),
            "views": t.get("views"),
            "created_at": t.get("created_at"),
        }
        for t in tweets
    ]


def _handle_output(
    data: Any,
    output: str | None,
    csv_path: str | None,
    ndjson_path: str | None = None,
    csv_data: list[dict[str, Any]] | None = None,
    table_fn=None,
    table_title: str = "",
):
    if csv_path:
        _write_csv(csv_path, csv_data or [])
    elif ndjson_path:
        _write_ndjson(ndjson_path, csv_data or [])
    elif output:
        print_json(data, output)
    elif table_fn:
        # Commands wrap their rows as {"count": n, "<kind>": [...]}; tables need the rows.
        rows = data if isinstance(data, list) else next((v for v in data.values() if isinstance(v, list)), [])
        table_fn(rows, table_title)
    else:
        print_json(data)


def print_users_table(users: list[dict[str, Any]], title: str = ""):
    if title:
        click.echo(f"\n{'─'*50}")
        click.echo(f"  {title} ({len(users)} users)")
        click.echo(f"{'─'*50}")
    for u in users:
        verified = "✓" if u.get("verified") else " "
        click.echo(
            f"  {verified} @{u.get('username', '?'):<25} "
            f"{u.get('name', ''):<25} "
            f"👥 {u.get('followers', 0):>8,}"
        )


def print_tweets_table(tweets: list[dict[str, Any]], title: str = ""):
    if title:
        click.echo(f"\n{'─'*60}")
        click.echo(f"  {title} ({len(tweets)} tweets)")
        click.echo(f"{'─'*60}")
    for t in tweets:
        author = t.get("author") or {}
        text = (t.get("text") or "")[:80].replace("\n", " ")
        likes = t.get("likes") or 0
        rts = t.get("retweets") or 0
        uname = author.get("username") or "?"
        click.echo(
            f"  @{uname:<20} "
            f"❤ {likes:>6}  "
            f"🔁 {rts:>5}  "
            f"{text}"
        )


def print_trends_table(trends: list[dict[str, Any]], title: str = ""):
    if title:
        click.echo(f"\n{'─'*50}")
        click.echo(f"  {title} ({len(trends)} trends)")
        click.echo(f"{'─'*50}")
    for i, t in enumerate(trends, 1):
        volume = t.get("tweet_volume")
        vol_str = f"{volume:>10,} tweets" if volume else ""
        click.echo(f"  {i:>2}. {t.get('name', '?')} {vol_str}")


def print_analysis(report: dict[str, Any], username: str):
    avg = report["averages"]
    click.echo(f"\n{'═'*55}")
    click.echo(f"  📊 Analysis of @{username} — {report['total_tweets']} tweets")
    click.echo(f"{'═'*55}")
    click.echo("  Averages per tweet:")
    click.echo(f"    ❤ {avg.get('likes', 0):>10,.1f}   🔁 {avg.get('retweets', 0):>8,.1f}   "
               f"💬 {avg.get('replies', 0):>6,.1f}   👁 {avg.get('views', 0):>10,.1f}")
    if report.get("engagement_rate_followers") is not None:
        click.echo(f"  Engagement rate (followers): {report['engagement_rate_followers']}%")
    if report.get("engagement_rate_views") is not None:
        click.echo(f"  Engagement rate (views):     {report['engagement_rate_views']}%")

    content = report.get("content", {})
    if content:
        click.echo(f"\n  Content: {content.get('with_media_pct', 0)}% with media, "
                   f"{content.get('replies_pct', 0)}% replies, "
                   f"{content.get('quotes_pct', 0)}% quotes")

    if report.get("best_hours"):
        hours = ", ".join(f"{h['hour']:02d}:00" for h in report["best_hours"])
        click.echo(f"  Best hours (UTC): {hours}")
    if report.get("best_days"):
        days = ", ".join(d["day"] for d in report["best_days"])
        click.echo(f"  Best days:        {days}")

    if report.get("top_tweets"):
        click.echo("\n  🏆 Top tweets:")
        for t in report["top_tweets"]:
            click.echo(f"    [{t['score']:>6}] ❤{t['likes'] or 0:<6} {(t['text'] or '')[:60]}")
    click.echo(f"{'═'*55}\n")


def export_options(fn):
    """--csv / --ndjson for commands whose result is a list of rows."""
    fn = click.option("--csv", "csv_path", default=None, help="Output CSV file")(fn)
    fn = click.option("--ndjson", "ndjson_path", default=None, help="Output NDJSON file")(fn)
    return fn


def export_rows(rows: list[dict[str, Any]], csv_path: str | None, ndjson_path: str | None) -> bool:
    """Write rows to --csv/--ndjson if requested. True when something was exported."""
    if csv_path:
        _write_csv(csv_path, rows)
    if ndjson_path:
        _write_ndjson(ndjson_path, rows)
    return bool(csv_path or ndjson_path)


def common_options(fn):
    """Options shared by the read commands."""
    fn = click.option(
        "--cookies",
        envvar=COOKIES_ENV,
        default="",
        help="Session cookies (prefer .env TWITTER_COOKIES or --cookies-file)",
    )(fn)
    fn = click.option("--cookies-file", type=click.Path(exists=True), default=None,
                      help="Cookie file (line format, Netscape, Cookie-Editor JSON)")(fn)
    fn = click.option(
        "--from-browser",
        type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]),
        default=None,
        help="Import auth_token/ct0 from an installed browser profile",
    )(fn)
    fn = click.option("--output", "-o", default=None, help="Output JSON file")(fn)
    fn = click.option("--csv", "csv_path", default=None, help="Output CSV file")(fn)
    fn = click.option("--ndjson", "ndjson_path", default=None, help="Output NDJSON file")(fn)
    fn = click.option("--table", is_flag=True, help="Show as a table instead of JSON")(fn)
    return fn
