from __future__ import annotations

import re
from collections import Counter

from .difficult_spans import (
    SOURCE_CONTINUATION_WORDS,
    ends_with_open_source_word,
    ends_with_terminal,
    normalize_inline,
    starts_with_continuation,
    suspicious_source_words,
)
from .models import Segment
from .text_quality import find_repeated_short_source_phrases, find_source_asr_suspicions


MAX_SOURCE_SPAN_SIZE = 8
MAX_SOURCE_SPAN_DURATION = 18.0
SPAN_FIRST_MAX_SEGMENTS = 4
SPAN_FIRST_MAX_DURATION = 12.0
SPAN_FIRST_MIN_RISK_SCORE = 10
SOFT_JOIN_GAP = 0.35
MEDIUM_JOIN_GAP = 0.75
LONG_SOURCE_CHARS = 120
COMPLEX_SOURCE_COMMAS = 2
COMMA_RE = re.compile(r"[,;:]")
INTERNAL_SENTENCE_RE = re.compile(r"(?<!\b[ap])(?<!\b[mM])(?<!\bMr)(?<!\bDr)([.!?])\s+(?=[A-Z0-9])")
LATIN_WORD_COUNT_RE = re.compile(r"[A-Za-z0-9']+")
SOURCE_SPAN_POLICY_VERSION = "source_spans_v2"


def source_word_count(text: str) -> int:
    return len(LATIN_WORD_COUNT_RE.findall(text or ""))


def segment_gap(left: Segment, right: Segment) -> float:
    return max(0.0, float(right.start) - float(left.end))


def source_segment_reasons(segment: Segment, previous: Segment | None, following: Segment | None) -> list[str]:
    text = normalize_inline(segment.source_text)
    reasons: list[str] = []
    if not text:
        return ["empty_source"]
    if starts_with_continuation(text):
        reasons.append("starts_with_continuation")
    if ends_with_open_source_word(text):
        reasons.append("ends_with_function_word")
    if not ends_with_terminal(text):
        reasons.append("open_clause")
    if source_word_count(text) <= 8 and not ends_with_terminal(text):
        reasons.append("short_open_fragment")
    if INTERNAL_SENTENCE_RE.search(text):
        reasons.append("internal_sentence_boundary")
    if suspicious_source_words(text):
        reasons.append("suspicious_asr_word")
    source_asr_suspicions = find_source_asr_suspicions(
        text,
        context_text=" ".join(
            item.source_text
            for item in (previous, segment, following)
            if item is not None
        ),
    )
    if source_asr_suspicions:
        reasons.extend(f"source_asr_{reason}" for reason in source_asr_suspicions)
    if find_repeated_short_source_phrases(text):
        reasons.append("repeated_short_phrase")
    if COMMA_RE.search(text) and len(text) >= 50:
        reasons.append("internal_clause_boundary")
    if previous and segment_gap(previous, segment) <= SOFT_JOIN_GAP and starts_with_continuation(text):
        reasons.append("tight_previous_continuation")
    if following and segment_gap(segment, following) <= SOFT_JOIN_GAP and not ends_with_terminal(text):
        reasons.append("tight_next_open_clause")
    return reasons


def should_join(current: Segment, following: Segment, current_reasons: set[str], following_reasons: set[str]) -> bool:
    gap = segment_gap(current, following)
    current_text = normalize_inline(current.source_text)
    following_text = normalize_inline(following.source_text)
    if not current_text or not following_text:
        return False
    if gap <= SOFT_JOIN_GAP and not ends_with_terminal(current_text):
        return True
    if gap <= MEDIUM_JOIN_GAP and (
        "ends_with_function_word" in current_reasons
        or "starts_with_continuation" in following_reasons
        or "short_open_fragment" in current_reasons
        or "short_open_fragment" in following_reasons
        or "tight_next_open_clause" in current_reasons
    ):
        return True
    if starts_with_continuation(following_text) and not ends_with_terminal(current_text):
        return True
    return False


def source_span_risk_score(reason_counts: Counter[str], source_joined: str, duration: float) -> int:
    risk_score = (
        reason_counts.get("suspicious_asr_word", 0) * 5
        + sum(int(count) * 5 for reason, count in reason_counts.items() if str(reason).startswith("source_asr_"))
        + reason_counts.get("repeated_short_phrase", 0) * 3
        + reason_counts.get("ends_with_function_word", 0) * 3
        + reason_counts.get("short_open_fragment", 0) * 3
        + reason_counts.get("internal_sentence_boundary", 0) * 2
        + reason_counts.get("starts_with_continuation", 0) * 2
        + reason_counts.get("open_clause", 0)
        + max(0, len(source_joined) - LONG_SOURCE_CHARS) // 30
    )
    if duration > MAX_SOURCE_SPAN_DURATION:
        risk_score += 2
        reason_counts["long_duration"] += 1
    return risk_score


