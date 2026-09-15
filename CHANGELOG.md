# Changelog

## v1.8.0 — 2026-09-10

### Added
- **Lightweight sentiment** (`xactions.sentiment`): bilingual EN/ES lexicon, `xactions sentiment QUERY|--file tweets.json`.
- **`xactions engage`**: like/retweet from search with `--dry-run` (default), `--execute`, `--delay`, `--min-likes`; respects daily write caps.
- **README rewrite**: full feature reference for v1.5–v1.8 (CLI, API, MCP, pipelines, safety).

### Tests
- **158 passing** (+10 since v1.7.0).

## v1.7.0 — 2026-09-10

### Added
- **`xactions report`**: Markdown/HTML engagement report for one account or a compare of two.
- **Declarative pipeline**: `xactions pipeline file.json` — steps `search` / `profile_tweets` / `filter` / `notify` / `report` / `print` / `like` (writes only with `--execute`).
- **Notify / webhook**: `XACTIONS_WEBHOOK_URL` POSTs JSON on watch/pipeline alerts (`notify.py`).
- **MCP tool groups**: `XACTIONS_MCP_TOOLS=read,analytics` / `XACTIONS_MCP_TOOLS_EXCLUDE=write` filter advertised tools at server start.

### Tests
- **148 passing** (+26 since v1.6.0).

## v1.6.0 — 2026-09-10

### Added
- **`xactions doctor`**: health checks (python, cookies, GraphQL cache, write caps, SQLite, proxy).
- **Daily write caps** (`~/.xactions/write_caps.json`): rolling 24h budget per account/operation; `post`/`like`/`follow`/`unfollow` refuse over-budget writes (`WriteCapExceeded`). Env override via limits JSON.
- **`--from-browser`**: import `auth_token`/`ct0` from Chrome/Chromium/Brave/Edge/Firefox profiles (Windows DPAPI via ctypes; encrypted leftovers fall back to Cookie-Editor export).
- **Multi-format `--cookies-file`**: Netscape `cookies.txt`, Cookie-Editor JSON, Playwright `storageState`, one cookie-string per line.
- **Write drafts + approval**: `XACTIONS_REQUIRE_APPROVAL=1` holds `post`/`like` as drafts; `xactions drafts list|approve|discard`; MCP `x_list_drafts` / `x_approve_draft` / `x_discard_draft`.
- **Payload-bound `x-client-transaction-id`** (SHA-256 + random, method/path bound). `XACTIONS_TXID_MODE=uuid` restores v1.5 behaviour.
- **`xactions watch`**: poll a search and print only new tweets (delta state under `~/.xactions/state/`).
- **Scrape checkpoints**: `scrape_followers`/`scrape_following` accept `checkpoint=True` to resume from last cursor.
- **`xactions download-media`**: download photos/videos from recent tweets.
- **`xactions snapshot-followers` / `xactions unfollowers`**: follower snapshot + unfollower diff.

### Tests
- **122 passing** (+44 since v1.5.0).

## v1.5.0 — 2026-08-17

### Added — GraphQL resilience
- **Auto-refresh of GraphQL query IDs** (`xactions/gql_refresh.py`):
  - Parses x.com JS bundles (responsive-web and x-web + relative assets).
  - Formats: classic `queryId`/`operationName` and Relay `id`/`name`.
  - **Multi-source:** logged-in bundle (if cookies) → anonymous bundle → twikit fallback.
  - Cache at `~/.xactions/gql_endpoints.json`.
- CLI: `xactions gql-status` and `xactions gql-refresh` (accepts cookies for a logged-in crawl).
- `TwitterClient.refresh_gql_endpoints()` — refresh using the session cookies.
- Client retries once when an endpoint returns 404 / “Query does not exist” (passing its cookies to refresh).
- Env `XACTIONS_NO_GQL_REFRESH=1` to disable network refresh in tests/CI.

### Added — Features
- **`build_search_query()`**: operators `from:`, `to:`, `since:`, `until:`, `min_faves:`, `lang:`, `filter:media`, `-filter:retweets`, etc.
- **CLI `search`**: flags `--from`, `--to`, `--since`, `--until`, `--min-faves`, `--min-retweets`, `--lang`, `--exclude-retweets`, `--exclude-replies`, `--media`.
- **`post_thread()` / CLI `thread` / MCP `x_post_thread`**: tweet threads by chaining replies.
- **`compare_accounts()` / CLI `compare` / MCP `x_compare_accounts`**: side-by-side metrics for two accounts.
- MCP `x_build_search_query`.

