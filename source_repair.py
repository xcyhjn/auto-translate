from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .glossary import clean_candidate, load_glossary_payload, normalize_term_key, term_pattern
from .models import Segment, Word
from .text_quality import ASMR_PET_CONTEXT_RE


WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'.-]*")
ASR_REPAIR_CONTEXT_RADIUS = 2


def source_context_text(segments: list[Segment], index: int, *, radius: int = ASR_REPAIR_CONTEXT_RADIUS) -> str:
    start = max(0, index - radius)
    end = min(len(segments), index + radius + 1)
    return " ".join(segment.source_text or "" for segment in segments[start:end])


def replace_i_love_fragment(text: str) -> tuple[str, int]:
    repaired, count = re.subn(r"\bI\s+love\s*\.\s*$", "I love you.", text, flags=re.IGNORECASE)
    return repaired, count


def repair_builtin_asr_text(text: str, *, context_text: str = "") -> tuple[str, list[dict]]:
    repaired = text or ""
    repairs: list[dict] = []

    pet_context = ASMR_PET_CONTEXT_RE.search(f"{context_text} {repaired}") is not None
    if pet_context:
        def replace_pet(match: re.Match[str]) -> str:
            prefix = match.group(1)
            return f"{prefix} pet you"

        repaired, count = re.subn(
            r"\b(I(?:'|’)?ll|I\s+will|when\s+I|while\s+I|if\s+I)\s+bet\s+you\b",
            replace_pet,
            repaired,
            flags=re.IGNORECASE,
        )
        if count:
            repairs.append(
                {
                    "bad_alias": "bet you",
                    "canonical": "pet you",
                    "reason": "builtin_asr_pet_bet_context",
                    "confidence": 0.92,
                    "replacement_count": count,
                }
            )

    repaired, count = re.subn(r"\bfeel\s+good\s+good\b", "feel good", repaired, flags=re.IGNORECASE)
    if count:
        repairs.append(
            {
                "bad_alias": "feel good good",
                "canonical": "feel good",
                "reason": "builtin_asr_duplicate_word",
                "confidence": 0.95,
                "replacement_count": count,
            }
        )

    repaired, count = re.subn(
        r"\bYou\s+don'?t\s+need\s+me\s+to\s+give\s+me\s+the\s+world\b",
        "You don't need to give me the world",
        repaired,
        flags=re.IGNORECASE,
    )
    if count:
        repairs.append(
            {
                "bad_alias": "You don't need me to give me the world",
                "canonical": "You don't need to give me the world",
                "reason": "builtin_asr_inserted_pronoun",
                "confidence": 0.9,
                "replacement_count": count,
            }
        )

    if pet_context or re.search(r"\b(?:you|darling|honey|sweetheart|baby)\b", f"{context_text} {repaired}", re.IGNORECASE):
        repaired, count = replace_i_love_fragment(repaired)
        if count:
            repairs.append(
                {
                    "bad_alias": "I love.",
                    "canonical": "I love you.",
                    "reason": "builtin_asr_truncated_phrase",
                    "confidence": 0.8,
                    "replacement_count": count,
                }
            )

    return repaired, repairs


def load_source_repair_rules(glossary_path: str | Path | None) -> list[dict]:
    if not glossary_path:
        return []
    path = Path(glossary_path)
    if not path.exists():
        return []

    payload = load_glossary_payload(path)
    rules: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.get("terms", []):
        if not isinstance(item, dict):
            continue
        canonical = clean_candidate(str(item.get("canonical") or ""))
        if len(canonical) < 3:
            continue
        confidence = float(item.get("confidence") or 0.0)
        term_id = str(item.get("id") or normalize_term_key(canonical)).strip()
        sources = [str(value) for value in item.get("sources") or []]
        for raw_alias in item.get("bad_aliases") or []:
            bad_alias = clean_candidate(str(raw_alias))
            if len(bad_alias) < 3:
                continue
            if normalize_term_key(bad_alias) == normalize_term_key(canonical):
                continue
            key = (normalize_term_key(bad_alias), canonical)
            if key in seen:
                continue
            seen.add(key)
            rules.append(
                {
                    "bad_alias": bad_alias,
                    "canonical": canonical,
                    "term_id": term_id,
                    "confidence": confidence,
                    "reason": "glossary_bad_alias",
                    "sources": sources,
                }
            )
    rules.sort(key=lambda item: len(str(item["bad_alias"])), reverse=True)
    return rules


