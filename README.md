# ⚡ xactions-py

**X/Twitter automation toolkit — Python port of [XActions](https://github.com/nirholas/XActions).**  
No npm. No Puppeteer. Just `httpx` + Twitter/X internal GraphQL API.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Dependencies](https://img.shields.io/badge/deps-3-brightgreen?style=flat-square)
![npm free](https://img.shields.io/badge/npm-free-red?style=flat-square)
![Tests](https://img.shields.io/badge/tests-40%20passing-brightgreen?style=flat-square)
![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue?style=flat-square)

---

## Why this project?

The original XActions is great but depends on npm, which has been the target of [massive supply chain attacks in 2025-2026](https://unit42.paloaltonetworks.com/npm-supply-chain-attack/) (Shai-Hulud worm, TanStack compromise, etc.). This Python port eliminates that attack surface entirely.

| | XActions (original) | xactions-py |
|---|---|---|
| Runtime | Node.js + npm | Python 3.10+ |
| Direct dependencies | ~100+ (npm) | **3** (httpx, click, python-dotenv) |
| Supply chain risk | ⚠️ High | ✅ Minimal |
| Headless browser | Puppeteer required | ❌ Not needed |
| MCP server | ✅ | ✅ |
| CLI | ✅ | ✅ |

---

## What's new in v1.5.0

- **📦 Paquete instalable real**: código en `src/xactions/`, imports `from xactions import ...`, sin `sys.path`
- **🔑 API pública unificada**: `TwitterClient`, scrapers, actions y wrappers sync desde un solo import
- **🔄 GraphQL auto-refresh**: si un queryId se rompe, el cliente reintenta tras refrescar IDs (bundle logueado → anónimo → twikit) — `xactions gql-status` / `xactions gql-refresh`
- **📜 LICENSE MIT** y marcador `py.typed` (soporte de tipos estáticos)
- **🖥️ CLI/MCP**: `xactions ...` y `python -m xactions.mcp_server` (ya no `python cli/xactions.py`)
- **🤖 MCP 2.x**: compatible con `mcp>=2` (`MCPServer`) y `mcp` 1.x (`FastMCP`)

> **Migración desde ≤1.4.x:** `from src.scraper...` / `from src.actions...` / `from cli.xactions import cli` → `from xactions...` / `from xactions.cli import cli`. El comando instalado sigue siendo `xactions`.

<details>
<summary>v1.4.0 changes</summary>

- **🛡️ Seguridad anti-duplicados**: las mutations ya no se reintentan ante errores de red (un timeout no puede duplicar un like/tweet)
- **🔑 CSRF auto-refresh**: `ct0` se actualiza solo cuando X lo rota en sesiones largas
- **🖥️ Headers modernos**: `x-client-uuid` + `x-client-transaction-id` en todas las peticiones
- **🚨 Errores claros**: búsqueda bloqueada (403) falla con mensaje explícito; cuentas suspendidas devuelven `NotFoundError` descriptivo
- **🧹 CLI refactorizado**: decorador `@with_client` (-~100 líneas de boilerplate), versión desde `importlib.metadata`
- **🗄️ SQLite concurrente**: WAL + `busy_timeout` para trackear desde varios procesos
- **🔍 MCP `dry_run`**: `x_bulk_unfollow_non_followers` permite previsualizar sin ejecutar
- **🪟 CI en Windows**: matriz con `windows-latest` además de Linux
- **🧪 40 tests** (8 nuevos: mutation no-retry, ct0 refresh, `close()` en loop, CLI)

</details>

<details>
<summary>v1.3.0 changes</summary>

- **📊 `analyze`**: engagement analytics for any account — averages, engagement rate (followers & views), top tweets, best hours/days to post
- **📈 `track` / `history`**: SQLite metric snapshots over time (followers delta, tweet history) — pure stdlib, zero new deps
- **👥 Multi-account pool**: `--cookies-file` with one cookie per line rotates accounts automatically on rate limits or dead cookies
- **📎 Media upload**: `post "text" --media photo.jpg` (up to 4 images)
- **🔁 Parallel non-followers**: followers + following fetched concurrently (~2x faster)
- **⚡ user_id cache**: repeated lookups no longer hit the profile endpoint
- **🤖 Auto `.env`**: CLI and MCP server load `.env` automatically
- **📤 NDJSON export**: `--ndjson` alongside `--csv` and `--output`
- **🧪 CI**: GitHub Actions (ruff + pytest on Python 3.10–3.13), 32 tests passing

</details>

<details>
<summary>v1.2.0 changes</summary>

- Persistent `httpx.AsyncClient` with connection pooling, retries + rate-limit aware backoff
- New scrapers: replies, likers, retweeters, user likes, bookmarks, home timeline, trends
- Actions: `create_bookmark` / `delete_bookmark`; `validate_cookies()`
- CLI: `--cookies-file`, `--csv`, `replies`, `likers`, `retweeters`, `likes`, `bookmarks`, `home`, `trends`, `bookmark`, `unbookmark`, `validate`
- pytest + respx suite; GraphQL query IDs synced with twikit

</details>

---

## Installation

```bash
git clone https://github.com/mamboyepez17/xactions-py
cd xactions-py
pip install -e .
# Optional: MCP server + dev tools
pip install -e ".[mcp,dev]"
```

With virtualenv (recommended on servers):

```bash
# Linux / macOS
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Windows (PowerShell)
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e .
```

---

## Configuration

Get your cookies from **x.com → DevTools (F12) → Application → Cookies → x.com**:
- `auth_token` — required for write actions (like, follow, tweet)
- `ct0` — CSRF token, required for all authenticated requests

```bash
cp .env.example .env
# Fill in your values in .env — it loads automatically (v1.3.0+)

# Or export directly:
export TWITTER_COOKIES="auth_token=YOUR_TOKEN; ct0=YOUR_CT0"
```

> **Note:** Use the full `ct0` value — the client handles CSRF token matching automatically.

### Multi-account pool (v1.3.0)

Put several accounts in a file, **one cookie string per line**, and the CLI rotates
them automatically when one hits a rate limit or dies:

```bash
# cookies.txt
auth_token=ACCOUNT1_TOKEN; ct0=ACCOUNT1_CT0
auth_token=ACCOUNT2_TOKEN; ct0=ACCOUNT2_CT0

xactions search "crypto" --cookies-file cookies.txt --limit 200
xactions validate --cookies-file cookies.txt   # checks every account
```

---

## Usage

### Sync wrappers (easiest way)

```python
from xactions import search_tweets_sync, scrape_profile_sync

cookies = "auth_token=xxx; ct0=yyy"

# Search tweets with engagement (mode="Top")
tweets = search_tweets_sync(cookies, "crypto Colombia", limit=20, mode="Top")
for t in tweets:
    print(f"[{t['likes']} likes, {t['retweets']} RTs] {t['text'][:60]}")
    print(f"  Author: @{t['author']['username']} ({t['author']['followers']} followers)")

# Get user profile
profile = scrape_profile_sync(cookies, "elonmusk")
print(f"@{profile['username']} — {profile['followers']} followers")
```

### Async API

```python
import asyncio
from xactions import TwitterClient, scrape_profile, search_tweets

async def main():
    async with TwitterClient(cookies="auth_token=xxx; ct0=yyy") as client:
        tweets = await search_tweets(client, "AI", limit=50, mode="Top")
        profile = await scrape_profile(client, "elonmusk")
        print(profile["username"], len(tweets))

asyncio.run(main())
```

### CLI

```bash
# Tras pip install -e . el comando es `xactions` (o python -m xactions.cli)
xactions profile elonmusk
xactions profile elonmusk --csv profile.csv

# Validate cookies
xactions validate
xactions validate --cookies-file cookies.txt

# Followers / Following
xactions followers elonmusk --limit 100 --table
xactions following elonmusk --output following.json

# Who doesn't follow you back
xactions non-followers YOUR_USERNAME --table

# Tweets and search
xactions tweets elonmusk --limit 50 --table
xactions search "artificial intelligence" --mode Top

# Engagement & conversation
xactions replies 1234567890 --limit 30 --table
xactions likers 1234567890 --limit 100 --csv likers.csv
xactions retweeters 1234567890 --limit 100
xactions likes elonmusk --limit 50

# Authenticated-only content
xactions bookmarks --limit 50 --table
xactions home --limit 50 --table
xactions trends --table

# Analytics & tracking
xactions analyze elonmusk --limit 100
xactions track elonmusk          # snapshot to SQLite
xactions history elonmusk        # follower evolution

# Export formats
xactions tweets elonmusk --csv tweets.csv
xactions tweets elonmusk --ndjson tweets.ndjson

# Write actions (require auth_token)
xactions post "Hello from xactions-py 🐍"
xactions post "With image" --media photo.jpg --media meme.png
xactions like 1234567890
xactions unlike 1234567890
xactions bookmark 1234567890
xactions unbookmark 1234567890
xactions follow jack
xactions unfollow jack

# Bulk unfollow non-followers
xactions bulk-unfollow YOUR_USERNAME --dry-run   # preview first!
xactions bulk-unfollow YOUR_USERNAME --limit 200 --delay 2.5
```

---

## Tweet data format

Each tweet returned by `search_tweets` / `search_tweets_sync` contains:

```python
{
    "id": "1234567890",
    "text": "Full tweet text here...",
    "author": {
        "id": "123", "username": "user", "name": "Name",
        "followers": 50000, "following": 200, "tweets_count": 5000,
        "verified": True, "avatar": "https://...",
    },
    "created_at": "Mon Jun 21 12:00:00 +0000 2026",
    "likes": 77815,
    "retweets": 17709,
    "replies": 2940,
    "quotes": 150,
    "views": 500000,
    "bookmarks": 42,
    "lang": "es",
    "is_reply": False,
    "is_retweet": False,
    "is_quote": False,
    "media": [{"type": "photo", "url": "https://..."}],
    "url": "https://x.com/i/web/status/1234567890",
}
```

---

## MCP Server (for AI agents)

Works with Claude Desktop, any MCP-compatible agent, or local agents like [OpenClaw](https://openclaw.ai).

```bash
TWITTER_COOKIES="auth_token=xxx; ct0=yyy" python -m xactions.mcp_server
```

### Claude Desktop config (`claude_desktop_config.json`):

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

### Available MCP tools

| Tool | Description | Auth required |
|---|---|---|
| `x_set_cookies` | Configure session at runtime | No |
| `x_validate_cookies` | Check if the session is valid | No |
| `x_get_profile` | Get user profile | No |
| `x_get_followers` | List followers | No* |
| `x_get_following` | List following | No* |
| `x_get_non_followers` | Who doesn't follow you back | No* |
| `x_get_tweets` | Recent tweets from a user | No |
| `x_get_user_likes` | Tweets liked by a user | No |
| `x_search_tweets` | Search tweets by query | No |
| `x_get_tweet_replies` | Replies/conversation of a tweet | No |
| `x_get_tweet_favoriters` | Users who liked a tweet | No |
| `x_get_tweet_retweeters` | Users who retweeted a tweet | No |
| `x_get_bookmarks` | Authenticated user's bookmarks | ✅ Yes |
| `x_get_home_timeline` | Authenticated user's home timeline | ✅ Yes |
| `x_get_trends` | Trending topics | No |
| `x_analyze_user` | Engagement analytics for a user | No |
| `x_post_tweet` | Post a tweet | ✅ Yes |
| `x_delete_tweet` | Delete a tweet | ✅ Yes |
| `x_like_tweet` | Like a tweet | ✅ Yes |
| `x_unlike_tweet` | Unlike a tweet | ✅ Yes |
| `x_retweet` | Retweet | ✅ Yes |
| `x_bookmark_tweet` | Bookmark a tweet | ✅ Yes |
| `x_unbookmark_tweet` | Remove a bookmark | ✅ Yes |
| `x_follow_user` | Follow a user | ✅ Yes |
| `x_unfollow_user` | Unfollow a user | ✅ Yes |
| `x_bulk_unfollow_non_followers` | Bulk unfollow non-followers | ✅ Yes |

*Some relationship endpoints require auth for private accounts or large volumes.

---

## Project structure

```
xactions-py/
├── src/
│   └── xactions/           # paquete instalable
│       ├── __init__.py     # API pública (TwitterClient, scrapers, actions…)
│       ├── client.py       # TwitterClient — async HTTP with httpx
│       ├── pool.py         # ClientPool — multi-account rotation
│       ├── scrapers.py     # profile, followers, tweets, search… + sync wrappers
│       ├── actions.py      # like, follow, tweet, bookmark, media, bulk_unfollow
│       ├── analyzer.py     # engagement analytics (pure stdlib)
│       ├── db.py           # SQLite metric tracking
│       ├── gql_refresh.py  # auto-refresh de GraphQL query IDs
│       ├── cli.py          # CLI (Click) → entry point `xactions`
│       ├── mcp_server.py   # MCP server (mcp 2.x MCPServer / 1.x FastMCP)
│       └── py.typed
├── tests/                  # pytest + respx (40 tests)
├── .github/workflows/
│   └── ci.yml              # ruff + pytest on 3.10–3.13
├── Implementation_Plan/    # plan de trabajo v1.5.0
├── .env.example
├── .gitignore
├── LICENSE
├── pyproject.toml
├── CHANGELOG.md
└── README.md
```

---

## Technical Notes

### Search modes

| Mode | Description | Use case |
|---|---|---|
| `"Top"` (default) | Tweets with most engagement (likes, RTs) | Trend analysis, finding popular content |
| `"Latest"` | Most recent tweets | Real-time monitoring, news |

### GraphQL POST vs GET

Twitter's GraphQL API uses **GET** for most read queries but requires **POST** for some endpoints:

| Endpoint | Method | Notes |
|---|---|---|
| `UserByScreenName` | GET | Profile lookup |
| `UserTweets` | GET | User timeline |
| `Followers` | POST | Follower list |
| `SearchTimeline` | POST | Tweet search |
| Mutations (like, tweet, etc.) | POST | All write operations |

### GraphQL Query IDs

Twitter's internal query IDs change when they deploy new JS bundles. v1.5.0 mitigates this:

1. **Auto-refresh** — on a stale query (HTTP 404 / “Query does not exist”), the client refreshes IDs once and retries.
2. **Manual** — `xactions gql-refresh` (or `gql-status` to inspect the cache).
3. Cache lives at `~/.xactions/gql_endpoints.json`.
4. Discovery multi-fuente: bundle logueado de X (si hay cookies) → bundle anónimo → [twikit `gql.py`](https://github.com/d60/twikit/blob/main/twikit/client/gql.py) como fallback.

If an endpoint still fails after refresh, check twikit or update `src/xactions/client.py` defaults.

---

## Tested Endpoints

All endpoints tested and working:

| Command | Status | Notes |
|---|---|---|
| `profile` | ✅ | Works with GET |
| `tweets` | ✅ | Works with GET |
| `search` (Top) | ✅ | Returns tweets with engagement metrics |
| `search` (Latest) | ✅ | Returns most recent tweets |
| `followers` | ✅ | Requires POST |
| `following` | ✅ | Works with GET |
| `non-followers` | ✅ | Combines followers + following |
| `replies` | ✅ | Via TweetDetail |
| `likers` | ✅ | Via Favoriters |
| `retweeters` | ✅ | Via Retweeters |
| `likes` | ✅ | User's public likes |
| `bookmarks` | ✅ | Requires auth |
| `home` | ✅ | Requires auth |
| `trends` | ✅ | Via REST trends/place |
| `validate` | ✅ | Via verify_credentials |
| `bulk-unfollow` | ✅ | Works with --dry-run |
| `post` | ✅ | Subject to daily tweet limits |
| `like` | ✅ | Requires valid tweet ID |
| `bookmark` | ✅ | Requires auth |

---

## Used by

- [TrendScope](https://github.com/mamboyepez17/trendscope) — Universal trend intelligence infrastructure (includes xactions-py as local module)

---

## Credits

- Inspired by [XActions](https://github.com/nirholas/XActions) by [@nichxbt](https://x.com/nichxbt)
- GraphQL query IDs referenced from [twikit](https://github.com/d60/twikit) and [twitter-scraper](https://github.com/the-convocation/twitter-scraper)

---

## License

MIT — use it, modify it, share it.

> ⚠️ **Disclaimer:** For educational and research purposes. Use responsibly and respect Twitter/X Terms of Service. Start with small volumes to avoid rate limits.
