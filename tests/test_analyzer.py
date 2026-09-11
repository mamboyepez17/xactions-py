"""Tests para el módulo de analytics."""

from xactions.analyzer import analyze_tweets, parse_tweet_date


def _tweet(**kwargs):
    base = {
        "id": "1",
        "text": "hello",
        "likes": 10,
        "retweets": 2,
        "replies": 1,
        "quotes": 0,
        "views": 1000,
        "bookmarks": 0,
        "created_at": "Mon Jun 21 12:00:00 +0000 2026",
        "media": [],
        "is_reply": False,
        "is_retweet": False,
        "is_quote": False,
    }
    base.update(kwargs)
    return base


def test_parse_tweet_date_valid():
    dt = parse_tweet_date("Mon Jun 21 12:00:00 +0000 2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.hour == 12


def test_parse_tweet_date_invalid():
    assert parse_tweet_date(None) is None
    assert parse_tweet_date("not a date") is None


def test_analyze_empty():
    report = analyze_tweets([])
    assert report["total_tweets"] == 0
    assert report["top_tweets"] == []


def test_analyze_averages_and_rates():
    tweets = [_tweet(likes=10, views=1000), _tweet(id="2", likes=30, views=3000)]
    profile = {"followers": 1000}
    report = analyze_tweets(tweets, profile=profile)

    assert report["total_tweets"] == 2
    assert report["averages"]["likes"] == 20.0
    assert report["averages"]["views"] == 2000.0
    # avg engagement por tweet = (13 + 33) / 2 = 23 → 23/1000*100 = 2.3%
    assert report["engagement_rate_followers"] == 2.3
    assert report["engagement_rate_views"] is not None


def test_analyze_top_tweets_sorted():
    tweets = [
        _tweet(id="low", likes=1),
        _tweet(id="high", likes=500, retweets=100),
        _tweet(id="mid", likes=50),
    ]
    report = analyze_tweets(tweets, top_n=2)
    assert report["top_tweets"][0]["id"] == "high"
    assert report["top_tweets"][1]["id"] == "mid"
    assert len(report["top_tweets"]) == 2


def test_analyze_best_hours_and_content():
    tweets = [
        _tweet(created_at="Mon Jun 22 09:00:00 +0000 2026", likes=100),
        _tweet(id="2", created_at="Mon Jun 22 09:30:00 +0000 2026", likes=50),
        _tweet(id="3", created_at="Tue Jun 23 20:00:00 +0000 2026", likes=5, media=[{"type": "photo"}]),
    ]
    report = analyze_tweets(tweets)
    assert report["best_hours"][0]["hour"] == 9
    assert report["best_days"][0]["day"] == "Monday"
    assert report["content"]["with_media_pct"] == 33.3
