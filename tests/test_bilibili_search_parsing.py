from __future__ import annotations

from autosub_zh.bilibili_search import (
    BilibiliSearchChannelLimited,
    build_bilibili_duplicate_report,
    is_bilibili_captcha_page,
    parse_bilibili_api_results,
    parse_bilibili_search_results,
)


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
    assert report["search_state"] == "searched_no_parseable_candidates"
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
    assert report["search_state"] == "searched_no_parseable_candidates"
    assert report["search_summary"]["searched"] is True
    assert report["search_summary"]["successful_query_count"] == 2
    assert report["errors"]


def test_parse_bilibili_api_extracts_target_candidate() -> None:
    payload = {
        "code": 0,
        "data": {
            "result": [
                {
                    "bvid": "BV1MWJK6SE4X",
                    "title": "<em class=\"keyword\">哲学</em>的世界令人惊叹 - Xandros - 中配",
                    "arcurl": "https://www.bilibili.com/video/BV1MWJK6SE4X/?from=search",
                    "author": "旁白_B",
                    "duration": "41:46",
                    "pubdate": 1781456317,
                    "description": "Xandros philosophy 中文配音",
                }
            ]
        },
    }

    candidates = parse_bilibili_api_results(
        payload,
        query="哲学的世界令人惊叹",
        search_url="https://search.bilibili.com/video?keyword=x",
        api_url="https://api.bilibili.com/x/web-interface/search/type?keyword=x",
    )

    assert len(candidates) == 1
    assert candidates[0]["bvid"] == "BV1MWJK6SE4X"
    assert candidates[0]["title"] == "哲学 的世界令人惊叹 - Xandros - 中配"
    assert candidates[0]["duration_seconds"] == 2506
    assert candidates[0]["search_channel"] == "api"


def test_bilibili_captcha_page_is_channel_limited_signal() -> None:
    html = "<html><head><title>验证码_哔哩哔哩</title></head><body>安全验证</body></html>"

    assert is_bilibili_captcha_page(html) is True


def test_all_channel_limited_searches_are_unavailable_not_empty_results() -> None:
    meta = {
        "title": "The World Of Philosophy Is Incredible",
        "description": "",
        "author": "Xandros",
    }

    def limited_search(query: str, **kwargs) -> list[dict]:
        raise BilibiliSearchChannelLimited("Bilibili search channel limited by captcha/risk page", channel="html")

    report = build_bilibili_duplicate_report(
        "https://www.youtube.com/watch?v=r6pWz2FnFOk",
        meta,
        search_func=limited_search,
        max_queries=2,
        sleep_seconds=0,
    )

    assert report["decision"] == "search_unavailable_manual_review"
    assert report["search_state"] == "search_unavailable"
    assert report["search_summary"]["searched"] is False
    assert report["search_summary"]["channel_limited_query_count"] == 2
    assert all(query["fallback_manual_review"] is True for query in report["queries"])


def test_target_candidate_scores_to_front_when_api_finds_it() -> None:
    meta = {
        "video_id": "r6pWz2FnFOk",
        "title": "The World Of Philosophy Is Incredible",
        "description": "#philosophy #science #funny\nmusic by Ben Parr",
        "author": "Xandros",
        "published_at": "2026-06-06 05:00:36",
        "duration": 2506,
    }

    def fake_search(query: str, **kwargs) -> list[dict]:
        if query in {"哲学的世界令人惊叹", "哲学 世界 令人惊叹", "Xandros 中配"}:
            return [
                {
                    "title": "哲学的世界令人惊叹 - Xandros - 中配",
                    "url": "https://www.bilibili.com/video/BV1MWJK6SE4X",
                    "bvid": "BV1MWJK6SE4X",
                    "uploader": "旁白_B",
                    "duration": "41:46",
                    "published_at": "2026-06-15 00:58:37",
                    "description": "Xandros philosophy 中文配音",
                    "matched_queries": [query],
                    "source_search_url": "https://search.bilibili.com/video?keyword=x",
                    "search_channel": "api",
                }
            ]
        return []

    report = build_bilibili_duplicate_report(
        "https://www.youtube.com/watch?v=r6pWz2FnFOk&t=487s",
        meta,
        search_func=fake_search,
        max_queries=8,
        sleep_seconds=0,
    )

    assert report["search_state"] == "matched_candidates"
    assert report["best_candidate"]["bvid"] == "BV1MWJK6SE4X"
    assert report["best_candidate"]["score"] >= 60
    assert "title_translation_phrase_hit" in report["best_candidate"]["reason_codes"]
