"""Tests offline del parser y cache de GraphQL query IDs."""

import json
from pathlib import Path

import httpx
import respx

from xactions.gql_refresh import (
    _bundle_urls_from_html,
    cache_status,
    endpoints_with_cache,
    extract_operations,
    extract_operations_from_twikit,
    load_cache,
    merge_endpoints,
    save_cache,
)

FAKE_JS = r"""
var a=queryId:"NimuplG1OB7Fd2btCLdBOw",operationName:"UserByScreenName";
var b=queryId:"NEWSEARCHID1234567890",operationName:"SearchTimeline";
var c=operationName:"CreateTweet",queryId:"NEWCREATETWEETID1234";
var d=queryId:"LikesID1234567890123",operationName:"Likes";
"""

FAKE_RELAY_JS = r"""
({id:`frIPQPuTi1WBHmfe-hRyrA`,metadata:{},name:`intentFollowUserByScreenNameQuery`,operationKind:`query`,text:null});
({id:`NimuplG1OB7Fd2btCLdBOw`,metadata:{},name:`UserByScreenName`,operationKind:`query`,text:null});
"""

FAKE_TWIKIT = """
class Endpoint:
    SEARCH_TIMELINE = url('flaR-PUMshxFWZWPNpq4zA/SearchTimeline')
    USER_BY_SCREEN_NAME = url('TWIKITUSERID12345678/UserByScreenName')
    CREATE_TWEET = url('TWIKITCREATETWEET123/CreateTweet')
"""


def test_extract_relay_backticks():
    ops = extract_operations(FAKE_RELAY_JS)
    assert ops["UserByScreenName"]["queryId"] == "NimuplG1OB7Fd2btCLdBOw"
    assert "intentFollowUserByScreenNameQuery" in ops


def test_extract_operations_from_twikit_source():
    ops = extract_operations_from_twikit(FAKE_TWIKIT)
    assert ops["SearchTimeline"]["queryId"] == "flaR-PUMshxFWZWPNpq4zA"
    assert ops["UserByScreenName"]["queryId"] == "TWIKITUSERID12345678"
    assert ops["CreateTweet"]["queryId"] == "TWIKITCREATETWEET123"


FAKE_HTML = """
<html><head>
<script src="https://abs.twimg.com/responsive-web/client-web/main.abc123.js"></script>
<script src="https://abs.twimg.com/responsive-web/client-web/api.def456.js"></script>
<script src="https://abs.twimg.com/x-web/x-web/entry-client-logged-out-Abc.js"></script>
</head></html>
"""


def test_extract_operations_both_orders():
    ops = extract_operations(FAKE_JS)
    assert ops["UserByScreenName"]["queryId"] == "NimuplG1OB7Fd2btCLdBOw"
    assert ops["SearchTimeline"]["queryId"] == "NEWSEARCHID1234567890"
    # operationName antes de queryId
    assert ops["CreateTweet"]["queryId"] == "NEWCREATETWEETID1234"
    # operationName distinto del key del store (Likes vs UserLikes)
    assert ops["Likes"]["queryId"] == "LikesID1234567890123"


def test_extract_ignores_short_ids():
    ops = extract_operations('queryId:"short",operationName:"Nope"')
    assert "Nope" not in ops


def test_bundle_urls_from_html_prefers_main():
    urls = _bundle_urls_from_html(FAKE_HTML)
    assert urls[0].endswith("main.abc123.js")
    assert any("api.def456.js" in u for u in urls)


def test_merge_updates_query_ids_and_keeps_method():
    base = {
        "SearchTimeline": {
            "queryId": "old",
            "operationName": "SearchTimeline",
            "method": "POST",
        },
        "UserLikes": {"queryId": "oldlikes", "operationName": "Likes"},
        "FollowUser": {"queryId": None, "operationName": None},
    }
    discovered = {
        "SearchTimeline": {"queryId": "new", "operationName": "SearchTimeline"},
        "Likes": {"queryId": "newlikes", "operationName": "Likes"},
    }
    merged = merge_endpoints(base, discovered)
    assert merged["SearchTimeline"]["queryId"] == "new"
    assert merged["SearchTimeline"]["method"] == "POST"
    assert merged["UserLikes"]["queryId"] == "newlikes"
    assert merged["FollowUser"]["queryId"] is None


def test_cache_roundtrip(tmp_path: Path):
    path = tmp_path / "gql.json"
    eps = {
        "UserByScreenName": {
            "queryId": "abc",
            "operationName": "UserByScreenName",
        }
    }
    save_cache(eps, path=path, source="test")
    loaded = load_cache(path)
    assert loaded is not None
    assert loaded["endpoints"]["UserByScreenName"]["queryId"] == "abc"
    status = cache_status(path)
    assert status["exists"] is True
    assert status["count"] == 1

    base = {
        "UserByScreenName": {"queryId": "default", "operationName": "UserByScreenName"},
        "Other": {"queryId": "x", "operationName": "Other"},
    }
    with_cache = endpoints_with_cache(base, cache_path=path)
    assert with_cache["UserByScreenName"]["queryId"] == "abc"
    assert with_cache["Other"]["queryId"] == "x"


