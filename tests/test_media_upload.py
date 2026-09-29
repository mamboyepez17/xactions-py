"""Tests for simple and chunked (INIT/APPEND/FINALIZE/STATUS) media upload."""

from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from xactions import actions
from xactions.actions import CHUNK_SIZE, MEDIA_UPLOAD_URL, check_media_set, upload_media
from xactions.client import TwitterClient, TwitterError


@pytest.fixture
def client():
    return TwitterClient(cookies="auth_token=a; ct0=b")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(actions.asyncio, "sleep", fake_sleep)
    return slept


def _form(request: httpx.Request) -> dict:
    """Decode urlencoded or multipart form fields into {name: value}."""
    body = request.read()
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("application/x-www-form-urlencoded"):
        return {k: v[0] for k, v in parse_qs(body.decode()).items()}
    fields = {}
    boundary = ctype.split("boundary=")[1].encode()
    for part in body.split(b"--" + boundary):
        if b'name="' not in part:
            continue
        head, _, value = part.partition(b"\r\n\r\n")
        name = head.split(b'name="')[1].split(b'"')[0].decode()
        fields[name] = value.rstrip(b"\r\n")
    return fields


@respx.mock
async def test_small_image_uses_single_request(client, tmp_path: Path):
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG" + b"0" * 100)
    route = respx.post(MEDIA_UPLOAD_URL).mock(return_value=httpx.Response(200, json={"media_id_string": "11"}))
    res = await upload_media(client, str(img))
    assert res == {"success": True, "media_id": "11", "size": None, "chunked": False}
    assert route.call_count == 1


@respx.mock
async def test_video_uses_chunked_flow_and_waits_for_processing(client, tmp_path: Path, no_sleep):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"v" * (CHUNK_SIZE + 10))  # two segments
    commands = []

    def upload(request):
        form = _form(request)
        cmd = form["command"].decode() if isinstance(form["command"], bytes) else form["command"]
        commands.append(cmd if cmd != "APPEND" else f"APPEND:{form['segment_index'].decode()}")
        if cmd == "INIT":
            assert form["media_type"] == "video/mp4"
            assert form["media_category"] == "tweet_video"
            assert form["total_bytes"] == str(CHUNK_SIZE + 10)
            return httpx.Response(202, json={"media_id_string": "77"})
        if cmd == "APPEND":
            return httpx.Response(204)
        return httpx.Response(200, json={"media_id_string": "77", "processing_info": {"state": "pending", "check_after_secs": 2}})

    respx.post(MEDIA_UPLOAD_URL).mock(side_effect=upload)
    status = respx.get(MEDIA_UPLOAD_URL).mock(
        side_effect=[
            httpx.Response(200, json={"processing_info": {"state": "in_progress", "check_after_secs": 3}}),
            httpx.Response(200, json={"processing_info": {"state": "succeeded"}}),
        ]
    )

    res = await upload_media(client, str(video))
    assert res["media_id"] == "77" and res["chunked"] and res["segments"] == 2
    assert commands == ["INIT", "APPEND:0", "APPEND:1", "FINALIZE"]
    assert status.call_count == 2
    assert status.calls.last.request.url.params["command"] == "STATUS"
    assert no_sleep == [2.0, 3.0]


@respx.mock
async def test_processing_failure_raises(client, tmp_path: Path):
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a")

    def upload(request):
        cmd = _form(request)["command"]
        cmd = cmd.decode() if isinstance(cmd, bytes) else cmd
        if cmd == "INIT":
            return httpx.Response(200, json={"media_id_string": "5"})
        if cmd == "APPEND":
            return httpx.Response(204)
        return httpx.Response(
            200, json={"processing_info": {"state": "failed", "error": {"message": "InvalidMedia"}}}
        )

    respx.post(MEDIA_UPLOAD_URL).mock(side_effect=upload)
    with pytest.raises(TwitterError, match="InvalidMedia"):
        await upload_media(client, str(gif))


@respx.mock
async def test_processing_timeout_raises(client, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(actions, "MAX_PROCESSING_WAIT", 5.0)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v")

    def upload(request):
        cmd = _form(request)["command"]
        cmd = cmd.decode() if isinstance(cmd, bytes) else cmd
        if cmd == "INIT":
            return httpx.Response(200, json={"media_id_string": "9"})
        if cmd == "APPEND":
            return httpx.Response(204)
        return httpx.Response(200, json={"processing_info": {"state": "pending", "check_after_secs": 3}})

    respx.post(MEDIA_UPLOAD_URL).mock(side_effect=upload)
    respx.get(MEDIA_UPLOAD_URL).mock(
        return_value=httpx.Response(200, json={"processing_info": {"state": "pending", "check_after_secs": 3}})
    )
    with pytest.raises(TwitterError, match="still processing"):
        await upload_media(client, str(video))


def test_check_media_set():
    check_media_set(["a.png", "b.jpg", "c.png", "d.webp"])
    check_media_set(["clip.mp4"])
    check_media_set([])
    with pytest.raises(ValueError, match="at most 4"):
        check_media_set(["1.png"] * 5)
    with pytest.raises(ValueError, match="only media"):
        check_media_set(["clip.mp4", "a.png"])
    with pytest.raises(ValueError, match="only media"):
        check_media_set(["a.gif", "b.gif"])
