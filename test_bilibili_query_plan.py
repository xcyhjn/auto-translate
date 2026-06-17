from __future__ import annotations

from autosub_zh.bilibili_search import build_bilibili_query_plan


def test_english_title_generates_chinese_and_mixed_queries() -> None:
    meta = {
        "title": "The Russian book about a dying god",
        "description": "A short video essay about a strange Russian novel and its dying deity.",
        "author": "Example Channel",
    }

    plan = build_bilibili_query_plan(meta)
    query_text = "\n".join(item["text"] for item in plan)

    assert "The Russian book about a dying god" in query_text
    assert "垂死的神 俄罗斯 小说" in query_text
    assert "Russian book dying god" in query_text
    assert any(item["kind"] == "mixed_keywords" for item in plan)
    assert len(plan) <= 12


def test_query_plan_dedupes_queries_and_preserves_search_urls() -> None:
    meta = {
        "title": "Episode 01: The Russian book about a dying god (full version)",
        "description": "",
        "author": "Example Channel",
    }

    plan = build_bilibili_query_plan(meta)
    keys = [item["text"].lower().replace(" ", "") for item in plan]

    assert len(keys) == len(set(keys))
    assert all(item["search_url"].startswith("https://search.bilibili.com/video?keyword=") for item in plan)
