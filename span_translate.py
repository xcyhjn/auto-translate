from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Callable

from .english_residue_policy import analyze_english_residue
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
    resolve_openai_timeout_seconds,
    short_error_message,
    style_glossary_hints,
)


SpanTranslateProgressCallback = Callable[[str, dict], None]
DEFAULT_MAX_SPANS = 16
DEFAULT_MAX_SEGMENTS_PER_SPAN = 4
DEFAULT_MAX_SPAN_DURATION = 12.0
DEFAULT_MIN_RISK_SCORE = 10
SPAN_TRANSLATION_POLICY_VERSION = "span_translation_v2"
DEFAULT_SPAN_EXAMPLES_PATH = Path(__file__).resolve().parent / "datasets" / "local_feedback" / "span_translation_examples.jsonl"
DEFAULT_SPAN_EXAMPLE_TOP_K = 3


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_span_translation_fingerprint(
    segments: list[Segment],
    source_spans: dict | None,
    *,
    glossary_text: str = "",
    model: str = "",
    style_prompt_text: str = "",
    span_examples: list[dict] | None = None,
    max_spans: int = DEFAULT_MAX_SPANS,
    max_segments_per_span: int = DEFAULT_MAX_SEGMENTS_PER_SPAN,
    max_duration: float = DEFAULT_MAX_SPAN_DURATION,
    min_risk_score: int = DEFAULT_MIN_RISK_SCORE,
    english_residue_validation_enabled: bool = True,
    english_residue_preserve_threshold: int = 85,
    english_residue_review_threshold: int = 70,
) -> dict:
    source_payload = [
        {
            "id": segment.id,
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "source_text": segment.source_text,
        }
        for segment in segments
    ]
    span_payload = [
        {
            "span_id": span.get("span_id"),
            "segment_ids": span.get("segment_ids") or [],
            "duration": span.get("duration"),
            "risk_score": span.get("risk_score"),
            "risk_reasons": span.get("risk_reasons") or {},
            "translation_strategy": span.get("translation_strategy"),
            "source_joined": span.get("source_joined") or "",
        }
        for span in (source_spans or {}).get("spans") or []
        if isinstance(span, dict)
    ]
    config = {
        "max_spans": int(max_spans or 0),
        "max_segments_per_span": int(max_segments_per_span or 0),
        "max_duration": round(float(max_duration or 0.0), 3),
        "min_risk_score": int(min_risk_score or 0),
        "english_residue_validation_enabled": bool(english_residue_validation_enabled),
        "english_residue_preserve_threshold": int(english_residue_preserve_threshold or 0),
        "english_residue_review_threshold": int(english_residue_review_threshold or 0),
    }
    return {
        "policy_version": SPAN_TRANSLATION_POLICY_VERSION,
        "source_segments_hash": _stable_hash(source_payload),
        "source_spans_hash": _stable_hash(span_payload),
        "glossary_hash": _stable_hash(glossary_text or ""),
        "style_prompt_hash": _stable_hash(style_prompt_text or ""),
        "span_examples_hash": _stable_hash(summarize_span_examples_for_hash(span_examples or [])),
        "model": model,
        "config": config,
    }


def summarize_span_examples_for_hash(examples: list[dict]) -> list[dict]:
    return [
        {
            "project_id": example.get("project_id"),
            "span_id": example.get("span_id"),
            "segment_ids": example.get("segment_ids") or [],
            "edit_tags": example.get("edit_tags") or [],
            "manual_target_by_id": example.get("manual_target_by_id") or {},
        }
        for example in examples
    ]


def read_span_examples(path: str | Path | None = DEFAULT_SPAN_EXAMPLES_PATH) -> list[dict]:
    if not path:
        return []
    examples_path = Path(path)
    if not examples_path.exists():
        return []
    records: list[dict] = []
    for raw_line in examples_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(payload, dict)
            and payload.get("accepted") is True
            and payload.get("use_for_span_prompt") is True
            and payload.get("use_for_eval") is not True
            and payload.get("learning_risk") != "high"
            and "bad_alignment" not in set(str(item) for item in payload.get("edit_tags") or [])
        ):
            records.append(payload)
    return records


TOKEN_RE = re.compile(r"[A-Za-z0-9']+|[\u3400-\u9fff]{1,2}")


def token_set(text: str) -> set[str]:
    return {token.casefold() for token in TOKEN_RE.findall(str(text or ""))}


