from __future__ import annotations

import json
import os
from pathlib import Path
import re
from collections import Counter
import time

from .models import BilingualSubtitleStyle, Segment
from .subtitle_io import normalize_inline_text, visible_text_length
from .translate import (
    classify_retry,
    contains_chinese,
    has_translatable_alpha_text,
    normalize_for_equality,
    resolve_openai_base_url,
    short_error_message,
)


OPEN_ENDING_SUFFIXES = (
    "，",
    "、",
    "；",
    "和",
    "与",
    "但",
    "而",
    "如果",
    "关于",
    "一个",
    "这个",
    "那个",
    "并",
    "被",
    "把",
    "在",
    "对",
    "从",
    "为",
    "以",
    "的",
)
LONE_FRAGMENT_PREFIXES = (
    "这就是",
    "因为",
    "也就是",
    "而且",
    "所以",
    "但是",
    "不过",
)
FILLER_PATTERNS = (
    (re.compile(r"\s+"), " "),
)
FILLER_PREFIX_RE = re.compile(r"^(嗯|呃|啊|就是|然后)[，,、\s]+")
FILLER_SUFFIX_RE = re.compile(r"[，,、\s]+(嗯|呃|啊)$")
REPEATED_PUNCTUATION_RE = re.compile(r"([，。！？；、!?;])\1+")


def ends_with_open_ending(text: str) -> bool:
    stripped = normalize_inline_text(text)
    return bool(stripped and stripped.endswith(OPEN_ENDING_SUFFIXES))


def is_lone_fragment(text: str) -> bool:
    stripped = normalize_inline_text(text)
    return bool(stripped in LONE_FRAGMENT_PREFIXES or stripped.rstrip("，,") in LONE_FRAGMENT_PREFIXES)


def cleanup_chinese_text(text: str) -> str:
    cleaned = normalize_inline_text(text)
    cleaned = cleaned.replace(" ,", "，").replace(" .", "。")
    cleaned = REPEATED_PUNCTUATION_RE.sub(r"\1", cleaned)
    for pattern, replacement in FILLER_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned).strip()
    return cleaned


def trim_soft_open_suffix(text: str) -> tuple[str, str | None]:
    stripped = normalize_inline_text(text)
    trim_candidates = ("，", "、", "；")
    for suffix in trim_candidates:
        if not stripped.endswith(suffix):
            continue
        candidate = stripped[: -len(suffix)].rstrip("，,、；; ")
        if visible_text_length(candidate) >= 4 and contains_chinese(candidate):
            return candidate, suffix
    return stripped, None


def rewrite_segment_text(segment: Segment, style: BilingualSubtitleStyle) -> tuple[str, list[str], dict]:
    original = segment.target_text or ""
    rewritten = cleanup_chinese_text(original)
    actions: list[str] = []
    details: dict = {}

    if rewritten != original:
        actions.append("cleanup")

    visible_len = visible_text_length(rewritten)
    duration = max(0.001, float(segment.end) - float(segment.start))
    cps = visible_len / duration
    hard_line_limit = max(8, int(style.zh_max_chars_per_line or 28))
    soft_cps_limit = 18.0

    if is_lone_fragment(rewritten):
        actions.append("review_lone_fragment")
    if ends_with_open_ending(rewritten):
        actions.append("review_open_ending")
    if FILLER_PREFIX_RE.search(rewritten) or FILLER_SUFFIX_RE.search(rewritten):
        actions.append("review_filler")
    if rewritten and not contains_chinese(rewritten) and has_translatable_alpha_text(segment.source_text):
        actions.append("review_no_chinese")
    if rewritten and normalize_for_equality(rewritten) == normalize_for_equality(segment.source_text):
        actions.append("review_source_echo")
    if visible_len > hard_line_limit:
        actions.append("review_line_long")
    if cps > soft_cps_limit:
        actions.append("review_cps_high")

    details.update(
        {
            "visible_length": visible_len,
            "duration": round(duration, 3),
            "cps": round(cps, 2),
            "line_limit": hard_line_limit,
        }
    )
    return rewritten, actions, details


def should_use_ai_display_rewrite(actions: list[str], details: dict) -> bool:
    if not actions:
        return False
    action_set = set(actions)
    if action_set & {"review_open_ending", "review_lone_fragment", "review_source_echo"}:
        return True
    if "review_cps_high" in action_set and float(details.get("cps") or 0.0) >= 20.0:
        return True
    if "review_line_long" in action_set and int(details.get("visible_length") or 0) >= 30:
        return True
    return False


def load_style_examples(style_prompt_path: str | Path | None) -> list[dict]:
    if not style_prompt_path:
        return []
    prompt_path = Path(style_prompt_path)
    examples_path = prompt_path.with_name("00_style_examples.jsonl")
    if not examples_path.exists():
        return []
    rows: list[dict] = []
    for raw_line in examples_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def tokenize_prompt_text(text: str) -> set[str]:
    normalized = normalize_inline_text(text)
    english_tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z]{2,}", normalized)
    }
    chinese_bigrams = {
        normalized[index : index + 2]
        for index in range(max(0, len(normalized) - 1))
        if re.search(r"[\u3400-\u9fff]", normalized[index : index + 2])
    }
    return english_tokens | chinese_bigrams


