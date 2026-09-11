"""Tests B1: browser/file cookie import formats."""

import json
import sqlite3
from pathlib import Path

from xactions.browser_cookies import (
    _cookie_dict_to_string,
    browser_cookie_db,
    load_cookies_from_file,
    parse_cookie_line,
    parse_json_export,
    parse_netscape_cookies,
    read_cookies_from_sqlite,
)


def test_parse_cookie_line():
    d = parse_cookie_line("auth_token=abc; ct0=xyz")
    assert d == {"auth_token": "abc", "ct0": "xyz"}
    assert parse_cookie_line("# comment") is None


def test_netscape_format(tmp_path: Path):
    text = (
        "# Netscape HTTP Cookie File\n"
        ".x.com\tTRUE\t/\tTRUE\t1893456000\tauth_token\tTOK123\n"
        ".x.com\tTRUE\t/\tTRUE\t1893456000\tct0\tCT0VAL\n"
        ".example.com\tTRUE\t/\tFALSE\t1\tother\tskip\n"
    )
    cookies = parse_netscape_cookies(text)
    assert cookies["auth_token"] == "TOK123"
    assert cookies["ct0"] == "CT0VAL"
    assert "other" not in cookies


def test_load_netscape_file(tmp_path: Path):
    p = tmp_path / "cookies.txt"
    p.write_text(
        ".x.com\tTRUE\t/\tTRUE\t1\tauth_token\tAAA\n.x.com\tTRUE\t/\tTRUE\t1\tct0\tBBB\n",
        encoding="utf-8",
    )
    lines = load_cookies_from_file(p)
    assert len(lines) == 1
    assert "auth_token=AAA" in lines[0]
    assert "ct0=BBB" in lines[0]


def test_load_cookie_editor_json(tmp_path: Path):
    data = [
        {"name": "auth_token", "value": "JSONTOK", "domain": ".x.com"},
        {"name": "ct0", "value": "JSONCT0", "domain": ".x.com"},
    ]
    p = tmp_path / "export.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    lines = load_cookies_from_file(p)
    assert lines and "auth_token=JSONTOK" in lines[0]


def test_load_playwright_storage_state(tmp_path: Path):
    data = {
        "cookies": [
            {"name": "auth_token", "value": "PW"},
            {"name": "ct0", "value": "PWCT0"},
        ]
    }
    p = tmp_path / "state.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    lines = load_cookies_from_file(p)
    assert lines and "auth_token=PW" in lines[0]


def test_load_plain_pool_lines(tmp_path: Path):
    p = tmp_path / "pool.txt"
    p.write_text(
        "auth_token=A1; ct0=B1\n# skip\nauth_token=A2; ct0=B2\n",
        encoding="utf-8",
    )
    lines = load_cookies_from_file(p)
    assert len(lines) == 2


def test_parse_json_export_shapes():
    assert parse_json_export([{"name": "a", "value": "1"}])["a"] == "1"
    assert parse_json_export({"cookies": [{"name": "b", "value": "2"}]})["b"] == "2"


def test_cookie_string_helper():
    assert _cookie_dict_to_string({"auth_token": "x", "ct0": "y"}) == "auth_token=x; ct0=y"
    assert _cookie_dict_to_string({"auth_token": "x"}) is None


def test_read_sqlite_plain_values(tmp_path: Path):
    db = tmp_path / "Cookies"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
    )
    conn.execute(
        "INSERT INTO cookies VALUES ('.x.com', 'auth_token', 'PLAIN', X'')"
    )
    conn.execute(
        "INSERT INTO cookies VALUES ('.x.com', 'ct0', 'PLAINCT0', X'')"
    )
    conn.commit()
    conn.close()
    cookies = read_cookies_from_sqlite(db)
    assert cookies.get("auth_token") == "PLAIN"
    assert cookies.get("ct0") == "PLAINCT0"


def test_browser_cookie_db_missing_returns_none():
    # Unlikely browser name
    assert browser_cookie_db("netscape-navigator") is None


def test_cli_has_from_browser():
    from click.testing import CliRunner

    from xactions.cli import cli

    r = CliRunner().invoke(cli, ["profile", "--help"])
    assert "--from-browser" in r.output
