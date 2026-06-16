from __future__ import annotations

from autosub_zh.models import BilingualSubtitleStyle, Segment, Word
from autosub_zh.semantic_allocation import build_semantic_allocation_report
from autosub_zh.segmentation_qa import build_segmentation_qa_metrics
from autosub_zh.source_repair import repair_source_segments
from autosub_zh.subtitle_io import DisplayCue
from autosub_zh.zh_reading_axis import group_short_complete_sentence_cues, merge_orphan_tail_display_cues


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


def test_orphan_terminal_tail_display_merge_cleans_zh_tail() -> None:
    cues = [
        DisplayCue(
            start=97.67,
            end=100.29,
            en_text="that was made into an even more famous video game",
            zh_text="\u540e\u6765\u8fd8\u88ab\u6539\u7f16\u6210\u4e86\u66f4\u6709\u540d\u7684\u7535\u5b50\u6e38\u620f\u3002",
            source_segment_id=1,
        ),
        DisplayCue(
            start=100.37,
            end=102.37,
            en_text="franchise.",
            zh_text="\u7cfb\u5217\u3002",
            source_segment_id=2,
        ),
    ]

    merged, report = merge_orphan_tail_display_cues(cues)

    assert len(merged) == 1
    assert merged[0].en_text == "that was made into an even more famous video game franchise."
    assert merged[0].zh_text == "\u540e\u6765\u8fd8\u88ab\u6539\u7f16\u6210\u4e86\u66f4\u6709\u540d\u7684\u7535\u5b50\u6e38\u620f\u7cfb\u5217\u3002"
    assert report["summary"]["merged_orphan_tail_count"] == 2


def test_orphan_terminal_tail_display_merge_handles_suspicious_period() -> None:
    cues = [
        DisplayCue(
            start=178.47,
            end=180.0,
            en_text="These are rare and go for a lot of money on the property.",
            zh_text="\u8fd9\u4e9b\u623f\u5b50\u5f88\u7a00\u6709\uff0c\u5728\u623f\u4ea7\u5e02\u573a\u4e0a\u5f88\u503c\u94b1\u3002",
            source_segment_id=1,
        ),
        DisplayCue(
            start=180.08,
            end=180.47,
            en_text="market.",
            zh_text="\u5e02\u573a\u4e0a\u5f88\u503c\u94b1\u3002",
            source_segment_id=2,
        ),
    ]

    merged, report = merge_orphan_tail_display_cues(cues)

    assert len(merged) == 1
    assert merged[0].en_text.endswith("property market.")
    assert merged[0].zh_text == "\u8fd9\u4e9b\u623f\u5b50\u5f88\u7a00\u6709\uff0c\u5728\u623f\u4ea7\u5e02\u573a\u4e0a\u5f88\u503c\u94b1\u3002"
    assert report["summary"]["group_count"] == 1


def test_orphan_terminal_tail_display_merge_preserves_real_short_sentence() -> None:
    cues = [
        DisplayCue(start=0.0, end=0.7, en_text="Hello.", zh_text="\u4f60\u597d\u3002", source_segment_id=1),
        DisplayCue(start=0.85, end=1.4, en_text="Goodbye.", zh_text="\u518d\u89c1\u3002", source_segment_id=2),
    ]

    merged, report = merge_orphan_tail_display_cues(cues)

    assert [cue.en_text for cue in merged] == ["Hello.", "Goodbye."]
    assert report["summary"]["group_count"] == 0


def test_orphan_terminal_tail_display_merge_preserves_standalone_particle() -> None:
    cues = [
        DisplayCue(start=0.0, end=0.7, en_text="Are you coming?", zh_text="\u4f60\u6765\u5417\uff1f", source_segment_id=1),
        DisplayCue(start=1.0, end=1.2, en_text="No.", zh_text="\u4e0d\u3002", source_segment_id=2),
    ]

    merged, report = merge_orphan_tail_display_cues(cues)

    assert [cue.en_text for cue in merged] == ["Are you coming?", "No."]
    assert report["summary"]["group_count"] == 0


