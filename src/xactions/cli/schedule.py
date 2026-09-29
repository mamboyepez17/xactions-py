"""Scheduled tweets: queue posts for later and publish them when due."""

from __future__ import annotations

import time

import click

from ..schedule import ScheduleStore, parse_when, run_due
from ._app import cli
from ._common import COOKIES_ENV, export_options, export_rows, get_client, print_json, run


@cli.group()
def schedule():
    """Queue tweets for later; publish them with `schedule run` (e.g. from cron)."""


@schedule.command("add")
@click.argument("text")
@click.option("--at", "when", required=True, help="When to post: ISO time (local if no offset) or +30m/+2h/+1d")
@click.option("--reply-to", default=None, help="ID of the tweet to reply to")
@click.option("--db", "db_path", default=None, help="SQLite database path (default ~/.xactions/xactions.db)")
def schedule_add(text, when, reply_to, db_path):
    """Queue TEXT to be posted at --at."""
    try:
        run_at = parse_when(when)
        item = ScheduleStore(db_path).add(text, run_at, reply_to_id=reply_to)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    local = run_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    click.echo(f"🗓️  Scheduled #{item['id']} for {local} ({item['run_at']})")


@schedule.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include posted, failed and cancelled posts")
@click.option("--db", "db_path", default=None, help="SQLite database path")
@click.option("--output", "-o", default=None, help="Output JSON file")
@export_options
def schedule_list(show_all, db_path, output, csv_path, ndjson_path):
    """List scheduled posts (pending only unless --all)."""
    items = ScheduleStore(db_path).list_posts(status=None if show_all else "pending")
    if export_rows(items, csv_path, ndjson_path):
        return
    if output:
        print_json({"count": len(items), "scheduled": items}, output)
        return
    if not items:
        click.echo("No scheduled posts.")
        return
    for it in items:
        extra = f" → {it['tweet_id']}" if it.get("tweet_id") else f" ({it['error']})" if it.get("error") else ""
        text = it["text"].replace("\n", " ")
        text = text if len(text) <= 60 else text[:57] + "..."
        click.echo(f"  #{it['id']:<4} {it['run_at']}  [{it['status']}]  {text}{extra}")


@schedule.command("cancel")
@click.argument("post_id", type=int)
@click.option("--db", "db_path", default=None, help="SQLite database path")
def schedule_cancel(post_id, db_path):
    """Cancel a pending scheduled post."""
    if not ScheduleStore(db_path).cancel(post_id):
        raise click.ClickException(f"#{post_id} is not a pending scheduled post")
    click.echo(f"🗑️  Cancelled #{post_id}")


@schedule.command("run")
@click.option("--dry-run", is_flag=True, help="Show what is due without posting")
@click.option("--every", type=int, default=None, help="Keep running, checking every N seconds")
@click.option("--db", "db_path", default=None, help="SQLite database path")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
def schedule_run(dry_run, every, db_path, cookies, cookies_file, from_browser):
    """Publish every due post (daily write caps apply)."""
    store = ScheduleStore(db_path)
    client = get_client(cookies, cookies_file, from_browser=from_browser)
    had_failure = False
    try:
        while True:
            result = run(run_due(client, store, dry_run=dry_run))
            if dry_run:
                for it in result["due"]:
                    click.echo(f"  due #{it['id']} {it['run_at']}  {it['text'][:60]}")
                click.echo(f"🔍 DRY-RUN — {len(result['due'])} post(s) due, nothing posted.")
            else:
                for it in result["posted"]:
                    click.echo(f"✅ #{it['id']} posted → {it['tweet_id']}")
                for it in result["failed"]:
                    click.echo(f"❌ #{it['id']} failed: {it['error']}", err=True)
                if result["stopped"]:
                    click.echo(f"🛑 Stopped: {result['stopped']}", err=True)
                had_failure = had_failure or bool(result["failed"])
            if not every or dry_run:
                break
            time.sleep(every)
    except KeyboardInterrupt:
        pass
    finally:
        run(client.aclose())
    if had_failure:
        raise SystemExit(1)
