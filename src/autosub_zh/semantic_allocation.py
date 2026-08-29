from __future__ import annotations

from collections import Counter
import re

from .models import Segment
from .subtitle_io import normalize_inline_text, split_by_meaning, visible_text_length
from .text_quality import contains_chinese, find_short_english_leaks


OPEN_ZH_SUFFIXES = ("，", "、", "；", "和", "与", "但", "而", "因为", "所以", "在", "从", "对", "的")
SENTENCE_END_RE = re.compile(r"[.!?。！？][\"'”’)\]]*$")
SOURCE_SENTENCE_RE = re.compile(r"(?<!\bMr)(?<!\bDr)(?<!\bMs)(?<!\bMrs)(?<!\be\.g)(?<!\bi\.e)[.!?]\s+")


def ends_sentence(text: str) -> bool:
    return bool(SENTENCE_END_RE.search(normalize_inline_text(text)))


def source_sentence_count(text: str) -> int:
    normalized = normalize_inline_text(text)
    if not normalized:
        return 0
    return len([part for part in SOURCE_SENTENCE_RE.split(normalized) if part.strip()])


def target_chunk_count(text: str) -> int:
    return len([part for part in split_by_meaning(text) if normalize_inline_text(part)])


def segment_allocation_flags(segment: Segment, *, span_segment_count: int) -> list[str]:
    source_text = normalize_inline_text(segment.source_text)
    target_text = normalize_inline_text(segment.target_text or "")
    flags: list[str] = []
    if not target_text:
        flags.append("empty_target")
        return flags
    if not contains_chinese(target_text) and re.search(r"[A-Za-z]", source_text):
        flags.append("target_without_chinese")
    if target_text.endswith(OPEN_ZH_SUFFIXES):
        flags.append("target_open_ending")
    if visible_text_length(target_text) <= 3 and visible_text_length(source_text) >= 18:
        flags.append("target_too_short")
    if find_short_english_leaks(target_text, dst_lang="zh-Hans"):
        flags.append("short_english_leak")
    if source_sentence_count(source_text) >= 2 and target_chunk_count(target_text) >= 2:
        flags.append("possible_two_sentence_target")
    if span_segment_count >= 2 and not ends_sentence(source_text) and target_text.endswith(("。", "！", "？")):
        flags.append("closed_translation_for_open_source")
    return flags


def build_semantic_allocation_report(
    segments: list[Segment],
    source_spans: dict | None,
    span_translation_report: dict | None,
    *,
    enabled: bool,
    max_spans: int = 16,
) -> dict:
    span_by_segment_id: dict[int, dict] = {}
    allowed_span_ids: set[str] | None = None
    if max_spans > 0:
        ranked_spans = sorted(
            [
                span
                for span in (source_spans or {}).get("spans") or []
                if isinstance(span, dict)
            ],
            key=lambda item: (-int(item.get("risk_score") or 0), int(item.get("start_segment_id") or 0)),
        )
        allowed_span_ids = {str(span.get("span_id")) for span in ranked_spans[:max_spans]}
    for span in (source_spans or {}).get("spans") or []:
        if not isinstance(span, dict):
            continue
        if allowed_span_ids is not None and str(span.get("span_id")) not in allowed_span_ids:
            continue
        for segment_id in span.get("segment_ids") or []:
            try:
                span_by_segment_id[int(segment_id)] = span
            except (TypeError, ValueError):
                continue

    translated_span_ids = {
        str(item.get("span_id"))
        for item in (span_translation_report or {}).get("results") or []
        if isinstance(item, dict) and item.get("status") == "translated"
    }

    allocations: list[dict] = []
    flag_counts: Counter[str] = Counter()
    duplicate_pairs = 0
    previous_target = ""
    previous_id: int | None = None
    applied_count = 0
    review_count = 0

    for segment in segments:
        span = span_by_segment_id.get(segment.id)
        target_text = normalize_inline_text(segment.target_text or "")
        source_text = normalize_inline_text(segment.source_text)
        span_id = str(span.get("span_id")) if span else ""
        span_segment_count = int(span.get("segment_count") or 1) if span else 1
        flags = segment_allocation_flags(segment, span_segment_count=span_segment_count)
        if previous_target and target_text and previous_target == target_text:
            flags.append("adjacent_duplicate_target")
            duplicate_pairs += 1
        for flag in flags:
            flag_counts[flag] += 1
        confidence = 0.92 if span_id in translated_span_ids else 0.76
        confidence -= min(0.55, 0.12 * len(set(flags)))
        confidence = round(max(0.05, confidence), 2)
        status = "applied" if enabled and target_text and confidence >= 0.58 else "review"
        if status == "applied":
            applied_count += 1
        else:
            review_count += 1
        allocations.append(
            {
                "segment_id": segment.id,
                "source_span_id": span_id,
                "start": segment.start,
                "end": segment.end,
                "source_text": source_text,
                "target_text": target_text,
                "allocation_confidence": confidence,
                "qa_flags": sorted(set(flags)),
                "allocation_status": status,
                "allocation_note": (
                    "span-first target accepted"
                    if status == "applied"
                    else "review semantic allocation before trusting this cue"
                ),
                "previous_segment_id": previous_id if previous_target == target_text and target_text else None,
            }
        )
        previous_target = target_text or previous_target
        previous_id = segment.id

    return {
        "schema_version": 1,
        "summary": {
            "enabled": bool(enabled),
            "segment_count": len(segments),
            "allocation_count": len(allocations),
            "applied_count": applied_count,
            "review_count": review_count,
            "translated_span_count": len(translated_span_ids),
            "flagged_segment_count": sum(1 for item in allocations if item["qa_flags"]),
            "adjacent_duplicate_target_count": duplicate_pairs,
            "flag_counts": dict(sorted(flag_counts.items())),
        },
        "allocations": allocations,
    }


def semantic_allocation_summary_for_segments(report: dict | None) -> dict:
    if not isinstance(report, dict):
        return {}
    summary = report.get("summary")
    return summary if isinstance(summary, dict) else {}