def score_span_example(span: dict, example: dict) -> int:
    score = 0
    span_risks = set((span.get("risk_reasons") or {}).keys()) if isinstance(span.get("risk_reasons"), dict) else set()
    example_risks = set((example.get("risk_reasons") or {}).keys()) if isinstance(example.get("risk_reasons"), dict) else set()
    score += len(span_risks & example_risks) * 8
    if str(span.get("translation_strategy") or "") == str(example.get("translation_strategy") or ""):
        score += 10
    source_tokens = token_set(str(span.get("source_joined") or ""))
    example_tokens = token_set(str(example.get("source_joined") or ""))
    if source_tokens and example_tokens:
        score += int(20 * len(source_tokens & example_tokens) / max(len(source_tokens | example_tokens), 1))
    span_count = len(span.get("segment_ids") or [])
    example_count = len(example.get("segment_ids") or [])
    score += max(0, 6 - abs(span_count - example_count) * 2)
    span_duration = float(span.get("duration") or 0.0)
    example_duration = float(example.get("duration") or 0.0)
    if span_duration and example_duration:
        score += max(0, 5 - int(abs(span_duration - example_duration)))
    if set(example.get("edit_tags") or []) & {"semantic_reallocation", "fragment_completion", "close_open_clause"}:
        score += 3
    return score


def select_span_prompt_examples(span: dict, examples: list[dict], *, top_k: int = DEFAULT_SPAN_EXAMPLE_TOP_K) -> list[dict]:
    if top_k <= 0 or not examples:
        return []
    scored = [
        (score_span_example(span, example), index, example)
        for index, example in enumerate(examples)
    ]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:top_k]]


def compact_span_prompt_example(example: dict) -> dict:
    return {
        "source_joined": str(example.get("source_joined") or "")[:500],
        "risk_reasons": example.get("risk_reasons") if isinstance(example.get("risk_reasons"), dict) else {},
        "translation_strategy": str(example.get("translation_strategy") or ""),
        "context_before": (example.get("context_before") or [])[-2:],
        "context_after": (example.get("context_after") or [])[:2],
        "manual_target_by_id": example.get("manual_target_by_id") if isinstance(example.get("manual_target_by_id"), dict) else {},
        "edit_tags": example.get("edit_tags") or [],
        "lesson": build_span_example_lesson(example),
    }


def build_span_example_lesson(example: dict) -> str:
    tags = set(str(item) for item in example.get("edit_tags") or [])
    lessons: list[str] = []
    if "semantic_reallocation" in tags:
        lessons.append("redistribute the full idea across IDs")
    if "fragment_completion" in tags:
        lessons.append("avoid orphan fragments")
    if "close_open_clause" in tags:
        lessons.append("close dangling clauses")
    if "compress_span" in tags:
        lessons.append("compress wordy span wording")
    if "expand_span" in tags:
        lessons.append("restore missing context")
    if "preserve_term" in tags:
        lessons.append("preserve key terms")
    return "; ".join(lessons) or "follow the manual ID-level span allocation"


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
    style_prompt_text: str = "",
    span_prompt_examples: list[dict] | None = None,
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
    examples_payload = [compact_span_prompt_example(example) for example in span_prompt_examples or []]
    examples_block = (
        "Matched local span examples JSON:\n"
        f"{json.dumps(examples_payload, ensure_ascii=False)}\n\n"
        if examples_payload
        else ""
    )
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
        "- In ASMR or comfort contexts, pet means 抚摸/摸摸/宠爱. If ASR says bet but the context is good boy, puppy, comfort, or feeling good, infer pet.\n"
        "- Translate have you to comfort as the speaker comforting the listener, such as 我还能安慰你/陪着你; do not write 让我安慰.\n"
        "- Translate I am complete naturally as 我就满足了/我就圆满了; avoid 我很完整/我就完整了.\n"
        "- Avoid stiff literal Chinese such as 让我安慰, 让我抚摸, 我就完整了, 把世界给我.\n"
        "- Preserve or translate names, album titles, numbers, and technical terms according to the glossary.\n"
        "- Chinese localization priority: common proper nouns with established Chinese names must be translated. Countries, cities, regions, peoples/languages, historical events, wars, and famous public institutions should be Chinese by default.\n"
        "- Examples: Japan=日本, Tokyo=东京, World War II=二战, Europe=欧洲, America/the United States=美国, Japanese=日本人/日本的 according to context.\n"
        "- Keep English only for channel names, sponsors/brands, software/library names, code/UI labels, album/title names without a common Chinese rendering, or niche names where a Chinese name would be guesswork.\n"
        "- Short function words and pronouns such as and, but, then, I, I'm, and that's must be translated or absorbed. Never leave mixed Chinese like Then我觉得, I'm可以, That's问题, or And I他妈太喜欢了.\n"
        "- Do not add manual line breaks, markdown, bullets, numbering, or polluted scripts.\n\n"
        f"Style guidance:\n{build_style_guidance(style_prompt_text)}\n\n"
        f"{examples_block}"
        f"{style_glossary_hints(glossary_text)}\n"
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
    glossary_text: str = "",
    english_residue_validation_enabled: bool = True,
    english_residue_preserve_threshold: int = 85,
    english_residue_review_threshold: int = 70,
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
        "english_residue": [],
    }
    for segment_id in sorted(expected_ids & returned_ids):
        target_text = translations.get(segment_id, "").strip()
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
        if english_residue_validation_enabled:
            residue_decisions = analyze_english_residue(
                target_text,
                source_text=source_text,
                reference_text=source_text,
                dst_lang=dst_lang,
                glossary_text=glossary_text,
                preserve_threshold=english_residue_preserve_threshold,
                review_threshold=english_residue_review_threshold,
            )
            if any(item.decision != "preserve" for item in residue_decisions):
                issues["english_residue"].append(segment_id)
    return {key: value for key, value in issues.items() if value}


