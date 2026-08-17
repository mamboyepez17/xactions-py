"""
XActions-PY — Actions
Like, unlike, follow, unfollow, tweet, retweet, delete, bookmark.
Todo vía GraphQL interna o REST legacy. Requiere auth_token + ct0 en cookies.

v1.2.0:
  - Agregados create_bookmark / delete_bookmark.
  - Mejor manejo de errores y cierre de cliente.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

# Permitir importaciones absolutas desde src/ cuando se ejecuta el CLI/scripts.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scraper.client import UPLOAD_BASE, AuthError, TwitterClient

_log = logging.getLogger(__name__)


def _require_auth(client: TwitterClient) -> None:
    if not client.is_authenticated():
        raise AuthError("Se requiere autenticación. Configura auth_token y ct0.")


# ─── Media upload ─────────────────────────────────────────────────────────────

async def upload_media(client: TwitterClient, file_path: str) -> dict[str, Any]:
    """
    Sube una imagen (jpg/png/gif/webp) a Twitter y devuelve su media_id.
    Requiere auth. Límite simple upload: ~5MB por imagen.
    (Los videos requieren chunked upload INIT/APPEND/FINALIZE — no soportado aún.)
    """
    _require_auth(client)
    data = await client.rest_upload(f"{UPLOAD_BASE}/1.1/media/upload.json", file_path)
    media_id = data.get("media_id_string") or str(data.get("media_id", ""))
    if not media_id:
        raise AuthError(f"No se obtuvo media_id: {data}")
    return {"success": True, "media_id": media_id, "size": data.get("size")}


# ─── Tweets ───────────────────────────────────────────────────────────────────

async def post_tweet(
    client: TwitterClient,
    text: str,
    reply_to_id: str | None = None,
    media_ids: list | None = None,
) -> dict[str, Any]:
    """Publica un tweet (con media opcional). Requiere auth."""
    _require_auth(client)

    media_entities = [{"media_id": mid, "tagged_users": []} for mid in (media_ids or [])]
    variables = {
        "tweet_text": text,
        "dark_request": False,
        "media": {"media_entities": media_entities, "possibly_sensitive": False},
        "semantic_annotation_ids": [],
    }
    if reply_to_id:
        variables["reply"] = {
            "in_reply_to_tweet_id": reply_to_id,
            "exclude_reply_user_ids": [],
        }

    data = await client.graphql("CreateTweet", variables=variables, mutation=True)
    result = (
        data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
    )
    return {"success": bool(result), "tweet_id": result.get("rest_id")}


async def delete_tweet(client: TwitterClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    data = await client.graphql(
        "DeleteTweet",
        variables={"tweet_id": tweet_id, "dark_request": False},
        mutation=True,
    )
    return {"success": "data" in data}


# ─── Engagement ─────────────────────────────────────────────────────────────

async def like_tweet(client: TwitterClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    data = await client.graphql(
        "FavoriteTweet",
        variables={"tweet_id": tweet_id},
        mutation=True,
    )
    return {"success": data.get("data", {}).get("favorite_tweet") == "Done"}


async def unlike_tweet(client: TwitterClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    data = await client.graphql(
        "UnfavoriteTweet",
        variables={"tweet_id": tweet_id},
        mutation=True,
    )
    return {"success": data.get("data", {}).get("unfavorite_tweet") == "Done"}


async def retweet(client: TwitterClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    data = await client.graphql(
        "CreateRetweet",
        variables={"tweet_id": tweet_id, "dark_request": False},
        mutation=True,
    )
    result = data.get("data", {}).get("create_retweet", {}).get("retweet_results", {})
    return {"success": bool(result)}


async def unretweet(client: TwitterClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    data = await client.graphql(
        "DeleteRetweet",
        variables={"source_tweet_id": tweet_id, "dark_request": False},
        mutation=True,
    )
    return {"success": bool(data.get("data"))}


# ─── Bookmarks ───────────────────────────────────────────────────────────────

async def create_bookmark(client: TwitterClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    data = await client.graphql(
        "CreateBookmark",
        variables={"tweet_id": tweet_id},
        mutation=True,
    )
    return {"success": "data" in data}


async def delete_bookmark(client: TwitterClient, tweet_id: str) -> dict[str, Any]:
    _require_auth(client)
    data = await client.graphql(
        "DeleteBookmark",
        variables={"tweet_id": tweet_id},
        mutation=True,
    )
    return {"success": "data" in data}


# ─── Follow / Unfollow ─────────────────────────────────────────────────────────

async def follow_user(client: TwitterClient, user_id: str) -> dict[str, Any]:
    """Follow por user_id. Usa REST endpoint (no GraphQL mutation disponible)."""
    _require_auth(client)
    data = await client.rest_post(
        "/1.1/friendships/create.json",
        {"user_id": user_id, "skip_status": "true"},
    )
    return {"success": bool(data.get("id_str") or data.get("id"))}


async def unfollow_user(client: TwitterClient, user_id: str) -> dict[str, Any]:
    """Unfollow por user_id."""
    _require_auth(client)
    data = await client.rest_post(
        "/1.1/friendships/destroy.json",
        {"user_id": user_id, "skip_status": "true"},
    )
    return {"success": bool(data.get("id_str") or data.get("id"))}


# ─── Bulk unfollow ─────────────────────────────────────────────────────────────

async def bulk_unfollow(
    client: TwitterClient,
    user_ids: list,
    delay_seconds: float = 2.0,
    on_progress: callable | None = None,
) -> dict[str, Any]:
    """
    Hace unfollow masivo con delay entre cada acción para evitar rate limits.
    on_progress: callable(current, total, username) opcional.
    """
    _require_auth(client)
    success = 0
    failed = 0

    for i, uid in enumerate(user_ids):
        try:
            result = await unfollow_user(client, uid)
            if result["success"]:
                success += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            _log.warning("bulk_unfollow: falló user_id=%s (%s)", uid, e)

        if on_progress:
            on_progress(i + 1, len(user_ids), uid)

        await asyncio.sleep(delay_seconds)

    return {
        "total": len(user_ids),
        "success": success,
        "failed": failed,
    }
