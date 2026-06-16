from __future__ import annotations

from collections import Counter
import re

from .models import Segment
from .subtitle_io import DisplayCue, normalize_inline_text, visible_text_length
from .text_quality import contains_chinese, find_short_english_leaks


SOURCE_SENTENCE_RE = re.compile(r"(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\be\.g)(?<!\bi\.e)[.!?]\s+")
START_CONTINUATION_WORD_RE = re.compile(
    r"^(?:and|as|because|but|for|from|if|in|of|on|or|so|that|then|to|with|while|when|which|who)$",
    re.IGNORECASE,
)
END_FUNCTION_WORD_RE = re.compile(
    r"^(?:a|an|and|as|at|because|but|for|from|if|in|of|on|or|so|that|the|to|with|while|when|which|who)$",
    re.IGNORECASE,
)
TERMINAL_RE = re.compile(r"[.!?。！？][\"'”’)\]]*$")
OPEN_END_RE = re.compile(r"[，,、；;：:]\s*$")


def source_sentence_count(text: str) -> int:
    normalized = normalize_inline_text(text)
    if not normalized:
        return 0
    return len([part for part in SOURCE_SENTENCE_RE.split(normalized) if part.strip()])


def source_word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", normalize_inline_text(text)))


def starts_with_function_word(text: str) -> bool:
    words = re.findall(r"[A-Za-z']+", normalize_inline_text(text))
    return bool(words and START_CONTINUATION_WORD_RE.match(words[0]))


def ends_with_function_word(text: str) -> bool:
    words = re.findall(r"[A-Za-z']+", normalize_inline_text(text))
    return bool(words and END_FUNCTION_WORD_RE.match(words[-1]))


def is_open_ending(text: str) -> bool:
    normalized = normalize_inline_text(text)
    return bool(normalized and (OPEN_END_RE.search(normalized) or normalized.endswith(("的", "和", "与", "但", "而", "因为", "所以"))))


def is_terminal_orphan_tail_text(text: str) -> bool:
    normalized = normalize_inline_text(text)
    return bool(normalized and source_word_count(normalized) <= 2 and TERMINAL_RE.search(normalized))


