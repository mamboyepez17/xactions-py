"""
XActions-PY — MCP tool groups (filter advertised tools).

Env:
  XACTIONS_MCP_TOOLS=read,analytics     # only these groups
  XACTIONS_MCP_TOOLS_EXCLUDE=write,dm   # subtract groups
"""

from __future__ import annotations

import os
from collections.abc import Iterable

# name prefix → group
TOOL_PREFIX_GROUPS: list[tuple[str, str]] = [
    ("x_get_", "read"),
    ("x_search_", "read"),
    ("x_validate_", "read"),
    ("x_set_cookies", "auth"),
    ("x_analyze_", "analytics"),
    ("x_compare_", "analytics"),
    ("x_build_search", "analytics"),
    ("x_post_", "write"),
    ("x_like_", "write"),
    ("x_unlike_", "write"),
    ("x_retweet", "write"),
    ("x_follow_", "write"),
    ("x_unfollow_", "write"),
    ("x_delete_", "write"),
    ("x_bookmark_", "write"),
    ("x_unbookmark_", "write"),
    ("x_bulk_", "write"),
    ("x_list_drafts", "drafts"),
    ("x_discard_draft", "drafts"),
]

ALL_GROUPS = sorted({g for _, g in TOOL_PREFIX_GROUPS})


def tool_group(name: str) -> str:
    for prefix, group in TOOL_PREFIX_GROUPS:
        if name.startswith(prefix):
            return group
    return "other"


def parse_group_list(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {p.strip().lower() for p in raw.replace(" ", "").split(",") if p.strip()}


def should_advertise(
    tool_name: str,
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
) -> bool:
    group = tool_group(tool_name)
    include = set(include or [])
    exclude = set(exclude or [])
    if include and group not in include and "all" not in include:
        return False
    if exclude and (group in exclude or "all" in exclude):
        return False
    return True


def filter_mcp_tools(
    tool_names: Iterable[str],
    include: str | None = None,
    exclude: str | None = None,
) -> list[str]:
    """Return tool names that pass the group filter."""
    inc = parse_group_list(include)
    exc = parse_group_list(exclude)
    return [n for n in tool_names if should_advertise(n, inc, exc)]


def apply_env_filter_to_mcp(mcp) -> list[str]:
    """
    Remove tools from an MCPServer/FastMCP instance based on env vars.
    Returns the list of tool names kept.

    Fails closed: if a filter is configured but the tool registry cannot be
    found (e.g. the mcp SDK changed its internals), raise instead of silently
    advertising every tool, write tools included.
    """
    include = os.getenv("XACTIONS_MCP_TOOLS")
    exclude = os.getenv("XACTIONS_MCP_TOOLS_EXCLUDE")
    tm = getattr(mcp, "_tool_manager", None)
    tools = getattr(tm, "_tools", None)
    if not include and not exclude:
        return sorted(tools or {}) if isinstance(tools, dict) else []

    if not isinstance(tools, dict):
        raise RuntimeError(
            "XACTIONS_MCP_TOOLS / XACTIONS_MCP_TOOLS_EXCLUDE is set but the MCP tool registry "
            "could not be located on this mcp SDK version; refusing to start with unfiltered tools."
        )
    kept = filter_mcp_tools(list(tools.keys()), include, exclude)
    keep_set = set(kept)
    remove = getattr(mcp, "remove_tool", None)
    for name in list(tools.keys()):
        if name in keep_set:
            continue
        if callable(remove):
            remove(name)
        else:
            tools.pop(name, None)
    leaked = set(tools) - keep_set
    if leaked:
        raise RuntimeError(f"Failed to remove MCP tools: {sorted(leaked)}")
    return sorted(keep_set)
