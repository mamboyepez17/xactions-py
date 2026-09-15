"""Tests B2: notify / webhook helpers."""

import httpx
import respx

from xactions.notify import format_tweet_alert, make_notifier, post_webhook, webhook_url


def test_format_tweet_alert_empty():
    assert format_tweet_alert([]) == "No new tweets"


def test_format_tweet_alert_lists_authors():
    tweets = [
        {"text": "hello world this is a long tweet that should truncate eventually",
         "author": {"username": "alice"}},
        {"text": "two", "author": {"username": "bob"}},
    ]
    msg = format_tweet_alert(tweets, query="ai")
    assert "2 new tweet(s)" in msg
    assert "ai" in msg
    assert "@alice" in msg
    assert "@bob" in msg


def test_format_alert_caps_preview():
    tweets = [{"text": f"t{i}", "author": {"username": f"u{i}"}} for i in range(8)]
    msg = format_tweet_alert(tweets)
    assert "+3 more" in msg


def test_webhook_url_env(monkeypatch):
    monkeypatch.setenv("XACTIONS_WEBHOOK_URL", "https://example.test/hook")
    assert webhook_url() == "https://example.test/hook"
    monkeypatch.delenv("XACTIONS_WEBHOOK_URL")
    assert webhook_url() is None


@respx.mock
def test_make_notifier_posts_webhook():
    route = respx.post("https://example.test/hook").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    notify = make_notifier("https://example.test/hook", extra={"source": "test"})
    notify("hello alert")
    assert route.called
    body = route.calls.last.request.read()
    assert b"hello alert" in body
    assert b"test" in body


def test_make_notifier_no_url_no_post():
    # should not raise without url
    n = make_notifier(None)
    n("just log")


@respx.mock
async def test_post_webhook():
    respx.post("https://example.test/h").mock(return_value=httpx.Response(204))
    r = await post_webhook("https://example.test/h", {"a": 1})
    assert r["ok"] is True
    assert r["status_code"] == 204
