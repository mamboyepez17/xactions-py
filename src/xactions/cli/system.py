"""Session, pipeline, GraphQL cache, doctor and drafts commands."""

from __future__ import annotations

import json
import sys

import click

from ._app import cli
from ._common import (
    COOKIES_ENV,
    _load_cookies_list,
    get_client,
    print_json,
    run,
    with_client,
)


@cli.command()
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@with_client
def validate(client):
    """Check that the cookies work against the API (every account in the pool)."""
    result = run(client.validate_cookies())
    if "accounts" in result:
        # Multi-account pool
        click.echo(f"\n🔐 Pool: {result['alive']}/{result['total']} accounts alive")
        for acc in result["accounts"]:
            if acc.get("valid"):
                click.echo(f"  ✅ account #{acc['account']}: @{acc.get('username')}")
            else:
                click.echo(f"  ❌ account #{acc['account']}: {acc.get('error')}")
        if result["alive"] == 0:
            sys.exit(1)
    elif result.get("valid"):
        click.echo(f"✅ Cookies valid. @{result.get('username')} ({result.get('user_id')})")
    else:
        click.echo(f"❌ Invalid cookies: {result.get('error')}", err=True)
        sys.exit(1)

@cli.command()
@click.argument("pipeline_file", type=click.Path(exists=True))
@click.option("--execute", is_flag=True, help="Allow write steps (like); default is dry-run")
@click.option("--output", "-o", default=None, help="JSON result file")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
@with_client
def pipeline(client, pipeline_file, execute, output, cookies, cookies_file, from_browser):
    """Run a declarative JSON pipeline (search → filter → notify/report/like)."""
    from ..pipeline import run_pipeline

    result = run(run_pipeline(client, pipeline_file, dry_run=not execute))
    # drop full tweet dump from CLI JSON unless requested via file
    payload = {k: v for k, v in result.items() if k != "tweets"}
    payload["tweet_count"] = len(result.get("tweets") or [])
    if output:
        print_json(payload, output)
        return
    click.echo(f"Pipeline {payload.get('name')}: {payload['tweet_count']} tweets after steps")
    for entry in payload.get("log") or []:
        click.echo(f"  {entry}")
    if result.get("dry_run"):
        click.echo("(dry-run: write steps skipped — use --execute to run likes)")


# ─── GraphQL endpoints ────────────────────────────────────────────────────────

@cli.command("gql-status")
@click.option("--output", "-o", default=None, help="Output JSON file")
def gql_status(output):
    """Show the state of the GraphQL query ID cache."""
    from ..client import _DEFAULT_GRAPHQL_ENDPOINTS, GRAPHQL_ENDPOINTS
    from ..gql_refresh import cache_status

    status = cache_status()
    payload = {
        **status,
        "loaded": {
            name: {
                "queryId": ep.get("queryId"),
                "operationName": ep.get("operationName"),
                "method": ep.get("method", "GET"),
            }
            for name, ep in sorted(GRAPHQL_ENDPOINTS.items())
        },
        "defaults_count": len(_DEFAULT_GRAPHQL_ENDPOINTS),
    }
    if output:
        print_json(payload, output)
        return

    click.echo(f"\n{'─'*55}")
    click.echo("  GraphQL query IDs")
    click.echo(f"{'─'*55}")
    if status["exists"]:
        click.echo(f"  Cache:  {status['path']}")
        click.echo(f"  Update: {status.get('updated_at')}")
        click.echo(f"  Source: {status.get('source')}")
    else:
        click.echo(f"  Cache:  (no file) {status['path']}")
        click.echo("  Using built-in defaults only")
    click.echo(f"  Endpoints cargados: {len(GRAPHQL_ENDPOINTS)}")
    click.echo(f"{'─'*55}\n")


