from __future__ import annotations

from autosub_zh.style_rules import build_style_guidance
from autosub_zh.text_quality import find_short_english_leaks


def test_default_style_guidance_captures_editor_translation_preferences() -> None:
    guidance = build_style_guidance()

    assert "And I" in guidance
    assert "There is/there are" in guidance
    assert "Arabic numerals" in guidance
    assert "一个" in guidance
    assert "每一行" in guidance


def test_short_english_leak_detection_catches_there_is_fragments() -> None:
    assert find_short_english_leaks("There is这里有一个谜题。", dst_lang="zh-Hans") == ["There is"]
