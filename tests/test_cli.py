"""Tests for the CLI (Click + respx)."""

import httpx
import respx
from click.testing import CliRunner

from xactions.cli import cli


@respx.mock
def test_profile_command():
    respx.get("https://x.com/i/api/graphql/NimuplG1OB7Fd2btCLdBOw/UserByScreenName").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "user": {
                        "result": {
                            "rest_id": "42",
                            "legacy": {
                                "screen_name": "test",
                                "name": "Test User",
                                "description": "bio",
                                "followers_count": 10,
                                "friends_count": 5,
                                "statuses_count": 3,
                            },
                            "is_blue_verified": False,
                        }
                    }
                }
            },
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["profile", "test"], env={"TWITTER_COOKIES": "auth_token=a; ct0=b"}
    )

    assert result.exit_code == 0
    assert "@test" in result.output


@respx.mock
def test_search_forbidden_error_message():
    respx.post("https://x.com/i/api/graphql/flaR-PUMshxFWZWPNpq4zA/SearchTimeline").mock(
        return_value=httpx.Response(403, json={"error": "Forbidden"})
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["search", "blocked", "--limit", "5"], env={"TWITTER_COOKIES": "auth_token=a; ct0=b"}
    )

    # No results and a block: the CLI must fail with a clear message.
    assert result.exit_code == 1
    assert "Access denied" in result.output


def test_version_option():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "version" in result.output.lower()


def test_table_output_renders_rows_not_the_wrapper(capsys):
    from xactions.cli._common import _handle_output, print_tweets_table, print_users_table

    tweets = [{"text": "hi", "author": {"username": "alice"}, "likes": 3, "retweets": 1}]
    _handle_output({"count": 1, "tweets": tweets}, None, None, table_fn=print_tweets_table, table_title="T")
    out = capsys.readouterr().out
    assert "@alice" in out and "T (1 tweets)" in out

    users = [{"username": "bob", "name": "Bob", "followers": 10}]
    _handle_output({"count": 1, "followers": users}, None, None, table_fn=print_users_table, table_title="F")
    assert "@bob" in capsys.readouterr().out