def parse_span_json_payload(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    payload = json.loads(text)
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"intent_zh": "", "translations": payload, "span_note": ""}
    raise ValueError("Span translation response JSON must be an object.")


def request_span_translation_with_chat_completions(client, *, model: str, prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\n"
                    "Return compact JSON in this exact shape: "
                    '{"intent_zh":"...","translations":[{"id":1,"target_text":"...","note":"..."}],"span_note":"..."}'
                ),
            },
        ],
        response_format={"type": "json_object"},
    )
    return (response.choices[0].message.content or "").strip()


def select_span_translation_candidates(
    source_spans: dict | None,
    locked_ids: set[int] | None = None,
    *,
    max_spans: int = DEFAULT_MAX_SPANS,
    max_segments_per_span: int = DEFAULT_MAX_SEGMENTS_PER_SPAN,
    max_duration: float = DEFAULT_MAX_SPAN_DURATION,
    min_risk_score: int = DEFAULT_MIN_RISK_SCORE,
) -> list[dict]:
    if max_spans <= 0:
        return []
    locked_ids = locked_ids or set()
    candidates: list[dict] = []
    for span in (source_spans or {}).get("spans") or []:
        if not isinstance(span, dict):
            continue
        if str(span.get("translation_strategy") or "") != "span_first":
            continue
        segment_ids = [int(value) for value in span.get("segment_ids") or [] if int(value) > 0]
        segment_count = int(span.get("segment_count") or len(segment_ids))
        risk_score = int(span.get("risk_score") or 0)
        duration = float(span.get("duration") or 0.0)
        if not segment_ids or len(segment_ids) > max_segments_per_span or segment_count > max_segments_per_span:
            continue
        if max_duration > 0 and duration > max_duration:
            continue
        if risk_score < min_risk_score:
            continue
        unlocked_ids = [segment_id for segment_id in segment_ids if segment_id not in locked_ids]
        if not unlocked_ids:
            continue
        item = dict(span)
        item["segment_ids"] = unlocked_ids
        candidates.append(item)
    candidates.sort(key=lambda item: (-int(item.get("risk_score") or 0), int(item.get("start_segment_id") or 0)))
    return candidates[:max_spans]


