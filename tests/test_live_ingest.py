"""Regression tests for live source status and yt-dlp fallback handling."""

import json
import subprocess

import pytest

from streamclipper.live import ingest


@pytest.mark.parametrize(
    "message",
    [
        "Stream is offline",
        "This live event has ended",
        "The live stream has ended",
        "Not currently live",
    ],
)
def test_explicit_offline_messages_are_terminal(message):
    assert ingest._offline_message(message)


@pytest.mark.parametrize(
    "message",
    [
        "Sign in to confirm you are not a bot",
        "HTTP Error 403: Forbidden",
        "Unable to open URL",
        "Connection timed out",
        "No playable streams found because the plugin failed",
        "",
    ],
)
def test_auth_and_transient_errors_are_not_offline(message):
    assert not ingest._offline_message(message)


def test_is_offline_reads_streamlink_json_error(monkeypatch):
    result = subprocess.CompletedProcess(
        args=["streamlink"], returncode=1, stdout=json.dumps({"error": "Stream is offline"}), stderr=""
    )
    monkeypatch.setattr(ingest, "streamlink_cmd", lambda: ["streamlink"])
    monkeypatch.setattr(ingest.subprocess, "run", lambda *a, **k: result)
    assert ingest.is_offline("youtube", "https://youtube.com/watch?v=test")


def test_is_offline_does_not_classify_auth_failure(monkeypatch):
    result = subprocess.CompletedProcess(
        args=["streamlink"], returncode=1,
        stdout=json.dumps({"error": "Sign in to confirm you are not a bot"}), stderr=""
    )
    monkeypatch.setattr(ingest, "streamlink_cmd", lambda: ["streamlink"])
    monkeypatch.setattr(ingest.subprocess, "run", lambda *a, **k: result)
    assert not ingest.is_offline("youtube", "https://youtube.com/watch?v=test")


def test_is_offline_timeout_is_retryable(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("streamlink", 30)

    monkeypatch.setattr(ingest, "streamlink_cmd", lambda: ["streamlink"])
    monkeypatch.setattr(ingest.subprocess, "run", timeout)
    assert not ingest.is_offline("youtube", "https://youtube.com/watch?v=test")


def test_ytdlp_hls_uses_configured_cookie_file(monkeypatch, tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setenv("STREAMCLIPPER_YTDLP_COOKIES", str(cookie_file))
    monkeypatch.setattr(ingest, "ytdlp_cmd", lambda: ["yt-dlp"])
    seen = {}

    def run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="https://example.test/live.m3u8\n", stderr="")

    monkeypatch.setattr(ingest.subprocess, "run", run)
    assert ingest.ytdlp_hls("https://youtube.com/watch?v=test") == "https://example.test/live.m3u8"
    assert seen["cmd"][1:3] == ["--cookies", str(cookie_file)]


def test_ytdlp_hls_auth_error_is_actionable(monkeypatch):
    monkeypatch.delenv("STREAMCLIPPER_YTDLP_COOKIES", raising=False)
    monkeypatch.setattr(ingest, "ytdlp_cmd", lambda: ["yt-dlp"])

    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout="", stderr="Sign in to confirm you are not a bot"
        )

    monkeypatch.setattr(ingest.subprocess, "run", run)
    with pytest.raises(ingest.ToolError, match="could not resolve"):
        ingest.ytdlp_hls("https://youtube.com/watch?v=test")
