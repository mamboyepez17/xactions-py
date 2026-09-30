"""The installed package, the CLI and pyproject.toml must agree on the version."""

import re
from pathlib import Path

from click.testing import CliRunner

import xactions
from xactions.cli import cli


def _pyproject_version() -> str:
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def test_package_version_matches_pyproject():
    assert xactions.__version__ == _pyproject_version()


def test_cli_version_matches_package():
    out = CliRunner().invoke(cli, ["--version"]).output
    assert xactions.__version__ in out
