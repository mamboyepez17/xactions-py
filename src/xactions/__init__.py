"""xactions — X/Twitter automation toolkit (sin npm, sin Puppeteer)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("xactions-py")
except PackageNotFoundError:
    __version__ = "1.5.0.dev0"

from .actions import (
    bulk_unfollow,
    create_bookmark,
    delete_bookmark,
    delete_tweet,
    follow_user,
    like_tweet,
    post_tweet,
    retweet,
    unfollow_user,
    unlike_tweet,
    unretweet,
    upload_media,
)
from .analyzer import analyze_tweets, parse_tweet_date
from .client import (
    AuthError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    TwitterClient,
    TwitterError,
)
from .db import TrackerDB, compute_profile_delta
from .pool import ClientPool
from .scrapers import (
    clear_user_id_cache,
    get_bookmarks,
    get_bookmarks_sync,
    get_home_timeline,
    get_home_timeline_sync,
    get_trends,
    get_trends_sync,
    get_tweet_favoriters,
    get_tweet_favoriters_sync,
    get_tweet_replies,
    get_tweet_replies_sync,
    get_tweet_retweeters,
    get_tweet_retweeters_sync,
    get_user_id,
    get_user_likes,
    get_user_likes_sync,
    scrape_followers,
    scrape_following,
    scrape_non_followers,
    scrape_profile,
    scrape_profile_sync,
    scrape_tweets,
    scrape_tweets_sync,
    search_tweets,
    search_tweets_sync,
    validate_cookies_sync,
)

__all__ = [
    "__version__",
    # client
    "TwitterClient",
    "ClientPool",
    "TwitterError",
    "AuthError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitError",
    # scrapers
    "scrape_profile",
    "scrape_profile_sync",
    "scrape_tweets",
    "scrape_tweets_sync",
    "scrape_followers",
    "scrape_following",
    "scrape_non_followers",
    "search_tweets",
    "search_tweets_sync",
    "get_user_id",
    "clear_user_id_cache",
    "get_user_likes",
    "get_user_likes_sync",
    "get_tweet_replies",
    "get_tweet_replies_sync",
    "get_tweet_favoriters",
    "get_tweet_favoriters_sync",
    "get_tweet_retweeters",
    "get_tweet_retweeters_sync",
    "get_bookmarks",
    "get_bookmarks_sync",
    "get_home_timeline",
    "get_home_timeline_sync",
    "get_trends",
    "get_trends_sync",
    "validate_cookies_sync",
    # actions
    "post_tweet",
    "delete_tweet",
    "like_tweet",
    "unlike_tweet",
    "retweet",
    "unretweet",
    "create_bookmark",
    "delete_bookmark",
    "follow_user",
    "unfollow_user",
    "upload_media",
    "bulk_unfollow",
    # analytics / storage
    "analyze_tweets",
    "parse_tweet_date",
    "TrackerDB",
    "compute_profile_delta",
]
