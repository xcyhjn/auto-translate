from __future__ import annotations

from pathlib import Path

import pytest

from autosub_zh.ui_server import (
    build_error_payload,
    configured_proxy_url,
    test_proxy_connection as probe_proxy_connection,
    validate_proxy_url,
)
from autosub_zh.youtube_meta import YouTubeMeta, ensure_cover


def test_youtube_error_payload_includes_proxy_and_operation() -> None:
    exc = RuntimeError("yt-dlp failed to read YouTube metadata via proxy http://127.0.0.1:7890: timed out")

    payload = build_error_payload(exc, proxy_url="http://127.0.0.1:7890", operation="youtube_meta")

    assert payload["operation"] == "youtube_meta"
    assert payload["proxy_url"] == "http://127.0.0.1:7890"
    assert payload["mode"] == "proxy"
    assert payload["exception_type"] == "RuntimeError"
    assert "operation: youtube_meta" in payload["error"]
    assert "proxy: http://127.0.0.1:7890" in payload["error"]


def test_proxy_status_reports_socket_error_for_unreachable_proxy(monkeypatch) -> None:
    monkeypatch.setattr("autosub_zh.ui_server.read_config", lambda: {"proxy_url": "http://127.0.0.1:9"})

    report = probe_proxy_connection()
    proxy_row = next(item for item in report["results"] if item["name"] == "proxy")

    assert report["mode"] == "proxy"
    assert proxy_row["ok"] is False
    assert "Proxy is not listening" in proxy_row["error"]
    assert proxy_row["exception_type"] == "ConnectionError"


def test_youtube_url_in_proxy_field_is_rejected(monkeypatch) -> None:
    bad_proxy = "https://www.youtube.com/watch?v=VWPkTdC488o"

    assert "not a proxy endpoint" in validate_proxy_url(bad_proxy)
    assert configured_proxy_url({"proxy_url": bad_proxy}) == ""


def test_ensure_cover_reports_primary_and_fallback_download_errors(monkeypatch, tmp_path: Path) -> None:
    meta = YouTubeMeta(
        video_id="dQw4w9WgXcQ",
        video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        author="test",
        published_at="Unknown",
        title="test",
        description="test",
        cover_url="https://example.invalid/primary.jpg",
    )

    def fail_download(url: str, output_path: Path, *, proxy_url: str | None = None) -> Path:
        raise RuntimeError(f"download failed for {url} via {proxy_url}")

    monkeypatch.setattr("autosub_zh.youtube_meta.download_cover", fail_download)

    with pytest.raises(RuntimeError) as excinfo:
        ensure_cover(meta, tmp_path, proxy_url="http://127.0.0.1:7890")

    message = str(excinfo.value)
    assert "primary_error=" in message
    assert "fallback_error=" in message
    assert "http://127.0.0.1:7890" in message