def test_orphan_terminal_tail_display_merge_absorbs_particle_word_after_open_fragment() -> None:
    cues = [
        DisplayCue(start=0.0, end=0.55, en_text="The answer is", zh_text="\u7b54\u6848\u662f", source_segment_id=1),
        DisplayCue(start=0.62, end=0.82, en_text="no.", zh_text="\u4e0d\u3002", source_segment_id=2),
    ]

    merged, report = merge_orphan_tail_display_cues(cues)

    assert [cue.en_text for cue in merged] == ["The answer is no."]
    assert merged[0].zh_text == "\u7b54\u6848\u662f\u4e0d\u3002"
    assert report["summary"]["group_count"] == 1


def test_orphan_terminal_tail_counts_as_blocking_metric() -> None:
    segments = [
        Segment(id=1, start=0.0, end=1.0, source_text="that was made into an even more famous video game"),
        Segment(id=2, start=1.05, end=2.0, source_text="franchise."),
    ]
    cues = [
        DisplayCue(start=0.0, end=1.0, en_text="that was made into an even more famous video game", zh_text="\u7535\u5b50\u6e38\u620f", source_segment_id=1),
        DisplayCue(start=1.05, end=2.0, en_text="franchise.", zh_text="\u7cfb\u5217\u3002", source_segment_id=2),
    ]

    metrics = build_segmentation_qa_metrics(segments, cues)

    assert metrics["segmentation"]["orphan_terminal_tail_count"] == 1
    assert metrics["summary"]["pass"] is False


def test_suspicious_closed_left_tail_counts_as_blocking_metric() -> None:
    segments = [
        Segment(id=1, start=0.0, end=1.0, source_text="These are rare on the property."),
        Segment(id=2, start=1.05, end=1.4, source_text="market."),
    ]
    cues = [
        DisplayCue(start=0.0, end=1.0, en_text="These are rare on the property.", zh_text="\u623f\u4ea7", source_segment_id=1),
        DisplayCue(start=1.05, end=1.4, en_text="market.", zh_text="\u5e02\u573a\u3002", source_segment_id=2),
    ]

    metrics = build_segmentation_qa_metrics(segments, cues)

    assert metrics["segmentation"]["orphan_terminal_tail_count"] == 1
    assert metrics["summary"]["pass"] is False


def test_discourse_particle_metrics_split_standalone_and_ambiguous() -> None:
    segments = [
        Segment(id=1, start=0.0, end=0.7, source_text="I don't know."),
        Segment(id=2, start=1.0, end=1.2, source_text="Yeah."),
        Segment(id=3, start=1.5, end=1.9, source_text="Is that"),
        Segment(id=4, start=2.0, end=2.2, source_text="right?"),
    ]
    cues = [
        DisplayCue(start=0.0, end=0.7, en_text="I don't know.", zh_text="\u6211\u4e0d\u77e5\u9053\u3002", source_segment_id=1),
        DisplayCue(start=1.0, end=1.2, en_text="Yeah.", zh_text="\u55ef\u3002", source_segment_id=2),
        DisplayCue(start=1.5, end=1.9, en_text="Is that", zh_text="\u90a3\u662f", source_segment_id=3),
        DisplayCue(start=2.0, end=2.2, en_text="right?", zh_text="\u5bf9\u5417\uff1f", source_segment_id=4),
    ]

    metrics = build_segmentation_qa_metrics(segments, cues)

    assert metrics["segmentation"]["standalone_discourse_particle_count"] == 1
    assert metrics["segmentation"]["ambiguous_discourse_tail_count"] == 0
    assert metrics["segmentation"]["orphan_terminal_tail_count"] == 1


def test_ambiguous_discourse_particle_is_review_not_blocker() -> None:
    segments = [
        Segment(id=1, start=0.0, end=0.8, source_text="I guess."),
        Segment(id=2, start=1.0, end=1.2, source_text="Right?"),
    ]
    cues = [
        DisplayCue(start=0.0, end=0.8, en_text="I guess.", zh_text="\u6211\u731c\u662f\u5427\u3002", source_segment_id=1),
        DisplayCue(start=1.0, end=1.2, en_text="Right?", zh_text="\u5bf9\u5427\uff1f", source_segment_id=2),
    ]

    metrics = build_segmentation_qa_metrics(segments, cues)

    assert metrics["segmentation"]["ambiguous_discourse_tail_count"] == 1
    assert metrics["segmentation"]["orphan_terminal_tail_count"] == 0
    assert metrics["summary"]["warning_issue_count"] >= 1
