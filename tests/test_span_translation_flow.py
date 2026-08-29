from __future__ import annotations

from autosub_zh.models import Segment
from autosub_zh.pipeline_core import load_span_translation_checkpoint
from autosub_zh.segment_io import save_segments_payload
from autosub_zh.source_spans import detect_source_spans
from autosub_zh.span_translate import (
    build_span_translation_prompt,
    build_span_translation_fingerprint,
    read_span_examples,
    select_span_prompt_examples,
    select_span_translation_candidates,
)


def make_segment(segment_id: int, start: float, end: float, text: str) -> Segment:
    return Segment(id=segment_id, start=start, end=end, source_text=text)


def test_source_spans_downgrades_long_open_context_from_span_first() -> None:
    segments = [
        make_segment(1, 0.0, 2.0, "The silence is only broken by the mechanical"),
        make_segment(2, 2.1, 4.0, "clicking of an old typewriter."),
        make_segment(3, 4.1, 6.0, "Dmitri works another long night,"),
        make_segment(4, 6.1, 8.0, "as he usually does."),
        make_segment(5, 8.1, 10.0, "While translation is not exciting,"),
        make_segment(6, 10.1, 12.0, "something has taken an interest"),
        make_segment(7, 12.1, 14.0, "in his current commission."),
    ]

    source_spans = detect_source_spans(segments)

    assert source_spans["summary"]["span_first_count"] == 0
    assert source_spans["summary"]["span_context_count"] >= 1


def test_source_spans_keeps_short_high_risk_span_first_candidate() -> None:
    segments = [
        make_segment(1, 0.0, 2.0, "He told me just before leaving, and"),
        make_segment(2, 2.1, 4.0, "and the next day the police"),
        make_segment(3, 4.1, 6.0, "knocked on his door."),
    ]

    source_spans = detect_source_spans(segments)

    assert source_spans["summary"]["span_first_count"] == 1


def test_span_translation_candidates_reject_long_and_low_risk_spans() -> None:
    source_spans = {
        "spans": [
            {
                "span_id": "long",
                "translation_strategy": "span_first",
                "segment_ids": [1, 2, 3, 4, 5],
                "segment_count": 5,
                "duration": 14.0,
                "risk_score": 50,
            },
            {
                "span_id": "low",
                "translation_strategy": "span_first",
                "segment_ids": [6, 7],
                "segment_count": 2,
                "duration": 4.0,
                "risk_score": 8,
            },
            {
                "span_id": "good",
                "translation_strategy": "span_first",
                "segment_ids": [8, 9],
                "segment_count": 2,
                "duration": 4.0,
                "risk_score": 32,
            },
        ]
    }

    candidates = select_span_translation_candidates(source_spans, max_spans=8)

    assert [candidate["span_id"] for candidate in candidates] == ["good"]


def test_span_translation_checkpoint_requires_matching_fingerprint(tmp_path) -> None:
    segments = [make_segment(1, 0.0, 1.0, "Node.js.")]
    source_spans = {"spans": []}
    fingerprint = build_span_translation_fingerprint(
        segments,
        source_spans,
        glossary_text="Node.js => Node.js",
        model="gpt-test",
    )
    path = tmp_path / "05a_span_translated_segments.json"
    segments[0].target_text = "Node.js"
    save_segments_payload(
        segments,
        path,
        summary={"fingerprint": fingerprint, "translated_segment_count": 1},
    )

    reused = load_span_translation_checkpoint(path, segments, expected_fingerprint=fingerprint)
    stale = load_span_translation_checkpoint(
        path,
        segments,
        expected_fingerprint={**fingerprint, "model": "different-model"},
    )

    assert reused is not None
    assert reused[1] == {1}
    assert stale is None


def test_span_prompt_examples_are_loaded_ranked_and_injected(tmp_path) -> None:
    examples_path = tmp_path / "span_translation_examples.jsonl"
    examples_path.write_text(
        "\n".join(
            [
                '{"accepted":true,"use_for_span_prompt":true,"use_for_eval":false,"learning_risk":"low","project_id":"p","span_id":"match","segment_ids":[1,2],"source_joined":"before leaving and the next day police","risk_reasons":{"ends_with_function_word":1},"translation_strategy":"span_first","manual_target_by_id":{"1":"他离开前说","2":"第二天警方来了"},"edit_tags":["fragment_completion"]}',
                '{"accepted":true,"use_for_span_prompt":true,"use_for_eval":false,"learning_risk":"low","project_id":"p","span_id":"other","segment_ids":[5],"source_joined":"beer and coffee","risk_reasons":{"internal_clause_boundary":1},"translation_strategy":"span_context","manual_target_by_id":{"5":"啤酒和咖啡"},"edit_tags":["compress_span"]}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    examples = read_span_examples(examples_path)
    span = {
        "span_id": "new",
        "segment_ids": [1, 2],
        "duration": 4.0,
        "source_joined": "He told me before leaving and the next day the police",
        "risk_reasons": {"ends_with_function_word": 1},
        "translation_strategy": "span_first",
    }

    ranked = select_span_prompt_examples(span, examples, top_k=1)
    prompt = build_span_translation_prompt(
        span=span,
        span_segments=[
            make_segment(1, 0.0, 1.0, "He told me before leaving and"),
            make_segment(2, 1.1, 2.0, "the next day the police"),
        ],
        context_before=[],
        context_after=[],
        src_lang="en",
        dst_lang="zh",
        glossary_text="",
        style_prompt_text="",
        span_prompt_examples=ranked,
    )

    assert ranked[0]["span_id"] == "match"
    assert "Matched local span examples JSON" in prompt
    assert "他离开前说" in prompt


def test_span_fingerprint_changes_with_examples() -> None:
    segments = [make_segment(1, 0.0, 1.0, "He told me before leaving and")]
    source_spans = {"spans": []}
    base = build_span_translation_fingerprint(segments, source_spans, model="gpt-test")
    learned = build_span_translation_fingerprint(
        segments,
        source_spans,
        model="gpt-test",
        span_examples=[{"project_id": "p", "span_id": "s", "segment_ids": [1], "manual_target_by_id": {"1": "他说"}}],
    )

    assert base["span_examples_hash"] != learned["span_examples_hash"]
