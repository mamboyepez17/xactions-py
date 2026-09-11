# Changelog

## v1.5.0 — 2026-08-17

### Added (B2 GraphQL resilience)
- **Auto-refresh de GraphQL query IDs** (`xactions/gql_refresh.py`):
  - Parser de bundles de x.com (responsive-web y x-web + assets relativos).
  - Formatos: `queryId`/`operationName` clásico y Relay `id`/`name`.
  - **Multi-fuente:** bundle logueado (si hay cookies) → bundle anónimo → fallback twikit.
  - Cache en `~/.xactions/gql_endpoints.json`.
- CLI: `xactions gql-status` y `xactions gql-refresh` (acepta cookies para crawl logueado).
- `TwitterClient.refresh_gql_endpoints()` — refresh con las cookies de la sesión.
- El cliente reintenta una vez si un endpoint devuelve 404 / “Query does not exist” (pasando sus cookies al refresh).
- Env `XACTIONS_NO_GQL_REFRESH=1` para tests/CI sin red.

### Added (B5 features)
- **`build_search_query()`**: operadores `from:`, `to:`, `since:`, `until:`, `min_faves:`, `lang:`, `filter:media`, `-filter:retweets`…
- **CLI `search`**: flags `--from`, `--to`, `--since`, `--until`, `--min-faves`, `--min-retweets`, `--lang`, `--exclude-retweets`, `--exclude-replies`, `--media`.
- **`post_thread()` / CLI `thread` / MCP `x_post_thread`**: hilos encadenando replies.
- **`compare_accounts()` / CLI `compare` / MCP `x_compare_accounts`**: métricas lado a lado de dos cuentas.
- MCP `x_build_search_query`.

### Added (B4 rate-limit + paginación)
- **Throttle proactivo**: el client guarda `x-rate-limit-remaining` / `x-rate-limit-reset` por endpoint y espera *antes* del request si remaining=0 (en vez de solo reaccionar al 429).
- **`max_rate_limit_wait`** configurable en `TwitterClient` (default 60s); el wait del 429 también se capa con ese valor.
- `client.rate_limit_status()` para inspección.
- **Páginas más grandes**: Followers/Following 100, engagement 50, tweets/home 40 (search sigue en 20 por límite de la API).

### Added (B3 seguridad cookies)
- Módulo `xactions/security.py`: `redact_cookies` / `redact_in_text` (nunca imprime valores).
- CLI: warning no bloqueante si pasas cookies con `--cookies` (historial del shell).
- CLI: warning si `--cookies-file` es legible por otros en Unix (sugiere `chmod 600`).
- Mensajes de error del CLI redactan `auth_token=` / `ct0=` si aparecen.
- Docs de seguridad en README.

### Changed (BREAKING para imports)
- El código vive ahora en el paquete instalable `src/xactions/` (antes carpetas sueltas `src/scraper`, `src/actions`, `src/analytics`, `src/storage`, `src/mcp_tools` + `cli/`).
- **Guía de migración:**
  - `from src.scraper.client import TwitterClient` → `from xactions.client import TwitterClient` (o `from xactions import TwitterClient`)
  - `from src.scraper.scrapers import search_tweets` → `from xactions.scrapers import search_tweets` (o desde `xactions`)
  - `from src.actions.actions import like_tweet` → `from xactions.actions import like_tweet`
  - `from cli.xactions import cli` → `from xactions.cli import cli`
  - MCP: `python src/mcp_tools/server.py` → `python -m xactions.mcp_server`
- Entry point del CLI: `xactions = xactions.cli:cli` (el comando `xactions` no cambia).
- Eliminados todos los `sys.path.insert`.
- `pyproject.toml`: packages bajo `src/`, `pythonpath` para pytest, ruff `src`.

### Added
- `LICENSE` MIT en la raíz.
- `py.typed` en el paquete `xactions` (PEP 561).
- `xactions/__init__.py` con API pública (`__all__`, `__version__`).
- README actualizado con la nueva estructura y ejemplos de import.
- MCP compatible con `mcp` 2.x (`MCPServer`) y 1.x (`FastMCP`).

### Fixed
- `bulk_unfollow.on_progress` tipado como `Callable[[int, int, str], None]` (antes `callable`, inválido).
- `post_tweet` extrae `tweet_id` de más formas de respuesta GraphQL (`rest_id`, `legacy.id_str`, `TweetWithVisibilityResults`).
- `validate_cookies`: usa GraphQL (`HomeLatestTimeline`) en vez del REST `verify_credentials` deprecado.
- CLI `post` muestra el mensaje de error de la API (antes solo “No se pudo publicar”).
- Live test: validate/post/delete OK; hilo limitado por cupo diario de X (error 344), no por bug del cliente.

### Tests
- **78 passing** (+38 desde v1.4.0): packaging, GraphQL refresh, seguridad, rate-limit, features B5.

## v1.4.0 — 2026-08-17

### Fixed
- `TwitterClient.close()`: la lógica de cierre síncrono estaba invertida y fallaba dentro de un loop corriendo; ahora programa el cierre sin bloquear.
- Mutations (like, tweet, unfollow, bookmark...) ya no se reintentan ante errores de red — un timeout tras ser procesada por el servidor podía duplicar la acción.
- CSRF token (`ct0`) se refresca automáticamente cuando Twitter lo rota vía `Set-Cookie` en la respuesta.
- `search_tweets`: ante un bloqueo 403 sin resultados ahora propaga `ForbiddenError` (antes devolvía una lista vacía silenciosa); con resultados parciales los devuelve con warning.
- `bulk_unfollow`: loggea cada fallo individual en vez de tragárselo silenciosamente.
- MCP server: al cambiar las cookies se cierra (`aclose`) el cliente anterior — antes quedaban sockets abiertos hasta el GC.
- `scrape_profile`: usuarios suspendidos/no disponibles ahora lanzan `NotFoundError` claro en vez de romper el CLI con `AttributeError`.

