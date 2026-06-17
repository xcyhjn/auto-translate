from __future__ import annotations

from autosub_zh.bilibili_search import build_bilibili_query_plan, score_bilibili_candidate


YOUTUBE_META = {
    "video_id": "abc123XYZ09",
    "video_url": "https://www.youtube.com/watch?v=abc123XYZ09",
    "title": "The Russian book about a dying god",
    "description": "A video essay about a Russian novel where a god is dying.",
    "author": "Paper Trail",
    "published_at": "2025-01-10",
    "duration": 1200,
}


def test_core_keyword_match_scores_medium_without_same_original_title() -> None:
    plan = build_bilibili_query_plan(YOUTUBE_META)
    candidate = {
        "title": "垂死的神：一部俄罗斯小说的奇怪神明",
        "url": "https://www.bilibili.com/video/BV1xx411c7mD",
        "uploader": "搬运字幕组",
        "duration": "20:10",
        "published_at": "2025-02-01",
        "description": "转载 Paper Trail，附中文字幕。",
        "matched_queries": ["垂死的神 俄罗斯 小说"],
        "source_search_url": "https://search.bilibili.com/video?keyword=x",
    }

    scored = score_bilibili_candidate(candidate, YOUTUBE_META, plan)

    assert scored["score"] >= 60
    assert scored["confidence"] in {"medium_confidence_review", "high_confidence_possible_duplicate"}
    assert "semantic_keyword_hit" in scored["reason_codes"]
    assert "duration_close" in scored["reason_codes"] or "duration_near_exact" in scored["reason_codes"]


def test_single_generic_term_candidate_scores_low() -> None:
    plan = build_bilibili_query_plan(YOUTUBE_META)
    candidate = {
        "title": "一本书的故事",
        "url": "https://www.bilibili.com/video/BV1yy411c7mD",
        "uploader": "随便聊聊",
        "duration": "19:40",
        "published_at": "2025-02-01",
        "description": "",
        "matched_queries": ["书"],
        "source_search_url": "https://search.bilibili.com/video?keyword=x",
    }

    scored = score_bilibili_candidate(candidate, YOUTUBE_META, plan)

    assert scored["score"] < 40
    assert "single_generic_term_penalty" in scored["reason_codes"]


def test_large_duration_gap_is_penalized() -> None:
    plan = build_bilibili_query_plan(YOUTUBE_META)
    candidate = {
        "title": "垂死的神：俄罗斯小说解说",
        "url": "https://www.bilibili.com/video/BV1zz411c7mD",
        "uploader": "搬运字幕组",
        "duration": "1:30",
        "published_at": "2025-02-01",
        "description": "转载 Paper Trail",
        "matched_queries": ["垂死的神 俄罗斯 小说"],
        "source_search_url": "https://search.bilibili.com/video?keyword=x",
    }

    scored = score_bilibili_candidate(candidate, YOUTUBE_META, plan)

    assert "duration_mismatch_penalty" in scored["reason_codes"]
    assert "candidate_too_short" in scored["reason_codes"]
    assert scored["score"] < 60
