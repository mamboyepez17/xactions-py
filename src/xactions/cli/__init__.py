"""
XActions-PY — command-line interface (`xactions`).

Commands are grouped into modules (read, analytics, write, monitor, system)
that register themselves on the root `cli` group when imported here.
"""

from __future__ import annotations

import io
import sys

from dotenv import load_dotenv

# Load .env automatically (no-op if it does not exist)
load_dotenv()

# Windows consoles default to a legacy code page; force UTF-8 for emoji output.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if isinstance(_stream, io.TextIOWrapper):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except ValueError:
                pass

from . import analytics, monitor, read, schedule, system, write  # noqa: F401  (register commands)
from ._app import cli
from ._common import _safe_error_message

__all__ = ["cli", "_safe_error_message"]