def alias_tokens(text: str) -> list[str]:
    return [normalize_term_key(token) for token in WORD_RE.findall(text or "") if normalize_term_key(token)]


def word_token(word: Word) -> str:
    return normalize_term_key(" ".join(WORD_RE.findall(word.word or "")))


def repair_word_items(words: list[Word], bad_alias: str, canonical: str) -> list[int]:
    bad_tokens = alias_tokens(bad_alias)
    canonical_tokens = WORD_RE.findall(canonical or "")
    if not words or not bad_tokens or len(bad_tokens) != len(canonical_tokens):
        return []

    changed: list[int] = []
    normalized_words = [word_token(word) for word in words]
    window_size = len(bad_tokens)
    for start in range(0, len(words) - window_size + 1):
        if normalized_words[start : start + window_size] != bad_tokens:
            continue
        for offset, replacement in enumerate(canonical_tokens):
            index = start + offset
            if words[index].word != replacement:
                words[index].word = replacement
                changed.append(index)
    return changed


def builtin_word_repair_items(words: list[Word], repair: dict) -> list[int]:
    bad_alias = str(repair.get("bad_alias") or "")
    canonical = str(repair.get("canonical") or "")
    if not words or not bad_alias or not canonical:
        return []
    return repair_word_items(words, bad_alias, canonical)


def repair_source_segments(
    segments: list[Segment],
    glossary_path: str | Path | None,
) -> dict:
    rules = load_source_repair_rules(glossary_path)
    repairs: list[dict] = []
    rule_hits: Counter[str] = Counter()

    for index, segment in enumerate(segments):
        original_text = segment.source_text or ""
        repaired_text = original_text
        segment_repairs: list[dict] = []
        repaired_text, builtin_repairs = repair_builtin_asr_text(
            repaired_text,
            context_text=source_context_text(segments, index),
        )
        for repair in builtin_repairs:
            changed_word_indexes = builtin_word_repair_items(segment.words, repair)
            segment_repairs.append(
                {
                    **repair,
                    "term_id": repair["reason"],
                    "word_indexes": changed_word_indexes,
                    "word_text_changed": bool(changed_word_indexes),
                    "sources": ["builtin_asr_repair"],
                }
            )
            rule_hits[str(repair["reason"])] += int(repair.get("replacement_count") or 0)

        for rule in rules:
            pattern = term_pattern(str(rule["bad_alias"]))
            repaired_text, count = pattern.subn(str(rule["canonical"]), repaired_text)
            if count <= 0:
                continue

            changed_word_indexes = repair_word_items(
                segment.words,
                str(rule["bad_alias"]),
                str(rule["canonical"]),
            )
            rule_hits[str(rule["term_id"])] += count
            segment_repairs.append(
                {
                    "bad_alias": rule["bad_alias"],
                    "canonical": rule["canonical"],
                    "reason": rule["reason"],
                    "confidence": rule["confidence"],
                    "term_id": rule["term_id"],
                    "replacement_count": count,
                    "word_indexes": changed_word_indexes,
                    "word_text_changed": bool(changed_word_indexes),
                    "sources": rule["sources"],
                }
            )

        if repaired_text == original_text:
            continue

        segment.source_text = repaired_text
        repairs.append(
            {
                "segment_id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "original_source_text": original_text,
                "repaired_source_text": repaired_text,
                "repairs": segment_repairs,
            }
        )

    return {
        "schema_version": 1,
        "summary": {
            "segment_count": len(segments),
            "rule_count": len(rules),
            "repaired_segment_count": len(repairs),
            "replacement_count": sum(
                int(item["replacement_count"])
                for repair in repairs
                for item in repair.get("repairs", [])
            ),
            "term_hit_count": dict(sorted(rule_hits.items())),
        },
        "repairs": repairs,
    }
