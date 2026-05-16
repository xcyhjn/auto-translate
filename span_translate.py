from __future__ import annotations

import json
import os
import time
from typing import Callable

from .models import Segment
from .text_quality import find_text_pollution
from .translate import (
    TranslationValidationError,
    classify_retry,
    contains_chinese,
    has_translatable_alpha_text,
    parse_json_payload,
    resolve_openai_base_url,
    short_error_message,
)


SpanTranslateProgressCallback = Callable[[str, dict], None]
DEFAULT_MAX_SPANS = 16
DEFAULT_MAX_SEGMENTS_PER_SPAN = 12


def build_span_translation_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "intent_zh": {"type": "string"},
            "translations": {
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
        "required": ["intent_zh", "translations", "span_note"],
        "additionalProperties": False,
    }


def build_span_translation_prompt(
    *,
    span: dict,
    span_segments: list[Segment],
    context_before: list[Segment],
    context_after: list[Segment],
    src_lang: str | None,
    dst_lang: str,
    glossary_text: str,
) -> str:
    input_payload = [
        {
            "id": segment.id,
            "start": segment.start,
            "end": segment.end,
            "source_text": segment.source_text,
        }
        for segment in span_segments
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
        "You are translating a high-risk subtitle span before normal chunk translation.\n"
        f"Translate from {src_lang or 'auto-detected source language'} to {dst_lang}.\n\n"
        "Goal:\n"
        "- Chinese is the primary subtitle; English is only a reference layer.\n"
        "- Read the whole span first and understand the complete idea.\n"
        "- Return a concise Chinese intent summary in intent_zh.\n"
        "- Then assign natural Chinese back to every original subtitle ID.\n"
        "- Every ID must be independently readable on screen.\n"
        "- You may lightly reorder Chinese within the span so each screen works.\n"
        "- Do not leave an ID as a dangling fragment such as 的, 和, 但, 一个, 关于, 因为, 所以.\n"
        "- Do not move all meaning into a neighboring ID; every ID must carry useful meaning.\n"
        "- Preserve names, album titles, numbers, and technical terms according to the glossary.\n"
        "- Do not add manual line breaks, markdown, bullets, numbering, or polluted scripts.\n\n"
        f"Source span metadata:\n{json.dumps(span, ensure_ascii=False)}\n\n"
        f"Glossary:\n{glossary_text or 'No glossary provided.'}\n\n"
        "Previous context JSON (read-only):\n"
        f"{json.dumps(before_payload, ensure_ascii=False)}\n\n"
        "Input span JSON:\n"
        f"{json.dumps(input_payload, ensure_ascii=False)}\n\n"
        "Next context JSON (read-only):\n"
        f"{json.dumps(after_payload, ensure_ascii=False)}\n\n"
        "Return JSON matching the supplied schema."
    )


def validate_span_translations(
    span_segments: list[Segment],
    translations: dict[int, str],
    *,
    dst_lang: str | None,
) -> dict[str, list[int]]:
    expected_ids = {segment.id for segment in span_segments}
    returned_ids = set(translations)
    source_by_id = {segment.id: segment.source_text for segment in span_segments}
    issues: dict[str, list[int]] = {
        "missing": sorted(expected_ids - returned_ids),
        "extra": sorted(returned_ids - expected_ids),
        "empty": [],
        "target_without_chinese": [],
        "text_pollution": [],
    }
    for segment_id in sorted(expected_ids & returned_ids):
        target_text = translations.get(segment_id, "").strip()
        source_text = source_by_id.get(segment_id, "")
        if not target_text:
            issues["empty"].append(segment_id)
            continue
        if has_translatable_alpha_text(source_text) and not contains_chinese(target_text):
            issues["target_without_chinese"].append(segment_id)
        if find_text_pollution(target_text, dst_lang=dst_lang):
            issues["text_pollution"].append(segment_id)
    return {key: value for key, value in issues.items() if value}


def select_span_translation_candidates(
    source_spans: dict | None,
    locked_ids: set[int] | None = None,
    *,
    max_spans: int = DEFAULT_MAX_SPANS,
    max_segments_per_span: int = DEFAULT_MAX_SEGMENTS_PER_SPAN,
) -> list[dict]:
    locked_ids = locked_ids or set()
    candidates: list[dict] = []
    for span in (source_spans or {}).get("spans") or []:
        if not isinstance(span, dict):
            continue
        if str(span.get("translation_strategy") or "") != "span_first":
            continue
        segment_ids = [int(value) for value in span.get("segment_ids") or [] if int(value) > 0]
        if not segment_ids or len(segment_ids) > max_segments_per_span:
            continue
        unlocked_ids = [segment_id for segment_id in segment_ids if segment_id not in locked_ids]
        if not unlocked_ids:
            continue
        item = dict(span)
        item["segment_ids"] = unlocked_ids
        candidates.append(item)
    candidates.sort(key=lambda item: (-int(item.get("risk_score") or 0), int(item.get("start_segment_id") or 0)))
    if max_spans > 0:
        candidates = candidates[:max_spans]
    return candidates