def build_segmentation_qa_metrics(
    segments: list[Segment],
    cues: list[DisplayCue],
    *,
    allocation_report: dict | None = None,
    display_group_report: dict | None = None,
    orphan_tail_display_report: dict | None = None,
    source_repair_report: dict | None = None,
    sample_limit: int = 20,
) -> dict:
    metrics = {
        "segment_count": len(segments),
        "cue_count": len(cues),
        "source_repair": {
            "candidate_count": 0,
            "repaired_segment_count": 0,
            "replacement_count": 0,
            "review_count": 0,
        },
        "display_grouping": {
            "group_count": 0,
            "merged_short_complete_sentence_count": 0,
            "orphan_tail_group_count": 0,
            "merged_orphan_tail_count": 0,
        },
        "allocation": {
            "applied_count": 0,
            "review_count": 0,
            "flagged_segment_count": 0,
            "adjacent_duplicate_target_count": 0,
        },
        "segmentation": {
            "short_fragment_count": 0,
            "mixed_sentence_count": 0,
            "function_edge_count": 0,
            "orphan_terminal_tail_count": 0,
            "too_short_count": 0,
            "too_long_count": 0,
            "short_fragment_samples": [],
            "mixed_sentence_samples": [],
            "function_edge_samples": [],
            "orphan_terminal_tail_samples": [],
            "too_short_samples": [],
            "too_long_samples": [],
        },
    }

    allocation_summary = (allocation_report or {}).get("summary") if isinstance(allocation_report, dict) else {}
    if isinstance(allocation_summary, dict):
        metrics["allocation"]["applied_count"] = int(allocation_summary.get("applied_count") or 0)
        metrics["allocation"]["review_count"] = int(allocation_summary.get("review_count") or 0)
        metrics["allocation"]["flagged_segment_count"] = int(allocation_summary.get("flagged_segment_count") or 0)
        metrics["allocation"]["adjacent_duplicate_target_count"] = int(allocation_summary.get("adjacent_duplicate_target_count") or 0)

    display_summary = (display_group_report or {}).get("summary") if isinstance(display_group_report, dict) else {}
    if isinstance(display_summary, dict):
        metrics["display_grouping"]["group_count"] = int(display_summary.get("group_count") or 0)
        metrics["display_grouping"]["merged_short_complete_sentence_count"] = int(display_summary.get("merged_short_complete_sentence_count") or 0)

    orphan_display_summary = (orphan_tail_display_report or {}).get("summary") if isinstance(orphan_tail_display_report, dict) else {}
    if isinstance(orphan_display_summary, dict):
        metrics["display_grouping"]["orphan_tail_group_count"] = int(orphan_display_summary.get("group_count") or 0)
        metrics["display_grouping"]["merged_orphan_tail_count"] = int(orphan_display_summary.get("merged_orphan_tail_count") or 0)

    repair_summary = (source_repair_report or {}).get("summary") if isinstance(source_repair_report, dict) else {}
    if isinstance(repair_summary, dict):
        metrics["source_repair"]["candidate_count"] = int(repair_summary.get("candidate_count") or 0)
        metrics["source_repair"]["repaired_segment_count"] = int(repair_summary.get("repaired_segment_count") or 0)
        metrics["source_repair"]["replacement_count"] = int(repair_summary.get("replacement_count") or 0)
        metrics["source_repair"]["review_count"] = int(repair_summary.get("review_count") or 0)

    def append_sample(key: str, value: object) -> None:
        if len(metrics["segmentation"][key]) < sample_limit:
            metrics["segmentation"][key].append(value)

    for index, segment in enumerate(segments, start=1):
        source_text = normalize_inline_text(segment.source_text)
        target_text = normalize_inline_text(segment.target_text or "")
        duration = max(0.001, float(segment.end) - float(segment.start))
        source_words = len(re.findall(r"[A-Za-z0-9']+", source_text))
        target_words = len(re.findall(r"[A-Za-z0-9']+", target_text))
        has_two_sentences = source_sentence_count(source_text) >= 2 or source_sentence_count(target_text) >= 2
        source_terminal = bool(TERMINAL_RE.search(source_text))

        if source_words <= 5 and source_text and not TERMINAL_RE.search(source_text):
            metrics["segmentation"]["short_fragment_count"] += 1
            append_sample("short_fragment_samples", {"segment_id": segment.id, "text": source_text})
        if has_two_sentences:
            metrics["segmentation"]["mixed_sentence_count"] += 1
            append_sample(
                "mixed_sentence_samples",
                {"segment_id": segment.id, "source_text": source_text, "target_text": target_text},
            )
        if (
            source_text
            and not source_terminal
            and (starts_with_function_word(source_text) or ends_with_function_word(source_text))
        ):
            metrics["segmentation"]["function_edge_count"] += 1
            append_sample(
                "function_edge_samples",
                {"segment_id": segment.id, "source_text": source_text},
            )
        if duration < 1.0:
            metrics["segmentation"]["too_short_count"] += 1
            append_sample(
                "too_short_samples",
                {"segment_id": segment.id, "duration": round(duration, 3), "text": source_text},
            )
        if duration > 6.95:
            metrics["segmentation"]["too_long_count"] += 1
            append_sample(
                "too_long_samples",
                {"segment_id": segment.id, "duration": round(duration, 3), "text": source_text},
            )
        if target_text and contains_chinese(target_text):
            if visible_text_length(target_text) <= 3 and source_words >= 8:
                metrics["segmentation"]["short_fragment_count"] += 1
                append_sample(
                    "short_fragment_samples",
                    {"segment_id": segment.id, "text": target_text},
                )
            if find_short_english_leaks(target_text, dst_lang="zh-Hans"):
                metrics["segmentation"]["mixed_sentence_count"] += 1

    sorted_cues = sorted(cues, key=lambda item: (item.start, item.end))
    for previous, current in zip(sorted_cues, sorted_cues[1:]):
        previous_text = normalize_inline_text(previous.en_text)
        current_text = normalize_inline_text(current.en_text)
        previous_terminal = bool(TERMINAL_RE.search(previous_text))
        suspicious_closed_left = (
            previous_terminal
            and source_word_count(previous_text) >= 4
            and current_text[:1].islower()
        )
        if previous_text and (not previous_terminal or suspicious_closed_left) and is_terminal_orphan_tail_text(current_text):
            metrics["segmentation"]["orphan_terminal_tail_count"] += 1
            append_sample(
                "orphan_terminal_tail_samples",
                {
                    "segment_id": current.source_segment_id,
                    "previous_text": previous_text,
                    "source_text": current_text,
                    "start": round(float(current.start), 3),
                    "end": round(float(current.end), 3),
                },
            )

    metrics["summary"] = {
        "blocking_issue_count": (
            metrics["segmentation"]["mixed_sentence_count"]
            + metrics["segmentation"]["short_fragment_count"]
            + metrics["segmentation"]["function_edge_count"]
            + metrics["segmentation"]["orphan_terminal_tail_count"]
            + metrics["segmentation"]["too_short_count"]
            + metrics["segmentation"]["too_long_count"]
        ),
        "warning_issue_count": metrics["allocation"]["review_count"] + metrics["source_repair"]["review_count"],
        "pass": (
            metrics["segmentation"]["mixed_sentence_count"] == 0
            and metrics["segmentation"]["short_fragment_count"] == 0
            and metrics["segmentation"]["orphan_terminal_tail_count"] == 0
        ),
    }
    return metrics
