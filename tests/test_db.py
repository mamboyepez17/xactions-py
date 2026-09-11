"""Tests para el tracking en SQLite."""

from xactions.db import TrackerDB, compute_profile_delta


def test_db_saves_and_reads_profile_snapshots(tmp_path):
    db = TrackerDB(str(tmp_path / "test.db"))
    assert db.get_last_profile_snapshot("elonmusk") is None

    db.save_profile_snapshot("elonmusk", {"followers": 100, "following": 10, "tweets_count": 5})
    db.save_profile_snapshot("elonmusk", {"followers": 150, "following": 10, "tweets_count": 8})

    last = db.get_last_profile_snapshot("elonmusk")
    assert last["followers"] == 150

    history = db.get_profile_history("elonmusk")
    assert len(history) == 2
    # Orden descendente por fecha
    assert history[0]["followers"] == 150


def test_db_saves_tweet_snapshots(tmp_path):
    db = TrackerDB(str(tmp_path / "test.db"))
    tweets = [
        {"id": "1", "author": {"username": "a"}, "likes": 10, "retweets": 1},
        {"id": "2", "author": {"username": "a"}, "likes": 20, "retweets": 2},
        {"author": {"username": "a"}},  # sin id → se descarta
    ]
    saved = db.save_tweet_snapshots(tweets)
    assert saved == 2

    history = db.get_tweet_history("1")
    assert len(history) == 1
    assert history[0]["likes"] == 10


def test_db_tracked_usernames(tmp_path):
    db = TrackerDB(str(tmp_path / "test.db"))
    db.save_profile_snapshot("Alice", {"followers": 1})
    db.save_profile_snapshot("bob", {"followers": 2})
    assert db.get_tracked_usernames() == ["alice", "bob"]


def test_compute_profile_delta():
    previous = {"followers": 100, "following": 50, "tweets_count": 10, "captured_at": "2026-01-01"}
    current = {"followers": 120, "following": 48, "tweets_count": 15}
    delta = compute_profile_delta(previous, current)
    assert delta["followers_delta"] == 20
    assert delta["following_delta"] == -2
    assert delta["tweets_delta"] == 5

    assert compute_profile_delta(None, current)["followers_delta"] is None
