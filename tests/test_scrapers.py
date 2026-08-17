"""Tests para parsers y scrapers de xactions-py."""

import httpx
import pytest
import respx

from src.scraper.client import ForbiddenError, TwitterClient
from src.scraper.scrapers import (
    _parse_tweet_list,
    _parse_user_list,
    clear_user_id_cache,
    get_user_id,
    parse_tweet,
    parse_user,
    search_tweets,
)


def test_parse_user_minimal():
    raw = {
        "rest_id": "123",
        "legacy": {
            "screen_name": "testuser",
            "name": "Test User",
            "description": "A test bio",
            "followers_count": 100,
            "friends_count": 50,
            "statuses_count": 1000,
            "verified": True,
            "profile_image_url_https": "https://pbs.twimg.com/profile_images/123_normal.jpg",
        },
        "is_blue_verified": True,
    }
    user = parse_user(raw)
    assert user["id"] == "123"
    assert user["username"] == "testuser"
    assert user["name"] == "Test User"
    assert user["verified"] is True
    assert user["avatar"] == "https://pbs.twimg.com/profile_images/123_400x400.jpg"
    assert user["followers"] == 100


def test_parse_user_unavailable():
    assert parse_user({"__typename": "UserUnavailable"}) is None


def test_parse_tweet_minimal():
    raw = {
        "rest_id": "987654321",
        "legacy": {
            "full_text": "Hello world",
            "created_at": "Mon Jun 21 12:00:00 +0000 2026",
            "favorite_count": 10,
            "retweet_count": 5,
            "reply_count": 2,
            "quote_count": 1,
            "lang": "en",
        },
        "views": {"count": "1000"},
    }
    tweet = parse_tweet(raw)
    assert tweet["id"] == "987654321"
    assert tweet["text"] == "Hello world"
    assert tweet["likes"] == 10
    assert tweet["retweets"] == 5
    assert tweet["replies"] == 2
    assert tweet["quotes"] == 1
    assert tweet["views"] == 1000
    assert tweet["url"] == "https://x.com/i/web/status/987654321"


def test_parse_tweet_with_visibility_results():
    raw = {
        "tweet_results": {
            "result": {
                "__typename": "TweetWithVisibilityResults",
                "tweet": {
                    "rest_id": "111",
                    "legacy": {"full_text": "Nested tweet", "favorite_count": 42},
                },
            }
        }
    }
    tweet = parse_tweet(raw)
    assert tweet["id"] == "111"
    assert tweet["text"] == "Nested tweet"
    assert tweet["likes"] == 42


def test_parse_tweet_tombstone():
    raw = {"tweet_results": {"result": {"__typename": "TweetTombstone"}}}
    assert parse_tweet(raw) is None


def test_parse_tweet_list():
    instructions = [
        {
            "type": "TimelineAddEntries",
            "entries": [
                {
                    "entryId": "tweet-123",
                    "content": {
                        "itemContent": {
                            "itemType": "TimelineTweet",
                            "tweet_results": {
                                "result": {
                                    "rest_id": "123",
                                    "legacy": {"full_text": "Tweet one", "favorite_count": 1},
                                }
                            },
                        }
                    },
                },
                {
                    "entryId": "cursor-bottom-456",
                    "content": {"value": "next_cursor"},
                },
            ],
        }
    ]
    tweets, cursor = _parse_tweet_list(instructions)
    assert len(tweets) == 1
    assert tweets[0]["id"] == "123"
    assert cursor == "next_cursor"


def test_parse_user_list():
    instructions = [
        {
            "type": "TimelineAddEntries",
            "entries": [
                {
                    "entryId": "user-123",
                    "content": {
                        "itemContent": {
                            "itemType": "TimelineUser",
                            "user_results": {
                                "result": {
                                    "rest_id": "123",
                                    "legacy": {"screen_name": "user1", "name": "User One"},
                                }
                            },
                        }
                    },
                },
                {
                    "entryId": "cursor-bottom",
                    "content": {"itemContent": {"value": "cursor123"}},
                },
            ],
        }
    ]
    users, cursor = _parse_user_list(instructions)
    assert len(users) == 1
    assert users[0]["username"] == "user1"
    assert cursor == "cursor123"


def test_safe_int_coerces_strings():
    from src.scraper.scrapers import _safe_int
    assert _safe_int("123") == 123
    assert _safe_int(None) == 0
    assert _safe_int("abc") == 0
    assert _safe_int("123", default=10) == 123


@respx.mock
async def test_get_user_id_uses_cache():
    clear_user_id_cache()
    profile_response = {
        "data": {
            "user": {
                "result": {
                    "rest_id": "44196397",
                    "legacy": {"screen_name": "elonmusk", "name": "Elon Musk"},
                }
            }
        }
    }
    route = respx.get(
        "https://x.com/i/api/graphql/NimuplG1OB7Fd2btCLdBOw/UserByScreenName"
    ).mock(return_value=httpx.Response(200, json=profile_response))

    async with TwitterClient(cookies="auth_token=a; ct0=b") as client:
        uid1 = await get_user_id(client, "elonmusk")
        uid2 = await get_user_id(client, "ElonMusk")  # case-insensitive cache hit

    assert uid1 == uid2 == "44196397"
    assert route.call_count == 1  # el segundo lookup salió del cache


@respx.mock
async def test_search_raises_forbidden_when_no_results():
    respx.post("https://x.com/i/api/graphql/flaR-PUMshxFWZWPNpq4zA/SearchTimeline").mock(
        return_value=httpx.Response(403, json={"error": "Forbidden"})
    )

    async with TwitterClient(cookies="auth_token=a; ct0=b") as client:
        with pytest.raises(ForbiddenError):
            await search_tweets(client, "query bloqueada", limit=10)
