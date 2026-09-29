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


# ─── Follower history chart ───────────────────────────────────────────────────

from xactions.report import (  # noqa: E402
    _nice_ticks,
    render_account_report_html,
    render_follower_chart_svg,
)

HISTORY = [
    {"captured_at": "2026-09-03T10:00:00+00:00", "followers": 1180, "following": 300, "tweets_count": 900},
    {"captured_at": "2026-09-01T10:00:00+00:00", "followers": 1000, "following": 298, "tweets_count": 880},
    {"captured_at": "2026-09-02T10:00:00+00:00", "followers": 1100, "following": 299, "tweets_count": 890},
]


def test_nice_ticks_are_round_and_cover_range():
    ticks = _nice_ticks(1000, 1180)
    assert ticks[0] <= 1000 and ticks[-1] >= 1180
    steps = {round(b - a, 6) for a, b in zip(ticks, ticks[1:])}
    assert len(steps) == 1 and steps.pop() in (20, 50, 100)


def test_chart_svg_orders_points_and_labels_latest():
    svg = render_follower_chart_svg(HISTORY)
    assert svg.startswith("<svg") and "</svg>" in svg
    assert 'aria-label="Followers from 1,000 to 1,180"' in svg
    assert ">1,180</text>" in svg  # direct label on the latest point
    assert svg.count("<title>") == 3
    assert "2026-09-01" in svg and "2026-09-03" in svg


def test_chart_needs_two_points():
    assert render_follower_chart_svg(HISTORY[:1]) == ""
    assert render_follower_chart_svg([]) == ""


def test_html_report_embeds_history_only_when_given():
    profile = {"username": "nasa", "followers": 1180}
    with_history = render_account_report_html(profile, [], history=HISTORY)
    assert "Follower history" in with_history and "<svg" in with_history
    assert "Snapshot table" in with_history
    assert "prefers-color-scheme:dark" in with_history
    assert "<svg" not in render_account_report_html(profile, [])
