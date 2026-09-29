"""X Lists: read a list's tweets and members, create lists and manage members."""

from __future__ import annotations

import click

from ..actions import create_list, list_add_member, list_remove_member
from ..scrapers import get_list_members, get_list_tweets, get_user_id
from ._app import cli
from ._common import (
    COOKIES_ENV,
    _flatten_tweets,
    _flatten_users,
    _handle_output,
    common_options,
    print_tweets_table,
    print_users_table,
    run,
    with_client,
)


def _write_options(fn):
    fn = click.option("--cookies", envvar=COOKIES_ENV, default="", help="Session cookies")(fn)
    fn = click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Cookie file")(fn)
    return fn


def _draft_if_required(action: str, params: dict) -> bool:
    """Save a draft instead of writing when XACTIONS_REQUIRE_APPROVAL is set."""
    from ..drafts import approval_required, create_draft

    if not approval_required():
        return False
    draft = create_draft(action, params)
    click.echo(f"📝 Draft saved: {draft['id']} — approve with: xactions drafts approve {draft['id']}")
    return True


@cli.group()
def lists():
    """Read and manage X Lists."""


@lists.command("tweets")
@click.argument("list_id")
@click.option("--limit", "-l", default=50, show_default=True, help="Number of tweets")
@common_options
@with_client
def lists_tweets(client, list_id, limit, output, csv_path, ndjson_path, table):
    """Latest tweets of a List."""
    data = run(get_list_tweets(client, list_id, limit=limit))
    _handle_output(
        {"list_id": list_id, "count": len(data), "tweets": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_tweets(data),
        table_fn=print_tweets_table if table else None,
        table_title=f"List {list_id}",
    )


@lists.command("members")
@click.argument("list_id")
@click.option("--limit", "-l", default=100, show_default=True, help="Number of members")
@common_options
@with_client
def lists_members(client, list_id, limit, output, csv_path, ndjson_path, table):
    """Members of a List."""
    data = run(get_list_members(client, list_id, limit=limit))
    _handle_output(
        {"list_id": list_id, "count": len(data), "members": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_users(data),
        table_fn=print_users_table if table else None,
        table_title=f"Members of list {list_id}",
    )


@lists.command("create")
@click.argument("name")
@click.option("--description", default="", help="List description")
@click.option("--private", is_flag=True, help="Create a private list")
@_write_options
@with_client
def lists_create(client, name, description, private):
    """Create a List. Requires auth_token."""
    if _draft_if_required("list_create", {"name": name, "description": description, "private": private}):
        return
    result = run(create_list(client, name, description, private))
    if result["success"]:
        click.echo(f"✅ List created: {result['name']} (id {result['list_id']})")
    else:
        click.echo("❌ Could not create the list.", err=True)


def _update_member(client, list_id: str, username: str, add: bool) -> None:
    username = username.lstrip("@")
    if _draft_if_required("list_add" if add else "list_remove", {"list_id": list_id, "username": username}):
        return
    user_id = run(get_user_id(client, username))
    runner = list_add_member if add else list_remove_member
    result = run(runner(client, list_id, user_id))
    verb = "added to" if add else "removed from"
    if result["success"]:
        click.echo(f"✅ @{username} {verb} list {list_id}.")
    else:
        click.echo(f"❌ Could not update list {list_id} for @{username}.", err=True)


@lists.command("add")
@click.argument("list_id")
@click.argument("username")
@_write_options
@with_client
def lists_add(client, list_id, username):
    """Add USERNAME to a List you own. Requires auth_token."""
    _update_member(client, list_id, username, add=True)


@lists.command("remove")
@click.argument("list_id")
@click.argument("username")
@_write_options
@with_client
def lists_remove(client, list_id, username):
    """Remove USERNAME from a List you own. Requires auth_token."""
    _update_member(client, list_id, username, add=False)