### Added
- Headers `x-client-uuid` y `x-client-transaction-id` en todas las peticiones (compatibilidad con la GraphQL actual, igual que twikit).
- MCP `x_bulk_unfollow_non_followers`: parámetro `dry_run` para previsualizar sin ejecutar.
- SQLite: `PRAGMA journal_mode=WAL` + `busy_timeout` para uso concurrente seguro.
- CLI refactorizado con decorador `@with_client` (~100 líneas menos de boilerplate); la versión se lee de `importlib.metadata` (fuente única: `pyproject.toml`).
- CI: matriz con `windows-latest` además de `ubuntu-latest`.
- Tests: 40 passing (mutation no-retry, ct0 refresh, `close()` en loop, búsqueda bloqueada, CLI con `CliRunner`).

## v1.3.0 — 2026-07-27

### Added
- **Analytics**: new `src/analytics` module + `xactions analyze USERNAME` command — engagement averages, engagement rate (followers & views), top tweets by weighted score, best hours/days to post, content mix. Also available as MCP tool `x_analyze_user`.
- **SQLite tracking**: new `src/storage` module (pure stdlib `sqlite3`) + commands `xactions track USERNAME` (snapshot metrics, show follower delta) and `xactions history USERNAME` (evolution table). DB lives at `~/.xactions/xactions.db` (override with `XACTIONS_DB` or `--db`).
- **Multi-account pool**: new `ClientPool` (`src/scraper/pool.py`) with the same interface as `TwitterClient`. `--cookies-file` now accepts one cookie string per line and rotates accounts automatically on `RateLimitError`; accounts with `AuthError`/`ForbiddenError` are marked dead. `xactions validate` checks every account in the pool. MCP server also supports multiple cookies separated by `|||` or newlines.
- **Media upload**: `upload_media()` action (v1.1 `media/upload.json`, images up to ~5MB) and `xactions post "text" --media photo.jpg` (up to 4 images).
- **NDJSON export**: `--ndjson` flag on all read commands, alongside `--csv` and `--output`.
- **`.env` auto-load**: CLI and MCP server call `load_dotenv()` at startup (`python-dotenv` is now a core dependency).
- **user_id cache**: `get_user_id()` memoizes username → id in memory; `clear_user_id_cache()` available.
- **CI**: GitHub Actions workflow running `ruff check` + `pytest` on Python 3.10–3.13.
- Tests: 32 passing (analyzer, pool rotation, SQLite tracking, user_id cache, plus existing client/parser suites).

### Changed
- `scrape_non_followers()` fetches followers and following **concurrently** with `asyncio.gather` (~2x faster).
- Ruff lint config in `pyproject.toml`; whole codebase passes `ruff check` (modernized type annotations to PEP 585/604).
- `TwitterClient.rest_upload()` for multipart uploads.

## v1.2.0 — 2026-07-26

### Added
- `TwitterClient` now keeps a persistent `httpx.AsyncClient` with HTTP/2 and connection pooling.
- Automatic retries with exponential backoff for network errors and rate limits (respects `x-rate-limit-reset` / `Retry-After`).
- New scrapers:
  - `get_tweet_replies` — conversation/thread of a tweet.
  - `get_tweet_favoriters` / `get_tweet_retweeters` — users who engaged with a tweet.
  - `get_user_likes` — public likes of a user.
  - `get_bookmarks` — authenticated user's bookmarks.
  - `get_home_timeline` — authenticated home timeline.
  - `get_trends` — trending topics via REST API.
- New actions: `create_bookmark` / `delete_bookmark`.
- `TwitterClient.validate_cookies()` and `xactions validate` CLI command.
- CLI: `--cookies-file`, `--csv` export, and commands `replies`, `likers`, `retweeters`, `likes`, `bookmarks`, `home`, `trends`, `bookmark`, `unbookmark`, `validate`.
- MCP server: `x_validate_cookies`, `x_get_user_likes`, `x_get_tweet_replies`, `x_get_tweet_favoriters`, `x_get_tweet_retweeters`, `x_get_bookmarks`, `x_get_home_timeline`, `x_get_trends`, `x_bookmark_tweet`, `x_unbookmark_tweet`.
- Test suite with `pytest` + `respx` + `pytest-asyncio`.
- `CHANGELOG.md`.

### Changed
- GraphQL query IDs synced with the latest `twikit` endpoints.
- CLI and API search default to `mode="Top"` for consistency with the README.
- CLI version bumped to `1.2.0`.
- Error handling now distinguishes `RateLimitError`, `AuthError`, `ForbiddenError`, `NotFoundError` and `TwitterError`.

### Fixed
- `search_tweets` no longer relies on fragile string matching to detect HTTP 403; it uses `ForbiddenError`.
- Sync wrappers now properly close the `TwitterClient` after execution.

## v1.1.0 — 2026-07-25

### Added
- Full metrics extraction in `parse_tweet` (likes, retweets, replies, quotes, views, bookmarks).
- `_safe_int()` helper for robust metric parsing.
- `mode="Top"` default in `search_tweets`.
- Sync wrappers: `search_tweets_sync`, `scrape_profile_sync`, `scrape_tweets_sync`.

### Fixed
- Better HTTP 403 handling during search.
- `pyproject.toml` build backend corrected to `setuptools.build_meta`.

## v1.0.0 — Initial release

- Python port of [XActions](https://github.com/nirholas/XActions).
- `httpx` + Twitter/X internal GraphQL API.
- Profile, followers, following, tweets, search, like, follow, tweet, delete, bulk-unfollow.
- CLI and MCP server.
