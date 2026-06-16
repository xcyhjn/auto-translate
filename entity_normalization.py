from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .glossary import load_glossary_payload
from .models import Segment
from .style_learning import parse_ass_dialogues


REGISTRY_PATH = Path(__file__).resolve().parent / "datasets" / "entity_registry.json"
PROJECT_DECISIONS_FILENAME = "00_entity_decisions.json"
BOOTSTRAP_MODE_OFF = "off"
BOOTSTRAP_MODE_ALWAYS = "always"
BOOTSTRAP_MODE_HIGH_CONFIDENCE_ONLY = "high_confidence_only"


@dataclass(slots=True)
class EntityRule:
    key: str
    entity_type: str
    canonical_en: str
    canonical_zh: str
    surface_forms: list[str]
    short_zh: str
    mention_strategy: str
    policy: str = "translate_full_name"
    canonical_native: str = ""


def _normalized_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def _entity_rule_from_item(item: dict) -> EntityRule | None:
    canonical_en = str(item.get("canonical_en") or "").strip()
    canonical_zh = str(item.get("canonical_zh") or "").strip()
    if not canonical_en or not canonical_zh:
        return None
    surface_forms = [str(value).strip() for value in item.get("surface_forms") or [] if str(value).strip()]
    if canonical_en not in surface_forms:
        surface_forms.insert(0, canonical_en)
    canonical_native = str(item.get("canonical_native") or "").strip()
    if canonical_native and canonical_native not in surface_forms:
        surface_forms.append(canonical_native)
    return EntityRule(
        key=str(item.get("key") or canonical_en),
        entity_type=str(item.get("entity_type") or "entity").strip(),
        canonical_en=canonical_en,
        canonical_zh=canonical_zh,
        surface_forms=surface_forms,
        short_zh=str(item.get("short_zh") or canonical_zh).strip(),
        mention_strategy=str(item.get("mention_strategy") or "full_only").strip(),
        policy=str(item.get("policy") or "translate_full_name").strip(),
        canonical_native=canonical_native,
    )


def _rules_from_payload(payload: object) -> list[EntityRule]:
    entities = payload.get("entities") if isinstance(payload, dict) else []
    rules: list[EntityRule] = []
    for item in entities:
        if not isinstance(item, dict):
            continue
        if rule := _entity_rule_from_item(item):
            rules.append(rule)
    return rules


def _entity_rule_to_dict(rule: EntityRule) -> dict:
    return {
        "key": rule.key,
        "entity_type": rule.entity_type,
        "canonical_en": rule.canonical_en,
        "canonical_native": rule.canonical_native,
        "canonical_zh": rule.canonical_zh,
        "surface_forms": rule.surface_forms,
        "short_zh": rule.short_zh,
        "mention_strategy": rule.mention_strategy,
        "policy": rule.policy,
    }


def load_entity_registry(path: str | Path | None = None) -> list[EntityRule]:
    registry_path = Path(path) if path else REGISTRY_PATH
    if not registry_path.exists():
        return []
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    return _rules_from_payload(payload)


def load_project_entity_decisions(project_dir: str | Path | None) -> list[EntityRule]:
    if not project_dir:
        return []
    decisions_path = Path(project_dir) / PROJECT_DECISIONS_FILENAME
    if not decisions_path.exists():
        return []
    payload = json.loads(decisions_path.read_text(encoding="utf-8"))
    return _rules_from_payload(payload)


def load_effective_entity_rules(
    *,
    registry_path: str | Path | None = None,
    project_dir: str | Path | None = None,
) -> list[EntityRule]:
    merged: dict[str, EntityRule] = {}
    for rule in load_entity_registry(registry_path):
        merged[rule.key] = rule
    for rule in load_project_entity_decisions(project_dir):
        merged[rule.key] = rule
    return list(merged.values())


def _build_en_replacement(rule: EntityRule) -> str:
    return rule.canonical_native or rule.canonical_en


def _surface_replacement(rule: EntityRule, surface: str, *, for_target: bool, mention_full: bool) -> str:
    normalized_surface = _normalized_key(surface)
    normalized_canonical_en = _normalized_key(rule.canonical_en)
    normalized_canonical_native = _normalized_key(rule.canonical_native)
    if for_target:
        if mention_full and re.search(r"\s", surface):
            return rule.canonical_zh
        if normalized_surface in {normalized_canonical_en, normalized_canonical_native}:
            return rule.canonical_zh if mention_full else rule.short_zh
        return rule.short_zh
    return _build_en_replacement(rule)


