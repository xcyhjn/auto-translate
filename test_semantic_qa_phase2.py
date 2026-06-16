from __future__ import annotations

from autosub_zh.models import BilingualSubtitleStyle, Segment, Word
from autosub_zh.semantic_allocation import build_semantic_allocation_report
from autosub_zh.segmentation_qa import build_segmentation_qa_metrics
from autosub_zh.source_repair import repair_source_segments
from autosub_zh.subtitle_io import DisplayCue
from autosub_zh.zh_reading_axis import group_short_complete_sentence_cues


def make_words(text: str, start: float, step: float = 0.2) -> list[Word]:
    words = []
    for index, raw in enumerate(text.split()):
        words.append(Word(word=raw, start=start + index * step, end=start + index * step + step * 0.8))
    return words


def test_semantic_allocation_flags_duplicate_and_short_targets() -> None:
    segments = [
        Segment(id=1, start=0.0, end=1.0, source_text="The city sleeps.", target_text="城市睡着了。"),
        Segment(id=2, start=1.1, end=2.0, source_text="He wonders.", target_text="城市睡着了。"),
        Segment(id=3, start=2.1, end=4.0, source_text="While translation isn't exciting", target_text="的"),
    ]
    source_spans = {
        "spans": [
            {"span_id": "srcspan-0001", "segment_ids": [1, 2, 3], "segment_count": 3, "risk_score": 9}
        ]
    }
    span_report = {"results": [{"span_id": "srcspan-0001", "status": "translated"}]}

    report = build_semantic_allocation_report(
        segments,
        source_spans,
        span_report,
        enabled=True,
    )

    assert report["summary"]["flagged_segment_count"] >= 2
    assert report["summary"]["adjacent_duplicate_target_count"] == 1
    assert "target_too_short" in report["summary"]["flag_counts"]


def test_display_grouping_merges_short_complete_sentences_without_touching_segments() -> None:
    segments = [
        Segment(id=1, start=0.0, end=0.7, source_text="The city sleeps.", target_text="城市睡着了。"),
        Segment(id=2, start=0.85, end=1.45, source_text="He wonders.", target_text="他在疑惑。"),
    ]
    cues = [
        DisplayCue(start=s.start, end=s.end, en_text=s.source_text, zh_text=s.target_text, words=s.words, source_segment_id=s.id)
        for s in segments
    ]

    grouped, report = group_short_complete_sentence_cues(cues)

    assert len(grouped) == 1
    assert grouped[0].start == 0.0
    assert grouped[0].end == 1.45
    assert [segment.start for segment in segments] == [0.0, 0.85]
    assert report["summary"]["group_count"] == 1


def test_source_repair_candidates_capture_mid_sentence_breaks() -> None:
    segments = [
        Segment(id=1, start=0.0, end=1.0, source_text="pinching his skin..."),
        Segment(id=2, start=1.1, end=2.0, source_text="it. Uri turns around."),
    ]

    report = repair_source_segments(segments, None)
    reasons = {
        candidate["reason"]
        for row in report["candidates"]
        for candidate in row["candidates"]
    }

    assert report["summary"]["candidate_count"] >= 2
    assert "ellipsis_tail" in reasons
    assert "punctuated_mid_sentence_break" in reasons


def test_source_repair_does_not_flag_safe_time_abbreviation() -> None:
    segments = [
        Segment(id=1, start=0.0, end=1.0, source_text="It's 3 a.m. on a workday. The city sleeps."),
    ]

    report = repair_source_segments(segments, None)
    reasons = {
        candidate["reason"]
        for row in report["candidates"]
        for candidate in row["candidates"]
    }

    assert "truncated_continuation" not in reasons


def test_segmentation_metrics_counts_core_qa_buckets() -> None:
    segments = [
        Segment(id=1, start=0.0, end=0.8, source_text="and then", target_text="然后"),
        Segment(id=2, start=1.0, end=3.0, source_text="He stops. He listens.", target_text="他停下。他听着。"),
    ]
    cues = [
        DisplayCue(start=s.start, end=s.end, en_text=s.source_text, zh_text=s.target_text, source_segment_id=s.id)
        for s in segments
    ]

    metrics = build_segmentation_qa_metrics(segments, cues)

    assert metrics["segmentation"]["short_fragment_count"] >= 1
    assert metrics["segmentation"]["mixed_sentence_count"] >= 1
    assert metrics["segmentation"]["function_edge_count"] >= 1
    assert metrics["segmentation"]["too_short_count"] == 1
