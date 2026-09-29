"""The root `xactions` click group; command modules attach to it."""

from __future__ import annotations

import click

from ._common import __version__

# ─── CLI principal ────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name="xactions-py")
def cli():
    """⚡ XActions-PY — Twitter automation sin npm."""
    pass
