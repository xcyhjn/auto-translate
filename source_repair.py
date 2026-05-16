from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .glossary import clean_candidate, load_glossary_payload, normalize_term_key, term_pattern
from .models import Segment, Word


WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'.-]*")


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


def repair_source_segments(
    segments: list[Segment],
    glossary_path: str | Path | None,
) -> dict:
    rules = load_source_repair_rules(glossary_path)
    repairs: list[dict] = []
    rule_hits: Counter[str] = Counter()

    if not rules:
        return {
            "schema_version": 1,
            "summary": {
                "segment_count": len(segments),
                "rule_count": 0,
                "repaired_segment_count": 0,
                "replacement_count": 0,
            },
            "repairs": [],
        }

    for segment in segments:
        original_text = segment.source_text or ""
        repaired_text = original_text
        segment_repairs: list[dict] = []
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
