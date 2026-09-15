"""Tests B0: lightweight sentiment."""

from xactions.sentiment import score_text, score_tweets, summarize_sentiment


def test_score_positive_en():
    r = score_text("This is great and amazing, I love it")
    assert r["label"] == "positive"
    assert r["score"] > 0
    assert "great" in r["hits_positive"]


def test_score_negative_es():
    r = score_text("Esto es terrible y una basura, odio el fracaso")
    assert r["label"] == "negative"
    assert r["score"] < 0
    assert "basura" in r["hits_negative"]


def test_score_neutral():
    r = score_text("The meeting is at noon")
    assert r["label"] == "neutral"
    assert r["score"] == 0.0


def test_score_mixed():
    r = score_text("good but terrible")
    assert r["hits_positive"] == ["good"]
    assert r["hits_negative"] == ["terrible"]
    assert r["score"] == 0.0  # 1-1 / 2


def test_score_tweets_attaches_key():
    tweets = [{"id": "1", "text": "love this win"}, {"id": "2", "text": "hate fail"}]
    out = score_tweets(tweets)
    assert out[0]["sentiment"]["label"] == "positive"
    assert out[1]["sentiment"]["label"] == "negative"
    # original not mutated
    assert "sentiment" not in tweets[0]


def test_summarize():
    tweets = [
        {"text": "great win"},
        {"text": "bad fail"},
        {"text": "ok"},
    ]
    s = summarize_sentiment(tweets)
    assert s["count"] == 3
    assert s["positive"] == 1
    assert s["negative"] == 1
    assert s["neutral"] == 1


def test_summarize_empty():
    assert summarize_sentiment([])["count"] == 0


def test_cli_sentiment_and_engage_registered():
    from xactions.cli import cli

    assert "sentiment" in cli.commands
    assert "engage" in cli.commands
