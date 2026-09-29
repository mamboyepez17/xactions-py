"""
XActions-PY — Safe handling of session cookies.

Rules:
  - Never print auth_token/ct0 values (names + *** only).
  - Warn when cookies come in on the command line (they end up in shell history).
  - Warn when a cookie file is readable by other users (Unix).
"""

from __future__ import annotations

import logging
import os
import re
import stat
import sys
from pathlib import Path

_log = logging.getLogger(__name__)

# Sensitive cookie names
_SENSITIVE_KEYS = frozenset(
    {
        "auth_token",
        "ct0",
        "kdt",
        "att",
        "twid",
        "auth_multi",
        "auth_multi_token",
    }
)

_SECRET_IN_TEXT = re.compile(
    r"(?i)\b(auth_token|ct0|kdt|att|auth_multi(?:_token)?)\s*=\s*[^;\s,]+"
)


def redact_cookies(cookie_str: str | None) -> str:
    """
    Safe way to display cookies: names only.
    E.g. 'auth_token=abc; ct0=xyz' → 'auth_token=***, ct0=***'
    """
    if not cookie_str:
        return "(empty)"
    names: list[str] = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            name = part.split("=", 1)[0].strip()
            if name:
                names.append(f"{name}=***")
        else:
            names.append("***")
    return ", ".join(names) if names else "***"


def redact_in_text(text: str) -> str:
    """Redact auth_token=... / ct0=... anywhere in a piece of text."""
    if not text:
        return text
    return _SECRET_IN_TEXT.sub(lambda m: f"{m.group(1)}=***", text)


def cookies_in_argv(argv: list[str] | None = None) -> bool:
    """True if cookies were passed with --cookies (not --cookies-file or env only)."""
    args = argv if argv is not None else sys.argv
    for a in args:
        if a == "--cookies":
            return True
        if a.startswith("--cookies=") and not a.startswith("--cookies-file"):
            return True
    return False


def warn_cli_cookies(cookies: str | None = None) -> str | None:
    """
    If cookies came in through --cookies in argv, return a warning (non-blocking).
    Prefer .env (TWITTER_COOKIES) or --cookies-file with mode 600.
    """
    if not cookies:
        return None
    if cookies_in_argv():
        msg = (
            "Cookies passed with --cookies can end up in your shell history. "
            "Prefer TWITTER_COOKIES in .env or --cookies-file (chmod 600)."
        )
        _log.warning(msg)
        return msg
    return None


def check_cookies_file_permissions(path: str | Path) -> str | None:
    """
    On Unix, return a warning if the file is accessible by group/other.
    Not applicable on Windows (returns None).
    """
    if os.name == "nt":
        return None
    p = Path(path)
    try:
        mode = p.stat().st_mode
    except OSError:
        return None
    if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
        return (
            f"Cookie file {p} is accessible by other users "
            f"(mode {oct(stat.S_IMODE(mode))}). Run: chmod 600 {p}"
        )
    return None


def safe_cookie_summary(cookie_list: list[str]) -> str:
    """Summary for logs/CLI: account count + cookie names, never values."""
    if not cookie_list:
        return "0 accounts"
    parts = [redact_cookies(c) for c in cookie_list[:3]]
    extra = f" (+{len(cookie_list) - 3} more)" if len(cookie_list) > 3 else ""
    return f"{len(cookie_list)} account(s): {parts}{extra}"
