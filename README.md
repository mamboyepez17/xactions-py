# ⚡ xactions-py

**X/Twitter automation toolkit in pure Python** — inspired by [XActions](https://github.com/nirholas/XActions), built lean: **no npm, no Puppeteer**, just `httpx` + X's internal GraphQL API.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Dependencies](https://img.shields.io/badge/deps-3-brightgreen?style=flat-square)
![npm free](https://img.shields.io/badge/npm-free-red?style=flat-square)
![Tests](https://img.shields.io/badge/tests-158%20passing-brightgreen?style=flat-square)
![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue?style=flat-square)

---

## Why this project?

XActions (JS) is a large platform (browser scripts, website, extension). **xactions-py** keeps the same idea — automate X without the official API — but as a **small, testable Python library + CLI + MCP server** with a 3-dependency runtime.

| | XActions (JS) | xactions-py |
|---|---|---|
| Runtime | Node + npm | **Python 3.10+** |
| Direct deps | ~100+ | **3** (httpx, click, python-dotenv) |
| Headless browser | Often Puppeteer | **Not needed** |
| CLI + MCP | ✅ | ✅ |
| Safety extras | caps, drafts | **caps, drafts, doctor, cookie redaction** |

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
xactions report userA userB --format html --out compare.html
xactions compare userA userB
xactions sentiment "openai" --limit 30
xactions watch "ai" --limit 20   # only new tweets vs last run
```

### Writes (auth required)

```bash
xactions post "Hello from xactions-py"
xactions thread "Part 1" "Part 2" "End"
xactions like 1234567890
xactions follow jack
xactions bulk-unfollow YOUR_USER --dry-run
xactions engage "keyword" --like --limit 5 --dry-run
xactions engage "keyword" --like --limit 5 --execute   # daily caps apply
```

**Daily write caps** live in `~/.xactions/write_caps.json` and stop over-budget writes before they hit X.

**Approval gate** (MCP/agent safety):

```bash
export XACTIONS_REQUIRE_APPROVAL=1
xactions post "this becomes a draft"
xactions drafts list
xactions drafts approve <id>
xactions drafts discard <id>
```

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

---

## MCP server (AI agents)

```bash
TWITTER_COOKIES="auth_token=...; ct0=..." python -m xactions.mcp_server
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

### Notable tools

| Group | Tools |
|-------|--------|
| read | `x_get_profile`, `x_search_tweets`, `x_get_followers`, … |
| write | `x_post_tweet`, `x_post_thread`, `x_like_tweet`, `x_follow_user`, … |
| analytics | `x_analyze_user`, `x_compare_accounts`, `x_build_search_query` |
| drafts | `x_list_drafts`, `x_approve_draft`, `x_discard_draft` |

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

## Project layout

```
src/xactions/
  client.py           # HTTP + GraphQL + rate-limit throttle
  scrapers.py         # profile, tweets, search, followers…
  actions.py          # writes (post, like, follow…) + caps
  analyzer.py         # engagement + compare
  report.py           # Markdown/HTML reports
  pipeline.py         # JSON pipelines
  notify.py           # webhooks
  watch.py            # deltas + scrape checkpoints
  caps.py             # daily write budgets
  drafts.py           # approval gate
  security.py         # cookie redaction
  browser_cookies.py  # --from-browser
  sentiment.py        # optional lexicon scorer
  gql_refresh.py      # query ID heal
  mcp_groups.py       # MCP tool filter
  mcp_server.py
  cli.py              # `xactions` entry point
tests/                # pytest + respx
```

---

## Versions (recent)

| Version | Highlights |
|---------|------------|
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

> ⚠️ Educational / research use. You are responsible for how you use your account.

---

## Credits

- Inspired by [XActions](https://github.com/nirholas/XActions)
- GraphQL IDs referenced from [twikit](https://github.com/d60/twikit)

## License

MIT — see [LICENSE](LICENSE).
