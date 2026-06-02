from __future__ import annotations

import json
import os
import time
from collections import Counter
from typing import Callable

from .difficult_spans import evaluate_segment
from .models import Segment
from .style_rules import build_style_guidance
from .text_quality import find_text_pollution
from .translate import (
    TranslationValidationError,
    classify_retry,
    contains_chinese,
    has_translatable_alpha_text,
    is_allowable_non_chinese_translation,
    parse_json_payload,
    resolve_openai_base_url,
    short_error_message,
    style_glossary_hints,
)

SpanRepairProgressCallback = Callable[[str, dict], None]
PRIORITY_REASON_CODES = {
    "target_text_pollution",
    "target_too_short",
    "source_suspicious_asr_word",
    "source_asr_suspicion",
    "source_repeated_short_phrase",
    "target_literal_chinese_artifact",
    "target_short_english_leak",
    "source_target_semantic_conflict",
    "number_mismatch",
}
TARGET_REPAIR_REASON_CODES = {
    "number_mismatch",
    "source_target_semantic_conflict",
    "target_cps_high",
    "target_line_long",
    "target_literal_chinese_artifact",
    "target_short_english_leak",
    "target_open_ending",
    "target_text_pollution",
    "target_too_short",
}
DEFAULT_MAX_SEGMENTS_PER_REPAIR = 24


def build_span_repair_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "repairs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "target_text": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["id", "target_text", "note"],
                    "additionalProperties": False,
                },
            },
            "span_note": {"type": "string"},
        },
        "required": ["repairs", "span_note"],
        "additionalProperties": False,
    }


def build_span_repair_prompt(
    *,
    span: dict,
    src_lang: str | None,
    dst_lang: str,
    glossary_text: str,
    context_before: list[Segment],
    context_after: list[Segment],
    style_prompt_text: str = "",
) -> str:
    span_payload = [
        {
            "id": item["id"],
            "start": item["start"],
            "end": item["end"],
            "source_text": item["source_text"],
            "current_target_text": item["target_text"],
            "risk_reasons": [reason["code"] for reason in item.get("reasons") or []],
        }
        for item in span.get("segments") or []
    ]
    before_payload = [
        {"id": segment.id, "source_text": segment.source_text, "target_text": segment.target_text or ""}
        for segment in context_before
    ]
    after_payload = [
        {"id": segment.id, "source_text": segment.source_text, "target_text": segment.target_text or ""}
        for segment in context_after
    ]
    return (
        "You are repairing problematic bilingual subtitle spans.\n"
        f"Translate from {src_lang or 'auto-detected source language'} to {dst_lang}.\n\n"
        "Goal:\n"
        "- Read the whole span as one sentence/idea first, then assign natural Chinese back to each original ID.\n"
        "- Preserve the original IDs exactly and return one target_text for every input ID.\n"
        "- Each target_text must be a readable on-screen Chinese subtitle for that ID.\n"
        "- Do not shift meaning into the previous or next ID; do not leave fragments like a lone noun, punctuation, or dangling connector.\n"
        "- If the ASR source has an obvious typo, infer the intended phrase from context, but keep the repair concise.\n"
        "- In ASMR or comfort contexts, pet means 抚摸/摸摸/宠爱. If ASR says bet but the context is good boy, puppy, comfort, or feeling good, infer pet.\n"
        "- Translate have you to comfort as the speaker comforting the listener, such as 我还能安慰你/陪着你; do not write 让我安慰.\n"
        "- Translate I am complete naturally as 我就满足了/我就圆满了; avoid 我很完整/我就完整了.\n"
        "- Avoid stiff literal Chinese such as 让我安慰, 让我抚摸, 我就完整了, 把世界给我.\n"
        "- Preserve or translate names, numbers, album titles, and technical terms according to the glossary.\n"
        "- Chinese localization priority: common proper nouns with established Chinese names must be translated. Countries, cities, regions, peoples/languages, historical events, wars, and famous public institutions should be Chinese by default.\n"
        "- Examples: Japan=日本, Tokyo=东京, World War II=二战, Europe=欧洲, America/the United States=美国, Japanese=日本人/日本的 according to context.\n"
        "- Keep English only for channel names, sponsors/brands, software/library names, code/UI labels, album/title names without a common Chinese rendering, or niche names where a Chinese name would be guesswork.\n"
        "- Do not preserve conversational discourse markers as English or as proper nouns. Words like because, maybe, right, well, okay, so, actually, basically, just, like, yeah, and sure must be translated or naturally absorbed into the Chinese line.\n"
        "- For ambiguous discourse markers, sample the Chinese meaning from context: right can be 对吧/是吧/好了/正确/右边, maybe can be 也许/可能/要不, because can be 因为/是因为/毕竟. Keep English only for literal UI/code labels.\n"
        "- Short function words and pronouns such as and, but, then, I, I'm, and that's must be translated or absorbed. Never leave mixed Chinese like Then我觉得, I'm可以, That's问题, or And I他妈太喜欢了.\n"
        "- Do not include Devanagari, Cyrillic, Arabic, Korean, Japanese, replacement characters, mojibake, markdown, or manual line breaks.\n\n"
        f"Style guidance:\n{build_style_guidance(style_prompt_text)}\n\n"
        f"{style_glossary_hints(glossary_text)}\n"
        f"Glossary:\n{glossary_text or 'No glossary provided.'}\n\n"
        "Previous context JSON (read-only):\n"
        f"{json.dumps(before_payload, ensure_ascii=False)}\n\n"
        "Problem span JSON:\n"
        f"{json.dumps(span_payload, ensure_ascii=False)}\n\n"
        "Next context JSON (read-only):\n"
        f"{json.dumps(after_payload, ensure_ascii=False)}\n\n"
        "Return JSON matching the supplied schema."
    )


