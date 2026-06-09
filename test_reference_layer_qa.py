from __future__ import annotations

from autosub_zh.qa import build_quality_metrics, qa_display_cues
from autosub_zh.subtitle_io import DisplayCue


def test_qa_display_cues_blocks_hidden_reference_text() -> None:
    cue = DisplayCue(
        start=0.0,
        end=2.0,
        en_text="",
        zh_text="\u4e2d\u6587\u5b57\u5e55",
        source_segment_id=1,
        rewrite_action="reference_hidden",
    )

    report = qa_display_cues([cue], dst_lang="zh-Hans")
    metrics = build_quality_metrics([], [cue], dst_lang="zh-Hans")

    assert any("reference text was hidden" in item for item in report.errors)
    assert metrics["display"]["reference_hidden_count"] == 1
    assert metrics["summary"]["blocking_issue_count"] == 1


def test_qa_display_cues_blocks_generated_reference_ellipsis() -> None:
    cue = DisplayCue(
        start=0.0,
        end=2.0,
        en_text="\u042d\u0442\u043e \u0434\u043b\u0438\u043d\u043d\u0430\u044f \u0440\u0435\u043f\u043b\u0438\u043a\u0430...",
        zh_text="\u4e2d\u6587\u5b57\u5e55",
        source_segment_id=1,
    )

    report = qa_display_cues([cue], dst_lang="zh-Hans")
    metrics = build_quality_metrics([], [cue], dst_lang="zh-Hans")

    assert any("ellipsized" in item for item in report.errors)
    assert metrics["display"]["reference_ellipsis_count"] == 1
    assert metrics["summary"]["blocking_issue_count"] == 1
