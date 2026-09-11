"""Tests del manejo seguro de cookies."""

import os

import pytest

from xactions.security import (
    check_cookies_file_permissions,
    cookies_in_argv,
    redact_cookies,
    redact_in_text,
    safe_cookie_summary,
    warn_cli_cookies,
)


def test_redact_cookies_hides_values():
    out = redact_cookies("auth_token=SECRETTOKEN; ct0=SECRETCT0")
    assert "SECRETTOKEN" not in out
    assert "SECRETCT0" not in out
    assert "auth_token=***" in out
    assert "ct0=***" in out


def test_redact_cookies_empty():
    assert redact_cookies(None) == "(vacío)"
    assert redact_cookies("") == "(vacío)"


def test_redact_in_text_message():
    msg = "HTTP 401 Cookie: auth_token=abc123def; ct0=xyz789"
    out = redact_in_text(msg)
    assert "abc123def" not in out
    assert "xyz789" not in out
    assert "auth_token=***" in out
    assert "ct0=***" in out


def test_cookies_in_argv_detects_flag():
    assert cookies_in_argv(["xactions", "validate", "--cookies", "auth_token=a; ct0=b"]) is True
    assert cookies_in_argv(["xactions", "validate", "--cookies=auth_token=a"]) is True
    assert cookies_in_argv(["xactions", "validate", "--cookies-file", "c.txt"]) is False
    assert cookies_in_argv(["xactions", "validate"]) is False


def test_warn_cli_cookies_returns_message():
    assert warn_cli_cookies("") is None
    msg = warn_cli_cookies("auth_token=a")  # sin argv real, puede no avisar
    # cookies_in_argv() usa sys.argv de pytest — no asumimos True
    assert msg is None or isinstance(msg, str)


def test_warn_cli_cookies_with_fake_argv(monkeypatch):
    monkeypatch.setattr("sys.argv", ["xactions", "--cookies", "auth_token=a; ct0=b"])
    msg = warn_cli_cookies("auth_token=a; ct0=b")
    assert msg is not None
    assert "historial" in msg.lower() or "shell" in msg.lower()


@pytest.mark.skipif(os.name == "nt", reason="permisos Unix")
def test_check_file_permissions_warns_when_world_readable(tmp_path):
    p = tmp_path / "cookies.txt"
    p.write_text("auth_token=a; ct0=b\n", encoding="utf-8")
    os.chmod(p, 0o644)
    warn = check_cookies_file_permissions(p)
    assert warn is not None
    assert "chmod 600" in warn

    os.chmod(p, 0o600)
    assert check_cookies_file_permissions(p) is None


def test_check_file_permissions_windows_noop(tmp_path):
    if os.name != "nt":
        pytest.skip("solo Windows")
    p = tmp_path / "cookies.txt"
    p.write_text("auth_token=a; ct0=b\n", encoding="utf-8")
    assert check_cookies_file_permissions(p) is None


def test_safe_cookie_summary_no_secrets():
    summary = safe_cookie_summary(["auth_token=SECRET1; ct0=S2", "auth_token=SECRET3; ct0=S4"])
    assert "SECRET1" not in summary
    assert "SECRET3" not in summary
    assert "2 cuenta" in summary


def test_client_error_path_redacts(caplog):
    """Un AuthError con cookie pegada no debe filtrar el valor al formatear."""
    from xactions.cli import _safe_error_message

    class FakeErr(Exception):
        pass

    err = FakeErr("failed auth_token=LEAKEDVALUE; ct0=LEAKEDCT0")
    out = _safe_error_message(err)
    assert "LEAKEDVALUE" not in out
    assert "LEAKEDCT0" not in out