def _count_surface_hits(text: str, surface_forms: list[str]) -> int:
    count = 0
    for surface in surface_forms:
        if not surface:
            continue
        pattern = re.compile(rf"(?<![A-Za-z]){re.escape(surface)}(?![A-Za-z])", re.IGNORECASE)
        count += len(pattern.findall(text))
    return count


def _replace_surfaces(
    text: str,
    rule: EntityRule,
    *,
    for_target: bool,
    mention_full: bool,
) -> tuple[str, int]:
    placeholders: dict[str, str] = {}
    updated = text
    total = 0
    ordered_forms = sorted({form for form in rule.surface_forms if form}, key=len, reverse=True)
    for index, surface in enumerate(ordered_forms):
        pattern = re.compile(rf"(?<![A-Za-z]){re.escape(surface)}(?![A-Za-z])", re.IGNORECASE)
        replacement = _surface_replacement(rule, surface, for_target=for_target, mention_full=mention_full)
        placeholder = f"@@{index}@@"
        placeholders[placeholder] = replacement
        updated, hits = pattern.subn(placeholder, updated)
        total += hits
    for placeholder, replacement in placeholders.items():
        updated = updated.replace(placeholder, replacement)
    return updated, total


def maybe_bootstrap_project_entity_decisions(
    project_dir: str | Path | None,
    decisions: list[dict],
    *,
    registry_path: str | Path | None = None,
    mode: str = BOOTSTRAP_MODE_OFF,
) -> str:
    normalized_mode = str(mode or BOOTSTRAP_MODE_OFF).strip().lower()
    if normalized_mode == BOOTSTRAP_MODE_OFF:
        return ""
    if not project_dir:
        return ""
    output_path = Path(project_dir) / PROJECT_DECISIONS_FILENAME
    if output_path.exists():
        return str(output_path)
    encountered_keys = sorted({str(item.get("entity_key") or "").strip() for item in decisions if str(item.get("entity_key") or "").strip()})
    if not encountered_keys:
        return ""
    if normalized_mode == BOOTSTRAP_MODE_HIGH_CONFIDENCE_ONLY:
        if not decisions or any(str(item.get("mention_mode") or "") != "full" for item in decisions):
            return ""
    registry_rules = {rule.key: rule for rule in load_entity_registry(registry_path)}
    entities = [_entity_rule_to_dict(registry_rules[key]) for key in encountered_keys if key in registry_rules]
    if not entities:
        return ""
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entities": entities,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output_path)