### Added — Rate limiting + pagination
- **Proactive throttle**: client stores `x-rate-limit-remaining` / `x-rate-limit-reset` per endpoint and waits *before* the request when remaining=0 (instead of only reacting to 429).
- **`max_rate_limit_wait`** configurable on `TwitterClient` (default 60s); 429 waits are capped with the same value.
- `client.rate_limit_status()` for inspection.
- **Larger page sizes**: Followers/Following 100, engagement 50, tweets/home 40 (search stays at 20 due to API limits).

### Added — Cookie security
- Module `xactions/security.py`: `redact_cookies` / `redact_in_text` (never print values).
- CLI: non-blocking warning if cookies are passed with `--cookies` (shell history risk).
- CLI: warning if `--cookies-file` is world-readable on Unix (suggests `chmod 600`).
- CLI error messages redact `auth_token=` / `ct0=` when present.
- Security notes in README.

### Changed (BREAKING for imports)
- Code now lives in the installable package `src/xactions/` (was loose folders `src/scraper`, `src/actions`, `src/analytics`, `src/storage`, `src/mcp_tools` + `cli/`).
- **Migration guide:**
  - `from src.scraper.client import TwitterClient` → `from xactions.client import TwitterClient` (or `from xactions import TwitterClient`)
  - `from src.scraper.scrapers import search_tweets` → `from xactions.scrapers import search_tweets` (or from `xactions`)
  - `from src.actions.actions import like_tweet` → `from xactions.actions import like_tweet`
  - `from cli.xactions import cli` → `from xactions.cli import cli`
  - MCP: `python src/mcp_tools/server.py` → `python -m xactions.mcp_server`
- CLI entry point: `xactions = xactions.cli:cli` (the `xactions` command name is unchanged).
- Removed all `sys.path.insert` hacks.
- `pyproject.toml`: packages under `src/`, pytest `pythonpath`, ruff `src`.

### Added
- MIT `LICENSE` at the repo root.
- `py.typed` in the `xactions` package (PEP 561).
- `xactions/__init__.py` public API (`__all__`, `__version__`).
- README updated for the new structure and import examples.
- MCP compatible with `mcp` 2.x (`MCPServer`) and 1.x (`FastMCP`).

### Fixed
- `bulk_unfollow.on_progress` typed as `Callable[[int, int, str], None]` (was invalid `callable`).
- `post_tweet` extracts `tweet_id` from more GraphQL response shapes (`rest_id`, `legacy.id_str`, `TweetWithVisibilityResults`).
- `validate_cookies`: uses GraphQL (`HomeLatestTimeline`) instead of deprecated REST `verify_credentials`.
- CLI `post` prints the API error message (was only “Could not publish”).
- Live test: validate/post/delete OK; thread limited by X daily tweet quota (error 344), not a client bug.

### Tests
- **78 passing** (+38 since v1.4.0): packaging, GraphQL refresh, security, rate-limit, B5 features.

## v1.4.0 — 2026-08-17

### Fixed
- `TwitterClient.close()`: the synchronous close path was inverted and failed inside a running loop; it now schedules close without blocking.
- Mutations (like, tweet, unfollow, bookmark…) are no longer retried on network errors — a timeout after the server processed the request could duplicate the action.
- CSRF token (`ct0`) is refreshed automatically when Twitter rotates it via `Set-Cookie` on the response.
- `search_tweets`: a 403 block with no results now raises `ForbiddenError` (previously returned an empty list silently); partial results are returned with a warning.
- `bulk_unfollow`: logs each individual failure instead of swallowing it.
- MCP server: changing cookies now `aclose`s the previous client (sockets used to leak until GC).
- `scrape_profile`: suspended/unavailable users raise a clear `NotFoundError` instead of crashing the CLI with `AttributeError`.

### Added
- Headers `x-client-uuid` and `x-client-transaction-id` on all requests (current GraphQL compatibility, same as twikit).
- MCP `x_bulk_unfollow_non_followers`: `dry_run` parameter to preview without executing.
- SQLite: `PRAGMA journal_mode=WAL` + `busy_timeout` for safe concurrent use.
- CLI refactored with `@with_client` decorator (~100 lines less boilerplate); version read from `importlib.metadata` (single source: `pyproject.toml`).
- CI: matrix with `windows-latest` in addition to `ubuntu-latest`.
- Tests: 40 passing (mutation no-retry, ct0 refresh, `close()` in loop, blocked search, CLI with `CliRunner`).

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
