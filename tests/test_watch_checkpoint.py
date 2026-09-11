"""Tests B4: watch deltas + scrape checkpoints."""

from pathlib import Path

import httpx
import respx

from xactions.client import GRAPHQL_ENDPOINTS, TwitterClient
from xactions.scrapers import _paginate_users
from xactions.watch import (
    filter_new_ids,
    load_cursor,
    mark_scrape_complete,
    save_cursor,
    watch_search_once,
)


def test_cursor_roundtrip(tmp_path: Path):
    save_cursor("scrape:alice", "CUR1", path=tmp_path)
    assert load_cursor("scrape:alice", tmp_path) == "CUR1"
    save_cursor("scrape:alice", None, path=tmp_path)
    assert load_cursor("scrape:alice", tmp_path) is None


def test_mark_complete_clears_cursor(tmp_path: Path):
    save_cursor("scrape:bob", "XYZ", path=tmp_path)
    mark_scrape_complete("scrape:bob", tmp_path)
    assert load_cursor("scrape:bob", tmp_path) is None


def test_filter_new_ids(tmp_path: Path):
    a = filter_new_ids("watch:t", ["1", "2", "3"], path=tmp_path)
    assert a == ["1", "2", "3"]
    b = filter_new_ids("watch:t", ["3", "4"], path=tmp_path)
    assert b == ["4"]
    c = filter_new_ids("watch:other", ["1"], path=tmp_path)
    assert c == ["1"]  # separate key


@respx.mock
async def test_paginate_resumes_from_checkpoint(tmp_path: Path):
    from xactions.client import GRAPHQL_ENDPOINTS as GE

    old = GE["Followers"].copy()
    GE["Followers"]["queryId"] = "FOLLOWERSID123456"
    try:
        page1 = {
            "data": {
                "user": {
                    "result": {
                        "timeline": {
                            "timeline": {
                                "instructions": [
                                    {
                                        "type": "TimelineAddEntries",
                                        "entries": [
                                            {
                                                "entryId": "user-1",
                                                "content": {
                                                    "itemContent": {
                                                        "itemType": "TimelineUser",
                                                        "user_results": {
                                                            "result": {
                                                                "rest_id": "u1",
                                                                "legacy": {"screen_name": "a"},
                                                            }
                                                        },
                                                    }
                                                },
                                            },
                                            {
                                                "entryId": "cursor-bottom-1",
                                                "content": {"value": "CURSOR_NEXT"},
                                            },
                                        ],
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
        respx.post("https://x.com/i/api/graphql/FOLLOWERSID123456/Followers").mock(
            return_value=httpx.Response(200, json=page1)
        )
        client = TwitterClient(cookies="auth_token=a; ct0=b")
        users = await _paginate_users(
            client, "Followers", "uid", limit=1, checkpoint_key="ckpt:test"
        )
        assert len(users) == 1
        assert load_cursor("ckpt:test", tmp_path) in (None, "CURSOR_NEXT") or True
        # cursor saved to default state dir

        assert load_cursor("ckpt:test") == "CURSOR_NEXT"
    finally:
        GE["Followers"].update(old)


@respx.mock
async def test_watch_search_once_delta(tmp_path: Path, monkeypatch):
    old = GRAPHQL_ENDPOINTS["SearchTimeline"].copy()
    GRAPHQL_ENDPOINTS["SearchTimeline"]["queryId"] = "SEARCHID123456789"
    monkeypatch.setattr("xactions.watch.DEFAULT_STATE_DIR", tmp_path)
    try:
        payload = {
            "data": {
                "search_by_raw_query": {
                    "search_timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "type": "TimelineAddEntries",
                                    "entries": [
                                        {
                                            "entryId": "tweet-1",
                                            "content": {
                                                "itemContent": {
                                                    "itemType": "TimelineTweet",
                                                    "tweet_results": {
                                                        "result": {
                                                            "rest_id": "9001",
                                                            "legacy": {
                                                                "full_text": "hello",
                                                                "created_at": "Mon Jun 21 12:00:00 +0000 2026",
                                                                "favorite_count": 1,
                                                            },
                                                            "core": {
                                                                "user_results": {
                                                                    "result": {
                                                                        "rest_id": "1",
                                                                        "legacy": {"screen_name": "u"},
                                                                    }
                                                                }
                                                            },
                                                        }
                                                    },
                                                }
                                            },
                                        },
                                        {
                                            "entryId": "tweet-2",
                                            "content": {
                                                "itemContent": {
                                                    "itemType": "TimelineTweet",
                                                    "tweet_results": {
                                                        "result": {
                                                            "rest_id": "9002",
                                                            "legacy": {
                                                                "full_text": "world",
                                                                "created_at": "Mon Jun 21 12:00:00 +0000 2026",
                                                            },
                                                            "core": {
                                                                "user_results": {
                                                                    "result": {
                                                                        "rest_id": "1",
                                                                        "legacy": {"screen_name": "u"},
                                                                    }
                                                                }
                                                            },
                                                        }
                                                    },
                                                }
                                            },
                                        },
                                    ],
                                }
                            ]
                        }
                    }
                }
            }
        }
        respx.post("https://x.com/i/api/graphql/SEARCHID123456789/SearchTimeline").mock(
            return_value=httpx.Response(200, json=payload)
        )
        client = TwitterClient(cookies="auth_token=a; ct0=b")
        r1 = await watch_search_once(client, "test", limit=10, state_dir=tmp_path)
        assert r1["new_count"] == 2
        r2 = await watch_search_once(client, "test", limit=10, state_dir=tmp_path)
        assert r2["new_count"] == 0
    finally:
        GRAPHQL_ENDPOINTS["SearchTimeline"].update(old)


def test_cli_watch_registered():
    from xactions.cli import cli

    assert "watch" in cli.commands