def validate_span_repairs(span_segments: list[Segment], repairs: dict[int, str], *, dst_lang: str | None) -> dict[str, list[int]]:
    expected_ids = {segment.id for segment in span_segments}
    returned_ids = set(repairs)
    source_by_id = {segment.id: segment.source_text for segment in span_segments}
    issues: dict[str, list[int]] = {
        "missing": sorted(expected_ids - returned_ids),
        "extra": sorted(returned_ids - expected_ids),
        "empty": [],
        "target_without_chinese": [],
        "text_pollution": [],
    }
    for segment_id in sorted(expected_ids & returned_ids):
        target_text = repairs.get(segment_id, "").strip()
        source_text = source_by_id.get(segment_id, "")
        if not target_text:
            issues["empty"].append(segment_id)
            continue
        if (
            has_translatable_alpha_text(source_text)
            and not contains_chinese(target_text)
            and not is_allowable_non_chinese_translation(source_text, target_text, set())
        ):
            issues["target_without_chinese"].append(segment_id)
        if find_text_pollution(target_text, dst_lang=dst_lang):
            issues["text_pollution"].append(segment_id)
    return {key: value for key, value in issues.items() if value}


def target_repair_issue_score(segments: list[Segment]) -> int:
    score = 0
    for index, segment in enumerate(segments):
        risk = evaluate_segment(segment, index)
        for reason in risk.reasons:
            if reason["code"] in TARGET_REPAIR_REASON_CODES:
                score += int(reason.get("weight") or 0)
    return score


def span_start_id(span: dict) -> int:
    return int(span.get("start_segment_id") or 0)


def span_end_id(span: dict) -> int:
    return int(span.get("end_segment_id") or 0)


def span_priority_score(span: dict) -> int:
    reason_counts = span.get("reason_counts") if isinstance(span.get("reason_counts"), dict) else {}
    score = sum(int(reason_counts.get(code) or 0) for code in PRIORITY_REASON_CODES)
    score += int(reason_counts.get("target_open_ending") or 0)
    score += int(reason_counts.get("source_starts_with_continuation") or 0)
    score += int(reason_counts.get("source_ends_with_open_word") or 0)
    score += int(reason_counts.get("target_literal_chinese_artifact") or 0) * 3
    score += int(reason_counts.get("target_short_english_leak") or 0) * 4
    score += int(reason_counts.get("source_target_semantic_conflict") or 0) * 4
    score += int(reason_counts.get("source_asr_suspicion") or 0) * 2
    score += int(reason_counts.get("source_repeated_short_phrase") or 0)
    return score


