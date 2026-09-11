"""Tests B5: media download + follower snapshot diff."""

from pathlib import Path

import httpx
import respx

from xactions.media import (
    collect_media_urls,
    diff_followers,
    download_media,
    load_follower_snapshot,
    safe_filename,
    save_follower_snapshot,
)


def test_safe_filename():
    assert safe_filename("hello world!!.jpg") == "hello_world_.jpg"
    assert safe_filename("") == "file"


def test_collect_media_urls():
    tweets = [
        {
            "id": "1",
            "media": [
                {"type": "photo", "url": "https://pbs.twimg.com/a.jpg"},
                {"type": "video", "url": "https://pbs.twimg.com/thumb.jpg", "video_url": "https://video.twimg.com/v.mp4"},
            ],
        },
        {"id": "2", "media": []},
    ]
    urls = collect_media_urls(tweets)
    assert len(urls) == 2
    assert urls[0]["url"].endswith("a.jpg")
    assert urls[1]["url"].endswith("v.mp4")
    assert urls[1]["type"] == "video"


@respx.mock
async def test_download_media(tmp_path: Path):
    respx.get("https://pbs.twimg.com/a.jpg").mock(
        return_value=httpx.Response(200, content=b"JPEGDATA")
    )
    items = [{"url": "https://pbs.twimg.com/a.jpg", "type": "photo", "tweet_id": "99"}]
    result = await download_media(items, tmp_path)
    assert len(result["downloaded"]) == 1
    p = Path(result["downloaded"][0])
    assert p.read_bytes() == b"JPEGDATA"
    # skip second time
    result2 = await download_media(items, tmp_path)
    assert len(result2["skipped"]) == 1
    assert result2["downloaded"] == []


def test_follower_snapshot_and_diff(tmp_path: Path):
    save_follower_snapshot("alice", ["1", "2", "3"], path=tmp_path)
    loaded = load_follower_snapshot("alice", tmp_path)
    assert loaded == ["1", "2", "3"]
    d = diff_followers(["1", "2", "3"], ["2", "3", "4"])
    assert d["unfollowed"] == ["1"]
    assert d["new_followers"] == ["4"]


def test_diff_empty_prev():
    d = diff_followers([], ["a"])
    assert d["unfollowed"] == []
    assert d["new_followers"] == ["a"]


def test_cli_commands_registered():
    from xactions.cli import cli

    assert "download-media" in cli.commands
    assert "snapshot-followers" in cli.commands
    assert "unfollowers" in cli.commands
