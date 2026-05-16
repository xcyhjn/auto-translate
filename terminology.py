from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .glossary import clean_candidate, load_glossary_payload, normalize_term_key
from .models import Segment
from .translate import normalize_term_text


LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
TRAILING_POSSESSIVE_RE = re.compile(r"(?:'s|s')$", re.IGNORECASE)


def normalize_pure_term_text(text: str) -> str:
    cleaned = clean_candidate(text)
    cleaned = LEADING_ARTICLE_RE.sub("", cleaned)
    cleaned = TRAILING_POSSESSIVE_RE.sub("", cleaned)
    return normalize_term_text(cleaned)


def load_terminology_rules(glossary_path: str | Path | None) -> list[dict]:
    if not glossary_path:
        return []
    path = Path(glossary_path)
    if not path.exists() or path.suffix.lower() != ".json":
        return []

    payload = load_glossary_payload(path)
    rules: list[dict] = []
    for item in payload.get("terms", []):
        if not isinstance(item, dict):
            continue
        canonical = clean_candidate(str(item.get("canonical") or ""))
        if len(canonical) < 2:
            continue
        zh = str(item.get("zh") or canonical).strip() or canonical
        policy = str(item.get("policy") or "preserve").strip()
        aliases = [clean_candidate(str(value)) for value in item.get("aliases") or [] if clean_candidate(str(value))]
        bad_aliases = [clean_candidate(str(value)) for value in item.get("bad_aliases") or [] if clean_candidate(str(value))]
        forms = [canonical, zh, *aliases, *bad_aliases]
        normalized_forms = {
            normalize_pure_term_text(form)
            for form in forms
            if normalize_pure_term_text(form)
        }
        rules.append(
            {
                "term_id": str(item.get("id") or normalize_term_key(canonical)),
                "canonical": canonical,
                "zh": zh,
                "policy": policy,
                "priority": str(item.get("priority") or ""),
                "type": str(item.get("type") or "term"),
                "confidence": float(item.get("confidence") or 0.0),
                "short_name": str(item.get("short_name") or ""),
                "normalized_forms": normalized_forms,
            }
        )
    rules.sort(key=lambda item: (str(item["priority"]) != "hard", -len(str(item["canonical"]))))
    return rules


def target_for_policy(rule: dict, *, first_mention: bool) -> str:
    canonical = str(rule["canonical"])
    zh = str(rule.get("zh") or canonical)
    policy = str(rule.get("policy") or "preserve")
    short_name = str(rule.get("short_name") or "").strip()
    if policy == "translate":
        return zh
    if policy == "mixed":
        if first_mention and zh and normalize_term_text(zh) != normalize_term_text(canonical):
            return f"{zh}（{canonical}）"
        return short_name or zh or canonical
    return canonical


def apply_terminology_short_circuit(
    segments: list[Segment],
    glossary_path: str | Path | None,
) -> tuple[set[int], dict]:
    rules = load_terminology_rules(glossary_path)
    locked_ids: set[int] = set()
    actions: list[dict] = []
    seen_terms: set[str] = set()
    policy_counts: Counter[str] = Counter()

    if not rules:
        return locked_ids, {
            "schema_version": 1,
            "summary": {
                "segment_count": len(segments),
                "rule_count": 0,
                "locked_segment_count": 0,
                "action_count": 0,
            },
            "actions": [],
        }

    for segment in segments:
        normalized_source = normalize_pure_term_text(segment.source_text or "")
        if not normalized_source:
            continue
        for rule in rules:
            if normalized_source not in rule["normalized_forms"]:
                continue
            term_id = str(rule["term_id"])
            first_mention = term_id not in seen_terms
            target_text = target_for_policy(rule, first_mention=first_mention)
            if not target_text:
                continue
            original_target = segment.target_text
            segment.target_text = target_text
            locked_ids.add(segment.id)
            seen_terms.add(term_id)
            policy_counts[str(rule.get("policy") or "preserve")] += 1
            actions.append(
                {
                    "segment_id": segment.id,
                    "start": segment.start,
                    "end": segment.end,
                    "source_text": segment.source_text,
                    "original_target_text": original_target or "",
                    "target_text": target_text,
                    "term_id": term_id,
                    "canonical": rule["canonical"],
                    "zh": rule.get("zh") or "",
                    "policy": rule.get("policy") or "preserve",
                    "first_mention": first_mention,
                    "reason": "pure_term_cue",
                }
            )
            break

    return locked_ids, {
        "schema_version": 1,
        "summary": {
            "segment_count": len(segments),
            "rule_count": len(rules),
            "locked_segment_count": len(locked_ids),
            "action_count": len(actions),
            "policy_counts": dict(sorted(policy_counts.items())),
        },
        "actions": actions,
    }
