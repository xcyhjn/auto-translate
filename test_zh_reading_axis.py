from __future__ import annotations

from autosub_zh.models import BilingualSubtitleStyle, Segment, Word
from autosub_zh.qa import build_quality_metrics, qa_display_cues
from autosub_zh.zh_reading_axis import (
    ZhReadingAxisConfig,
    build_zh_display_cues,
    build_zh_reading_groups,
    source_reference_cues_from_segments,
)


def make_segment(segment_id: int, start: float, end: float, text: str) -> Segment:
    words = [
        Word(word=word, start=start + index * 0.2, end=start + index * 0.2 + 0.18)
        for index, word in enumerate(text.split())
    ]
    if words:
        words[-1].end = end
    return Segment(id=segment_id, start=start, end=end, source_text=text, words=words)


def test_short_russian_fragments_merge_into_one_reading_group() -> None:
    segments = [
        make_segment(1, 0.0, 0.6, "\u042f"),
        make_segment(2, 0.65, 1.3, "\u0432\u044b\u0431\u0440\u0430\u043b\u0430"),
        make_segment(3, 1.35, 2.6, "\u0432\u0442\u043e\u0440\u043e\u0439 \u0441\u0442\u0443\u0434\u0438\u0439\u043d\u0438\u043a."),
    ]

    groups = build_zh_reading_groups(segments)

    assert len(groups) == 1
    assert groups[0].source_segment_ids == [1, 2, 3]
    assert groups[0].start == 0.0
    assert groups[0].end == 2.6


def test_complete_short_sentence_is_not_split_for_display() -> None:
    segment = Segment(
        id=1,
        start=0.0,
        end=4.0,
        source_text="source",
        target_text="\u6211\u9009\u4e86\u4ed6\u4eec\u7684\u7b2c2\u5f20\u5f55\u97f3\u5ba4\u4e13\u8f91\u3002",
    )

    cues = build_zh_display_cues([segment], style=BilingualSubtitleStyle(), config=ZhReadingAxisConfig())

    assert len(cues) == 1
    assert cues[0].start == 0.0
    assert cues[0].end == 4.0


def test_long_or_overflowing_chinese_group_splits_for_display() -> None:
    segment = Segment(
        id=1,
        start=0.0,
        end=9.2,
        source_text="source",
        target_text=(
            "\u8fd9\u5f20\u4e13\u8f91\u628a\u8106\u5f31\u7684\u6c11\u8c23\u3001"
            "\u5b9e\u9a8c\u566a\u97f3\u548c\u88ab\u521b\u4f24\u7684\u5185\u5fc3\u4e16\u754c\u653e\u5728\u4e00\u8d77\u3002"
        ),
    )

    cues = build_zh_display_cues([segment], style=BilingualSubtitleStyle(), config=ZhReadingAxisConfig())

    assert len(cues) == 2
    assert cues[0].zh_text != cues[1].zh_text
    assert cues[-1].end == 9.2


def test_source_reference_cues_keep_word_timing() -> None:
    segment = make_segment(1, 10.0, 12.0, "\u041f\u0440\u0438\u0432\u0435\u0442 \u0432\u0441\u0435\u043c.")
    segment.start = 9.5
    segment.end = 13.0

    cues = source_reference_cues_from_segments([segment], reference_lang="ru")

    assert len(cues) == 1
    assert cues[0].start == 10.0
    assert cues[0].end == 12.0
    assert cues[0].zh_text is None


def test_dual_axis_qa_allows_unbound_reference_cues() -> None:
    source_cue = source_reference_cues_from_segments(
        [make_segment(1, 0.0, 1.0, "\u041f\u0440\u0438\u0432\u0435\u0442.")],
        reference_lang="ru",
    )[0]
    zh_cue = build_zh_display_cues(
        [
            Segment(
                id=1,
                start=0.0,
                end=3.0,
                source_text="\u041f\u0440\u0438\u0432\u0435\u0442.",
                target_text="\u5927\u5bb6\u597d\u3002",
            )
        ],
        style=BilingualSubtitleStyle(),
    )[0]

    report = qa_display_cues([zh_cue, source_cue], dst_lang="zh-Hans", require_bound_zh=False)
    metrics = build_quality_metrics([], [zh_cue, source_cue], dst_lang="zh-Hans", require_bound_zh=False)

    assert not report.errors
    assert metrics["display"]["empty_chinese_cue_count"] == 0
