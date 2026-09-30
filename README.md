# ⚡ xactions-py

**X/Twitter automation toolkit in pure Python** — inspired by [XActions](https://github.com/nirholas/XActions), built lean: **no npm, no Puppeteer**, just `httpx` + X's internal GraphQL API.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Dependencies](https://img.shields.io/badge/deps-3-brightgreen?style=flat-square)
![npm free](https://img.shields.io/badge/npm-free-red?style=flat-square)
[![CI](https://github.com/mamboyepez17/xactions-py/actions/workflows/ci.yml/badge.svg)](https://github.com/mamboyepez17/xactions-py/actions/workflows/ci.yml)

---

## Why this project?

XActions (JS) is a large platform (browser scripts, website, extension). **xactions-py** keeps the same idea — automate X without the official API — but as a **small, testable Python library + CLI + MCP server** with a 3-dependency runtime.

| | XActions (JS) | xactions-py |
|---|---|---|
| Runtime | Node + npm | **Python 3.10+** |
| Direct deps | ~100+ | **3** (httpx, click, python-dotenv) |
| Headless browser | Often Puppeteer | **Not needed** |
| CLI + MCP | ✅ | ✅ |
| Safety extras | caps, drafts | **caps, drafts, doctor, cookie redaction, signed webhooks** |

---

## Features

- **Read:** profiles, tweets, replies, likes, followers/following, non-followers, search with advanced operators, home timeline, bookmarks, trends, X Lists.
- **Write:** post (text, up to 4 images, or 1 video/GIF with chunked upload), threads, like/retweet/bookmark, follow/unfollow, bulk-unfollow, Lists, keyword `engage`.
- **Scheduling:** queue tweets for later with `xactions schedule` (cron-friendly).
- **Analytics:** engagement stats, account comparison, sentiment, SQLite tracking, and Markdown/HTML reports with a follower-history chart.
- **Monitoring:** `watch` for new tweets, follower snapshots and unfollower diffs, media download, JSON pipelines with (optionally signed) webhooks.
- **Export:** JSON, CSV, NDJSON or a terminal table on every command that returns rows.
- **Safety:** daily write caps per account, human approval gate for agent writes, dry-runs, cookie redaction, `doctor` health check.
- **AI agents:** MCP server with tool groups you can switch on and off.
- **Resilience:** multi-account pool, proactive rate-limit throttling, GraphQL query IDs that heal themselves when X rotates them.

---

## Install

```bash
git clone https://github.com/mamboyepez17/xactions-py
cd xactions-py
pip install -e .
# Optional: MCP + dev tools
pip install -e ".[mcp,dev]"
```

Virtualenv (recommended):

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows
.venv\Scripts\Activate.ps1
pip install -e ".[mcp,dev]"
```

---

## Configure cookies

From **x.com → DevTools (F12) → Application → Cookies → x.com**:

- `auth_token` — required for writes (like, follow, tweet)
- `ct0` — CSRF token for authenticated requests
- `twid` — optional; lets `validate` report your own user ID and handle without an extra lookup

```bash
cp .env.example .env
# TWITTER_COOKIES="auth_token=...; ct0=..."
```

Or:

```bash
# file: one cookie string per line, or Netscape / Cookie-Editor JSON / Playwright storageState
xactions validate --cookies-file cookies.txt

# from an installed browser profile (Chrome/Chromium/Brave/Edge/Firefox)
xactions profile nasa --from-browser chrome
```

**Security:** prefer `.env` or `--cookies-file` over `--cookies` on the command line. The CLI redacts cookie values in errors/logs and warns on world-readable cookie files (Unix `chmod 600`).

### Multi-account pool

```bash
# cookies.txt — one account per line
auth_token=A1; ct0=B1
auth_token=A2; ct0=B2
xactions search "ai" --cookies-file cookies.txt
```

---

## Quick start (CLI)

The installed command is **`xactions`** (also `python -m xactions.cli`).

```bash
xactions doctor                 # health: cookies, GraphQL cache, caps, DB
xactions validate               # check session
xactions profile nasa
xactions tweets nasa --limit 20 --table
xactions search "crypto" --from elonmusk --min-faves 50 --lang es --exclude-retweets
xactions analyze nasa           # engagement stats
xactions report nasa --format md
xactions track nasa && xactions report nasa --format html --out nasa.html  # + follower-history chart
xactions report userA userB --format html --out compare.html
xactions compare userA userB
xactions sentiment "openai" --limit 30
xactions watch "ai" --limit 20   # only new tweets vs last run
```

### Writes (auth required)

```bash
xactions post "Hello from xactions-py"
xactions post "Look at this" --media a.png --media b.jpg   # up to 4 images
xactions post "New demo" --media demo.mp4                  # or 1 video/GIF (chunked upload)
xactions thread "Part 1" "Part 2" "End"
xactions like 1234567890
xactions follow jack
xactions bulk-unfollow YOUR_USER --dry-run
xactions engage "keyword" --like --limit 5 --dry-run
xactions engage "keyword" --like --limit 5 --execute   # daily caps apply
```

### Lists

```bash
xactions lists tweets 1234567890 --limit 30 --table
xactions lists members 1234567890 --csv members.csv
xactions lists create "AI builders" --description "people shipping" --private
xactions lists add 1234567890 @jack       # writes: daily caps + approval gate apply
xactions lists remove 1234567890 @jack
```

MCP: `x_get_list_tweets`, `x_get_list_members` (read) and `x_create_list`,
`x_add_list_member`, `x_remove_list_member` (write, draft-gated).

### Scheduled tweets

```bash
xactions schedule add "Launch day 🚀" --at "2026-10-01T09:00"   # local time
xactions schedule add "Reminder" --at +2h                        # or +30m / +1d
xactions schedule list [--all]
xactions schedule cancel 3
xactions schedule run            # publish everything due (daily caps apply)
xactions schedule run --every 60 # or keep running
# cron: */5 * * * * xactions schedule run
```

Posts live in the tracking SQLite DB. A post is claimed atomically before
publishing, so overlapping runs never double-post; one interrupted mid-publish
stays `posting` for you to check rather than being retried.

### Daily write caps

Every write is counted per account over a rolling 24 hours in `~/.xactions/write_caps.json`,
and a write that would go over budget is refused **before** it reaches X.

| Operation | Default / 24h | Operation | Default / 24h |
|---|---:|---|---:|
| `tweet` | 50 | `follow` / `unfollow` | 50 / 50 |
| `thread_tweet` (each tweet of a thread) | 50 | `bookmark` / `unbookmark` | 100 / 100 |
| `like` / `unlike` | 100 / 100 | `delete` | 50 |
| `retweet` / `unretweet` | 50 / 50 | `list_create` / `list_add` / `list_remove` | 10 / 100 / 100 |

- **Changing the limits:** add a `"limits": {"like": 30}` object to `write_caps.json`.
- **Counting:** the budget survives restarts, and each account in a pool has its own.
- **Corrupt file:** if the file is corrupt, writes are refused until you fix or delete it; deleting it resets the budget.
- **Status:** `xactions doctor` shows what has been used.

### Approval gate (MCP / agent safety)

```bash
export XACTIONS_REQUIRE_APPROVAL=1
xactions post "this becomes a draft"
xactions drafts list [--all] [--csv drafts.csv]
xactions drafts approve <id>     # a human runs the write
xactions drafts discard <id>
```

- **MCP:** with the gate on, **every** MCP write tool saves a draft instead of writing. That includes `x_bulk_unfollow_non_followers`, which saves one draft per user to unfollow.
- **CLI:** `post`, `like` and `lists create/add/remove` save drafts too. The other CLI writes run directly, since you are the human at the keyboard.
- **Media:** drafts cannot carry media yet, so `post --media` is refused while the gate is on.

### Data tools

```bash
xactions followers USER --limit 100 --csv f.csv
xactions non-followers USER --table
xactions track USER              # SQLite snapshot
xactions history USER
xactions snapshot-followers USER
xactions unfollowers USER --save # who left since last snapshot
xactions download-media USER --dest ./media
xactions gql-status
xactions gql-refresh --cookies-file cookies.txt
```

**Output formats.** Every command that returns rows takes `-o out.json`, `--csv out.csv` and
`--ndjson out.ndjson`. Besides the read commands, that includes `history`, `compare`,
`sentiment`, `unfollowers`, `schedule list` and `drafts list`. Read commands also take
`--table` to print a table in the terminal:

```bash
xactions history nasa --csv nasa_history.csv
xactions compare userA userB --ndjson compare.ndjson
xactions sentiment "openai" --csv scored.csv
```

`non-followers` and `bulk-unfollow` always read your **full** follower list. If X returns
noticeably fewer followers than your profile shows (under 90%), they stop with an error
instead of listing people who do follow you.

### Pipelines

```json
{
  "name": "hot-ai",
  "steps": [
    {"type": "search", "query": "ai", "limit": 30, "mode": "Latest"},
    {"type": "filter", "min_likes": 10, "exclude_retweets": true},
    {"type": "notify", "message": "hits={count}"},
    {"type": "print", "limit": 5}
  ]
}
```

```bash
xactions pipeline hot-ai.json           # dry-run (no writes)
xactions pipeline hot-ai.json --execute # allow like steps
export XACTIONS_WEBHOOK_URL=https://ntfy.sh/your-topic
```

**Signed webhooks.** Set `XACTIONS_WEBHOOK_SECRET` and every delivery carries
`X-Xactions-Timestamp` and `X-Xactions-Signature: sha256=<hex>`, an HMAC-SHA256 of
`"<timestamp>.<raw body>"`. Verify it on the receiver (rejects forged and replayed calls):

```python
from xactions.notify import verify_signature

ok = verify_signature(secret, request_body_bytes,
                      headers["X-Xactions-Timestamp"], headers["X-Xactions-Signature"])
```

---

## Python API

```python
from xactions import (
    TwitterClient,
    search_tweets_sync,
    scrape_profile_sync,
    search_tweets,
    scrape_profile,
    post_tweet,
    post_thread,
    analyze_tweets,
    compare_accounts,
    build_search_query,
)

# Sync (no asyncio in your code)
cookies = "auth_token=xxx; ct0=yyy"
tweets = search_tweets_sync(cookies, "crypto", limit=20, mode="Top")
profile = scrape_profile_sync(cookies, "nasa")

# Async
import asyncio
from xactions import TwitterClient, search_tweets

async def main():
    async with TwitterClient(cookies=cookies) as client:
        tweets = await search_tweets(client, "ai", limit=10)

asyncio.run(main())
```

Advanced search:

```python
from xactions import build_search_query
q = build_search_query("crypto", from_user="elonmusk", min_faves=100, exclude_retweets=True)
```

Lists, media, multi-account and scheduling:

```python
from xactions import (
    ClientPool, ScheduleStore, create_list, get_list_tweets, list_add_member,
    parse_when, post_tweet, run_due, upload_media,
)

async def demo():
    # A pool rotates accounts on rate limits; it works anywhere a client does.
    async with ClientPool([cookies_a, cookies_b]) as pool:
        tweets = await get_list_tweets(pool, "1234567890", limit=20)

    async with TwitterClient(cookies=cookies) as client:
        media = await upload_media(client, "demo.mp4")        # chunked for video/GIF
        await post_tweet(client, "New demo", media_ids=[media["media_id"]])

        lst = await create_list(client, "AI builders", private=True)
        await list_add_member(client, lst["list_id"], "783214")  # user ID

        store = ScheduleStore()                               # tracking SQLite DB
        store.add("Later!", parse_when("+2h"))
        await run_due(client, store)                          # posts what is due
```

Writes raise `WriteCapExceeded` when a daily cap would be exceeded. Every function that
takes a client accepts anything implementing the `XClient` protocol (`TwitterClient`,
`ClientPool`, or your own fake in tests).

---

## MCP server (AI agents)

```bash
pip install -e ".[mcp]"
TWITTER_COOKIES="auth_token=...; ct0=..." xactions-mcp     # or: python -m xactions.mcp_server
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "xactions-py": {
      "command": "python",
      "args": ["-m", "xactions.mcp_server"],
      "env": {
        "TWITTER_COOKIES": "auth_token=YOUR_TOKEN; ct0=YOUR_CT0"
      }
    }
  }
}
```

### Tool groups

```bash
export XACTIONS_MCP_TOOLS=read,analytics
export XACTIONS_MCP_TOOLS_EXCLUDE=write
```

### Tools

| Group | Tools |
|-------|--------|
| read | `x_get_profile`, `x_get_tweets`, `x_get_user_likes`, `x_search_tweets`, `x_get_tweet_replies`, `x_get_tweet_favoriters`, `x_get_tweet_retweeters`, `x_get_followers`, `x_get_following`, `x_get_non_followers`, `x_get_home_timeline`, `x_get_bookmarks`, `x_get_trends`, `x_get_list_tweets`, `x_get_list_members`, `x_validate_cookies` |
| write | `x_post_tweet`, `x_post_thread`, `x_delete_tweet`, `x_like_tweet`, `x_unlike_tweet`, `x_retweet`, `x_bookmark_tweet`, `x_unbookmark_tweet`, `x_follow_user`, `x_unfollow_user`, `x_bulk_unfollow_non_followers`, `x_create_list`, `x_add_list_member`, `x_remove_list_member` |
| analytics | `x_analyze_user`, `x_compare_accounts`, `x_build_search_query` |
| drafts | `x_list_drafts`, `x_discard_draft` |
| auth | `x_set_cookies` |

With `XACTIONS_REQUIRE_APPROVAL=1`, every MCP write tool (including `x_bulk_unfollow_non_followers`) saves a draft instead of hitting X. Drafts can only be released by a human with `xactions drafts approve <id>` — the MCP server deliberately has no approve tool.

The tool-group filter is applied when the server module is imported, so it holds for `python -m xactions.mcp_server`, the `xactions-mcp` script and `mcp run`. If a filter is set but cannot be applied, the server refuses to start.

Compatible with **mcp 2.x** (`MCPServer`) and **1.x** (`FastMCP`).

---

## GraphQL resilience

X rotates internal query IDs. v1.5+ mitigates this:

1. **Auto-refresh** on 404 / “Query does not exist” (logged-in bundle → anonymous → twikit fallback)
2. Manual: `xactions gql-refresh` / `xactions gql-status`
3. Cache: `~/.xactions/gql_endpoints.json`
4. Disable in CI/tests: `XACTIONS_NO_GQL_REFRESH=1`

`x-client-transaction-id` is bound to method+path (`XACTIONS_TXID_MODE=uuid` for legacy uuid4).

---

## Environment variables

| Variable | Purpose |
|---|---|
| `TWITTER_COOKIES` | Session cookie string; several accounts separated by `\|\|\|` |
| `TWITTER_PROXY` | `http://host:port` or `socks5://host:port` |
| `XACTIONS_HOME` | Base folder for caps, drafts, watch state and the GraphQL cache (default `~/.xactions`) |
| `XACTIONS_DB` | Tracking/scheduling SQLite DB (default `~/.xactions/xactions.db`) |
| `XACTIONS_REQUIRE_APPROVAL` | `1` turns writes into drafts (see *Approval gate*) |
| `XACTIONS_WEBHOOK_URL` | Where `watch`/pipeline notifications are POSTed |
| `XACTIONS_WEBHOOK_SECRET` | Signs webhook deliveries (HMAC-SHA256) |
| `XACTIONS_MCP_TOOLS` / `XACTIONS_MCP_TOOLS_EXCLUDE` | MCP tool groups to advertise / hide |
| `XACTIONS_NO_GQL_REFRESH` | `1` disables the network GraphQL refresh (CI/tests) |
| `XACTIONS_TXID_MODE` | `uuid` for the legacy `x-client-transaction-id` |

`.env` in the working directory is loaded automatically.

---

## Development

```bash
pip install -e ".[mcp,dev]"
pre-commit install                # ruff + mypy + hygiene hooks on every commit
pytest --cov                      # coverage floor: 55%
ruff check src tests && mypy src  # same checks CI runs
```

CI runs on Linux and Windows with Python 3.10 to 3.13. Tests never touch the network or
your real `~/.xactions`.

---

## Releasing

1. Bump `version` in `pyproject.toml` and move the CHANGELOG `Unreleased` notes under it.
2. Tag and push: `git tag v1.9.0 && git push origin v1.9.0`.
3. `.github/workflows/release.yml` runs the tests, builds, checks and publishes to PyPI.

One-time setup: on PyPI, add a *Trusted Publisher* for this repo (workflow `release.yml`,
environment `pypi`), and create the `pypi` environment under the repo's GitHub settings.
No API token is stored anywhere.

---

## Project layout

```
src/xactions/
  client.py           # HTTP + GraphQL + rate-limit throttle, XClient protocol
  pool.py             # multi-account ClientPool
  scrapers.py         # profile, tweets, search, followers, lists…
  actions.py          # writes (post, like, follow, lists…) + media upload + caps
  search_query.py     # advanced search query builder
  analyzer.py         # engagement + compare
  report.py           # Markdown/HTML reports + follower chart
  db.py               # SQLite tracking (snapshots)
  schedule.py         # scheduled tweets queue
  pipeline.py         # JSON pipelines
  notify.py           # webhooks (+ HMAC signing)
  watch.py            # deltas + scrape checkpoints
  media.py            # media download + follower snapshots
  caps.py             # daily write budgets
  drafts.py           # approval gate + draft executor
  security.py         # cookie redaction
  browser_cookies.py  # --from-browser
  sentiment.py        # optional lexicon scorer
  gql_refresh.py      # query ID heal
  transaction_id.py   # x-client-transaction-id
  doctor.py           # health check
  mcp_groups.py       # MCP tool filter
  mcp_server.py       # MCP server (`xactions-mcp`)
  cli/                # `xactions` entry point
    _common.py        #   client setup, output writers, tables
    read.py           #   profile, tweets, search, timelines
    analytics.py      #   analyze, track, compare, report, sentiment
    write.py          #   post, like, follow, bulk-unfollow, engage
    monitor.py        #   watch, download-media, unfollowers
    system.py         #   validate, pipeline, gql-*, doctor, drafts
    schedule.py       #   schedule add/list/cancel/run
    lists.py          #   lists tweets/members/create/add/remove
tests/                # pytest + respx
```

---

## Versions (recent)

| Version | Highlights |
|---------|------------|
| **1.9.0** | Scheduled tweets, X Lists, video/GIF upload, signed webhooks, follower-history chart, CSV/NDJSON everywhere, PyPI release workflow; write-safety fixes (caps that persist, full follower list for non-followers, MCP approval gate), English-only codebase |
| **1.8.0** | Sentiment lexicon, `engage` with caps |
| **1.7.0** | `report`, `pipeline`, webhook notify, MCP tool groups |
| **1.6.0** | `doctor`, daily caps, `--from-browser`, drafts, txid, `watch`, media, unfollowers |
| **1.5.0** | Package `src/xactions`, GraphQL auto-refresh, cookie security, rate-limit, search ops, `thread`, `compare` |

See [CHANGELOG.md](CHANGELOG.md) for the full history.

---

## Safety & limits

- Unofficial API: **use responsibly**; respect X Terms of Service.
- Start with small volumes; daily caps and `--dry-run` are on purpose.
- Mutations are **not retried** on network errors (no accidental double-likes).
- Proactive rate-limit waits (`max_rate_limit_wait`).
- Daily caps fail closed, agent writes can require human approval, and scheduled posts are never double-posted.
- A 403 on one resource (protected account, blocked search) does not take an account out of the pool; only expired sessions (401) do.

> ⚠️ Educational / research use. You are responsible for how you use your account.

---

## Credits

- Inspired by [XActions](https://github.com/nirholas/XActions)
- GraphQL IDs referenced from [twikit](https://github.com/d60/twikit)

## License

MIT — see [LICENSE](LICENSE).
