#!/usr/bin/env python3
"""
XActions-PY — CLI
Interfaz de línea de comandos. Sin npm.

v1.3.0:
  - Carga automática de .env (TWITTER_COOKIES, TWITTER_PROXY).
  - Pool de cookies: --cookies-file acepta varias cuentas (una por línea).
  - Export NDJSON (--ndjson).
  - Comandos nuevos: analyze, track, history.
  - post soporta --media para adjuntar imágenes.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from typing import Any

import click
from dotenv import load_dotenv

# Carga .env automáticamente (no rompe si no existe)
load_dotenv()

# Fix encoding para Windows (emojis, caracteres especiales)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions.actions import (
    bulk_unfollow,
    create_bookmark,
    delete_bookmark,
    delete_tweet,
    follow_user,
    like_tweet,
    post_tweet,
    unfollow_user,
    unlike_tweet,
    upload_media,
)
from analytics.analyzer import analyze_tweets
from scraper.client import TwitterClient
from scraper.pool import ClientPool
from scraper.scrapers import (
    get_bookmarks,
    get_home_timeline,
    get_trends,
    get_tweet_favoriters,
    get_tweet_replies,
    get_tweet_retweeters,
    get_user_id,
    get_user_likes,
    scrape_followers,
    scrape_following,
    scrape_non_followers,
    scrape_profile,
    scrape_tweets,
    search_tweets,
)
from storage.db import TrackerDB, compute_profile_delta

# ─── Helpers ──────────────────────────────────────────────────────────────────

COOKIES_ENV = "TWITTER_COOKIES"
PROXY_ENV = "TWITTER_PROXY"

AnyClient = TwitterClient | ClientPool


def _load_cookies_list(cookies: str, cookies_file: str | None) -> list[str]:
    """
    Devuelve la lista de strings de cookies disponibles.
    - --cookies-file: una cookie por línea (líneas vacías y # ignoradas).
    - --cookies / TWITTER_COOKIES: una sola cookie, o varias separadas por '|||'.
    """
    raw: list[str] = []
    if cookies_file:
        if not os.path.exists(cookies_file):
            raise click.ClickException(f"Archivo no encontrado: {cookies_file}")
        with open(cookies_file, encoding="utf-8") as f:
            raw = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    else:
        value = cookies or os.getenv(COOKIES_ENV, "")
        if value:
            raw = [c.strip() for c in value.split("|||") if c.strip()]
    return raw


def get_client(cookies: str = "", cookies_file: str | None = None) -> AnyClient:
    """Devuelve un TwitterClient (1 cookie) o un ClientPool (varias)."""
    cookie_list = _load_cookies_list(cookies, cookies_file)
    proxy = os.getenv(PROXY_ENV)
    if len(cookie_list) > 1:
        return ClientPool(cookie_list, proxy=proxy)
    return TwitterClient(cookies=cookie_list[0] if cookie_list else "", proxy=proxy)


def run(coro):
    return asyncio.run(coro)


def print_json(data: Any, output: str | None = None):
    out = json.dumps(data, ensure_ascii=False, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(out)
        click.echo(f"✅ Guardado en {output}")
    else:
        click.echo(out)


def _write_csv(path: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None):
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


def _write_ndjson(path: str, rows: list[dict[str, Any]]):
    if not rows:
        click.echo("⚠️  No hay datos para exportar a NDJSON.")
        return
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    click.echo(f"✅ NDJSON guardado en {path}")


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
        table_fn(data, table_title)
    else:
        print_json(data)


def print_users_table(users: list[dict[str, Any]], title: str = ""):
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
    click.echo(f"  📊 Análisis de @{username} — {report['total_tweets']} tweets")
    click.echo(f"{'═'*55}")
    click.echo("  Promedios por tweet:")
    click.echo(f"    ❤ {avg.get('likes', 0):>10,.1f}   🔁 {avg.get('retweets', 0):>8,.1f}   "
               f"💬 {avg.get('replies', 0):>6,.1f}   👁 {avg.get('views', 0):>10,.1f}")
    if report.get("engagement_rate_followers") is not None:
        click.echo(f"  Engagement rate (followers): {report['engagement_rate_followers']}%")
    if report.get("engagement_rate_views") is not None:
        click.echo(f"  Engagement rate (views):     {report['engagement_rate_views']}%")

    content = report.get("content", {})
    if content:
        click.echo(f"\n  Contenido: {content.get('with_media_pct', 0)}% con media, "
                   f"{content.get('replies_pct', 0)}% replies, "
                   f"{content.get('quotes_pct', 0)}% quotes")

    if report.get("best_hours"):
        hours = ", ".join(f"{h['hour']:02d}:00" for h in report["best_hours"])
        click.echo(f"  Mejores horas (UTC): {hours}")
    if report.get("best_days"):
        days = ", ".join(d["day"] for d in report["best_days"])
        click.echo(f"  Mejores días:        {days}")

    if report.get("top_tweets"):
        click.echo("\n  🏆 Top tweets:")
        for t in report["top_tweets"]:
            click.echo(f"    [{t['score']:>6}] ❤{t['likes'] or 0:<6} {(t['text'] or '')[:60]}")
    click.echo(f"{'═'*55}\n")


def common_options(fn):
    """Opciones comunes para comandos de lectura."""
    fn = click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")(fn)
    fn = click.option("--cookies-file", type=click.Path(exists=True), default=None,
                      help="Archivo con cookies (una por línea = pool multi-cuenta)")(fn)
    fn = click.option("--output", "-o", default=None, help="Archivo JSON de salida")(fn)
    fn = click.option("--csv", "csv_path", default=None, help="Archivo CSV de salida")(fn)
    fn = click.option("--ndjson", "ndjson_path", default=None, help="Archivo NDJSON de salida")(fn)
    fn = click.option("--table", is_flag=True, help="Mostrar como tabla en vez de JSON")(fn)
    return fn


# ─── CLI principal ────────────────────────────────────────────────────────────

@click.group()
@click.version_option("1.3.0", prog_name="xactions-py")
def cli():
    """⚡ XActions-PY — Twitter automation sin npm."""
    pass


@cli.command()
@click.argument("username")
@common_options
def profile(username, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Obtiene el perfil de un usuario."""
    client = get_client(cookies, cookies_file)
    try:
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
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True, help="Máximo de usuarios")
@common_options
def followers(username, limit, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Lista los followers de un usuario."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(scrape_followers(client, username, limit=limit))
        _handle_output(
            {"count": len(data), "followers": data},
            output, csv_path, ndjson_path,
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
def following(username, limit, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Lista los usuarios que sigue una cuenta."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(scrape_following(client, username, limit=limit))
        _handle_output(
            {"count": len(data), "following": data},
            output, csv_path, ndjson_path,
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
def non_followers_cmd(username, limit, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Muestra quién no te sigue de vuelta."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(scrape_non_followers(client, username, limit=limit))
        _handle_output(
            {"count": len(data), "non_followers": data},
            output, csv_path, ndjson_path,
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
def tweets(username, limit, replies, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Obtiene los tweets recientes de un usuario."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(scrape_tweets(client, username, limit=limit, include_replies=replies))
        _handle_output(
            {"count": len(data), "tweets": data},
            output, csv_path, ndjson_path,
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
def search(query, limit, mode, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Busca tweets por query."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(search_tweets(client, query, limit=limit, mode=mode))
        _handle_output(
            {"query": query, "count": len(data), "tweets": data},
            output, csv_path, ndjson_path,
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
def replies(tweet_id, limit, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Obtiene replies/conversación de un tweet."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_tweet_replies(client, tweet_id, limit=limit))
        _handle_output(
            {"tweet_id": tweet_id, "count": len(data), "tweets": data},
            output, csv_path, ndjson_path,
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
def likers(tweet_id, limit, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Usuarios que dieron like a un tweet."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_tweet_favoriters(client, tweet_id, limit=limit))
        _handle_output(
            {"tweet_id": tweet_id, "count": len(data), "users": data},
            output, csv_path, ndjson_path,
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
def retweeters(tweet_id, limit, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Usuarios que hicieron retweet a un tweet."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_tweet_retweeters(client, tweet_id, limit=limit))
        _handle_output(
            {"tweet_id": tweet_id, "count": len(data), "users": data},
            output, csv_path, ndjson_path,
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
def likes(username, limit, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Tweets a los que les dio like un usuario."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_user_likes(client, username, limit=limit))
        _handle_output(
            {"username": username, "count": len(data), "tweets": data},
            output, csv_path, ndjson_path,
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
def bookmarks(limit, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Bookmarks del usuario autenticado."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_bookmarks(client, limit=limit))
        _handle_output(
            {"count": len(data), "bookmarks": data},
            output, csv_path, ndjson_path,
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
def trends(woeid, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Trending topics de Twitter/X."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_trends(client, woeid=woeid))
        _handle_output(
            {"count": len(data), "trends": data},
            output, csv_path, ndjson_path,
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
def home(limit, latest, cookies, cookies_file, output, csv_path, ndjson_path, table):
    """Home timeline del usuario autenticado."""
    client = get_client(cookies, cookies_file)
    try:
        data = run(get_home_timeline(client, limit=limit, latest=latest))
        _handle_output(
            {"count": len(data), "tweets": data},
            output, csv_path, ndjson_path,
            csv_data=_flatten_tweets(data),
            table_fn=print_tweets_table if table else None,
            table_title="Home timeline",
        )
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


# ─── Analytics & tracking ─────────────────────────────────────────────────────

@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=100, show_default=True, help="Tweets a analizar")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@click.option("--output", "-o", default=None, help="Archivo JSON de salida")
def analyze(username, limit, cookies, cookies_file, output):
    """Analiza el engagement de un usuario (promedios, top tweets, mejores horas)."""
    client = get_client(cookies, cookies_file)
    try:
        async def _analyze():
            profile = await scrape_profile(client, username)
            tw = await scrape_tweets(client, username, limit=limit)
            return profile, tw

        profile, tw = run(_analyze())
        report = analyze_tweets(tw, profile=profile)
        report["username"] = username
        report["followers"] = profile.get("followers")

        if output:
            print_json(report, output)
        else:
            print_analysis(report, username)
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


@cli.command()
@click.argument("username")
@click.option("--limit", "-l", default=50, show_default=True, help="Tweets a trackear")
@click.option("--db", "db_path", default=None, help="Path de la base SQLite (default ~/.xactions/xactions.db)")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def track(username, limit, db_path, cookies, cookies_file):
    """Guarda un snapshot de métricas de un usuario en SQLite y muestra el delta."""
    client = get_client(cookies, cookies_file)
    try:
        db = TrackerDB(db_path)

        async def _collect():
            profile = await scrape_profile(client, username)
            tw = await scrape_tweets(client, username, limit=limit)
            return profile, tw

        profile, tw = run(_collect())

        previous = db.get_last_profile_snapshot(username)
        delta = compute_profile_delta(previous, profile)

        db.save_profile_snapshot(username, profile)
        saved = db.save_tweet_snapshots(tw)

        click.echo(f"\n📸 Snapshot guardado para @{username} ({saved} tweets)")
        click.echo(f"  Followers: {profile.get('followers', 0):,}")
        if delta["followers_delta"] is not None:
            sign = "+" if delta["followers_delta"] >= 0 else ""
            click.echo(f"  Δ followers: {sign}{delta['followers_delta']:,} (desde {delta.get('since')})")
            click.echo(f"  Δ tweets:    {'+' if delta['tweets_delta'] >= 0 else ''}{delta['tweets_delta']:,}")
        else:
            click.echo("  (primer snapshot — corre el comando de nuevo para ver deltas)")
        click.echo(f"  DB: {db.path}\n")
    except Exception as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    finally:
        run(client.aclose())


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


# ─── Write actions ────────────────────────────────────────────────────────────

@cli.command()
@click.argument("text")
@click.option("--reply-to", default=None, help="ID del tweet al que responder")
@click.option("--media", "media_files", multiple=True, type=click.Path(exists=True),
              help="Imagen a adjuntar (se puede repetir, máx 4)")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
def post(text, reply_to, media_files, cookies, cookies_file):
    """Publica un tweet. Requiere auth_token."""
    client = get_client(cookies, cookies_file)
    try:
        async def _post():
            media_ids = []
            for path in media_files[:4]:
                up = await upload_media(client, path)
                media_ids.append(up["media_id"])
                click.echo(f"📎 Media subida: {path} (id {up['media_id']})")
            return await post_tweet(client, text, reply_to_id=reply_to, media_ids=media_ids)

        result = run(_post())
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
            click.echo("\n🔍 Dry-run: no se hizo nada. Remueve --dry-run para ejecutar.")
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
    """Valida que las cookies funcionan contra la API (todas las del pool)."""
    client = get_client(cookies, cookies_file)
    try:
        result = run(client.validate_cookies())
        if "accounts" in result:
            # Pool multi-cuenta
            click.echo(f"\n🔐 Pool: {result['alive']}/{result['total']} cuentas vivas")
            for acc in result["accounts"]:
                if acc.get("valid"):
                    click.echo(f"  ✅ cuenta #{acc['account']}: @{acc.get('username')}")
                else:
                    click.echo(f"  ❌ cuenta #{acc['account']}: {acc.get('error')}")
            if result["alive"] == 0:
                sys.exit(1)
        elif result.get("valid"):
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
