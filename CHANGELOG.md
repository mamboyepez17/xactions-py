# Changelog

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
