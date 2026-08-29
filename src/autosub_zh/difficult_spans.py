from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .models import Segment
from .text_quality import (
    find_literal_chinese_artifacts,
    find_repeated_short_source_phrases,
    find_short_english_leaks,
    find_source_asr_suspicions,
    find_source_target_semantic_conflicts,
    find_text_pollution,
    find_untranslated_discourse_markers,
)


SOURCE_CONTINUATION_WORDS = {
    "and",
    "as",
    "because",
    "but",
    "for",
    "from",
    "how",
    "i",
    "if",
    "of",
    "or",
    "that",
    "then",
    "to",
    "when",
    "which",
    "while",
    "who",
    "with",
}
SOURCE_OPEN_END_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "his",
    "in",
    "into",
    "of",
    "on",
    "the",
    "to",
    "with",
}
TARGET_OPEN_SUFFIXES = (
    "，",
    "、",
    "；",
    "和",
    "与",
    "及",
    "并",
    "而",
    "但",
    "被",
    "把",
    "在",
    "从",
    "对",
    "向",
    "为",
    "由",
    "是",
    "以",
    "的",
)
SOURCE_SUSPICIOUS_WORDS = {
    "aifex",
    "afex",
    "synthetons",
    "sinthetons",
    "synthtons",
    "druckuse",
    "averall",
}
TERMINAL_RE = re.compile(r"[.!?。！？][\"')\]]*$")
LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'.-]*")


@dataclass(slots=True)
class SegmentRisk:
    segment_id: int
    index: int
    score: int = 0
    reasons: list[dict] = field(default_factory=list)

    def add(self, code: str, message: str, weight: int) -> None:
        self.reasons.append({"code": code, "message": message, "weight": weight})
        self.score += weight