def normalize_entities(
    segments: list[Segment],
    *,
    registry_path: str | Path | None = None,
    project_dir: str | Path | None = None,
    bootstrap_project_decisions: str | bool = BOOTSTRAP_MODE_OFF,
) -> dict:
    rules = load_effective_entity_rules(registry_path=registry_path, project_dir=project_dir)
    existing_project_decisions_path = ""
    if project_dir:
        candidate_path = Path(project_dir) / PROJECT_DECISIONS_FILENAME
        if candidate_path.exists():
            existing_project_decisions_path = str(candidate_path)
    if not rules:
        return {
            "summary": {
                "segments_changed": 0,
                "reference_text_replacements": 0,
                "target_text_replacements": 0,
                "rules_loaded": 0,
                "decision_count": 0,
                "project_decisions_path": existing_project_decisions_path,
            },
            "decisions": [],
        }

    changed_segments = 0
    reference_replacements = 0
    target_replacements = 0
    seen_entities: set[str] = set()
    decisions: list[dict] = []

    for segment in segments:
        changed = False
        reference_text = segment.reference_text or segment.source_text or ""
        target_text = segment.target_text or ""
        segment_decisions: list[dict] = []

        for rule in rules:
            segment_reference_hits = _count_surface_hits(reference_text, rule.surface_forms)
            segment_target_hits = _count_surface_hits(target_text, rule.surface_forms) if target_text else 0
            if not segment_reference_hits and not segment_target_hits:
                continue

            mention_full = rule.key not in seen_entities or rule.mention_strategy == "full_only"
            zh_replacement = rule.canonical_zh if mention_full else rule.short_zh
            normalized_reference, reference_hits = _replace_surfaces(
                reference_text,
                rule,
                for_target=False,
                mention_full=mention_full,
            )
            normalized_target, target_hits = (
                _replace_surfaces(
                    target_text,
                    rule,
                    for_target=True,
                    mention_full=mention_full,
                )
                if target_text
                else (target_text, 0)
            )

            if reference_hits:
                reference_text = normalized_reference
                reference_replacements += reference_hits
                changed = True
            if target_hits:
                target_text = normalized_target
                target_replacements += target_hits
                changed = True

            seen_entities.add(rule.key)
            segment_decisions.append(
                {
                    "segment_id": segment.id,
                    "entity_key": rule.key,
                    "entity_type": rule.entity_type,
                    "canonical_en": rule.canonical_en,
                    "canonical_zh": rule.canonical_zh,
                    "applied_target_text": zh_replacement,
                    "applied_reference_text": _build_en_replacement(rule),
                    "reference_hits": reference_hits,
                    "target_hits": target_hits,
                    "mention_mode": "full" if mention_full else "short",
                }
            )

        if changed:
            segment.reference_text = reference_text
            if segment.target_text is not None:
                segment.target_text = target_text
            changed_segments += 1
            decisions.extend(segment_decisions)

    project_decisions_path = maybe_bootstrap_project_entity_decisions(
        project_dir,
        decisions,
        registry_path=registry_path,
        mode=(
            BOOTSTRAP_MODE_ALWAYS
            if bootstrap_project_decisions is True
            else BOOTSTRAP_MODE_OFF
            if bootstrap_project_decisions is False
            else str(bootstrap_project_decisions or BOOTSTRAP_MODE_OFF)
        ),
    )

    return {
        "summary": {
            "segments_changed": changed_segments,
            "reference_text_replacements": reference_replacements,
            "target_text_replacements": target_replacements,
            "rules_loaded": len(rules),
            "decision_count": len(decisions),
            "project_decisions_path": project_decisions_path or existing_project_decisions_path,
        },
        "decisions": decisions,
    }


def build_entity_review_rows(
    segments: list[Segment],
    *,
    registry_path: str | Path | None = None,
    project_dir: str | Path | None = None,
    glossary_path: str | Path | None = None,
) -> list[dict]:
    rules = load_effective_entity_rules(registry_path=registry_path, project_dir=project_dir)
    known_surfaces = {_normalized_key(surface) for rule in rules for surface in rule.surface_forms}
    preserved_surfaces = {
        _normalized_key(surface)
        for rule in rules
        if rule.policy in {"preserve", "preserve_en"}
        for surface in rule.surface_forms
    }
    if glossary_path:
        glossary_payload = load_glossary_payload(Path(glossary_path))
        for item in glossary_payload.get("terms", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("policy") or "").strip() not in {"preserve", "preserve_en"}:
                continue
            canonical = str(item.get("canonical") or "").strip()
            if canonical:
                preserved_surfaces.add(_normalized_key(canonical))
            for alias in item.get("aliases") or []:
                cleaned = str(alias).strip()
                if cleaned:
                    preserved_surfaces.add(_normalized_key(cleaned))
    rows: list[dict] = []
    for segment in segments:
        target_text = segment.target_text or ""
        source_text = segment.source_text or ""
        reference_text = segment.reference_text or segment.source_text or ""
        if not target_text or not re.search(r"[\u3400-\u9fff]", target_text):
            continue
        source_norm = _normalized_key(source_text)
        reference_norm = _normalized_key(reference_text)
        for match in re.finditer(r"\b[A-Z][A-Za-z'.-]*(?:\s+[A-Z][A-Za-z'.-]*)*\b", target_text):
            candidate = match.group(0).strip()
            if not candidate:
                continue
            normalized_candidate = _normalized_key(candidate)
            if normalized_candidate in known_surfaces:
                continue
            if normalized_candidate in preserved_surfaces:
                continue
            if len(candidate) <= 2:
                continue
            if normalized_candidate not in source_norm and normalized_candidate not in reference_norm:
                continue
            if re.search(rf"[《“\"(（]\s*{re.escape(candidate)}\s*[》”\")）]", target_text):
                continue
            rows.append(
                {
                    "segment_id": segment.id,
                    "candidate": candidate,
                    "entity_type": "unknown",
                    "source_text": source_text,
                    "reference_text": reference_text,
                    "target_text": target_text,
                    "reason": "unknown_english_residue_in_chinese_target",
                }
            )
    return rows


