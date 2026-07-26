"""
XActions-PY — Twitter HTTP Client
Replica del TwitterHttpClient de XActions pero en Python puro.
Sin npm, sin Puppeteer. Solo httpx + las GraphQL internas de Twitter.

v1.2.0:
  - Cliente HTTP persistente (connection pooling / keep-alive).
  - Reintentos con backoff exponencial para errores de red y rate limits.
  - Logging estructurado.
  - Context manager async para cerrar conexiones de forma segura.
  - Helpers REST (GET/POST) para validación de sesión y endpoints legacy.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, Dict, Optional
from urllib.parse import unquote

import httpx

# ─── Bearer Token público (embebido en el JS bundle de Twitter) ───────────────
BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

GRAPHQL_BASE = "https://x.com/i/api/graphql"
REST_BASE = "https://x.com/i/api"
API_BASE = "https://api.x.com"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# ─── GraphQL endpoints (reverse-engineered, actualizados desde twikit) ─────────
GRAPHQL_ENDPOINTS: Dict[str, Dict[str, Any]] = {
    "UserByScreenName": {"queryId": "NimuplG1OB7Fd2btCLdBOw", "operationName": "UserByScreenName"},
    "UserByRestId": {"queryId": "tD8zKvQzwY3kdx5yz6YmOw", "operationName": "UserByRestId"},
    "UserTweets": {"queryId": "QWF3SzpHmykQHsQMixG0cg", "operationName": "UserTweets"},
    "UserTweetsAndReplies": {"queryId": "vMkJyzx1wdmvOeeNG0n6Wg", "operationName": "UserTweetsAndReplies"},
    "UserMedia": {"queryId": "2tLOJWwGuCTytDrGBg8VwQ", "operationName": "UserMedia"},
    "UserLikes": {"queryId": "IohM3gxQHfvWePH5E3KuNA", "operationName": "Likes"},
    "TweetDetail": {"queryId": "U0HTv-bAWTBYylwEMT7x5A", "operationName": "TweetDetail"},
    "Favoriters": {"queryId": "LLkw5EcVutJL6y-2gkz22A", "operationName": "Favoriters"},
    "Retweeters": {"queryId": "X-XEqG5qHQSAwmvy00xfyQ", "operationName": "Retweeters"},
    "SearchTimeline": {"queryId": "flaR-PUMshxFWZWPNpq4zA", "operationName": "SearchTimeline", "method": "POST"},
    "Followers": {"queryId": "gC_lyAxZOptAMLCJX5UhWw", "operationName": "Followers", "method": "POST"},
    "Following": {"queryId": "2vUj-_Ek-UmBVDNtd8OnQA", "operationName": "Following"},
    "Bookmarks": {"queryId": "qToeLeMs43Q8cr7tRYXmaQ", "operationName": "Bookmarks"},
    "HomeTimeline": {"queryId": "-X_hcgQzmHGl29-UXxz4sw", "operationName": "HomeTimeline", "method": "POST"},
    "HomeLatestTimeline": {"queryId": "U0cdisy7QFIoTfu3-Okw0A", "operationName": "HomeLatestTimeline", "method": "POST"},
    # Mutations
    "CreateTweet": {"queryId": "SiM_cAu83R0wnrpmKQQSEw", "operationName": "CreateTweet"},
    "FavoriteTweet": {"queryId": "lI07N6Otwv1PhnEgXILM7A", "operationName": "FavoriteTweet"},
    "UnfavoriteTweet": {"queryId": "ZYKSe-w7KEslx3JhSIk5LA", "operationName": "UnfavoriteTweet"},
    "CreateRetweet": {"queryId": "ojPdsZsimiJrUGLR1sjUtA", "operationName": "CreateRetweet"},
    "DeleteRetweet": {"queryId": "iQtK4dl5hBmXewYZuEOKVw", "operationName": "DeleteRetweet"},
    "DeleteTweet": {"queryId": "VaenaVgh5q5ih7kvyVjgtg", "operationName": "DeleteTweet"},
    "CreateBookmark": {"queryId": "aoDbu3RHznuiSkQ9aNM67Q", "operationName": "CreateBookmark"},
    "DeleteBookmark": {"queryId": "Wlmlj2-xzyS1GN3a6cj-mQ", "operationName": "DeleteBookmark"},
    "FollowUser": {"queryId": None, "operationName": None},  # REST endpoint
    "UnfollowUser": {"queryId": None, "operationName": None},  # REST endpoint
}

DEFAULT_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": False,
    "tweet_awards_web_tipping_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

_log = logging.getLogger(__name__)


# ─── Excepciones ───────────────────────────────────────────────────────────────

class TwitterError(Exception):
    """Base de errores del cliente."""
    pass


class RateLimitError(TwitterError):
    """HTTP 429 o código 88 de la API."""
    pass


class AuthError(TwitterError):
    """HTTP 401/403 o código 32 de la API."""
    pass


class NotFoundError(TwitterError):
    """HTTP 404 o código 34 de la API."""
    pass


class ForbiddenError(TwitterError):
    """HTTP 403 — acceso denegado a un recurso."""
    pass


# ─── Cliente ────────────────────────────────────────────────────────────────────

class TwitterClient:
    """
    Cliente HTTP asíncrono para la GraphQL interna de Twitter/X.
    Equivalente directo del TwitterHttpClient de XActions en Python.

    Uso:
        async with TwitterClient(cookies=...) as client:
            profile = await scrape_profile(client, "elonmusk")
    """

    def __init__(
        self,
        cookies: Optional[str] = None,
        proxy: Optional[str] = None,
        max_retries: int = 3,
        timeout: float = 30.0,
        user_agent: Optional[str] = None,
    ):
        self._cookie_str = cookies or ""
        self._cookies: Dict[str, str] = {}
        self._proxy = proxy
        self._max_retries = max(0, max_retries)
        self._timeout = timeout
        self._user_agent = user_agent or random.choice(USER_AGENTS)
        self._csrf_token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._closed = False
        self._last_rate_limit_reset: Optional[int] = None

        if cookies:
            self._parse_cookies(cookies)

    # ─── Ciclo de vida ─────────────────────────────────────────────────────────

    async def __aenter__(self) -> "TwitterClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    def __del__(self):
        # Limpieza best-effort si el usuario olvidó cerrar.
        if self._client is not None and not self._closed:
            try:
                asyncio.get_running_loop().create_task(self.aclose())
            except RuntimeError:
                pass

    async def aclose(self) -> None:
        """Cierra el cliente HTTP y libera conexiones."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._closed = True
        _log.debug("TwitterClient cerrado")

    def close(self) -> None:
        """Cierre síncrono (útil para wrappers sync)."""
        try:
            loop = asyncio.get_running_loop()
            loop.run_until_complete(self.aclose())
        except RuntimeError:
            # No hay loop corriendo; usamos un loop nuevo.
            asyncio.run(self.aclose())

    @property
    def _http(self) -> httpx.AsyncClient:
        """Devuelve el cliente HTTP persistente, creándolo si es necesario."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                proxy=self._proxy,
                timeout=self._timeout,
                follow_redirects=True,
            )
            _log.debug("TwitterClient: cliente HTTP creado")
        return self._client

    # ─── Cookies / auth ──────────────────────────────────────────────────────────

    def _parse_cookies(self, cookie_str: str) -> None:
        """Parsea string de cookies 'name=val; name2=val2' a dict."""
        self._cookies = {}
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                self._cookies[k.strip()] = unquote(v.strip())
        self._csrf_token = self._cookies.get("ct0", "")
        self._cookie_str = "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    def set_cookies(self, cookie_str: str) -> None:
        self._cookie_str = cookie_str
        self._parse_cookies(cookie_str)

    def is_authenticated(self) -> bool:
        return bool(self._cookies.get("auth_token"))

    def _build_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {BEARER_TOKEN}",
            "User-Agent": self._user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://x.com/",
            "Origin": "https://x.com",
            "x-twitter-active-user": "yes",
            "x-twitter-client-language": "en",
        }
        if self._csrf_token:
            headers["x-csrf-token"] = self._csrf_token
        if self._cookies:
            headers["Cookie"] = self._cookie_str
        if self.is_authenticated():
            headers["x-twitter-auth-type"] = "OAuth2Session"
        if extra:
            headers.update(extra)
        return headers

    # ─── Requests ────────────────────────────────────────────────────────────────

    def _retry_delay(self, attempt: int, response: Optional[httpx.Response] = None) -> float:
        """Calcula segundos de espera antes de reintentar."""
        if response is not None and response.status_code == 429:
            # Twitter usa x-rate-limit-reset (timestamp unix) o retry-after.
            reset_ts = response.headers.get("x-rate-limit-reset")
            if reset_ts:
                try:
                    wait = max(0.0, float(reset_ts) - time.time())
                    self._last_rate_limit_reset = int(reset_ts)
                    # Cap a 30s para evitar esperas absurdas cuando el header
                    # viene mal o muy lejano (también útil en tests).
                    wait = min(wait, 30.0)
                    _log.warning("Rate limit. Esperando %.1fs (reset=%s)", wait, reset_ts)
                    return wait
                except (ValueError, TypeError):
                    pass
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    return float(retry_after)
                except (ValueError, TypeError):
                    pass
        return min(2.0 ** attempt, 30.0)

    async def _request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        data_payload: Optional[Dict[str, Any]] = None,
        allow_replay: bool = True,
    ) -> httpx.Response:
        """Request base con reintentos, rate-limit handling y logging."""
        request_headers = self._build_headers(headers)
        last_exception: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                if method.upper() == "GET":
                    resp = await self._http.get(url, headers=request_headers, params=params)
                elif json_payload is not None:
                    resp = await self._http.post(url, headers=request_headers, json=json_payload)
                elif data_payload is not None:
                    resp = await self._http.post(url, headers=request_headers, data=data_payload)
                else:
                    resp = await self._http.post(url, headers=request_headers)

                if resp.status_code == 429:
                    if attempt < self._max_retries:
                        delay = self._retry_delay(attempt, resp)
                        await asyncio.sleep(delay)
                        continue
                    raise RateLimitError(f"Rate limited. Reset: {self._last_rate_limit_reset}")

                if resp.status_code == 401:
                    raise AuthError(f"No autenticado o cookie expirada (HTTP {resp.status_code})")

                if resp.status_code == 403:
                    raise ForbiddenError(f"Acceso denegado (HTTP {resp.status_code}): {resp.text[:200]}")

                if resp.status_code == 404:
                    raise NotFoundError(f"Recurso no encontrado (HTTP {resp.status_code})")

                if resp.status_code >= 400:
                    raise TwitterError(f"HTTP {resp.status_code}: {resp.text[:500]}")

                return resp

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt < self._max_retries:
                    delay = 2.0 ** attempt
                    _log.warning("Error de red en intento %d/%d: %s. Reintentando en %.1fs", attempt + 1, self._max_retries + 1, e, delay)
                    await asyncio.sleep(delay)
                    continue
                raise TwitterError(f"Error de red tras {self._max_retries + 1} intentos: {e}")

        raise TwitterError(f"Max reintentos alcanzados: {last_exception}")

    # ─── GraphQL ─────────────────────────────────────────────────────────────────

    async def graphql(
        self,
        endpoint_name: str,
        variables: Dict[str, Any],
        features: Optional[Dict[str, Any]] = None,
        mutation: bool = False,
    ) -> Dict[str, Any]:
        """Ejecuta una query o mutation GraphQL contra la API interna de Twitter."""
        ep = GRAPHQL_ENDPOINTS[endpoint_name]
        query_id = ep["queryId"]
        operation = ep["operationName"]

        if not query_id or not operation:
            raise TwitterError(f"Endpoint {endpoint_name} no tiene queryId/operationName configurado")

        url = f"{GRAPHQL_BASE}/{query_id}/{operation}"
        features_payload = features if features is not None else DEFAULT_FEATURES
        use_post = mutation or ep.get("method") == "POST"

        if use_post:
            payload = {
                "variables": variables,
                "features": features_payload,
                "queryId": query_id,
            }
            resp = await self._request(
                "POST",
                url,
                headers={"Content-Type": "application/json"},
                json_payload=payload,
            )
        else:
            params = {
                "variables": json.dumps(variables),
                "features": json.dumps(features_payload),
            }
            resp = await self._request("GET", url, params=params)

        data = resp.json()
        if "errors" in data and data["errors"]:
            err = data["errors"][0]
            code = err.get("code", 0)
            message = err.get("message", "Unknown API error")
            if code == 32:
                raise AuthError(message)
            if code == 88:
                raise RateLimitError(message)
            if code == 34:
                raise NotFoundError(message)
            raise TwitterError(f"API error {code}: {message}")

        return data

    # ─── REST helpers ────────────────────────────────────────────────────────────

    async def rest_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET a un endpoint REST (ej. verify_credentials)."""
        url = f"{REST_BASE}{path}"
        resp = await self._request("GET", url, params=params)
        return resp.json()

    async def rest_post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST a un endpoint REST (usado para follow/unfollow)."""
        url = f"{REST_BASE}{path}"
        resp = await self._request(
            "POST",
            url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data_payload=data,
        )
        return resp.json()

    # ─── Validación de sesión ────────────────────────────────────────────────────

    async def validate_cookies(self) -> Dict[str, Any]:
        """
        Verifica que las cookies sean válidas haciendo una petición autenticada.
        Devuelve información básica de la cuenta o lanza AuthError/ForbiddenError.
        """
        if not self.is_authenticated():
            raise AuthError("Falta auth_token en las cookies")
        try:
            data = await self.rest_get("/1.1/account/verify_credentials.json", params={"skip_status": "true"})
            return {
                "valid": True,
                "user_id": data.get("id_str"),
                "username": data.get("screen_name"),
                "name": data.get("name"),
            }
        except (AuthError, ForbiddenError) as e:
            return {"valid": False, "error": str(e)}
