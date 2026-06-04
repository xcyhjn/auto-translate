from __future__ import annotations

import re

from .models import Segment


RU_REFERENCE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bShushu\b", re.IGNORECASE), "Xiu Xiu"),
    (re.compile(r"\bShu-shu\b", re.IGNORECASE), "Xiu Xiu"),
    (re.compile(r"\bShu shu\b", re.IGNORECASE), "Xiu Xiu"),
    (re.compile(r"\bШу\s*-\s*Шу\b", re.IGNORECASE), "Xiu Xiu"),
    (re.compile(r"\bШу\s+Шу\b", re.IGNORECASE), "Xiu Xiu"),
    (re.compile(r"\bХиу\s*-\s*Хиу\b", re.IGNORECASE), "Hiu-hiu"),
    (re.compile(r"\bСю\s*-\s*Сю\b", re.IGNORECASE), "Syu-Syu"),
    (re.compile(r"\bThe sent\s*-\s*down girl\b", re.IGNORECASE), "The Sent-Down Girl"),
    (re.compile(r"\bв этой графе\b", re.IGNORECASE), "в дискографии"),
    (re.compile(r"\bвставив его в свой гостиничный номер\b", re.IGNORECASE), "затащив его в свой гостиничный номер"),
    (re.compile(r"\bI must have forgot nothing to prove\.", re.IGNORECASE), "I must have forgotten I had nothing to prove."),
)


ZH_TARGET_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bShushu\b", re.IGNORECASE), "Xiu Xiu"),
    (re.compile(r"\bShu-shu\b", re.IGNORECASE), "Xiu Xiu"),
    (re.compile(r"\bShu shu\b", re.IGNORECASE), "Xiu Xiu"),
    (re.compile(r"舒舒"), "Xiu Xiu"),
    (re.compile(r"休休"), "Xiu Xiu"),
    (re.compile(r"咻咻"), "Xiu Xiu"),
    (re.compile(r"XiuXiu", re.IGNORECASE), "Xiu Xiu"),
    (re.compile(r"《Shushu：下乡女孩》"), "《Xiu Xiu: The Sent-Down Girl》"),
    (re.compile(r"《Shu Shu:\s*The Sent-Down Girl》", re.IGNORECASE), "《Xiu Xiu: The Sent-Down Girl》"),
    (re.compile(r"《Shu Shu:\s*The sent-down girl》", re.IGNORECASE), "《Xiu Xiu: The Sent-Down Girl》"),
    (re.compile(r"《Shu Shu:\s*The Sent-DownGirl》", re.IGNORECASE), "《Xiu Xiu: The Sent-Down Girl》"),
    (re.compile(r"而不叫“XIU XIU”或“Syu-Syu”"), "而不叫“Hiu-hiu”或“Syu-Syu”"),
)


def apply_text_replacements(
    text: str | None,
    replacements: tuple[tuple[re.Pattern[str], str], ...],
) -> tuple[str | None, int]:
    if text is None:
        return None, 0
    updated = text
    count = 0
    for pattern, replacement in replacements:
        updated, hits = pattern.subn(replacement, updated)
        count += hits
    return updated, count


def postprocess_bilingual_segments(segments: list[Segment]) -> dict:
    source_count = 0
    target_count = 0
    changed_segments = 0

    for segment in segments:
        changed = False
        source_text, source_hits = apply_text_replacements(segment.source_text, RU_REFERENCE_REPLACEMENTS)
        target_text, target_hits = apply_text_replacements(segment.target_text, ZH_TARGET_REPLACEMENTS)
        if source_hits:
            segment.source_text = source_text or ""
            source_count += source_hits
            changed = True
        if target_hits and target_text is not None:
            segment.target_text = target_text
            target_count += target_hits
            changed = True
        if changed:
            changed_segments += 1

    return {
        "segments_changed": changed_segments,
        "source_text_replacements": source_count,
        "target_text_replacements": target_count,
        "total_replacements": source_count + target_count,
    }
