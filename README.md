# ⚡ xactions-py

**X/Twitter automation toolkit — Python port of [XActions](https://github.com/nirholas/XActions).**  
No npm. No Puppeteer. Just `httpx` + Twitter/X internal GraphQL API.

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Dependencies](https://img.shields.io/badge/deps-2-brightgreen?style=flat-square)
![npm free](https://img.shields.io/badge/npm-free-red?style=flat-square)
![Tests](https://img.shields.io/badge/tests-pytest%20%2B%20respx-blue?style=flat-square)

---

## Why this project?

The original XActions is great but depends on npm, which has been the target of [massive supply chain attacks in 2025-2026](https://unit42.paloaltonetworks.com/npm-supply-chain-attack/) (Shai-Hulud worm, TanStack compromise, etc.). This Python port eliminates that attack surface entirely.

| | XActions (original) | xactions-py |
|---|---|---|
| Runtime | Node.js + npm | Python 3.10+ |
| Direct dependencies | ~100+ (npm) | **2** (httpx, click) |
| Supply chain risk | ⚠️ High | ✅ Minimal |
| Headless browser | Puppeteer required | ❌ Not needed |
| MCP server | ✅ | ✅ |
| CLI | ✅ | ✅ |

---

## What's new in v1.2.0

- **Persistent HTTP client**: `TwitterClient` now reuses a single `httpx.AsyncClient` with HTTP/2 + connection pooling, dramatically reducing overhead
- **Resilient retries**: automatic exponential backoff for network errors and rate limits (respects `x-rate-limit-reset` and `Retry-After`)
- **New scrapers**: replies, likers, retweeters, user likes, bookmarks, home timeline, trending topics
- **New actions**: `create_bookmark` / `delete_bookmark`
- **Cookie validation**: `validate_cookies()` / `xactions validate` quickly checks if your session works
- **CLI improvements**: `--cookies-file`, `--csv` export, `replies`, `likers`, `retweeters`, `likes`, `bookmarks`, `trends`, `home`, `bookmark`, `unbookmark`, `validate`
- **Tests**: pytest + respx suite covering client retries, auth errors, parsing and timeline extraction
- **Updated GraphQL query IDs**: synced with `twikit` endpoints for higher reliability
- **Consistent defaults**: search CLI and API now default to `mode="Top"`

---

## Installation

```bash
git clone https://github.com/mamboyepez17/xactions-py
cd xactions-py
pip install httpx click
# Optional: for MCP server
pip install "mcp[cli]"
```

With virtualenv (recommended on servers):

```bash
# Linux / macOS
python3 -m venv .venv && source .venv/bin/activate
pip install httpx click

# Windows (PowerShell)
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install httpx click
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

## Usage

### Sync wrappers (v1.1.0 — easiest way)

```python
from src.scraper.scrapers import search_tweets_sync, scrape_profile_sync

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

### Async API (original)

```python
import asyncio
from src.scraper.client import TwitterClient
from src.scraper.scrapers import search_tweets, scrape_profile

async def main():
    client = TwitterClient(cookies="auth_token=xxx; ct0=yyy")
    
    # Search tweets
    tweets = await search_tweets(client, "AI", limit=50, mode="Top")
    
    # Get profile
    profile = await scrape_profile(client, "elonmusk")

asyncio.run(main())
```

### CLI

```bash
# Profile
python cli/xactions.py profile elonmusk
python cli/xactions.py profile elonmusk --csv profile.csv

# Validate cookies
python cli/xactions.py validate
python cli/xactions.py validate --cookies-file cookies.txt

# Followers / Following
python cli/xactions.py followers elonmusk --limit 100 --table
python cli/xactions.py following elonmusk --output following.json

# Who doesn't follow you back
python cli/xactions.py non-followers YOUR_USERNAME --table

# Tweets and search
python cli/xactions.py tweets elonmusk --limit 50 --table
python cli/xactions.py search "artificial intelligence" --mode Top

# Engagement & conversation
python cli/xactions.py replies 1234567890 --limit 30 --table
python cli/xactions.py likers 1234567890 --limit 100 --csv likers.csv
python cli/xactions.py retweeters 1234567890 --limit 100
python cli/xactions.py likes elonmusk --limit 50

# Authenticated-only content
python cli/xactions.py bookmarks --limit 50 --table
python cli/xactions.py home --limit 50 --table
python cli/xactions.py trends --table

# Write actions (require auth_token)
python cli/xactions.py post "Hello from xactions-py 🐍"
python cli/xactions.py like 1234567890
python cli/xactions.py unlike 1234567890
python cli/xactions.py bookmark 1234567890
python cli/xactions.py unbookmark 1234567890
python cli/xactions.py follow jack
python cli/xactions.py unfollow jack

# Bulk unfollow non-followers
python cli/xactions.py bulk-unfollow YOUR_USERNAME --dry-run   # preview first!
python cli/xactions.py bulk-unfollow YOUR_USERNAME --limit 200 --delay 2.5
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
│   ├── scraper/
│   │   ├── client.py       # TwitterClient — async HTTP with httpx
│   │   └── scrapers.py     # profile, followers, tweets, search, replies, bookmarks, trends + sync wrappers
│   ├── actions/
│   │   └── actions.py      # like, follow, tweet, bookmark, bulk_unfollow
│   └── mcp_tools/
│       └── server.py       # MCP server (FastMCP)
├── cli/
│   └── xactions.py         # CLI (Click)
├── tests/
│   ├── test_client.py      # pytest + respx
│   └── test_scrapers.py
├── .env.example
├── .gitignore
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
