"""Tests B0: report renderers (offline)."""

from xactions.report import (
    render_account_report_html,
    render_account_report_md,
    render_compare_report_html,
    render_compare_report_md,
)

PROFILE = {
    "username": "demo",
    "name": "Demo User",
    "followers": 1234,
    "following": 10,
    "tweets_count": 99,
    "verified": True,
    "bio": "Hello **world**\nline2",
}

TWEETS = [
    {
        "id": "1",
        "text": "First tweet about AI",
        "likes": 10,
        "retweets": 2,
        "replies": 1,
        "quotes": 0,
        "views": 500,
        "created_at": "Mon Jun 21 12:00:00 +0000 2026",
        "media": [],
    },
    {
        "id": "2",
        "text": "Second tweet with more engagement",
        "likes": 100,
        "retweets": 20,
        "replies": 5,
        "quotes": 1,
        "views": 5000,
        "created_at": "Mon Jun 21 13:00:00 +0000 2026",
        "media": [{"type": "photo", "url": "https://x/img.jpg"}],
    },
]


def test_account_report_md_contains_profile_and_metrics():
    md = render_account_report_md(PROFILE, TWEETS)
    assert "# X report — @demo" in md
    assert "1,234" in md
    assert "Engagement rate" in md
    assert "Second tweet" in md
    assert "| ID |" in md


def test_account_report_html_wraps_document():
    html = render_account_report_html(PROFILE, TWEETS)
    assert html.startswith("<!DOCTYPE html>")
    assert "@demo" in html
    assert "<table>" in html
    assert "</html>" in html


def test_compare_report_md():
    md = render_compare_report_md(PROFILE, TWEETS, {**PROFILE, "username": "other", "followers": 9}, TWEETS)
    assert "@demo vs @other" in md
    assert "Winners" in md


def test_compare_report_html():
    html = render_compare_report_html(PROFILE, TWEETS, {**PROFILE, "username": "other"}, TWEETS)
    assert "<!DOCTYPE html>" in html
    assert "other" in html


def test_empty_tweets_report():
    md = render_account_report_md(PROFILE, [])
    assert "0" in md or "—" in md
    assert "No tweets" in md or "Tweets analyzed" in md


def test_cli_report_registered():
    from xactions.cli import cli

    assert "report" in cli.commands
