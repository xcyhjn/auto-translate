from __future__ import annotations

from autosub_zh.bilibili_search import build_bilibili_duplicate_report, parse_bilibili_search_results


def test_parse_bilibili_html_extracts_video_candidate() -> None:
    html = """
    <html><body>
      <a class="bili-video-card__info--tit" href="//www.bilibili.com/video/BV1AB411c7mD/" title="垂死的神：俄罗斯小说解说">
        垂死的神：俄罗斯小说解说
      </a>
      <span class="bili-video-card__info--author">字幕组</span>
      <span>20:03</span>
      <span>2025-02-01</span>
    </body></html>
    """

    candidates = parse_bilibili_search_results(html, query="垂死的神 俄罗斯 小说", search_url="https://search.example")

    assert len(candidates) == 1
    assert candidates[0]["title"] == "垂死的神：俄罗斯小说解说"
    assert candidates[0]["url"] == "https://www.bilibili.com/video/BV1AB411c7mD"
    assert candidates[0]["duration_seconds"] == 1203
    assert candidates[0]["source_search_url"] == "https://search.example"


def test_parse_failure_keeps_search_url_fallback_in_report() -> None:
    meta = {
        "title": "The Russian book about a dying god",
        "description": "",
        "author": "Paper Trail",
        "published_at": "2025-01-10",
        "duration": 1200,
    }

    def empty_search(query: str, **kwargs) -> list[dict]:
        return []

    report = build_bilibili_duplicate_report(
        "https://www.youtube.com/watch?v=abc123XYZ09",
        meta,
        search_func=empty_search,
        max_queries=2,
        sleep_seconds=0,
    )

    assert report["decision"] == "no_candidates_search_completed"
    assert report["queries"]
    assert report["queries"][0]["fallback_manual_review"] is True
    assert report["queries"][0]["search_url"].startswith("https://search.bilibili.com/video?keyword=")


def test_partial_search_timeout_is_not_reported_as_total_failure() -> None:
    meta = {
        "title": "The Russian book about a dying god",
        "description": "",
        "author": "Paper Trail",
        "published_at": "2025-01-10",
        "duration": 1200,
    }
    calls = {"count": 0}

    def empty_then_timeout(query: str, **kwargs) -> list[dict]:
        calls["count"] += 1
        if calls["count"] >= 3:
            raise TimeoutError("Bilibili request timed out")
        return []

    report = build_bilibili_duplicate_report(
        "https://www.youtube.com/watch?v=abc123XYZ09",
        meta,
        search_func=empty_then_timeout,
        max_queries=4,
        sleep_seconds=0,
    )

    assert report["decision"] == "no_candidates_search_completed"
    assert report["search_summary"]["searched"] is True
    assert report["search_summary"]["successful_query_count"] == 2
    assert report["errors"]
