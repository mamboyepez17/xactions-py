"""Read-only scraping commands (profiles, tweets, search, timelines)."""

from __future__ import annotations

import click

from ..scrapers import (
    get_bookmarks,
    get_home_timeline,
    get_trends,
    get_tweet_favoriters,
    get_tweet_replies,
    get_tweet_retweeters,
    get_user_likes,
    scrape_followers,
    scrape_following,
    scrape_non_followers,
    scrape_profile,
    scrape_tweets,
    search_tweets,
)
from ..search_query import build_search_query
from ._app import cli
from ._common import (
    _flatten_tweets,
    _flatten_users,
    _handle_output,
    common_options,
    print_trends_table,
    print_tweets_table,
    print_users_table,
    run,
    with_client,
)


@cli.command()
@click.argument("username")
@common_options
@with_client
def profile(client, username, output, csv_path, ndjson_path, table):
    """Obtiene el perfil de un usuario."""
    data = run(scrape_profile(client, username))
    flat = [{
        "id": data.get("id"),
        "username": data.get("username"),
        "name": data.get("name"),
        "followers": data.get("followers"),
        "following": data.get("following"),
        "tweets_count": data.get("tweets_count"),
        "verified": data.get("verified"),
        "bio": (data.get("bio") or "").replace("\n", " "),
        "created_at": data.get("created_at"),
    }]
    if csv_path or ndjson_path or output:
        _handle_output(data, output, csv_path, ndjson_path, csv_data=flat)
    else:
        click.echo(f"\n{'─'*50}")
        click.echo(f"  @{data.get('username')} — {data.get('name')}")
        click.echo(f"  {'✓ Verificado' if data.get('verified') else 'No verificado'}")
        click.echo(f"  Bio: {data.get('bio', '')[:100]}")
        click.echo(f"  Followers: {data.get('followers', 0):,}")
        click.echo(f"  Following: {data.get('following', 0):,}")
        click.echo(f"  Tweets:    {data.get('tweets_count', 0):,}")
        click.echo(f"  Ubicación: {data.get('location', 'N/A')}")
        click.echo(f"  Creado:    {data.get('created_at', 'N/A')}")
        click.echo(f"{'─'*50}\n")


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True, help="Máximo de usuarios")
@common_options
@with_client
def followers(client, username, limit, output, csv_path, ndjson_path, table):
    """Lista los followers de un usuario."""
    data = run(scrape_followers(client, username, limit=limit))
    _handle_output(
        {"count": len(data), "followers": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_users(data),
        table_fn=print_users_table if table else None,
        table_title=f"Followers de @{username}",
    )


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True, help="Máximo de usuarios")
@common_options
@with_client
def following(client, username, limit, output, csv_path, ndjson_path, table):
    """Lista los usuarios que sigue una cuenta."""
    data = run(scrape_following(client, username, limit=limit))
    _handle_output(
        {"count": len(data), "following": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_users(data),
        table_fn=print_users_table if table else None,
        table_title=f"Following de @{username}",
    )


@cli.command("non-followers")
@click.argument("username")
@click.option("--limit", "-l", default=200, show_default=True, help="Cuántos following revisar")
@common_options
@with_client
def non_followers_cmd(client, username, limit, output, csv_path, ndjson_path, table):
    """Muestra quién no te sigue de vuelta."""
    data = run(scrape_non_followers(client, username, limit=limit))
    _handle_output(
        {"count": len(data), "non_followers": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_users(data),
        table_fn=print_users_table if table else None,
        table_title=f"No te siguen de vuelta (@{username})",
    )


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de tweets")
@click.option("--replies", is_flag=True, help="Incluir respuestas")
@common_options
@with_client
def tweets(client, username, limit, replies, output, csv_path, ndjson_path, table):
    """Obtiene los tweets recientes de un usuario."""
    data = run(scrape_tweets(client, username, limit=limit, include_replies=replies))
    _handle_output(
        {"count": len(data), "tweets": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_tweets(data),
        table_fn=print_tweets_table if table else None,
        table_title=f"Tweets de @{username}",
    )


@cli.command()
@click.argument("query", required=False, default="")
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de resultados")
@click.option("--mode", default="Top", type=click.Choice(["Latest", "Top"]), show_default=True)
@click.option("--from", "from_user", default=None, help="Operador from:USERNAME")
@click.option("--to", "to_user", default=None, help="Operador to:USERNAME")
@click.option("--since", default=None, help="since:YYYY-MM-DD")
@click.option("--until", default=None, help="until:YYYY-MM-DD")
@click.option("--min-faves", type=int, default=None, help="min_faves:N")
@click.option("--min-retweets", type=int, default=None, help="min_retweets:N")
@click.option("--lang", default=None, help="lang:es|en|...")
@click.option("--exclude-retweets", is_flag=True, help="-filter:retweets")
@click.option("--exclude-replies", is_flag=True, help="-filter:replies")
@click.option("--media", "filter_media", is_flag=True, help="filter:media")
@common_options
@with_client
def search(
    client, query, limit, mode, from_user, to_user, since, until,
    min_faves, min_retweets, lang, exclude_retweets, exclude_replies, filter_media,
    output, csv_path, ndjson_path, table,
):
    """Busca tweets por query (acepta operadores avanzados)."""
    q = build_search_query(
        query,
        from_user=from_user,
        to_user=to_user,
        since=since,
        until=until,
        min_faves=min_faves,
        min_retweets=min_retweets,
        lang=lang,
        exclude_retweets=exclude_retweets,
        exclude_replies=exclude_replies,
        filter_media=filter_media,
    )
    if not q.strip():
        raise click.ClickException("Query vacía: pasa un término o flags (--from, --lang, …)")
    data = run(search_tweets(client, q, limit=limit, mode=mode))
    _handle_output(
        {"query": q, "count": len(data), "tweets": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_tweets(data),
        table_fn=print_tweets_table if table else None,
        table_title=f'Resultados: "{q}" ({mode})',
    )


@cli.command()
@click.argument("tweet_id")
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de replies")
@common_options
@with_client
def replies(client, tweet_id, limit, output, csv_path, ndjson_path, table):
    """Obtiene replies/conversación de un tweet."""
    data = run(get_tweet_replies(client, tweet_id, limit=limit))
    _handle_output(
        {"tweet_id": tweet_id, "count": len(data), "tweets": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_tweets(data),
        table_fn=print_tweets_table if table else None,
        table_title=f"Replies a {tweet_id}",
    )


@cli.command()
@click.argument("tweet_id")
@click.option("--limit", "-l", default=100, show_default=True, help="Cantidad de usuarios")
@common_options
@with_client
def likers(client, tweet_id, limit, output, csv_path, ndjson_path, table):
    """Usuarios que dieron like a un tweet."""
    data = run(get_tweet_favoriters(client, tweet_id, limit=limit))
    _handle_output(
        {"tweet_id": tweet_id, "count": len(data), "users": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_users(data),
        table_fn=print_users_table if table else None,
        table_title=f"Likers de {tweet_id}",
    )


@cli.command()
@click.argument("tweet_id")
@click.option("--limit", "-l", default=100, show_default=True, help="Cantidad de usuarios")
@common_options
@with_client
def retweeters(client, tweet_id, limit, output, csv_path, ndjson_path, table):
    """Usuarios que hicieron retweet a un tweet."""
    data = run(get_tweet_retweeters(client, tweet_id, limit=limit))
    _handle_output(
        {"tweet_id": tweet_id, "count": len(data), "users": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_users(data),
        table_fn=print_users_table if table else None,
        table_title=f"Retweeters de {tweet_id}",
    )


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de tweets")
@common_options
@with_client
def likes(client, username, limit, output, csv_path, ndjson_path, table):
    """Tweets a los que les dio like un usuario."""
    data = run(get_user_likes(client, username, limit=limit))
    _handle_output(
        {"username": username, "count": len(data), "tweets": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_tweets(data),
        table_fn=print_tweets_table if table else None,
        table_title=f"Likes de @{username}",
    )


@cli.command()
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de bookmarks")
@common_options
@with_client
def bookmarks(client, limit, output, csv_path, ndjson_path, table):
    """Bookmarks del usuario autenticado."""
    data = run(get_bookmarks(client, limit=limit))
    _handle_output(
        {"count": len(data), "bookmarks": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_tweets(data),
        table_fn=print_tweets_table if table else None,
        table_title="Bookmarks",
    )


@cli.command()
@click.option("--woeid", default=1, show_default=True, help="Yahoo Where On Earth ID (1=worldwide)")
@common_options
@with_client
def trends(client, woeid, output, csv_path, ndjson_path, table):
    """Trending topics de Twitter/X."""
    data = run(get_trends(client, woeid=woeid))
    _handle_output(
        {"count": len(data), "trends": data},
        output, csv_path, ndjson_path,
        csv_data=data,
        table_fn=print_trends_table if table else None,
        table_title="Trending topics",
    )


@cli.command()
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de tweets")
@click.option("--latest", is_flag=True, help="Usar HomeLatestTimeline en vez de HomeTimeline")
@common_options
@with_client
def home(client, limit, latest, output, csv_path, ndjson_path, table):
    """Home timeline del usuario autenticado."""
    data = run(get_home_timeline(client, limit=limit, latest=latest))
    _handle_output(
        {"count": len(data), "tweets": data},
        output, csv_path, ndjson_path,
        csv_data=_flatten_tweets(data),
        table_fn=print_tweets_table if table else None,
        table_title="Home timeline",
    )