def translate_source_span_with_openai(
    *,
    span: dict,
    all_segments: list[Segment],
    segments_by_id: dict[int, Segment],
    src_lang: str | None,
    dst_lang: str,
    glossary_text: str,
    model: str,
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

    span_ids = [int(value) for value in span.get("segment_ids") or []]
    span_segments = [segments_by_id[segment_id] for segment_id in span_ids if segment_id in segments_by_id]
    if not span_segments:
        return {"span_id": span.get("span_id"), "status": "skipped", "reason": "empty_span"}

    first_index = max(0, span_segments[0].id - 1)
    last_index = min(len(all_segments) - 1, span_segments[-1].id - 1)
    context_window = max(0, int(context_window or 0))
    context_before = all_segments[max(0, first_index - context_window) : first_index]
    context_after = all_segments[last_index + 1 : min(len(all_segments), last_index + 1 + context_window)]
    prompt = build_span_translation_prompt(
        span=span,
        span_segments=span_segments,
        context_before=context_before,
        context_after=context_after,
        src_lang=src_lang,
        dst_lang=dst_lang,
        glossary_text=glossary_text,
    )

    client_kwargs = {"timeout": 600.0}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)
    schema = build_span_translation_schema()

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
                        "name": "subtitle_span_translation",
                        "strict": True,
                        "schema": schema,
                    },
                    "verbosity": "low",
                },
            )
            raw_text = response.output_text.strip()
            payload = json.loads(raw_text)
            translations_payload = payload.get("translations") if isinstance(payload, dict) else parse_json_payload(raw_text)
            translations = {
                int(item["id"]): str(item["target_text"]).strip()
                for item in translations_payload
                if isinstance(item, dict) and "id" in item and "target_text" in item
            }
            for extra_id in sorted(set(translations) - set(span_ids)):
                translations.pop(extra_id, None)
            issues = validate_span_translations(span_segments, translations, dst_lang=dst_lang)
            if issues:
                raise TranslationValidationError(issues)
            for segment in span_segments:
                segment.target_text = translations[segment.id]
            return {
                "span_id": span.get("span_id"),
                "status": "translated",
                "segment_ids": span_ids,
                "translated_count": len(span_segments),
                "intent_zh": str(payload.get("intent_zh") or "") if isinstance(payload, dict) else "",
                "span_note": str(payload.get("span_note") or "") if isinstance(payload, dict) else "",
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


def translate_source_spans(
    segments: list[Segment],
    source_spans: dict | None,
    *,
    src_lang: str | None,
    dst_lang: str,
    glossary_text: str,
    model: str,
    base_url: str | None = None,
    max_retries: int = 2,
    locked_ids: set[int] | None = None,
    max_spans: int = DEFAULT_MAX_SPANS,
    progress_callback: SpanTranslateProgressCallback | None = None,
) -> tuple[set[int], dict]:
    locked_ids = set(locked_ids or set())
    candidates = select_span_translation_candidates(source_spans, locked_ids, max_spans=max_spans)
    if not candidates:
        return set(), {
            "schema_version": 1,
            "summary": {
                "eligible_span_count": 0,
                "attempted_count": 0,
                "translated_span_count": 0,
                "translated_segment_count": 0,
                "failed_count": 0,
            },
            "results": [],
        }

    segments_by_id = {segment.id: segment for segment in segments}
    resolved_base_url = resolve_openai_base_url(base_url)
    translated_ids: set[int] = set()
    results: list[dict] = []
    for index, span in enumerate(candidates, start=1):
        if progress_callback:
            progress_callback(
                "span_translation_start",
                {
                    "span_index": index,
                    "span_total": len(candidates),
                    "span_id": span.get("span_id"),
                    "segment_ids": span.get("segment_ids") or [],
                },
            )
        result = translate_source_span_with_openai(
            span=span,
            all_segments=segments,
            segments_by_id=segments_by_id,
            src_lang=src_lang,
            dst_lang=dst_lang,
            glossary_text=glossary_text,
            model=model,
            base_url=resolved_base_url,
            max_retries=max_retries,
        )
        results.append(result)
        if result.get("status") == "translated":
            translated_ids.update(int(value) for value in result.get("segment_ids") or [])
        if progress_callback:
            progress_callback(
                "span_translation_complete",
                {
                    "span_index": index,
                    "span_total": len(candidates),
                    **result,
                },
            )

    failed_count = sum(1 for item in results if item.get("status") == "failed")
    translated_span_count = sum(1 for item in results if item.get("status") == "translated")
    return translated_ids, {
        "schema_version": 1,
        "summary": {
            "eligible_span_count": len(candidates),
            "attempted_count": len(results),
            "translated_span_count": translated_span_count,
            "translated_segment_count": len(translated_ids),
            "failed_count": failed_count,
        },
        "results": results,
    }
