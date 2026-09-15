"""Tests B3: MCP tool groups."""

from xactions.mcp_groups import (
    ALL_GROUPS,
    apply_env_filter_to_mcp,
    filter_mcp_tools,
    parse_group_list,
    should_advertise,
    tool_group,
)


def test_tool_group_mapping():
    assert tool_group("x_get_profile") == "read"
    assert tool_group("x_search_tweets") == "read"
    assert tool_group("x_post_tweet") == "write"
    assert tool_group("x_like_tweet") == "write"
    assert tool_group("x_analyze_user") == "analytics"
    assert tool_group("x_list_drafts") == "drafts"
    assert tool_group("x_unknown_thing") == "other"
    assert "read" in ALL_GROUPS


def test_parse_group_list():
    assert parse_group_list("read, analytics") == {"read", "analytics"}
    assert parse_group_list(None) == set()
    assert parse_group_list("") == set()


def test_should_advertise_include_exclude():
    assert should_advertise("x_get_profile", include={"read"})
    assert not should_advertise("x_post_tweet", include={"read"})
    assert should_advertise("x_get_profile", exclude={"write"})
    assert not should_advertise("x_post_tweet", exclude={"write"})
    assert should_advertise("x_get_profile")  # no filter


def test_filter_mcp_tools():
    tools = ["x_get_profile", "x_post_tweet", "x_analyze_user", "x_list_drafts"]
    only_read = filter_mcp_tools(tools, include="read")
    assert only_read == ["x_get_profile"]
    no_write = filter_mcp_tools(tools, exclude="write")
    assert "x_post_tweet" not in no_write
    assert "x_get_profile" in no_write


def test_apply_env_filter_to_mcp(monkeypatch):
    class FakeTM:
        def __init__(self):
            self._tools = {
                "x_get_profile": object(),
                "x_post_tweet": object(),
                "x_analyze_user": object(),
            }

    class FakeMCP:
        def __init__(self):
            self._tool_manager = FakeTM()

    m = FakeMCP()
    monkeypatch.setenv("XACTIONS_MCP_TOOLS", "read,analytics")
    kept = apply_env_filter_to_mcp(m)
    assert set(kept) == {"x_get_profile", "x_analyze_user"}
    assert "x_post_tweet" not in m._tool_manager._tools


def test_apply_env_no_filter_keeps_all(monkeypatch):
    monkeypatch.delenv("XACTIONS_MCP_TOOLS", raising=False)
    monkeypatch.delenv("XACTIONS_MCP_TOOLS_EXCLUDE", raising=False)

    class FakeTM:
        def __init__(self):
            self._tools = {"x_get_profile": 1, "x_post_tweet": 2}

    class FakeMCP:
        def __init__(self):
            self._tool_manager = FakeTM()

    m = FakeMCP()
    kept = apply_env_filter_to_mcp(m)
    assert set(kept) == {"x_get_profile", "x_post_tweet"}