@cli.command("gql-refresh")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies (enables the richer logged-in crawl)")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@click.option("--output", "-o", default=None, help="Output JSON file")
def gql_refresh_cmd(cookies, cookies_file, output):
    """
    Refresh the GraphQL query IDs.

    With cookies, X's logged-in bundle is preferred; without them the
    anonymous bundle is tried, falling back to twikit.
    """
    from ..client import refresh_graphql_endpoints

    cookie_list = _load_cookies_list(cookies, cookies_file)
    cookie = cookie_list[0] if cookie_list else None
    if cookie:
        click.echo("🔐 Using cookies for the logged-in crawl (token not printed)")
    merged = run(refresh_graphql_endpoints(force=True, cookie=cookie))
    changed = {
        name: ep.get("queryId")
        for name, ep in sorted(merged.items())
        if ep.get("queryId")
    }
    if output:
        print_json({"count": len(changed), "endpoints": changed}, output)
        return
    click.echo(f"\n✅ GraphQL endpoints refreshed ({len(changed)} with a queryId)")
    for name, qid in list(changed.items())[:8]:
        click.echo(f"  {name}: {qid}")
    if len(changed) > 8:
        click.echo(f"  … and {len(changed) - 8} more")
    click.echo("")


@cli.command()
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")
@click.option("--output", "-o", default=None, help="Output JSON file")
@click.option("--json", "as_json", is_flag=True, help="Print JSON to stdout")
def doctor(cookies, cookies_file, output, as_json):
    """Check local setup: cookies, GraphQL cache, write caps, DB."""
    from ..doctor import run_doctor

    report = run_doctor(cookies=cookies or None, cookies_file=cookies_file)
    if output:
        print_json(report, output)
        return
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        if not report["ok"]:
            sys.exit(1)
        return

    icon = {"ok": "✅", "warn": "⚠️ ", "error": "❌"}
    click.echo(f"\n{'─'*55}")
    click.echo(f"  🩺 xactions doctor — {report['summary']}")
    click.echo(f"{'─'*55}")
    for c in report["checks"]:
        click.echo(f"  {icon.get(c['status'], '•')} {c['check']:<14} {c['message']}")
    click.echo(f"{'─'*55}\n")
    if not report["ok"]:
        sys.exit(1)


@cli.group()
def drafts():
    """Review and release write drafts (approval gate)."""
    pass


@drafts.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include executed/discarded")
@click.option("--output", "-o", default=None, help="JSON output file")
def drafts_list(show_all, output):
    from ..drafts import list_drafts

    items = list_drafts(status=None if show_all else "pending")
    if output:
        print_json({"count": len(items), "drafts": items}, output)
        return
    if not items:
        click.echo("No pending drafts.")
        return
    click.echo(f"\n{'─'*55}\n  📝 {len(items)} draft(s)\n{'─'*55}")
    for d in items:
        params = json.dumps(d.get("params"), ensure_ascii=False)
        if len(params) > 60:
            params = params[:57] + "..."
        click.echo(f"  {d['id']}  [{d.get('status')}]  {d.get('action')}  {params}")
    click.echo(f"{'─'*55}\n")


@drafts.command("approve")
@click.argument("draft_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
def drafts_approve(draft_id, cookies, cookies_file, from_browser):
    """Mark draft approved and execute it now."""
    from ..drafts import approve as approve_draft
    from ..drafts import execute_draft, load_draft, mark_executed

    draft = load_draft(draft_id)
    if not draft:
        raise click.ClickException(f"Draft not found: {draft_id}")
    if draft.get("status") != "pending":
        raise click.ClickException(f"Draft {draft_id} is {draft.get('status')}, not pending")

    approve_draft(draft_id)
    action = draft.get("action")
    client = get_client(cookies, cookies_file, from_browser=from_browser)
    try:
        try:
            result = run(execute_draft(client, draft))
        except ValueError as e:
            raise click.ClickException(str(e)) from e
        mark_executed(draft_id, result)
        if result.get("success"):
            click.echo(f"✅ Draft {draft_id} executed ({action}).")
        else:
            click.echo(f"❌ Draft {draft_id} failed: {result}", err=True)
            sys.exit(1)
    finally:
        run(client.aclose())


@drafts.command("discard")
@click.argument("draft_id")
def drafts_discard(draft_id):
    from ..drafts import discard

    d = discard(draft_id)
    if not d:
        raise click.ClickException(f"Draft not found: {draft_id}")
    click.echo(f"🗑️  Draft {draft_id} discarded.")
