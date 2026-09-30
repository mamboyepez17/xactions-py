"""The root `xactions` click group; command modules attach to it."""

from __future__ import annotations

import click

from .. import __version__  # single source of truth: package metadata

# ─── CLI principal ────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name="xactions-py")
def cli():
    """⚡ XActions-PY — X/Twitter automation without npm."""
    pass
