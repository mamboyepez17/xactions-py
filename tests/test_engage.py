"""Tests B1: engage dry-run path."""

from click.testing import CliRunner

from xactions.cli import cli


def test_engage_requires_action_flag():
    runner = CliRunner()
    r = runner.invoke(cli, ["engage", "ai"], env={"TWITTER_COOKIES": "auth_token=a; ct0=b"})
    assert r.exit_code != 0
    assert "like" in r.output.lower() or "retweet" in r.output.lower()


def test_engage_help_documents_execute():
    r = CliRunner().invoke(cli, ["engage", "--help"])
    assert r.exit_code == 0
    assert "--execute" in r.output
    assert "--dry-run" in r.output
    assert "--min-likes" in r.output