def audit_ass_entities(
    ass_path: str | Path,
    *,
    registry_path: str | Path | None = None,
    project_dir: str | Path | None = None,
) -> dict:
    rules = load_effective_entity_rules(registry_path=registry_path, project_dir=project_dir)
    bad_surfaces = {
        surface: rule
        for rule in rules
        for surface in rule.surface_forms
        if _normalized_key(surface) not in {_normalized_key(rule.canonical_en), _normalized_key(rule.canonical_native)}
    }
    dialogues = parse_ass_dialogues(ass_path)
    issues: list[dict] = []
    for row in dialogues:
        text = row.text or ""
        if row.layer == 0:
            for match in re.finditer(r"\b[A-Z][A-Za-z'.-]*(?:\s+[A-Z][A-Za-z'.-]*)*\b", text):
                issues.append(
                    {
                        "layer": row.layer,
                        "style": row.style,
                        "start": row.start,
                        "end": row.end,
                        "issue_type": "english_residue_in_chinese_layer",
                        "text": match.group(0),
                        "line_text": text,
                    }
                )
        if row.layer == 1:
            normalized_text = _normalized_key(text)
            seen_rule_keys: set[str] = set()
            for surface, rule in bad_surfaces.items():
                if _normalized_key(surface) and _normalized_key(surface) in normalized_text:
                    if rule.key in seen_rule_keys:
                        continue
                    seen_rule_keys.add(rule.key)
                    issues.append(
                        {
                            "layer": row.layer,
                            "style": row.style,
                            "start": row.start,
                            "end": row.end,
                            "issue_type": "non_canonical_reference_name",
                            "entity_type": rule.entity_type,
                            "text": surface,
                            "canonical_en": rule.canonical_en,
                            "canonical_native": rule.canonical_native,
                            "line_text": text,
                        }
                    )
    return {
        "summary": {
            "issue_count": len(issues),
            "english_residue_count": sum(1 for item in issues if item["issue_type"] == "english_residue_in_chinese_layer"),
            "reference_name_issue_count": sum(1 for item in issues if item["issue_type"] == "non_canonical_reference_name"),
        },
        "issues": issues,
    }


def build_entity_metrics(entity_report: dict, ass_entity_audit: dict, quality_metrics: dict) -> dict:
    entity_summary = entity_report.get("summary") if isinstance(entity_report, dict) else {}
    audit_summary = ass_entity_audit.get("summary") if isinstance(ass_entity_audit, dict) else {}
    translation = quality_metrics.get("translation") if isinstance(quality_metrics, dict) else {}
    decisions = entity_report.get("decisions") if isinstance(entity_report, dict) else []
    entity_type_counts: dict[str, int] = {}
    if isinstance(decisions, list):
        for item in decisions:
            if not isinstance(item, dict):
                continue
            entity_type = str(item.get("entity_type") or "unknown")
            entity_type_counts[entity_type] = entity_type_counts.get(entity_type, 0) + 1
    return {
        "schema_version": 1,
        "summary": {
            "entity_decision_count": int(entity_summary.get("decision_count") or 0),
            "segments_changed": int(entity_summary.get("segments_changed") or 0),
            "reference_text_replacements": int(entity_summary.get("reference_text_replacements") or 0),
            "target_text_replacements": int(entity_summary.get("target_text_replacements") or 0),
            "ass_issue_count": int(audit_summary.get("issue_count") or 0),
            "ass_english_residue_count": int(audit_summary.get("english_residue_count") or 0),
            "ass_reference_name_issue_count": int(audit_summary.get("reference_name_issue_count") or 0),
            "target_entity_residue_count": int(translation.get("entity_residue_count") or 0),
            "english_residue_count": int(translation.get("english_residue_count") or 0),
            "english_residue_review_count": int(translation.get("english_residue_review_count") or 0),
            "english_residue_preserved_count": int(translation.get("english_residue_preserved_count") or 0),
        },
        "entity_report_summary": entity_summary or {},
        "ass_entity_audit_summary": audit_summary or {},
        "entity_type_counts": entity_type_counts,
        "entity_residue_samples": list(translation.get("entity_residue_samples") or []) if isinstance(translation, dict) else [],
    }
