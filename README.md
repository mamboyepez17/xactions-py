# ⚡ xactions-py

**X/Twitter automation toolkit — Python port of [XActions](https://github.com/nirholas/XActions).**  
No npm. No Puppeteer. Just `httpx` + Twitter/X internal GraphQL API.

![Python](https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Dependencies](https://img.shields.io/badge/deps-3-brightgreen?style=flat-square)
![npm free](https://img.shields.io/badge/npm-free-red?style=flat-square)

---

## Why this project?

The original XActions is great but depends on npm, which has been the target of [massive supply chain attacks in 2025-2026](https://unit42.paloaltonetworks.com/npm-supply-chain-attack/) (Shai-Hulud worm, TanStack compromise, etc.). This Python port eliminates that attack surface entirely.

| | XActions (original) | xactions-py |
|---|---|---|
| Runtime | Node.js + npm | Python 3.11+ |
| Direct dependencies | ~100+ (npm) | **3** (httpx, mcp, click) |
| Supply chain risk | ⚠️ High | ✅ Minimal |
| Headless browser | Puppeteer required | ❌ Not needed |
| MCP server | ✅ | ✅ |
| CLI | ✅ | ✅ |

---

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/xactions-py
cd xactions-py
pip install httpx "mcp[cli]" click
```

With virtualenv (recommended on servers):

```bash
# Linux / macOS
python3 -m venv .venv && source .venv/bin/activate
pip install httpx "mcp[cli]" click

# Windows (PowerShell)
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install httpx "mcp[cli]" click
```

---

## Configuration

Get your cookies from **x.com → DevTools (F12) → Application → Cookies → x.com**:
- `auth_token` — required for write actions (like, follow, tweet)
- `ct0` — CSRF token, required for all authenticated requests

```bash
cp .env.example .env
# Fill in your values in .env

# Or export directly:
export TWITTER_COOKIES="auth_token=YOUR_TOKEN; ct0=YOUR_CT0"
```

> **Note:** Use the full `ct0` value — the client handles CSRF token matching automatically.

---

## CLI Usage

```bash
# Profile
python cli/xactions.py profile elonmusk

# Followers / Following
python cli/xactions.py followers elonmusk --limit 100 --table
python cli/xactions.py following elonmusk --output following.json

# Who doesn't follow you back
python cli/xactions.py non-followers YOUR_USERNAME --table

# Tweets and search
python cli/xactions.py tweets elonmusk --limit 50 --table
python cli/xactions.py search "artificial intelligence" --mode Latest

# Write actions (require auth_token in TWITTER_COOKIES)
python cli/xactions.py post "Hello from xactions-py 🐍"
python cli/xactions.py like 1234567890
python cli/xactions.py follow jack
python cli/xactions.py unfollow jack

# Bulk unfollow non-followers
python cli/xactions.py bulk-unfollow YOUR_USERNAME --dry-run   # preview first!
python cli/xactions.py bulk-unfollow YOUR_USERNAME --limit 200 --delay 2.5
```

---

## MCP Server (for AI agents)

Works with Claude Desktop, any MCP-compatible agent, or local agents like [OpenClaw](https://openclaw.ai).

```bash
TWITTER_COOKIES="auth_token=xxx; ct0=yyy" python src/mcp_tools/server.py
```

### Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "xactions-py": {
      "command": "python3",
      "args": ["/path/to/xactions-py/src/mcp_tools/server.py"],
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
| `x_get_profile` | Get user profile | No |
| `x_get_followers` | List followers | No* |
| `x_get_following` | List following | No* |
| `x_get_non_followers` | Who doesn't follow you back | No* |
| `x_get_tweets` | Recent tweets from a user | No |
| `x_search_tweets` | Search tweets by query | No |
| `x_post_tweet` | Post a tweet | ✅ Yes |
| `x_delete_tweet` | Delete a tweet | ✅ Yes |
| `x_like_tweet` | Like a tweet | ✅ Yes |
| `x_unlike_tweet` | Unlike a tweet | ✅ Yes |
| `x_retweet` | Retweet | ✅ Yes |
| `x_follow_user` | Follow a user | ✅ Yes |
| `x_unfollow_user` | Unfollow a user | ✅ Yes |
| `x_bulk_unfollow_non_followers` | Bulk unfollow non-followers | ✅ Yes |

*Some relationship endpoints require auth for private accounts or large volumes.

---

## Project structure

```
xactions-py/
├── src/
│   ├── scraper/
│   │   ├── client.py       # TwitterClient — async HTTP with httpx
│   │   └── scrapers.py     # profile, followers, tweets, search
│   ├── actions/
│   │   └── actions.py      # like, follow, tweet, bulk_unfollow
│   └── mcp_tools/
│       └── server.py       # MCP server (FastMCP)
├── cli/
│   └── xactions.py         # CLI (Click)
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## Technical Notes

### GraphQL POST vs GET

Twitter's GraphQL API uses **GET** for most read queries but requires **POST** for some endpoints:

| Endpoint | Method | Notes |
|---|---|---|
| `UserByScreenName` | GET | Profile lookup |
| `UserTweets` | GET | User timeline |
| `Followers` | POST | Follower list |
| `SearchTimeline` | POST | Tweet search |
| Mutations (like, tweet, etc.) | POST | All write operations |

This is handled automatically by the `"method": "POST"` flag in the endpoint config.

### GraphQL Query IDs

Twitter's internal query IDs change when they deploy new JS bundles. If an endpoint stops working:

1. Fetch `https://x.com` and find the main JS bundle URL
2. Search for `queryId:"...",operationName:"EndpointName"`
3. Update `src/scraper/client.py`

Or reference [twikit/gql.py](https://github.com/d60/twikit/blob/main/twikit/client/gql.py) which keeps them up to date.

---

## Tested Endpoints

All endpoints tested and working:

| Command | Status | Notes |
|---|---|---|
| `profile` | ✅ | Works with GET |
| `tweets` | ✅ | Works with GET |
| `search` | ✅ | Requires POST |
| `followers` | ✅ | Requires POST |
| `following` | ✅ | Works with GET |
| `non-followers` | ✅ | Combines followers + following |
| `bulk-unfollow` | ✅ | Works with --dry-run |
| `post` | ✅ | Subject to daily tweet limits |
| `like` | ✅ | Requires valid tweet ID |

---

## Credits

- Inspired by [XActions](https://github.com/nirholas/XActions) by [@nichxbt](https://x.com/nichxbt)
- GraphQL query IDs referenced from [twikit](https://github.com/d60/twikit) and [twitter-scraper](https://github.com/the-convocation/twitter-scraper)

---

## License

MIT — use it, modify it, share it.

> ⚠️ **Disclaimer:** For educational and research purposes. Use responsibly and respect Twitter/X Terms of Service. Start with small volumes to avoid rate limits.