def test_cache_status_missing(tmp_path: Path):
    status = cache_status(tmp_path / "nope.json")
    assert status["exists"] is False
    assert status["count"] == 0


@respx.mock
async def test_discover_from_bundles(tmp_path: Path):
    from xactions.gql_refresh import refresh_endpoints

    respx.get("https://x.com").mock(
        return_value=httpx.Response(200, text=FAKE_HTML)
    )
    respx.get("https://abs.twimg.com/responsive-web/client-web/main.abc123.js").mock(
        return_value=httpx.Response(200, text=FAKE_JS)
    )
    respx.get("https://abs.twimg.com/responsive-web/client-web/api.def456.js").mock(
        return_value=httpx.Response(200, text=FAKE_JS)
    )
    respx.get("https://abs.twimg.com/x-web/x-web/entry-client-logged-out-Abc.js").mock(
        return_value=httpx.Response(200, text=FAKE_JS)
    )
    respx.get("https://raw.githubusercontent.com/d60/twikit/main/twikit/client/gql.py").mock(
        return_value=httpx.Response(200, text=FAKE_TWIKIT)
    )

    base = {
        "UserByScreenName": {
            "queryId": "old",
            "operationName": "UserByScreenName",
            "method": "GET",
        },
        "SearchTimeline": {
            "queryId": "oldsearch",
            "operationName": "SearchTimeline",
            "method": "POST",
        },
        "UserLikes": {"queryId": "oldlikes", "operationName": "Likes"},
    }
    path = tmp_path / "cache.json"
    merged = await refresh_endpoints(base, cache_path=path, persist=True)
    assert merged["UserByScreenName"]["queryId"] == "NimuplG1OB7Fd2btCLdBOw"
    assert merged["SearchTimeline"]["queryId"] == "NEWSEARCHID1234567890"
    assert merged["SearchTimeline"]["method"] == "POST"
    assert merged["UserLikes"]["queryId"] == "LikesID1234567890123"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "updated_at" in data


@respx.mock
async def test_refresh_prefers_auth_bundle_and_falls_back_to_twikit(tmp_path: Path):
    """Sin cookie → twikit. Con cookie → bundle logueado manda."""
    from xactions.gql_refresh import refresh_endpoints

    respx.get("https://x.com").mock(return_value=httpx.Response(200, text=FAKE_HTML))
    for u in (
        "https://abs.twimg.com/responsive-web/client-web/main.abc123.js",
        "https://abs.twimg.com/responsive-web/client-web/api.def456.js",
        "https://abs.twimg.com/x-web/x-web/entry-client-logged-out-Abc.js",
    ):
        respx.get(u).mock(return_value=httpx.Response(200, text="/* empty */"))
    respx.get("https://raw.githubusercontent.com/d60/twikit/main/twikit/client/gql.py").mock(
        return_value=httpx.Response(200, text=FAKE_TWIKIT)
    )

    base = {
        "UserByScreenName": {"queryId": "old", "operationName": "UserByScreenName"},
        "SearchTimeline": {"queryId": "oldsearch", "operationName": "SearchTimeline"},
        "CreateTweet": {"queryId": "oldcreate", "operationName": "CreateTweet"},
    }

    # Sin cookies: bundles vacíos → twikit
    path1 = tmp_path / "a.json"
    merged = await refresh_endpoints(base, cache_path=path1, persist=True)
    assert merged["UserByScreenName"]["queryId"] == "TWIKITUSERID12345678"
    assert json.loads(path1.read_text(encoding="utf-8"))["source"] == "twikit"

    # Con cookies: mockeamos que el HTML trae entry-client-logged-in con ops
    logged_html = FAKE_HTML.replace(
        "entry-client-logged-out-Abc.js",
        "entry-client-logged-in-XYZ.js",
    )
    respx.get("https://x.com").mock(return_value=httpx.Response(200, text=logged_html))
    respx.get("https://abs.twimg.com/x-web/x-web/entry-client-logged-in-XYZ.js").mock(
        return_value=httpx.Response(200, text=FAKE_JS)
    )

    path2 = tmp_path / "b.json"
    merged2 = await refresh_endpoints(
        base,
        cache_path=path2,
        persist=True,
        cookie="auth_token=abc; ct0=xyz",
    )
    # FAKE_JS trae los IDs "reales" de UserByScreenName / SearchTimeline
    assert merged2["UserByScreenName"]["queryId"] == "NimuplG1OB7Fd2btCLdBOw"
    assert merged2["SearchTimeline"]["queryId"] == "NEWSEARCHID1234567890"
    assert json.loads(path2.read_text(encoding="utf-8"))["source"] == "bundle-auth"