def normalize_inline(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def visible_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def starts_with_continuation(text: str) -> bool:
    words = LATIN_WORD_RE.findall(text or "")
    return bool(words and words[0].casefold().strip(".'") in SOURCE_CONTINUATION_WORDS)


def ends_with_terminal(text: str) -> bool:
    return bool(TERMINAL_RE.search(normalize_inline(text)))


def ends_with_open_source_word(text: str) -> bool:
    words = LATIN_WORD_RE.findall(text or "")
    return bool(words and words[-1].casefold().strip(".'") in SOURCE_OPEN_END_WORDS)


def ends_with_open_target(text: str) -> bool:
    stripped = normalize_inline(text)
    return bool(stripped and stripped.endswith(TARGET_OPEN_SUFFIXES))


def extract_numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", text or "")


def suspicious_source_words(text: str) -> list[str]:
    found: list[str] = []
    for word in LATIN_WORD_RE.findall(text or ""):
        lowered = word.casefold().strip(".'")
        if lowered in SOURCE_SUSPICIOUS_WORDS:
            found.append(word)
    return found


def has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def evaluate_segment(segment: Segment, index: int, *, zh_max_cps: float = 18.0, zh_max_chars: int = 28) -> SegmentRisk:
    source_text = normalize_inline(segment.source_text)
    target_text = normalize_inline(segment.target_text or "")
    risk = SegmentRisk(segment_id=segment.id, index=index)

    if starts_with_continuation(source_text):
        risk.add("source_starts_with_continuation", "source cue starts with a continuation word", 1)
    if source_text and not ends_with_terminal(source_text):
        risk.add("source_open_clause", "source cue does not end at a sentence boundary", 1)
    if ends_with_open_source_word(source_text):
        risk.add("source_ends_with_open_word", "source cue ends with an open function word", 2)
    if ends_with_open_target(target_text):
        risk.add("target_open_ending", "Chinese target ends as an unfinished fragment", 2)
    if target_text and has_chinese(target_text) and visible_len(target_text) <= 3 and visible_len(source_text) >= 10:
        risk.add("target_too_short", "Chinese target is too short for the source cue", 4)

    pollution = find_text_pollution(target_text, dst_lang="zh-Hans")
    if pollution:
        risk.add("target_text_pollution", "; ".join(pollution), 6)
    discourse_markers = find_untranslated_discourse_markers(target_text, dst_lang="zh-Hans")
    if discourse_markers:
        risk.add(
            "target_untranslated_discourse_marker",
            "untranslated discourse marker(s): " + ", ".join(discourse_markers),
            6,
        )
    short_english_leaks = find_short_english_leaks(target_text, dst_lang="zh-Hans")
    if short_english_leaks:
        risk.add(
            "target_short_english_leak",
            "short English fragment(s): " + ", ".join(short_english_leaks),
            7,
        )

    suspicious_words = suspicious_source_words(source_text)
    if suspicious_words:
        risk.add("source_suspicious_asr_word", ", ".join(suspicious_words), 4)
    source_asr_suspicions = find_source_asr_suspicions(source_text)
    if source_asr_suspicions:
        risk.add("source_asr_suspicion", ", ".join(source_asr_suspicions), 5)
    repeated_source_phrases = find_repeated_short_source_phrases(source_text)
    if repeated_source_phrases:
        risk.add(
            "source_repeated_short_phrase",
            "repeated short phrase(s): " + "; ".join(repeated_source_phrases[:3]),
            4,
        )
    literal_artifacts = find_literal_chinese_artifacts(target_text, source_text=source_text)
    if literal_artifacts:
        risk.add("target_literal_chinese_artifact", ", ".join(literal_artifacts), 6)
    semantic_conflicts = find_source_target_semantic_conflicts(source_text, target_text)
    if semantic_conflicts:
        risk.add("source_target_semantic_conflict", ", ".join(semantic_conflicts), 7)

    source_numbers = extract_numbers(source_text)
    if source_numbers:
        target_numbers = set(extract_numbers(target_text))
        missing = [number for number in source_numbers if number not in target_numbers]
        if missing and visible_len(source_text) >= 12:
            risk.add("number_mismatch", f"numbers missing in target: {', '.join(missing)}", 2)

    duration = max(0.001, float(segment.end) - float(segment.start))
    if target_text and has_chinese(target_text):
        cps = visible_len(target_text) / duration
        if cps > zh_max_cps:
            weight = 2 if cps >= zh_max_cps * 1.25 else 1
            risk.add("target_cps_high", f"Chinese CPS {cps:.1f} > {zh_max_cps:.1f}", weight)
        if visible_len(target_text) > zh_max_chars:
            risk.add("target_line_long", f"Chinese length {visible_len(target_text)} > {zh_max_chars}", 1)

    return risk


def expand_span(segments: list[Segment], risks: list[SegmentRisk], center_index: int, *, max_span_size: int) -> tuple[int, int]:
    start = center_index
    end = center_index

    while start > 0 and end - start + 1 < max_span_size:
        previous = segments[start - 1]
        current = segments[start]
        if ends_with_terminal(previous.source_text) and not starts_with_continuation(current.source_text):
            break
        start -= 1

    while end < len(segments) - 1 and end - start + 1 < max_span_size:
        current = segments[end]
        following = segments[end + 1]
        current_risk_codes = {reason["code"] for reason in risks[end].reasons}
        should_continue = (
            not ends_with_terminal(current.source_text)
            or starts_with_continuation(following.source_text)
            or "target_open_ending" in current_risk_codes
            or "source_ends_with_open_word" in current_risk_codes
        )
        if not should_continue:
            break
        end += 1

    return start, end


def span_severity(score: int, reason_codes: set[str]) -> str:
    if reason_codes & {
        "target_text_pollution",
        "target_too_short",
        "source_suspicious_asr_word",
        "source_asr_suspicion",
        "source_target_semantic_conflict",
        "target_literal_chinese_artifact",
        "target_untranslated_discourse_marker",
        "target_short_english_leak",
    }:
        return "high"
    if "source_repeated_short_phrase" in reason_codes and score >= 8:
        return "high"
    if (
        "target_open_ending" in reason_codes
        and ("source_starts_with_continuation" in reason_codes or "source_ends_with_open_word" in reason_codes)
        and score >= 10
    ):
        return "high"
    if (
        score >= 14
        and "target_open_ending" in reason_codes
        and ("source_starts_with_continuation" in reason_codes or "source_ends_with_open_word" in reason_codes)
    ):
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def build_span(
    segments: list[Segment],
    risks: list[SegmentRisk],
    start: int,
    end: int,
    *,
    span_index: int,
) -> dict:
    span_segments = segments[start : end + 1]
    span_risks = risks[start : end + 1]
    reason_counter: Counter[str] = Counter(
        reason["code"]
        for risk in span_risks
        for reason in risk.reasons
    )
    reason_codes = set(reason_counter)
    score = sum(risk.score for risk in span_risks)
    severity = span_severity(score, reason_codes)
    return {
        "span_id": f"span-{span_index:04d}",
        "start_segment_id": span_segments[0].id,
        "end_segment_id": span_segments[-1].id,
        "start": span_segments[0].start,
        "end": span_segments[-1].end,
        "segment_count": len(span_segments),
        "score": score,
        "severity": severity,
        "action": "needs_ai_repair" if severity == "high" else "review",
        "reason_counts": dict(sorted(reason_counter.items())),
        "segments": [
            {
                "id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "source_text": segment.source_text,
                "target_text": segment.target_text or "",
                "risk_score": risk.score,
                "reasons": risk.reasons,
            }
            for segment, risk in zip(span_segments, span_risks)
        ],
        "source_joined": normalize_inline(" ".join(segment.source_text for segment in span_segments)),
        "target_joined": normalize_inline(" ".join(segment.target_text or "" for segment in span_segments)),
    }


def detect_difficult_spans(
    segments: list[Segment],
    *,
    zh_max_cps: float = 18.0,
    zh_max_chars: int = 28,
    max_span_size: int = 10,
) -> dict:
    risks = [
        evaluate_segment(segment, index, zh_max_cps=zh_max_cps, zh_max_chars=zh_max_chars)
        for index, segment in enumerate(segments)
    ]
    candidate_indexes = [risk.index for risk in risks if risk.score >= 2]

    ranges: list[tuple[int, int]] = []
    for index in candidate_indexes:
        start, end = expand_span(segments, risks, index, max_span_size=max_span_size)
        if ranges and start <= ranges[-1][1] + 1:
            previous_start, previous_end = ranges[-1]
            ranges[-1] = (previous_start, min(max(previous_end, end), previous_start + max_span_size - 1))
        else:
            ranges.append((start, end))

    spans = [
        build_span(segments, risks, start, end, span_index=span_index)
        for span_index, (start, end) in enumerate(ranges, start=1)
    ]
    severity_counts = Counter(span["severity"] for span in spans)
    action_counts = Counter(span["action"] for span in spans)
    return {
        "summary": {
            "segment_count": len(segments),
            "span_count": len(spans),
            "high_count": severity_counts.get("high", 0),
            "medium_count": severity_counts.get("medium", 0),
            "low_count": severity_counts.get("low", 0),
            "needs_ai_repair_count": action_counts.get("needs_ai_repair", 0),
            "review_count": action_counts.get("review", 0),
        },
        "spans": spans,
    }