def score_style_example(segment: Segment, example: dict) -> float:
    target_tokens = tokenize_prompt_text(segment.source_text) | tokenize_prompt_text(segment.target_text or "")
    example_features = example.get("features") if isinstance(example.get("features"), dict) else {}
    example_tokens = set(example_features.get("source_tokens") or []) | set(example_features.get("machine_tokens") or [])
    overlap = len(target_tokens & example_tokens)
    if not overlap:
        return 0.0
    source_length = len(segment.source_text or "")
    example_length = int(example_features.get("source_length") or len(str(example.get("source_text") or "")))
    length_penalty = abs(source_length - example_length) / max(1, source_length, example_length)
    tag_bonus = 0.0
    example_tags = set(example.get("edit_tags") or [])
    if example_tags & {"fixed_open_ending", "compressed", "manual_linebreak"}:
        tag_bonus += 0.5
    signal_score = float(example.get("signal_score") or 0.0)
    return overlap - length_penalty + tag_bonus + signal_score * 0.15


def score_style_example_for_actions(example: dict, actions: list[str]) -> float:
    action_score = 0.0
    example_tags = set(example.get("edit_tags") or [])
    action_set = set(actions)
    if "review_open_ending" in action_set and "fixed_open_ending" in example_tags:
        action_score += 3.0
    if "review_cps_high" in action_set and "compressed" in example_tags:
        action_score += 2.5
    if "review_line_long" in action_set and ("compressed" in example_tags or "manual_linebreak" in example_tags):
        action_score += 2.0
    if "review_no_chinese" in action_set and "preserve_english" in example_tags:
        action_score += 1.5
    if "review_lone_fragment" in action_set and "fixed_open_ending" in example_tags:
        action_score += 2.0
    return action_score


def select_relevant_style_examples(
    segment: Segment,
    examples: list[dict],
    *,
    actions: list[str],
    limit: int = 4,
) -> list[dict]:
    ranked = sorted(
        (
            (score_style_example(segment, example) + score_style_example_for_actions(example, actions), example)
            for example in examples
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    selected = [example for score, example in ranked if score > 0][:limit]
    return selected


def build_display_rewrite_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "target_text": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["target_text", "note"],
        "additionalProperties": False,
    }


def build_display_rewrite_prompt(
    *,
    segment: Segment,
    style: BilingualSubtitleStyle,
    style_prompt_text: str,
    style_examples: list[dict],
    actions: list[str],
    details: dict,
) -> str:
    example_lines: list[str] = []
    for example in style_examples:
        operation_summary = example.get("operation_summary") if isinstance(example.get("operation_summary"), dict) else {}
        example_lines.extend(
            [
                f"- Edit pattern: {operation_summary.get('operation', 'rewrite')}",
                f"  Strategies: {', '.join(operation_summary.get('strategies') or []) or 'rewrite'}",
                f"  Machine shape: {operation_summary.get('machine_shape', '')}",
                f"  Manual shape: {operation_summary.get('manual_shape', '')}",
                f"  Length delta: {operation_summary.get('length_delta', 0)}",
                f"  Drops open ending: {operation_summary.get('drops_open_ending', False)}",
                f"  Tags: {', '.join(example.get('edit_tags') or []) or 'none'}",
                f"  Signal: {example.get('signal_score', 0)}",
            ]
        )
    examples_block = "\n".join(example_lines) if example_lines else "- No closely related examples found."
    return (
        "You are editing a Chinese subtitle line for final on-screen readability.\n"
        "Rewrite only the Chinese target text.\n\n"
        "Rules:\n"
        "- Chinese must read naturally and stand on its own on screen.\n"
        "- Keep the meaning aligned with the source text.\n"
        "- Compress instead of expanding when the line is too dense.\n"
        "- Avoid dangling endings such as 的, 和, 但, 因为, 所以.\n"
        "- Preserve names and glossary-sensitive terms when already present.\n"
        "- Learn from the abstract editing patterns of examples, not from their topic content.\n"
        "- Apply segmentation, semantic closure, and compression strategies in a content-agnostic way.\n"
        "- Do not add markdown, bullets, explanations, or manual line breaks.\n"
        f"- Target line length should fit within about {int(style.zh_max_chars_per_line or 28)} visible Chinese characters.\n"
        f"- Target CPS should be close to or below 18 when possible.\n\n"
        f"Style guidance:\n{style_prompt_text or 'No extra style guidance.'}\n\n"
        f"Relevant style examples:\n{examples_block}\n\n"
        f"Source text: {segment.source_text}\n"
        f"Current target text: {segment.target_text or ''}\n"
        f"Risk actions: {', '.join(actions)}\n"
        f"Metrics: {json.dumps(details, ensure_ascii=False)}\n\n"
        "Return JSON matching the supplied schema."
    )


def rewrite_segment_with_openai(
    segment: Segment,
    *,
    style: BilingualSubtitleStyle,
    style_prompt_text: str,
    style_examples: list[dict],
    actions: list[str],
    details: dict,
    model: str,
    base_url: str | None,
    max_retries: int,
) -> tuple[str | None, str]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The OpenAI Python SDK is not installed. Install it with: python -m pip install openai"
        ) from exc

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")

    client_kwargs = {"timeout": 600.0}
    resolved_base_url = resolve_openai_base_url(base_url)
    if resolved_base_url:
        client_kwargs["base_url"] = resolved_base_url
    client = OpenAI(**client_kwargs)
    prompt = build_display_rewrite_prompt(
        segment=segment,
        style=style,
        style_prompt_text=style_prompt_text,
        style_examples=style_examples,
        actions=actions,
        details=details,
    )
    schema = build_display_rewrite_schema()
    raw_text = ""

    for attempt in range(max_retries + 1):
        try:
            response = client.responses.create(
                model=model,
                input=prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "display_rewrite",
                        "strict": True,
                        "schema": schema,
                    },
                    "verbosity": "low",
                },
            )
            raw_text = response.output_text.strip()
            payload = json.loads(raw_text)
            target_text = normalize_inline_text(str(payload.get("target_text") or ""))
            note = str(payload.get("note") or "").strip()
            if not target_text:
                raise RuntimeError("Empty AI display rewrite result.")
            return target_text, note
        except Exception as exc:
            if attempt >= max_retries:
                return None, short_error_message(exc)
            wait_seconds, _ = classify_retry(exc, attempt, max_retries)
            time.sleep(wait_seconds)

    return None, "unknown"


