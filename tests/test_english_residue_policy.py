from __future__ import annotations

import json

from autosub_zh.english_residue_policy import build_english_residue_report, score_english_residue
from autosub_zh.models import Segment
from autosub_zh.span_translate import validate_span_translations
from autosub_zh.translate import validate_translations
from autosub_zh.translate import resolve_preserve_only_translation


def score(candidate: str, *, source_text: str | None = None, target_text: str | None = None) -> int:
    return score_english_residue(
        candidate,
        source_text=source_text or candidate,
        target_text=target_text or f"这是 {candidate}。",
        reference_text=source_text or candidate,
    ).preserve_score


def test_common_names_places_and_terms_do_not_pass_preserve_threshold() -> None:
    assert score("Moscow") < 85
    assert score("Yucatan") < 85
    assert score("Spanish") < 85
    assert score("World War II") < 85
    assert score("Dmitri Alexeovich") < 85
    assert score("Yuri Andreevich Knorosov") < 85


def test_discourse_and_plain_words_score_near_zero_in_chinese_lines() -> None:
    assert score("well", target_text="well，这不对。") <= 15
    assert score("yeah", target_text="yeah，我知道。") <= 15
    assert score("and", target_text="and 然后他走了。") <= 15
    assert score("Chapter", target_text="标题是 Chapter 2。") <= 40


def test_code_software_and_paths_can_be_preserved() -> None:
    assert score("Node.js", target_text="项目使用 Node.js。") >= 85
    assert score("ffmpeg", target_text="用 ffmpeg 烧录字幕。") >= 85
    assert score(r"C:\path\file.srt", target_text=r"文件在 C:\path\file.srt。") >= 85
    assert score("Ctrl+C", target_text="按 Ctrl+C 取消。") >= 85


def test_glossary_preserve_and_translate_policies_override_scores() -> None:
    preserve = score_english_residue(
        "Metro 2033",
        source_text="Metro 2033",
        target_text="《Metro 2033》很好。",
        glossary_text="- Metro 2033 | zh=Metro 2033 | policy=preserve | priority=hard",
    )
    translate = score_english_residue(
        "Metro",
        source_text="Metro",
        target_text="Metro 系列。",
        glossary_text="- Metro | zh=地铁 | policy=translate",
    )

    assert preserve.preserve_score == 100
    assert preserve.decision == "preserve"
    assert translate.preserve_score < 85
    assert translate.decision == "translate"


def test_auto_glossary_preserve_does_not_auto_allow_person_names() -> None:
    decision = score_english_residue(
        "Dmitri",
        source_text="Dmitri waits.",
        target_text="Dmitri 在等待。",
        glossary_text="- Dmitri | zh=Dmitri | policy=preserve | sources=asr_count:30",
    )

    assert decision.preserve_score < 85
    assert decision.decision != "preserve"
    assert "auto_glossary_preserve_needs_review" in decision.reason_codes


def test_translate_validation_blocks_low_score_english_residue() -> None:
    segment = Segment(id=1, start=0.0, end=2.0, source_text="I live in Moscow.")
    issues = validate_translations(
        [segment],
        {1: "我住在 Moscow。"},
        dst_lang="zh-Hans",
        glossary_text="",
    )

    assert issues["english_residue"] == [1]


def test_translate_validation_blocks_pure_low_score_person_name() -> None:
    segment = Segment(id=1, start=0.0, end=2.0, source_text="Juan Kokom.")
    issues = validate_translations(
        [segment],
        {1: "Juan Kokom."},
        dst_lang="zh-Hans",
        glossary_text="",
    )

    assert issues["english_residue"] == [1]


def test_span_validation_blocks_low_score_english_residue() -> None:
    segment = Segment(id=1, start=0.0, end=2.0, source_text="Juan Kokom tells the conquistador.")
    issues = validate_span_translations(
        [segment],
        {1: "Juan Kokom 告诉征服者。"},
        dst_lang="zh-Hans",
    )

    assert issues["english_residue"] == [1]


def test_report_summarizes_blocking_review_and_preserved_items() -> None:
    segments = [
        Segment(id=1, start=0, end=1, source_text="I live in Moscow.", target_text="我住在 Moscow。"),
        Segment(id=2, start=1, end=2, source_text="Use Node.js.", target_text="使用 Node.js。"),
    ]
    report = build_english_residue_report(segments, dst_lang="zh-Hans")

    assert report["summary"]["english_residue_total_count"] == 2
    assert report["summary"]["english_residue_blocking_count"] == 1
    assert report["summary"]["english_residue_preserved_count"] == 1
    assert report["summary"]["pass"] is False
    json.dumps(report, ensure_ascii=False)


def test_preserve_only_translation_requires_exact_normalized_match() -> None:
    preserve_map = {
        "thetranslationfollows": "The Translation Follows",
    }

    assert resolve_preserve_only_translation("translation.", preserve_map) is None
    assert resolve_preserve_only_translation("The Translation Follows", preserve_map) == "The Translation Follows"
