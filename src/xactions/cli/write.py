"""Commands that write to X (posts, likes, follows, engage)."""

from __future__ import annotations

import re
import sys

import click

from ..actions import (
    bulk_unfollow,
    create_bookmark,
    delete_bookmark,
    delete_tweet,
    follow_user,
    like_tweet,
    post_thread,
    post_tweet,
    unfollow_user,
    unlike_tweet,
    upload_media,
)
from ..scrapers import (
    get_user_id,
    scrape_non_followers,
)
from ._app import cli
from ._common import (
    COOKIES_ENV,
    print_users_table,
    run,
    with_client,
)

# ─── Write actions ────────────────────────────────────────────────────────────

@cli.command()
@click.argument("text")
@click.option("--reply-to", default=None, help="ID del tweet al que responder")
@click.option("--media", "media_files", multiple=True, type=click.Path(exists=True),
              help="Imagen a adjuntar (se puede repetir, máx 4)")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def post(client, text, reply_to, media_files):
    """Publica un tweet. Requiere auth_token."""
    from ..drafts import approval_required, create_draft

    if approval_required():
        if media_files:
            raise click.ClickException(
                "Approval is required (XACTIONS_REQUIRE_APPROVAL) and drafts cannot carry media yet. "
                "Post without --media or disable approval."
            )
        draft = create_draft(
            "post_tweet",
            {"text": text, "reply_to_id": reply_to},
        )
        click.echo(f"📝 Draft saved (approval required): {draft['id']}")
        click.echo("   Review: xactions drafts list → xactions drafts approve <id>")
        return

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
        click.echo(f"❌ No se pudo publicar. {result.get('error') or ''}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("tweets", nargs=-1)
@click.option("--from-file", type=click.Path(exists=True), default=None,
              help="Archivo de texto: un tweet por línea o separados por ---")
@click.option("--delay", default=1.5, show_default=True, help="Segundos entre tweets del hilo")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def thread(client, tweets, from_file, delay):
    """Publica un hilo. Cada argumento es un tweet, o usa --from-file."""
    parts: list[str] = []
    if from_file:
        raw = open(from_file, encoding="utf-8").read()
        # separar por --- o saltos dobles si no hay ---
        if "\n---\n" in raw or raw.strip().startswith("---"):
            chunks = [c.strip() for c in re.split(r"\n?---\n?", raw) if c.strip()]
        else:
            chunks = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        parts.extend(chunks)
    parts.extend(t.strip() for t in tweets if t and t.strip())

    if not parts:
        raise click.ClickException("Pasa tweets como argumentos o usa --from-file")

    click.echo(f"🧵 Publicando hilo de {len(parts)} tweets…")
    result = run(post_thread(client, parts, delay_seconds=delay))
    if result["success"]:
        click.echo(f"✅ Hilo publicado. Root: {result['root_id']} ({result['count']} tweets)")
    else:
        click.echo(f"❌ {result.get('error', 'Error')}", err=True)
        if result.get("tweet_ids"):
            click.echo(f"   Publicados parcialmente: {', '.join(result['tweet_ids'])}", err=True)
        sys.exit(1)

@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def delete(client, tweet_id):
    """Elimina un tweet por ID. Requiere auth_token."""
    result = run(delete_tweet(client, tweet_id))
    click.echo("✅ Tweet eliminado." if result["success"] else "❌ No se pudo eliminar.")


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def like(client, tweet_id):
    """Da like a un tweet. Requiere auth_token."""
    from ..drafts import approval_required, create_draft

    if approval_required():
        draft = create_draft("like", {"tweet_id": tweet_id})
        click.echo(f"📝 Draft saved: {draft['id']} — approve with: xactions drafts approve {draft['id']}")
        return
    result = run(like_tweet(client, tweet_id))
    click.echo("✅ Like dado." if result["success"] else "❌ Error dando like.")


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def unlike(client, tweet_id):
    """Quita el like de un tweet. Requiere auth_token."""
    result = run(unlike_tweet(client, tweet_id))
    click.echo("✅ Like quitado." if result["success"] else "❌ Error quitando like.")


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def bookmark(client, tweet_id):
    """Agrega un tweet a bookmarks. Requiere auth_token."""
    result = run(create_bookmark(client, tweet_id))
    click.echo("✅ Bookmark agregado." if result["success"] else "❌ Error agregando bookmark.")


@cli.command()
@click.argument("tweet_id")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def unbookmark(client, tweet_id):
    """Elimina un tweet de bookmarks. Requiere auth_token."""
    result = run(delete_bookmark(client, tweet_id))
    click.echo("✅ Bookmark eliminado." if result["success"] else "❌ Error eliminando bookmark.")


@cli.command()
@click.argument("username")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def follow(client, username):
    """Sigue a un usuario. Requiere auth_token."""
    user_id = run(get_user_id(client, username))
    result = run(follow_user(client, user_id))
    click.echo(f"✅ Siguiendo a @{username}." if result["success"] else f"❌ Error siguiendo a @{username}.")


@cli.command()
@click.argument("username")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@with_client
def unfollow(client, username):
    """Deja de seguir a un usuario. Requiere auth_token."""
    user_id = run(get_user_id(client, username))
    result = run(unfollow_user(client, user_id))
    click.echo(f"✅ Unfollow de @{username}." if result["success"] else f"❌ Error en unfollow de @{username}.")


@cli.command("bulk-unfollow")
@click.argument("username")
@click.option("--limit", "-l", default=200, show_default=True, help="Cuántos following revisar")
@click.option("--delay", default=2.0, show_default=True, help="Segundos entre unfollows")
@click.option("--cookies", envvar=COOKIES_ENV, default="", help="Cookies de sesión")
@click.option("--cookies-file", type=click.Path(exists=True), default=None, help="Archivo con cookies")
@click.option("--dry-run", is_flag=True, help="Solo muestra quién sería unfollowed, sin hacer nada")
@with_client
def bulk_unfollow_cmd(client, username, limit, delay, dry_run):
    """
    Unfollow masivo de cuentas que no te siguen de vuelta.
    ⚠️  Usa --dry-run primero para ver qué pasaría.
    """
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

@cli.command()
@click.argument("query")
@click.option("--like", is_flag=True, help="Like matching tweets")
@click.option("--retweet", is_flag=True, help="Retweet matching tweets")
@click.option("--limit", "-l", default=10, show_default=True, help="Max tweets to consider")
@click.option("--delay", default=3.0, show_default=True, help="Seconds between write actions")
@click.option("--min-likes", type=int, default=None, help="Skip tweets below this like count")
@click.option("--dry-run", is_flag=True, default=True, help="Preview only (default)")
@click.option("--execute", is_flag=True, help="Actually perform likes/RTs (uses daily caps)")
@click.option("--cookies", envvar=COOKIES_ENV, default="")
@click.option("--cookies-file", type=click.Path(exists=True), default=None)
@click.option("--from-browser", type=click.Choice(["chrome", "chromium", "brave", "edge", "firefox"]), default=None)
@with_client
def engage(client, query, like, retweet, limit, delay, min_likes, dry_run, execute):
    """
    Engage with search results (like / retweet) with delay and daily caps.

    Always preview with --dry-run; add --execute to write.
    """
    from ..actions import like_tweet
    from ..actions import retweet as rt_action
    from ..caps import WriteCapExceeded
    from ..scrapers import search_tweets

    if not like and not retweet:
        raise click.ClickException("Pass --like and/or --retweet")
    if execute:
        dry_run = False

    tweets = run(search_tweets(client, query, limit=limit, mode="Latest"))
    if min_likes is not None:
        tweets = [t for t in tweets if (t.get("likes") or 0) >= min_likes]

    click.echo(f"Found {len(tweets)} tweets for “{query}”")
    planned = []
    for t in tweets:
        planned.append(
            {
                "id": t.get("id"),
                "like": like,
                "retweet": retweet,
                "likes": t.get("likes"),
                "text": (t.get("text") or "")[:60],
            }
        )

    if dry_run:
        click.echo("🔍 DRY-RUN — nothing will be written. Use --execute to run.")
        for p in planned:
            acts = "+".join([a for a, on in (("like", p["like"]), ("rt", p["retweet"])) if on])
            click.echo(f"  [{acts}] {p['id']} ❤{p['likes']} {p['text']}")
        return

    done = {"like": 0, "retweet": 0, "skipped": 0, "failed": 0}
    import time as _time

    for p in planned:
        tid = p["id"]
        if not tid:
            continue
        try:
            if p["like"]:
                r = run(like_tweet(client, str(tid)))
                if r.get("success"):
                    done["like"] += 1
                else:
                    done["failed"] += 1
                _time.sleep(delay)
            if p["retweet"]:
                r = run(rt_action(client, str(tid)))
                if r.get("success"):
                    done["retweet"] += 1
                else:
                    done["failed"] += 1
                _time.sleep(delay)
        except WriteCapExceeded as e:
            click.echo(f"🛑 Cap reached: {e}", err=True)
            done["skipped"] += 1
            break
    click.echo(
        f"Engage done: likes={done['like']} rts={done['retweet']} "
        f"failed={done['failed']} stopped_cap={done['skipped']}"
    )