def rewrite_display_segments(
    segments: list[Segment],
    style: BilingualSubtitleStyle | None = None,
    *,
    style_prompt_path: str | Path | None = None,
    enable_ai_rewrite: bool = False,
    ai_model: str = "gpt-5.4-mini",
    openai_base_url: str | None = None,
    max_retries: int = 2,
    max_ai_segments: int = 12,
) -> dict:
    if style is None:
        style = BilingualSubtitleStyle()

    style_prompt_excerpt = ""
    style_prompt_text = ""
    style_examples: list[dict] = []
    if style_prompt_path:
        candidate = Path(style_prompt_path)
        if candidate.exists():
            style_prompt_text = candidate.read_text(encoding="utf-8").strip()
            style_prompt_excerpt = "\n".join(style_prompt_text.splitlines()[:12])[:600]
            style_examples = load_style_examples(candidate)

    changes: list[dict] = []
    action_counts: Counter[str] = Counter()
    ai_rewrite_attempted = 0
    ai_rewrite_changed = 0
    for segment in segments:
        if segment.target_text is None:
            continue
        original = segment.target_text
        rewritten, actions, details = rewrite_segment_text(segment, style)
        ai_note = ""
        if (
            enable_ai_rewrite
            and style_prompt_text
            and ai_rewrite_attempted < max(0, int(max_ai_segments or 0))
            and should_use_ai_display_rewrite(actions, details)
        ):
            ai_rewrite_attempted += 1
            matched_examples = select_relevant_style_examples(
                segment,
                style_examples,
                actions=actions,
            )
            ai_rewritten, ai_note = rewrite_segment_with_openai(
                segment,
                style=style,
                style_prompt_text=style_prompt_text,
                style_examples=matched_examples,
                actions=actions,
                details=details,
                model=ai_model,
                base_url=openai_base_url,
                max_retries=max_retries,
            )
            if ai_rewritten and ai_rewritten != rewritten:
                rewritten = ai_rewritten
                actions.append("ai_style_rewrite")
                ai_rewrite_changed += 1
        if rewritten != original:
            segment.target_text = rewritten
        if actions:
            action_counts.update(actions)
            changes.append(
                {
                    "segment_id": segment.id,
                    "start": segment.start,
                    "end": segment.end,
                    "source_text": segment.source_text,
                    "original_target_text": original,
                    "rewritten_target_text": rewritten,
                    "changed": rewritten != original,
                    "actions": actions,
                    "ai_note": ai_note,
                    "matched_style_example_count": len(matched_examples) if enable_ai_rewrite and style_prompt_text else 0,
                    "matched_style_example_ids": [
                        str(item.get("example_id") or "")
                        for item in matched_examples
                    ] if enable_ai_rewrite and style_prompt_text else [],
                    **details,
                }
            )

    return {
        "schema_version": 1,
        "summary": {
            "segment_count": len(segments),
            "review_or_change_count": len(changes),
            "changed_count": sum(1 for item in changes if item.get("changed")),
            "action_counts": dict(sorted(action_counts.items())),
            "style_prompt_loaded": bool(style_prompt_excerpt),
            "ai_rewrite_enabled": bool(enable_ai_rewrite),
            "ai_rewrite_attempted": ai_rewrite_attempted,
            "ai_rewrite_changed": ai_rewrite_changed,
        },
        "style_prompt_excerpt": style_prompt_excerpt,
        "changes": changes,
    }