def build_repair_cluster(
    candidate: dict,
    all_spans: list[dict],
    all_segments: list[Segment],
    *,
    max_segments_per_repair: int = DEFAULT_MAX_SEGMENTS_PER_REPAIR,
    max_gap_segments: int = 1,
) -> dict:
    spans = sorted(all_spans, key=lambda item: span_start_id(item))
    start_id = span_start_id(candidate)
    end_id = span_end_id(candidate)
    included = [candidate]

    changed = True
    while changed:
        changed = False
        for other in spans:
            other_start = span_start_id(other)
            other_end = span_end_id(other)
            if any(other.get("span_id") == item.get("span_id") for item in included):
                continue
            touches_left = 0 < start_id - other_end <= max_gap_segments + 1
            touches_right = 0 < other_start - end_id <= max_gap_segments + 1
            overlaps = other_start <= end_id and other_end >= start_id
            if not (touches_left or touches_right or overlaps):
                continue
            new_start = min(start_id, other_start)
            new_end = max(end_id, other_end)
            if new_end - new_start + 1 > max_segments_per_repair:
                continue
            start_id = new_start
            end_id = new_end
            included.append(other)
            changed = True

    segment_by_id = {segment.id: segment for segment in all_segments}
    reason_by_segment: dict[int, list[dict]] = {}
    score_by_segment: Counter[int] = Counter()
    reason_counts: Counter[str] = Counter()
    for span in included:
        reason_counts.update(span.get("reason_counts") or {})
        for item in span.get("segments") or []:
            segment_id = int(item.get("id") or 0)
            reasons = item.get("reasons") if isinstance(item.get("reasons"), list) else []
            reason_by_segment.setdefault(segment_id, []).extend(reasons)
            score_by_segment[segment_id] += int(item.get("risk_score") or 0)

    cluster_segments = [
        segment_by_id[segment_id]
        for segment_id in range(start_id, end_id + 1)
        if segment_id in segment_by_id
    ]
    return {
        "span_id": f"{candidate.get('span_id')}-cluster",
        "source_span_ids": [span.get("span_id") for span in sorted(included, key=lambda item: span_start_id(item))],
        "start_segment_id": start_id,
        "end_segment_id": end_id,
        "start": cluster_segments[0].start if cluster_segments else candidate.get("start"),
        "end": cluster_segments[-1].end if cluster_segments else candidate.get("end"),
        "segment_count": len(cluster_segments),
        "score": sum(int(span.get("score") or 0) for span in included),
        "severity": "high",
        "action": "needs_ai_repair",
        "reason_counts": dict(sorted(reason_counts.items())),
        "segments": [
            {
                "id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "source_text": segment.source_text,
                "target_text": segment.target_text or "",
                "risk_score": int(score_by_segment.get(segment.id) or 0),
                "reasons": reason_by_segment.get(segment.id, []),
            }
            for segment in cluster_segments
        ],
        "source_joined": " ".join(segment.source_text for segment in cluster_segments),
        "target_joined": " ".join(segment.target_text or "" for segment in cluster_segments),
    }


def select_repair_clusters(
    segments: list[Segment],
    difficult_spans: dict,
    *,
    max_spans: int,
    min_severity: str,
    max_segments_per_repair: int = DEFAULT_MAX_SEGMENTS_PER_REPAIR,
) -> tuple[list[dict], int]:
    severity_rank = {"low": 1, "medium": 2, "high": 3}
    minimum_rank = severity_rank.get(min_severity, 3)
    all_spans = list(difficult_spans.get("spans") or [])
    candidates = [
        span
        for span in all_spans
        if severity_rank.get(str(span.get("severity") or "low"), 1) >= minimum_rank
        and str(span.get("action") or "") == "needs_ai_repair"
    ]
    candidates = sorted(
        candidates,
        key=lambda item: (
            -span_priority_score(item),
            -int(item.get("score") or 0),
            int(item.get("start_segment_id") or 0),
        ),
    )

    selected: list[dict] = []
    used_segment_ids: set[int] = set()
    for candidate in candidates:
        cluster = build_repair_cluster(
            candidate,
            all_spans,
            segments,
            max_segments_per_repair=max_segments_per_repair,
        )
        cluster_ids = {
            int(item.get("id") or 0)
            for item in cluster.get("segments") or []
            if int(item.get("id") or 0) > 0
        }
        if not cluster_ids or cluster_ids & used_segment_ids:
            continue
        selected.append(cluster)
        used_segment_ids.update(cluster_ids)
        if max_spans > 0 and len(selected) >= max_spans:
            break

    return selected, len(candidates)


