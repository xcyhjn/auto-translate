from __future__ import annotations

from autosub_zh.difficult_spans import detect_difficult_spans
from autosub_zh.glossary import apply_translate_policy_corrections, generate_asr_terms
from autosub_zh.models import Segment
from autosub_zh.qa import qa_check, qa_final_ass_file, qa_glossary_consistency
from autosub_zh.source_repair import repair_source_segments
from autosub_zh.text_quality import find_short_english_leaks


def test_builtin_source_repair_handles_whisper_asr_errors() -> None:
    segments = [
        Segment(id=1, start=0.0, end=1.0, source_text="Good boy."),
        Segment(
            id=2,
            start=1.0,
            end=3.0,
            source_text="I hope it does. I'll bet you. I'll bet you. I hope it does.",
        ),
        Segment(id=3, start=3.0, end=5.0, source_text="You don't need me to give me the world."),
        Segment(id=4, start=5.0, end=6.0, source_text="I love."),
    ]

    report = repair_source_segments(segments, None)

    assert segments[1].source_text == "I hope it does. I'll pet you. I'll pet you. I hope it does."
    assert segments[2].source_text == "You don't need to give me the world."
    assert segments[3].source_text == "I love you."
    assert report["summary"]["repaired_segment_count"] == 3
    assert report["summary"]["replacement_count"] == 4


def test_difficult_spans_flags_literal_chinese_and_semantic_conflicts() -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="I'll bet you forever.",
            target_text="我会一直抚摸你。",
        ),
        Segment(
            id=2,
            start=3.0,
            end=5.0,
            source_text="as long as I have you to comfort, I am complete.",
            target_text="只要还有你让我安慰，我就完整了。",
        ),
    ]

    result = detect_difficult_spans(segments)

    assert result["summary"]["needs_ai_repair_count"] >= 1
    reason_counts = {}
    for span in result["spans"]:
        reason_counts.update(span["reason_counts"])
    assert "source_target_semantic_conflict" in reason_counts
    assert "target_literal_chinese_artifact" in reason_counts


def test_common_proper_nouns_are_hard_translate_terms() -> None:
    segments = [
        Segment(id=1, start=0.0, end=2.0, source_text="Post World War II, Japan rebuilt Tokyo."),
        Segment(id=2, start=2.0, end=4.0, source_text="Japan sits near Tokyo."),
        Segment(id=3, start=4.0, end=6.0, source_text="Tokyo's cables are chaotic."),
    ]

    glossary = generate_asr_terms(segments, min_count=1)
    terms = {item["canonical"]: item for item in glossary["terms"]}

    assert terms["World War II"]["policy"] == "translate"
    assert terms["World War II"]["priority"] == "hard"
    assert terms["World War II"]["zh"] == "二战"
    assert terms["Japan"]["zh"] == "日本"
    assert terms["Tokyo"]["zh"] == "东京"


def test_translate_policy_corrections_replace_common_english_terms(tmp_path) -> None:
    glossary_path = tmp_path / "glossary.json"
    glossary_path.write_text(
        """
{
  "version": 1,
  "terms": [
    {"canonical": "Japan", "zh": "日本", "policy": "translate", "priority": "hard", "aliases": ["Japan's"], "sources": ["test"]},
    {"canonical": "Tokyo", "zh": "东京", "policy": "translate", "priority": "hard", "aliases": ["Tokyo's"], "sources": ["test"]},
    {"canonical": "World War II", "zh": "二战", "policy": "translate", "priority": "hard", "sources": ["test"]}
  ]
}
""".strip(),
        encoding="utf-8",
    )
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="Post World War II, Japan wasn't just rebuilding.",
            target_text="World War II之后，Japan不只是在重建。",
        ),
        Segment(
            id=2,
            start=2.0,
            end=4.0,
            source_text="Tokyo's cables are underground.",
            target_text="Tokyo's也只有15%的电缆在地下。",
        ),
    ]

    stats = apply_translate_policy_corrections(segments, glossary_path)

    assert stats["target_text_replacements"] == 3
    assert segments[0].target_text == "二战之后，日本不只是在重建。"
    assert segments[1].target_text == "东京也只有15%的电缆在地下。"


def test_qa_blocks_hard_translate_terms_left_in_english(tmp_path) -> None:
    glossary_path = tmp_path / "glossary.json"
    glossary_path.write_text(
        """
{
  "version": 1,
  "terms": [
    {"canonical": "Japan", "zh": "日本", "policy": "translate", "priority": "hard", "sources": ["test"]}
  ]
}
""".strip(),
        encoding="utf-8",
    )
    segments = [
        Segment(id=1, start=0.0, end=2.0, source_text="Japan rebuilt quickly.", target_text="Japan迅速重建。")
    ]

    report = qa_glossary_consistency(segments, glossary_path)

    assert report.errors
    assert "expected zh '日本'" in report.errors[0]


def test_short_english_leaks_are_blocking_translation_errors() -> None:
    leaks = find_short_english_leaks("And I他妈太喜欢了。", dst_lang="zh-Hans")

    assert "And" in leaks
    assert "I" in leaks
    assert find_short_english_leaks("That`s问题。", dst_lang="zh-Hans") == ["That's"]

    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="And I love it.",
            target_text="And I他妈太喜欢了。",
        )
    ]

    qa_report = qa_check(segments, dst_lang="zh-Hans")
    difficult = detect_difficult_spans(segments)

    assert any("short English fragment" in error for error in qa_report.errors)
    assert any("target_short_english_leak" in span["reason_counts"] for span in difficult["spans"])


def test_final_ass_qa_blocks_short_english_leaks(tmp_path) -> None:
    ass_path = tmp_path / "leak.ass"
    ass_path.write_text(
        "\n".join(
            [
                "[Script Info]",
                "Title: test",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,And I他妈太喜欢了。",
                "Dialogue: 1,0:00:00.00,0:00:02.00,EnglishSmall,,0,0,0,,And I love it.",
            ]
        ),
        encoding="utf-8",
    )

    report = qa_final_ass_file(ass_path, dst_lang="zh-Hans")

    assert any("short English fragment" in error for error in report.errors)
