# Changelog

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