def repair_span_with_openai(
    *,
    span: dict,
    segments_by_id: dict[int, Segment],
    all_segments: list[Segment],
    src_lang: str | None,
    dst_lang: str,
    glossary_text: str,
    model: str,
    style_prompt_text: str = "",
    base_url: str | None = None,
    max_retries: int = 2,
    context_window: int = 4,
) -> dict:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The OpenAI Python SDK is not installed. Install it with: "
            "python -m pip install openai"
        ) from exc

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")

    span_ids = [int(item["id"]) for item in span.get("segments") or []]
    span_segments = [segments_by_id[segment_id] for segment_id in span_ids if segment_id in segments_by_id]
    if not span_segments:
        return {"span_id": span.get("span_id"), "status": "skipped", "reason": "empty_span"}
    original_targets = {segment.id: segment.target_text for segment in span_segments}
    before_target_issue_score = target_repair_issue_score(span_segments)

    first_index = max(0, span_segments[0].id - 1)
    last_index = min(len(all_segments) - 1, span_segments[-1].id - 1)
    context_window = max(0, int(context_window or 0))
    context_before = all_segments[max(0, first_index - context_window) : first_index]
    context_after = all_segments[last_index + 1 : min(len(all_segments), last_index + 1 + context_window)]

    prompt = build_span_repair_prompt(
        span=span,
        src_lang=src_lang,
        dst_lang=dst_lang,
        glossary_text=glossary_text,
        style_prompt_text=style_prompt_text,
        context_before=context_before,
        context_after=context_after,
    )
    schema = build_span_repair_schema()
    client_kwargs = {"timeout": 600.0}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    raw_text = ""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.responses.create(
                model=model,
                input=prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "subtitle_span_repair",
                        "strict": True,
                        "schema": schema,
                    },
                    "verbosity": "low",
                },
            )
            raw_text = response.output_text.strip()
            payload = json.loads(raw_text)
            repairs_payload = payload.get("repairs") if isinstance(payload, dict) else parse_json_payload(raw_text)
            repairs = {
                int(item["id"]): str(item["target_text"]).strip()
                for item in repairs_payload
                if isinstance(item, dict) and "id" in item and "target_text" in item
            }
            for extra_id in sorted(set(repairs) - set(span_ids)):
                repairs.pop(extra_id, None)
            issues = validate_span_repairs(span_segments, repairs, dst_lang=dst_lang)
            if issues:
                raise TranslationValidationError(issues)
            for segment in span_segments:
                segment.target_text = repairs[segment.id]
            after_target_issue_score = target_repair_issue_score(span_segments)
            if after_target_issue_score > before_target_issue_score:
                for segment in span_segments:
                    segment.target_text = original_targets[segment.id]
                return {
                    "span_id": span.get("span_id"),
                    "status": "rejected",
                    "segment_ids": span_ids,
                    "reason": "repair increased target-side risk score",
                    "before_target_issue_score": before_target_issue_score,
                    "after_target_issue_score": after_target_issue_score,
                    "span_note": str(payload.get("span_note") or "") if isinstance(payload, dict) else "",
                }
            return {
                "span_id": span.get("span_id"),
                "status": "repaired",
                "segment_ids": span_ids,
                "span_note": str(payload.get("span_note") or "") if isinstance(payload, dict) else "",
                "repaired_count": len(span_segments),
                "before_target_issue_score": before_target_issue_score,
                "after_target_issue_score": after_target_issue_score,
            }
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries:
                return {
                    "span_id": span.get("span_id"),
                    "status": "failed",
                    "segment_ids": span_ids,
                    "reason": short_error_message(exc),
                    "last_raw_output": raw_text,
                }
            wait_seconds, _ = classify_retry(exc, attempt, max_retries)
            time.sleep(wait_seconds)

    return {
        "span_id": span.get("span_id"),
        "status": "failed",
        "segment_ids": span_ids,
        "reason": short_error_message(last_error) if last_error else "unknown",
        "last_raw_output": raw_text,
    }


def repair_difficult_spans(
    segments: list[Segment],
    difficult_spans: dict,
    *,
    src_lang: str | None,
    dst_lang: str,
    glossary_text: str,
    model: str,
    style_prompt_text: str = "",
    base_url: str | None = None,
    max_retries: int = 2,
    max_spans: int = 12,
    min_severity: str = "high",
    max_segments_per_repair: int = DEFAULT_MAX_SEGMENTS_PER_REPAIR,
    progress_callback: SpanRepairProgressCallback | None = None,
) -> dict:
    candidates, eligible_count = select_repair_clusters(
        segments,
        difficult_spans,
        max_spans=max_spans,
        min_severity=min_severity,
        max_segments_per_repair=max_segments_per_repair,
    )

    segments_by_id = {segment.id: segment for segment in segments}
    results: list[dict] = []
    resolved_base_url = resolve_openai_base_url(base_url)
    for index, span in enumerate(candidates, start=1):
        if progress_callback:
            progress_callback(
                "span_repair_start",
                {
                    "span_index": index,
                    "span_total": len(candidates),
                    "span_id": span.get("span_id"),
                    "segment_ids": [item.get("id") for item in span.get("segments") or []],
                },
            )
        result = repair_span_with_openai(
            span=span,
            segments_by_id=segments_by_id,
            all_segments=segments,
            src_lang=src_lang,
            dst_lang=dst_lang,
            glossary_text=glossary_text,
            style_prompt_text=style_prompt_text,
            model=model,
            base_url=resolved_base_url,
            max_retries=max_retries,
        )
        results.append(result)
        if progress_callback:
            progress_callback(
                "span_repair_complete",
                {
                    "span_index": index,
                    "span_total": len(candidates),
                    **result,
                },
            )

    repaired_count = sum(int(item.get("repaired_count") or 0) for item in results)
    failed_count = sum(1 for item in results if item.get("status") == "failed")
    rejected_count = sum(1 for item in results if item.get("status") == "rejected")
    return {
        "summary": {
            "eligible_span_count": eligible_count,
            "candidate_count": len(candidates),
            "attempted_count": len(results),
            "repaired_segment_count": repaired_count,
            "failed_count": failed_count,
            "rejected_count": rejected_count,
        },
        "results": results,
    }
