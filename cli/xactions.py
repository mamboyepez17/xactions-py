#!/usr/bin/env python3
"""
XActions-PY — CLI
Interfaz de línea de comandos. Sin npm.

Uso:
  xactions profile elonmusk
  xactions followers elonmusk --limit 100
  xactions following elonmusk --limit 100
  xactions non-followers tuusuario --limit 200
  xactions tweets elonmusk --limit 50
  xactions search "inteligencia artificial" --limit 30
  xactions post "Hola desde XActions-PY!"
  xactions like 1234567890
  xactions follow elonmusk
  xactions unfollow elonmusk
  xactions bulk-unfollow tuusuario --limit 200
"""

import os
import sys
import json
import asyncio
import click

# Fix encoding para Windows (emojis, caracteres especiales)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scraper.client import TwitterClient
from scraper.scrapers import (
    scrape_profile,
    scrape_followers,
    scrape_following,
    scrape_non_followers,
    scrape_tweets,
    search_tweets,
    get_user_id,
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
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

COOKIES_ENV = "TWITTER_COOKIES"
PROXY_ENV   = "TWITTER_PROXY"


def get_client(cookies: str = None) -> TwitterClient:
    effective = cookies or os.getenv(COOKIES_ENV, "")
    proxy = os.getenv(PROXY_ENV)
    return TwitterClient(cookies=effective, proxy=proxy)


def run(coro):
    return asyncio.run(coro)


def print_json(data, output: str = None):
    out = json.dumps(data, ensure_ascii=False, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(out)
        click.echo(f"✅ Guardado en {output}")
    else:
        click.echo(out)


def print_users_table(users: list, title: str = ""):
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


def print_tweets_table(tweets: list, title: str = ""):
    if title:
        click.echo(f"\n{'─'*60}")
        click.echo(f"  {title} ({len(tweets)} tweets)")
        click.echo(f"{'─'*60}")
    for t in tweets:
        author = t.get("author") or {}
        text   = (t.get("text") or "")[:80].replace("\n", " ")
        likes  = t.get("likes") or 0
        rts    = t.get("retweets") or 0
        uname  = author.get("username") or "?"
        click.echo(
            f"  @{uname:<20} "
            f"❤ {likes:>6}  "
            f"🔁 {rts:>5}  "
            f"{text}"
        )


# ─── CLI principal ────────────────────────────────────────────────────────────

@click.group()
@click.version_option("1.0.0", prog_name="xactions-py")
def cli():
    """⚡ XActions-PY — Twitter automation sin npm."""
    pass


@cli.command()
@click.argument("username")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--output", "-o", default=None, help="Guardar resultado en archivo JSON")
def profile(username, cookies, output):
    """Obtiene el perfil de un usuario."""
    try:
        client  = get_client(cookies)
        data    = run(scrape_profile(client, username))
        if output:
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


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True, help="Máximo de usuarios")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--output", "-o", default=None, help="Archivo JSON de salida")
@click.option("--table", is_flag=True, help="Mostrar como tabla en vez de JSON")
def followers(username, limit, cookies, output, table):
    """Lista los followers de un usuario."""
    try:
        client = get_client(cookies)
        data   = run(scrape_followers(client, username, limit=limit))
        if table:
            print_users_table(data, f"Followers de @{username}")
        else:
            print_json({"count": len(data), "followers": data}, output)
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True)
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--output", "-o", default=None)
@click.option("--table", is_flag=True)
def following(username, limit, cookies, output, table):
    """Lista los usuarios que sigue una cuenta."""
    try:
        client = get_client(cookies)
        data   = run(scrape_following(client, username, limit=limit))
        if table:
            print_users_table(data, f"Following de @{username}")
        else:
            print_json({"count": len(data), "following": data}, output)
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command("non-followers")
@click.argument("username")
@click.option("--limit", "-l", default=200, show_default=True)
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--output", "-o", default=None)
@click.option("--table", is_flag=True)
def non_followers_cmd(username, limit, cookies, output, table):
    """Muestra quién no te sigue de vuelta."""
    try:
        client = get_client(cookies)
        data   = run(scrape_non_followers(client, username, limit=limit))
        if table:
            print_users_table(data, f"No te siguen de vuelta (@{username})")
        else:
            print_json({"count": len(data), "non_followers": data}, output)
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=50, show_default=True)
@click.option("--replies", is_flag=True, help="Incluir respuestas")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--output", "-o", default=None)
@click.option("--table", is_flag=True)
def tweets(username, limit, replies, cookies, output, table):
    """Obtiene los tweets recientes de un usuario."""
    try:
        client = get_client(cookies)
        data   = run(scrape_tweets(client, username, limit=limit, include_replies=replies))
        if table:
            print_tweets_table(data, f"Tweets de @{username}")
        else:
            print_json({"count": len(data), "tweets": data}, output)
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=50, show_default=True)
@click.option("--mode", default="Latest", type=click.Choice(["Latest", "Top"]))
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--output", "-o", default=None)
@click.option("--table", is_flag=True)
def search(query, limit, mode, cookies, output, table):
    """Busca tweets por query."""
    try:
        client = get_client(cookies)
        data   = run(search_tweets(client, query, limit=limit, mode=mode))
        if table:
            print_tweets_table(data, f'Resultados: "{query}"')
        else:
            print_json({"query": query, "count": len(data), "tweets": data}, output)
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("text")
@click.option("--reply-to", default=None, help="ID del tweet al que responder")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
def post(text, reply_to, cookies):
    """Publica un tweet. Requiere auth_token."""
    try:
        client = get_client(cookies)
        result = run(post_tweet(client, text, reply_to_id=reply_to))
        if result["success"]:
            click.echo(f"✅ Tweet publicado! ID: {result['tweet_id']}")
        else:
            click.echo("❌ No se pudo publicar.", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
def delete(tweet_id, cookies):
    """Elimina un tweet por ID. Requiere auth_token."""
    try:
        result = run(delete_tweet(get_client(cookies), tweet_id))
        click.echo("✅ Tweet eliminado." if result["success"] else "❌ No se pudo eliminar.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
def like(tweet_id, cookies):
    """Da like a un tweet. Requiere auth_token."""
    try:
        result = run(like_tweet(get_client(cookies), tweet_id))
        click.echo("✅ Like dado." if result["success"] else "❌ Error dando like.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("username")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
def follow(username, cookies):
    """Sigue a un usuario. Requiere auth_token."""
    try:
        client  = get_client(cookies)
        user_id = run(get_user_id(client, username))
        result  = run(follow_user(client, user_id))
        click.echo(f"✅ Siguiendo a @{username}." if result["success"] else f"❌ Error siguiendo a @{username}.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("username")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
def unfollow(username, cookies):
    """Deja de seguir a un usuario. Requiere auth_token."""
    try:
        client  = get_client(cookies)
        user_id = run(get_user_id(client, username))
        result  = run(unfollow_user(client, user_id))
        click.echo(f"✅ Unfollow de @{username}." if result["success"] else f"❌ Error en unfollow de @{username}.")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)


@cli.command("bulk-unfollow")
@click.argument("username")
@click.option("--limit", "-l", default=200, show_default=True, help="Cuántos following revisar")
@click.option("--delay", default=2.0, show_default=True, help="Segundos entre unfollows")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--dry-run", is_flag=True, help="Solo muestra quién sería unfollowed, sin hacer nada")
def bulk_unfollow_cmd(username, limit, delay, cookies, dry_run):
    """
    Unfollow masivo de cuentas que no te siguen de vuelta.

    ⚠️  Usa --dry-run primero para ver qué pasaría.
    """
    try:
        client        = get_client(cookies)
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


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
