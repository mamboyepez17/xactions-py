#!/usr/bin/env python3
"""
XActions-PY — CLI
Interfaz de línea de comandos. Sin npm.

v1.2.0:
  - Comandos nuevos: replies, likers, retweeters, likes, bookmarks, trends,
    home, bookmark, unbookmark, validate.
  - Exportación a CSV (--csv).
  - Lectura de cookies desde archivo (--cookies-file).
  - Default de búsqueda en modo Top.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import asyncio
from typing import Any, Dict, List, Optional

import click

# Fix encoding para Windows (emojis, caracteres especiales)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scraper.client import TwitterClient, TwitterError
from scraper.scrapers import (
    scrape_profile,
    scrape_followers,
    scrape_following,
    scrape_non_followers,
    scrape_tweets,
    search_tweets,
    get_user_id,
    get_user_likes,
    get_tweet_replies,
    get_tweet_favoriters,
    get_tweet_retweeters,
    get_bookmarks,
    get_trends,
    get_home_timeline,
)
from actions.actions import (
    post_tweet,
    delete_tweet,
    like_tweet,
    unlike_tweet,
    retweet,
    follow_user,
    unfollow_user,
    bulk_unfollow,
    create_bookmark,
    delete_bookmark,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

COOKIES_ENV = "TWITTER_COOKIES"
PROXY_ENV = "TWITTER_PROXY"


def _load_cookies(cookies: str, cookies_file: Optional[str]) -> str:
    if cookies_file:
        if not os.path.exists(cookies_file):
            raise click.ClickException(f"Archivo no encontrado: {cookies_file}")
        with open(cookies_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    return cookies or os.getenv(COOKIES_ENV, "")


def get_client(cookies: str = "", cookies_file: Optional[str] = None) -> TwitterClient:
    effective = _load_cookies(cookies, cookies_file)
    proxy = os.getenv(PROXY_ENV)
    return TwitterClient(cookies=effective, proxy=proxy)


def run(coro):
    return asyncio.run(coro)


def print_json(data: Any, output: Optional[str] = None):
    out = json.dumps(data, ensure_ascii=False, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(out)
        click.echo(f"✅ Guardado en {output}")
    else:
        click.echo(out)


def _write_csv(path: str, rows: List[Dict[str, Any]], fieldnames: Optional[List[str]] = None):
    if not rows:
        click.echo("⚠️  No hay datos para exportar a CSV.")
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    click.echo(f"✅ CSV guardado en {path}")


def _flatten_users(users: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def _flatten_tweets(tweets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    output: Optional[str],
    csv_path: Optional[str],
    csv_data: Optional[List[Dict[str, Any]]] = None,
    table_fn=None,
    table_title: str = "",
):
    if csv_path:
        rows = csv_data if csv_data is not None else []
        _write_csv(csv_path, rows)
    elif output:
        print_json(data, output)
    elif table_fn:
        table_fn(data, table_title)
    else:
        print_json(data)


def print_users_table(users: List[Dict[str, Any]], title: str = ""):
    if title:
        click.echo(f"\n{'─'*50}")
        click.echo(f"  {title} ({len(users)} usuarios)")
        click.echo(f"{'─'*50}")
    for u in users:
        verified = "✓" if u.get("verified") else " "
        click.echo(
            f"  {verified} @{u.get('username', '?'):<25} "
            f"{u.get('name', ''):<25} "
            f"👥 {u.get('followers', 0):>8,}"
        )


def print_tweets_table(tweets: List[Dict[str, Any]], title: str = ""):
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


def print_trends_table(trends: List[Dict[str, Any]], title: str = ""):
    if title:
        click.echo(f"\n{'─'*50}")
        click.echo(f"  {title} ({len(trends)} trends)")
        click.echo(f"{'─'*50}")
    for i, t in enumerate(trends, 1):
        volume = t.get("tweet_volume")
        vol_str = f"{volume:>10,} tweets" if volume else ""
        click.echo(f"  {i:>2}. {t.get('name', '?')} {vol_str}")


def common_options(fn):
    """Opciones comunes para comandos de lectura."""
    fn = click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")(fn)
    fn = click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")(fn)
    fn = click.option("--output", "-o", default=None, help="Archivo JSON de salida")(fn)
    fn = click.option("--csv", "csv_path", default=None, help="Archivo CSV de salida")(fn)
    fn = click.option("--table", is_flag=True, help="Mostrar como tabla en vez de JSON")(fn)
    return fn


# ─── CLI principal ────────────────────────────────────────────────────────────

@click.group()
@click.version_option("1.2.0", prog_name="xactions-py")
def cli():
    """⚡ XActions-PY — Twitter automation sin npm."""
    pass


@cli.command()
@click.argument("username")
@common_options
def profile(username, cookies, cookies_file, output, csv_path, table):
    """Obtiene el perfil de un usuario."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(scrape_profile(client, username))
        if csv_path:
            _write_csv(csv_path, [{
                "id": data.get("id"),
                "username": data.get("username"),
                "name": data.get("name"),
                "followers": data.get("followers"),
                "following": data.get("following"),
                "tweets_count": data.get("tweets_count"),
                "verified": data.get("verified"),
                "bio": (data.get("bio") or "").replace("\n", " "),
                "created_at": data.get("created_at"),
            }])
        elif output:
            print_json(data, output)
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
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True, help="Máximo de usuarios")
@common_options
def followers(username, limit, cookies, cookies_file, output, csv_path, table):
    """Lista los followers de un usuario."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(scrape_followers(client, username, limit=limit))
        _handle_output(
            {"count": len(data), "followers": data},
            output,
            csv_path,
            csv_data=_flatten_users(data),
            table_fn=print_users_table if table else None,
            table_title=f"Followers de @{username}",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True, help="Máximo de usuarios")
@common_options
def following(username, limit, cookies, cookies_file, output, csv_path, table):
    """Lista los usuarios que sigue una cuenta."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(scrape_following(client, username, limit=limit))
        _handle_output(
            {"count": len(data), "following": data},
            output,
            csv_path,
            csv_data=_flatten_users(data),
            table_fn=print_users_table if table else None,
            table_title=f"Following de @{username}",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command("non-followers")
@click.argument("username")
@click.option("--limit", "-l", default=200, show_default=True, help="Cuántos following revisar")
@common_options
def non_followers_cmd(username, limit, cookies, cookies_file, output, csv_path, table):
    """Muestra quién no te sigue de vuelta."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(scrape_non_followers(client, username, limit=limit))
        _handle_output(
            {"count": len(data), "non_followers": data},
            output,
            csv_path,
            csv_data=_flatten_users(data),
            table_fn=print_users_table if table else None,
            table_title=f"No te siguen de vuelta (@{username})",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de tweets")
@click.option("--replies", is_flag=True, help="Incluir respuestas")
@common_options
def tweets(username, limit, replies, cookies, cookies_file, output, csv_path, table):
    """Obtiene los tweets recientes de un usuario."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(scrape_tweets(client, username, limit=limit, include_replies=replies))
        _handle_output(
            {"count": len(data), "tweets": data},
            output,
            csv_path,
            csv_data=_flatten_tweets(data),
            table_fn=print_tweets_table if table else None,
            table_title=f"Tweets de @{username}",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de resultados")
@click.option("--mode", default="Top", type=click.Choice(["Latest", "Top"]), show_default=True)
@common_options
def search(query, limit, mode, cookies, cookies_file, output, csv_path, table):
    """Busca tweets por query."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(search_tweets(client, query, limit=limit, mode=mode))
        _handle_output(
            {"query": query, "count": len(data), "tweets": data},
            output,
            csv_path,
            csv_data=_flatten_tweets(data),
            table_fn=print_tweets_table if table else None,
            table_title=f'Resultados: "{query}" ({mode})',
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("tweet_id")
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de replies")
@common_options
def replies(tweet_id, limit, cookies, cookies_file, output, csv_path, table):
    """Obtiene replies/conversación de un tweet."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_tweet_replies(client, tweet_id, limit=limit))
        _handle_output(
            {"tweet_id": tweet_id, "count": len(data), "tweets": data},
            output,
            csv_path,
            csv_data=_flatten_tweets(data),
            table_fn=print_tweets_table if table else None,
            table_title=f"Replies a {tweet_id}",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("tweet_id")
@click.option("--limit", "-l", default=100, show_default=True, help="Cantidad de usuarios")
@common_options
def likers(tweet_id, limit, cookies, cookies_file, output, csv_path, table):
    """Usuarios que dieron like a un tweet."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_tweet_favoriters(client, tweet_id, limit=limit))
        _handle_output(
            {"tweet_id": tweet_id, "count": len(data), "users": data},
            output,
            csv_path,
            csv_data=_flatten_users(data),
            table_fn=print_users_table if table else None,
            table_title=f"Likers de {tweet_id}",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("tweet_id")
@click.option("--limit", "-l", default=100, show_default=True, help="Cantidad de usuarios")
@common_options
def retweeters(tweet_id, limit, cookies, cookies_file, output, csv_path, table):
    """Usuarios que hicieron retweet a un tweet."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_tweet_retweeters(client, tweet_id, limit=limit))
        _handle_output(
            {"tweet_id": tweet_id, "count": len(data), "users": data},
            output,
            csv_path,
            csv_data=_flatten_users(data),
            table_fn=print_users_table if table else None,
            table_title=f"Retweeters de {tweet_id}",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de tweets")
@common_options
def likes(username, limit, cookies, cookies_file, output, csv_path, table):
    """Tweets a los que les dio like un usuario."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_user_likes(client, username, limit=limit))
        _handle_output(
            {"username": username, "count": len(data), "tweets": data},
            output,
            csv_path,
            csv_data=_flatten_tweets(data),
            table_fn=print_tweets_table if table else None,
            table_title=f"Likes de @{username}",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de bookmarks")
@common_options
def bookmarks(limit, cookies, cookies_file, output, csv_path, table):
    """Bookmarks del usuario autenticado."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_bookmarks(client, limit=limit))
        _handle_output(
            {"count": len(data), "bookmarks": data},
            output,
            csv_path,
            csv_data=_flatten_tweets(data),
            table_fn=print_tweets_table if table else None,
            table_title="Bookmarks",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.option("--woeid", default=1, show_default=True, help="Yahoo Where On Earth ID (1=worldwide)")
@common_options
def trends(woeid, cookies, cookies_file, output, csv_path, table):
    """Trending topics de Twitter/X."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_trends(client, woeid=woeid))
        _handle_output(
            {"count": len(data), "trends": data},
            output,
            csv_path,
            csv_data=data,
            table_fn=print_trends_table if table else None,
            table_title="Trending topics",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.option("--limit", "-l", default=50, show_default=True, help="Cantidad de tweets")
@click.option("--latest", is_flag=True, help="Usar HomeLatestTimeline en vez de HomeTimeline")
@common_options
def home(limit, latest, cookies, cookies_file, output, csv_path, table):
    """Home timeline del usuario autenticado."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_home_timeline(client, limit=limit, latest=latest))
        _handle_output(
            {"count": len(data), "tweets": data},
            output,
            csv_path,
            csv_data=_flatten_tweets(data),
            table_fn=print_tweets_table if table else None,
            table_title="Home timeline",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("text")
@click.option("--reply-to", default=None, help="ID del tweet al que responder")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def post(text, reply_to, cookies, cookies_file):
    """Publica un tweet. Requiere auth_token."""
    client = get_client(cookies, cookies_file)
    try:
        result = run(post_tweet(client, text, reply_to_id=reply_to))
        if result["success"]:
            click.echo(f"✅ Tweet publicado! ID: {result['tweet_id']}")
        else:
            click.echo("❌ No se pudo publicar.", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def delete(tweet_id, cookies, cookies_file):
    """Elimina un tweet por ID. Requiere auth_token."""
    client = get_client(cookies, cookies_file)
    try:
        result = run(delete_tweet(client, tweet_id))
        click.echo("✅ Tweet eliminado." if result["success"] else "❌ No se pudo eliminar.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def like(tweet_id, cookies, cookies_file):
    """Da like a un tweet. Requiere auth_token."""
    client = get_client(cookies, cookies_file)
    try:
        result = run(like_tweet(client, tweet_id))
        click.echo("✅ Like dado." if result["success"] else "❌ Error dando like.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def unlike(tweet_id, cookies, cookies_file):
    """Quita el like de un tweet. Requiere auth_token."""
    client = get_client(cookies, cookies_file)
    try:
        result = run(unlike_tweet(client, tweet_id))
        click.echo("✅ Like quitado." if result["success"] else "❌ Error quitando like.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def bookmark(tweet_id, cookies, cookies_file):
    """Agrega un tweet a bookmarks. Requiere auth_token."""
    client = get_client(cookies, cookies_file)
    try:
        result = run(create_bookmark(client, tweet_id))
        click.echo("✅ Bookmark agregado." if result["success"] else "❌ Error agregando bookmark.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def unbookmark(tweet_id, cookies, cookies_file):
    """Elimina un tweet de bookmarks. Requiere auth_token."""
    client = get_client(cookies, cookies_file)
    try:
        result = run(delete_bookmark(client, tweet_id))
        click.echo("✅ Bookmark eliminado." if result["success"] else "❌ Error eliminando bookmark.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("username")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def follow(username, cookies, cookies_file):
    """Sigue a un usuario. Requiere auth_token."""
    client = get_client(cookies, cookies_file)
    try:
        user_id = run(get_user_id(client, username))
        result = run(follow_user(client, user_id))
        click.echo(f"✅ Siguiendo a @{username}." if result["success"] else f"❌ Error siguiendo a @{username}.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("username")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def unfollow(username, cookies, cookies_file):
    """Deja de seguir a un usuario. Requiere auth_token."""
    client = get_client(cookies, cookies_file)
    try:
        user_id = run(get_user_id(client, username))
        result = run(unfollow_user(client, user_id))
        click.echo(f"✅ Unfollow de @{username}." if result["success"] else f"❌ Error en unfollow de @{username}.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command("bulk-unfollow")
@click.argument("username")
@click.option("--limit", "-l", default=200, show_default=True, help="Cuántos following revisar")
@click.option("--delay", default=2.0, show_default=True, help="Segundos entre unfollows")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@click.option("--dry-run", is_flag=True, help="Solo muestra quién sería unfollowed, sin hacer nada")
def bulk_unfollow_cmd(username, limit, delay, cookies, cookies_file, dry_run):
    """
    Unfollow masivo de cuentas que no te siguen de vuelta.
    ⚠️  Usa --dry-run primero para ver qué pasaría.
    """
    client = get_client(cookies, cookies_file)
    try:
        non_followers = run(scrape_non_followers(client, username, limit=limit))

        if not non_followers:
            click.echo("✅ ¡Todos tus following te siguen de vuelta!")
            return

        click.echo(f"\n📋 Encontrados {len(non_followers)} no-followers:")
        print_users_table(non_followers[:10])
        if len(non_followers) > 10:
            click.echo(f"  ... y {len(non_followers) - 10} más")

        if dry_run:
            click.echo(f"\n🔍 Dry-run: no se hizo nada. Remueve --dry-run para ejecutar.")
            return

        click.confirm(f"\n⚠️  ¿Hacer unfollow de {len(non_followers)} usuarios?", abort=True)

        user_ids = [u["id"] for u in non_followers if u.get("id")]

        with click.progressbar(length=len(user_ids), label="Unfollowing") as bar:
            def on_progress(current, total, uid):
                bar.update(1)

            result = run(bulk_unfollow(client, user_ids, delay_seconds=delay, on_progress=on_progress))

        click.echo(
            f"\n✅ Completado: {result['success']} éxitos, {result['failed']} fallos de {result['total']} total."
        )

    except click.Abort:
        click.echo("\nCancelado.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def validate(cookies, cookies_file):
    """Valida que las cookies funcionan contra la API."""
    client = get_client(cookies, cookies_file)
    try:
        result = run(client.validate_cookies())
        if result.get("valid"):
            click.echo(f"✅ Cookies válidas. @{result.get('username')} ({result.get('user_id')})")
        else:
            click.echo(f"❌ Cookies inválidas: {result.get('error')}", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