def translate_source_span_with_openai(
    *,
    span: dict,
    all_segments: list[Segment],
    segments_by_id: dict[int, Segment],
    src_lang: str | None,
    dst_lang: str,
    glossary_text: str,
    model: str,
    style_prompt_text: str = "",
    span_prompt_examples: list[dict] | None = None,
    base_url: str | None = None,
    max_retries: int = 2,
    context_window: int = 4,
    english_residue_validation_enabled: bool = True,
    english_residue_preserve_threshold: int = 85,
    english_residue_review_threshold: int = 70,
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
        style_prompt_text=style_prompt_text,
        span_prompt_examples=span_prompt_examples,
    )

    client_kwargs = {"timeout": resolve_openai_timeout_seconds(), "max_retries": 0}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)
    schema = build_span_translation_schema()

    raw_text = ""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            if base_url:
                raw_text = request_span_translation_with_chat_completions(
                    client,
                    model=model,
                    prompt=prompt,
                )
            else:
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
            payload = parse_span_json_payload(raw_text)
            translations_payload = payload.get("translations") if isinstance(payload, dict) else parse_json_payload(raw_text)
            translations = {
                int(item["id"]): str(item["target_text"]).strip()
                for item in translations_payload
                if isinstance(item, dict) and "id" in item and "target_text" in item
            }
            for extra_id in sorted(set(translations) - set(span_ids)):
                translations.pop(extra_id, None)
            issues = validate_span_translations(
                span_segments,
                translations,
                dst_lang=dst_lang,
                glossary_text=glossary_text,
                english_residue_validation_enabled=english_residue_validation_enabled,
                english_residue_preserve_threshold=english_residue_preserve_threshold,
                english_residue_review_threshold=english_residue_review_threshold,
            )
            if issues:
                raise TranslationValidationError(issues)
            for segment in span_segments:
                segment.target_text = translations[segment.id]
            return {
                "span_id": span.get("span_id"),
                "status": "translated",
                "segment_ids": span_ids,
                "translated_count": len(span_segments),
                "matched_span_example_count": len(span_prompt_examples or []),
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
    style_prompt_text: str = "",
    span_prompt_examples: list[dict] | None = None,
    span_prompt_example_top_k: int = DEFAULT_SPAN_EXAMPLE_TOP_K,
    base_url: str | None = None,
    max_retries: int = 2,
    locked_ids: set[int] | None = None,
    max_spans: int = DEFAULT_MAX_SPANS,
    max_segments_per_span: int = DEFAULT_MAX_SEGMENTS_PER_SPAN,
    max_duration: float = DEFAULT_MAX_SPAN_DURATION,
    min_risk_score: int = DEFAULT_MIN_RISK_SCORE,
    english_residue_validation_enabled: bool = True,
    english_residue_preserve_threshold: int = 85,
    english_residue_review_threshold: int = 70,
    progress_callback: SpanTranslateProgressCallback | None = None,
) -> tuple[set[int], dict]:
    locked_ids = set(locked_ids or set())
    selection_policy = {
        "max_spans": int(max_spans or 0),
        "max_segments_per_span": int(max_segments_per_span or 0),
        "max_duration": round(float(max_duration or 0.0), 3),
        "min_risk_score": int(min_risk_score or 0),
    }
    candidates = select_span_translation_candidates(
        source_spans,
        locked_ids,
        max_spans=max_spans,
        max_segments_per_span=max_segments_per_span,
        max_duration=max_duration,
        min_risk_score=min_risk_score,
    )
    if not candidates:
        return set(), {
            "schema_version": 1,
            "summary": {
                "eligible_span_count": 0,
                "attempted_count": 0,
                "translated_span_count": 0,
                "translated_segment_count": 0,
                "failed_count": 0,
                "selection_policy": selection_policy,
            },
            "results": [],
        }

    segments_by_id = {segment.id: segment for segment in segments}
    resolved_base_url = resolve_openai_base_url(base_url)
    span_prompt_examples = list(span_prompt_examples or [])
    translated_ids: set[int] = set()
    results: list[dict] = []
    for index, span in enumerate(candidates, start=1):
        matched_examples = select_span_prompt_examples(
            span,
            span_prompt_examples,
            top_k=span_prompt_example_top_k,
        )
        if progress_callback:
            progress_callback(
                "span_translation_start",
                {
                    "span_index": index,
                    "span_total": len(candidates),
                    "span_id": span.get("span_id"),
                    "segment_ids": span.get("segment_ids") or [],
                    "matched_span_example_count": len(matched_examples),
                },
            )
        result = translate_source_span_with_openai(
            span=span,
            all_segments=segments,
            segments_by_id=segments_by_id,
            src_lang=src_lang,
            dst_lang=dst_lang,
            glossary_text=glossary_text,
            style_prompt_text=style_prompt_text,
            span_prompt_examples=matched_examples,
            model=model,
            base_url=resolved_base_url,
            max_retries=max_retries,
            english_residue_validation_enabled=english_residue_validation_enabled,
            english_residue_preserve_threshold=english_residue_preserve_threshold,
            english_residue_review_threshold=english_residue_review_threshold,
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
            "span_prompt_example_count": len(span_prompt_examples),
            "span_prompt_example_top_k": int(span_prompt_example_top_k or 0),
            "selection_policy": selection_policy,
        },
        "results": results,
    }
