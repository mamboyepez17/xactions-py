"""
XActions-PY — ClientPool
Client pool with cookie rotation (multi-account).

When an account hits a rate limit (429) or its cookies die (401),
the pool rotates to the next available account automatically.

Usage:
    pool = ClientPool([cookies1, cookies2, cookies3])
    profile = await scrape_profile(pool, "elonmusk")   # works with any scraper
    await pool.aclose()
"""

from __future__ import annotations

import logging
from typing import Any

from .client import AuthError, RateLimitError, TwitterClient, TwitterError

_log = logging.getLogger(__name__)


class ClientPool:
    """
    Round-robin pool of TwitterClient.

    Exposes the same interface as TwitterClient (`graphql`, `rest_get`,
    `rest_post`, `is_authenticated`, `validate_cookies`, `aclose`), so it
    can be passed to any scraper/action in place of a client.
    """

    def __init__(
        self,
        cookies_list: list[str] | None = None,
        proxy: str | None = None,
        max_retries: int = 3,
        clients: list[TwitterClient] | None = None,
    ):
        if clients is not None:
            self._clients = list(clients)
        else:
            if not cookies_list:
                raise ValueError("ClientPool needs at least one cookie string")
            self._clients = [
                TwitterClient(cookies=c, proxy=proxy, max_retries=max_retries)
                for c in cookies_list
                if c and c.strip()
            ]
        if not self._clients:
            raise ValueError("ClientPool has no valid clients")
        self._idx = 0
        self._dead: set[int] = set()

    # ─── Pool management ──────────────────────────────────────────────────────

    @property
    def current(self) -> TwitterClient:
        return self._clients[self._idx]

    @property
    def size(self) -> int:
        return len(self._clients)

    @property
    def alive(self) -> int:
        return self.size - len(self._dead)

    def _rotate(self) -> None:
        """Advance to the next live account. Raises TwitterError if none is left."""
        if self.alive <= 0:
            raise TwitterError("Every account in the pool is exhausted (rate limited or invalid cookies)")
        for _ in range(self.size):
            self._idx = (self._idx + 1) % self.size
            if self._idx not in self._dead:
                return

    def mark_dead(self) -> None:
        """Mark the current account as dead and rotate."""
        _log.warning("ClientPool: marking account #%d as dead", self._idx)
        self._dead.add(self._idx)
        self._rotate()

    # ─── TwitterClient-compatible interface ───────────────────────────────────

    def is_authenticated(self) -> bool:
        return self.current.is_authenticated()

    async def _execute(self, method_name: str, *args, **kwargs) -> Any:
        """
        Call a method on the current client, rotating automatically
        on rate limits and authentication errors.
        """
        last_exc: Exception | None = None
        attempts = self.size

        for _ in range(attempts):
            method = getattr(self.current, method_name)
            try:
                return await method(*args, **kwargs)
            except RateLimitError as e:
                last_exc = e
                _log.warning("ClientPool: account #%d rate limited, rotating", self._idx)
                self._rotate()
            except AuthError as e:
                last_exc = e
                self.mark_dead()
            # ForbiddenError (403) is not caught: it usually means the *resource*
            # is off-limits (protected account, blocked search), not that this
            # account's session died, so rotating or killing the account is wrong.

        raise last_exc or TwitterError("ClientPool: every account failed")

    async def graphql(self, *args, **kwargs) -> dict[str, Any]:
        return await self._execute("graphql", *args, **kwargs)

    async def rest_get(self, *args, **kwargs) -> dict[str, Any]:
        return await self._execute("rest_get", *args, **kwargs)

    async def rest_post(self, *args, **kwargs) -> dict[str, Any]:
        return await self._execute("rest_post", *args, **kwargs)

    async def rest_upload(self, *args, **kwargs) -> dict[str, Any]:
        return await self._execute("rest_upload", *args, **kwargs)

    async def upload_request(self, *args, **kwargs) -> dict[str, Any]:
        return await self._execute("upload_request", *args, **kwargs)

    async def validate_cookies(self) -> dict[str, Any]:
        """Validate every account in the pool and return a summary."""
        results = []
        for i, client in enumerate(self._clients):
            if i in self._dead:
                results.append({"account": i, "valid": False, "error": "marked dead"})
                continue
            try:
                res = await client.validate_cookies()
                results.append({"account": i, **res})
                if not res.get("valid"):
                    self._dead.add(i)
            except Exception as e:  # noqa: BLE001 — best-effort validation
                results.append({"account": i, "valid": False, "error": str(e)})
                self._dead.add(i)
        # Leave the index pointing at a live account
        if self._idx in self._dead and self.alive > 0:
            self._rotate()
        return {
            "total": self.size,
            "alive": self.alive,
            "accounts": results,
        }

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    async def aclose(self) -> None:
        for client in self._clients:
            await client.aclose()

    async def __aenter__(self) -> ClientPool:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()