def has_strong_span_first_reason(reason_counts: Counter[str]) -> bool:
    if reason_counts.get("repeated_short_phrase"):
        return True
    if reason_counts.get("ends_with_function_word") and reason_counts.get("starts_with_continuation"):
        return True
    if reason_counts.get("ends_with_function_word") and reason_counts.get("tight_previous_continuation"):
        return True
    if any(reason.startswith("source_asr_") for reason in reason_counts):
        return True
    return False


def span_strategy(
    reason_counts: Counter[str],
    source_joined: str,
    segment_count: int,
    *,
    duration: float,
    risk_score: int,
) -> str:
    if reason_counts.get("suspicious_asr_word"):
        return "source_repair_review"
    if any(reason.startswith("source_asr_") for reason in reason_counts):
        return "source_repair_review"
    if (
        segment_count <= SPAN_FIRST_MAX_SEGMENTS
        and duration <= SPAN_FIRST_MAX_DURATION
        and risk_score >= SPAN_FIRST_MIN_RISK_SCORE
        and has_strong_span_first_reason(reason_counts)
    ):
        return "span_first"
    if reason_counts.get("internal_sentence_boundary"):
        return "span_context"
    if segment_count >= 2 and (
        reason_counts.get("starts_with_continuation")
        or reason_counts.get("ends_with_function_word")
        or reason_counts.get("short_open_fragment")
        or reason_counts.get("open_clause", 0) >= 2
    ):
        return "span_context"
    if len(source_joined) >= LONG_SOURCE_CHARS or source_joined.count(",") >= COMPLEX_SOURCE_COMMAS:
        return "span_context"
    return "normal"


def build_source_span(segments: list[Segment], start: int, end: int, reasons_by_index: dict[int, list[str]], index: int) -> dict:
    span_segments = segments[start : end + 1]
    reason_counts: Counter[str] = Counter(
        reason
        for segment_index in range(start, end + 1)
        for reason in reasons_by_index.get(segment_index, [])
    )
    source_joined = normalize_inline(" ".join(segment.source_text for segment in span_segments))
    duration = max(0.0, float(span_segments[-1].end) - float(span_segments[0].start))
    risk_score = source_span_risk_score(reason_counts, source_joined, duration)
    strategy = span_strategy(
        reason_counts,
        source_joined,
        len(span_segments),
        duration=duration,
        risk_score=risk_score,
    )
    return {
        "span_id": f"srcspan-{index:04d}",
        "start_segment_id": span_segments[0].id,
        "end_segment_id": span_segments[-1].id,
        "segment_ids": [segment.id for segment in span_segments],
        "start": span_segments[0].start,
        "end": span_segments[-1].end,
        "duration": round(duration, 3),
        "segment_count": len(span_segments),
        "risk_score": risk_score,
        "risk_reasons": dict(sorted(reason_counts.items())),
        "translation_strategy": strategy,
        "source_joined": source_joined,
        "segments": [
            {
                "id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "source_text": segment.source_text,
                "reasons": reasons_by_index.get(segment_index, []),
            }
            for segment_index, segment in enumerate(span_segments, start=start)
        ],
    }


def detect_source_spans(segments: list[Segment], *, max_span_size: int = MAX_SOURCE_SPAN_SIZE) -> dict:
    reasons_by_index: dict[int, list[str]] = {}
    for index, segment in enumerate(segments):
        previous = segments[index - 1] if index > 0 else None
        following = segments[index + 1] if index < len(segments) - 1 else None
        reasons_by_index[index] = source_segment_reasons(segment, previous, following)

    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(segments):
        end = start
        while end < len(segments) - 1 and end - start + 1 < max_span_size:
            current_reasons = set(reasons_by_index.get(end, []))
            following_reasons = set(reasons_by_index.get(end + 1, []))
            if not should_join(segments[end], segments[end + 1], current_reasons, following_reasons):
                break
            end += 1
        if end > start:
            ranges.append((start, end))
        else:
            reasons = set(reasons_by_index.get(start, []))
            text = normalize_inline(segments[start].source_text)
            if (
                "suspicious_asr_word" in reasons
                or any(reason.startswith("source_asr_") for reason in reasons)
                or "repeated_short_phrase" in reasons
                or "short_open_fragment" in reasons
                or "internal_sentence_boundary" in reasons
                or len(text) >= LONG_SOURCE_CHARS
                or text.count(",") >= COMPLEX_SOURCE_COMMAS
            ):
                ranges.append((start, start))
        start = end + 1

    spans = [
        build_source_span(segments, start, end, reasons_by_index, index)
        for index, (start, end) in enumerate(ranges, start=1)
    ]
    strategy_counts = Counter(str(span["translation_strategy"]) for span in spans)
    return {
        "schema_version": 1,
        "policy_version": SOURCE_SPAN_POLICY_VERSION,
        "summary": {
            "segment_count": len(segments),
            "span_count": len(spans),
            "span_first_count": strategy_counts.get("span_first", 0),
            "span_context_count": strategy_counts.get("span_context", 0),
            "source_repair_review_count": strategy_counts.get("source_repair_review", 0),
            "normal_count": strategy_counts.get("normal", 0),
        },
        "spans": spans,
    }
