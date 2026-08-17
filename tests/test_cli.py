"""Tests para el CLI (Click + respx)."""

import httpx
import respx
from click.testing import CliRunner

from cli.xactions import cli


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

    # Sin resultados y con bloqueo, el CLI debe fallar con un mensaje claro.
    assert result.exit_code == 1
    assert "Acceso denegado" in result.output


def test_version_option():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "version" in result.output.lower()
