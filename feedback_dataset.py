from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .bilibili_search import build_bilibili_query_plan, parse_duration_to_seconds, score_bilibili_candidate
from .style_learning import (
    align_segments_to_manual_ass,
    build_edit_operation_summary,
    build_style_features,
    detect_edit_tags,
)


SCHEMA_VERSION = 1
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET_DIR = BASE_DIR / "datasets" / "local_feedback"
BILIBILI_LABELS = {"duplicate", "not_duplicate", "same_topic", "manual_review"}
STYLE_FEEDBACK_TYPES = {
    "bad_example",
    "linebreak_fix",
    "qa_repair",
    "semantic_fix",
    "style_edit",
    "surface_edit",
    "term_fix",
}
STYLE_LEARNING_RISKS = {"low", "medium", "high"}
STYLE_LEARNING_RECOMMENDATIONS = {"eval_candidate", "review_only", "style_prompt_candidate"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Invalid JSONL at {path}:{line_no}: record must be an object")
        records.append(payload)
    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def dataset_paths(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict[str, Path]:
    return {
        "root": dataset_dir,
        "schema": dataset_dir / "schema_version.json",
        "bilibili_labels": dataset_dir / "bilibili_duplicate_labels.jsonl",
        "translation_edits": dataset_dir / "translation_edit_examples.jsonl",
        "term_decisions": dataset_dir / "term_entity_decisions.jsonl",
        "qa_repairs": dataset_dir / "qa_repair_examples.jsonl",
        "eval_sets": dataset_dir / "eval_sets",
        "bilibili_gold": dataset_dir / "eval_sets" / "bilibili_duplicate_gold.jsonl",
        "style_gold": dataset_dir / "eval_sets" / "translation_style_gold.jsonl",
        "eval_reports": dataset_dir / "eval_reports",
        "latest_bilibili_eval": dataset_dir / "eval_reports" / "latest_bilibili_eval.json",
        "latest_style_eval": dataset_dir / "eval_reports" / "latest_style_eval.json",
        "learned_bilibili_hints": dataset_dir / "learned_bilibili_hints.json",
        "learned_style_guidelines": dataset_dir / "learned_style_guidelines.md",
        "learning_summary": dataset_dir / "learning_summary.md",
        "readme": dataset_dir / "README.md",
    }


def ensure_dataset_layout(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict[str, Path]:
    paths = dataset_paths(dataset_dir)
    paths["root"].mkdir(parents=True, exist_ok=True)
    paths["eval_sets"].mkdir(parents=True, exist_ok=True)
    paths["eval_reports"].mkdir(parents=True, exist_ok=True)
    for key in ("bilibili_labels", "translation_edits", "term_decisions", "qa_repairs", "bilibili_gold", "style_gold"):
        paths[key].touch(exist_ok=True)
    if not paths["schema"].exists():
        write_json(
            paths["schema"],
            {
                "schema_version": SCHEMA_VERSION,
                "dataset": "local_feedback",
                "created_at": utc_now(),
                "separation_rule": "Do not mark the same sample for learning and eval.",
                "label_values": sorted(BILIBILI_LABELS),
            },
        )
    if not paths["readme"].exists():
        paths["readme"].write_text(build_dataset_readme(), encoding="utf-8")
    return paths


def build_dataset_readme() -> str:
    return """# Local Feedback Dataset

This directory stores local, human-reviewable feedback for the subtitle workflow.

Principles:
- JSONL files are append-friendly and versionable.
- New samples default to review-only flags.
- A sample must not be used for learning and eval at the same time.
- The first learning layer is explainable subtitle-translation hints, few-shot examples, and offline eval.

Main files:
- `bilibili_duplicate_labels.jsonl`: Bilibili duplicate-search candidate labels.
- `translation_edit_examples.jsonl`: aligned machine subtitle text and manual ASS edits.
- `term_entity_decisions.jsonl`: reserved for terminology/entity decisions.
- `qa_repair_examples.jsonl`: reserved for QA repair examples.
- `eval_sets/`: frozen gold samples copied from reviewed feedback.
- `eval_reports/latest_style_eval.json`: latest offline subtitle-translation feedback eval.
- `eval_reports/latest_bilibili_eval.json`: latest offline Bilibili replay eval.

Typical commands:

```powershell
$env:PYTHONPATH='D:\\'
python -m autosub_zh.feedback_dataset collect-bilibili --project "D:\\autosub_zh\\output\\project"
python -m autosub_zh.feedback_dataset collect-style --project "D:\\autosub_zh\\output\\project"
python -m autosub_zh.feedback_dataset validate
python -m autosub_zh.feedback_dataset build-gold
python -m autosub_zh.feedback_dataset eval-style
python -m autosub_zh.feedback_dataset eval-bilibili
python -m autosub_zh.feedback_dataset summarize
```
"""


def extract_bvid(value: object) -> str:
    text = str(value or "")
    match = re.search(r"\b(BV[0-9A-Za-z]+)\b", text)
    return match.group(1) if match else ""


def extract_youtube_video_id(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    patterns = [
        r"[?&]v=([A-Za-z0-9_-]{6,})",
        r"youtu\.be/([A-Za-z0-9_-]{6,})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{6,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def normalize_youtube_meta(meta: dict, input_url: str = "") -> dict:
    url = str(meta.get("url") or meta.get("video_url") or input_url or "").strip()
    video_id = str(meta.get("video_id") or extract_youtube_video_id(url)).strip()
    return {
        "video_id": video_id,
        "url": url,
        "title": str(meta.get("title") or "").strip(),
        "description": str(meta.get("description") or "").strip(),
        "author": str(meta.get("author") or meta.get("channel") or "").strip(),
        "published_at": str(meta.get("published_at") or meta.get("upload_date") or "").strip(),
        "duration_seconds": parse_duration_to_seconds(
            meta.get("duration_seconds") or meta.get("duration") or meta.get("length_seconds")
        ),
    }


def normalize_candidate(candidate: dict) -> dict:
    url = str(candidate.get("url") or "").strip()
    duration_seconds = parse_duration_to_seconds(candidate.get("duration_seconds") or candidate.get("duration"))
    return {
        "bvid": str(candidate.get("bvid") or extract_bvid(url)).strip(),
        "url": url,
        "title": str(candidate.get("title") or "").strip(),
        "uploader": str(candidate.get("uploader") or candidate.get("author") or "").strip(),
        "duration_seconds": duration_seconds,
        "published_at": str(candidate.get("published_at") or "").strip(),
        "description": str(candidate.get("description") or candidate.get("snippet") or "").strip(),
        "matched_queries": list(candidate.get("matched_queries") or []),
        "score": int(candidate.get("score") or 0),
        "confidence": str(candidate.get("confidence") or "").strip(),
        "reason_codes": list(candidate.get("reason_codes") or []),
        "evidence": list(candidate.get("evidence") or []),
        "score_parts": candidate.get("score_parts") if isinstance(candidate.get("score_parts"), dict) else {},
    }


def bilibili_record_key(record: dict) -> str:
    youtube = record.get("youtube") if isinstance(record.get("youtube"), dict) else {}
    candidate = record.get("candidate") if isinstance(record.get("candidate"), dict) else {}
    source_key = str(youtube.get("video_id") or youtube.get("url") or "").strip()
    candidate_key = str(candidate.get("bvid") or candidate.get("url") or candidate.get("title") or "").strip()
    return f"{source_key}::{candidate_key}"


def style_record_key(record: dict) -> str:
    parts = [
        str(record.get("project_id") or ""),
        str(record.get("segment_id") or ""),
        str(record.get("machine_target_text") or ""),
        str(record.get("manual_target_text") or ""),
    ]
    return "::".join(parts)


def append_new_records(path: Path, records: list[dict], key_func: Callable[[dict], str]) -> dict:
    existing = read_jsonl(path)
    existing_keys = {key_func(record) for record in existing}
    to_add: list[dict] = []
    skipped = 0
    for record in records:
        key = key_func(record)
        if key in existing_keys:
            skipped += 1
            continue
        existing_keys.add(key)
        to_add.append(record)
    append_jsonl(path, to_add)
    return {"added": len(to_add), "skipped_existing": skipped, "path": str(path)}


def collect_bilibili_project(project: Path, dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict:
    paths = ensure_dataset_layout(dataset_dir)
    project = project.resolve()
    report_path = project / "00b_bilibili_duplicate_search.json"
    if not report_path.exists():
        raise FileNotFoundError(f"Bilibili duplicate report not found: {report_path}")
    report = read_json(report_path)
    youtube = normalize_youtube_meta(report.get("youtube_meta") or {}, str(report.get("input_youtube_url") or ""))
    project_id = project.name
    records: list[dict] = []
    for candidate in report.get("candidates") or []:
        records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "created_at": utc_now(),
                "source": {
                    "kind": "bilibili_duplicate_report",
                    "project_id": project_id,
                    "project_path": str(project),
                    "report_path": str(report_path),
                },
                "youtube": youtube,
                "query_plan": report.get("query_plan") or [],
                "candidate": normalize_candidate(candidate),
                "label": "manual_review",
                "human_note": "",
                "use_for_eval": False,
                "use_for_learning": False,
            }
        )
    result = append_new_records(paths["bilibili_labels"], records, bilibili_record_key)
    result.update({"project": str(project), "candidate_count": len(records)})
    return result


def build_bilibili_feedback_record(
    *,
    report: dict,
    candidate: dict,
    label: str = "manual_review",
    human_note: str = "",
    source: dict | None = None,
    use_for_eval: bool = False,
    use_for_learning: bool | None = None,
) -> dict:
    if label not in BILIBILI_LABELS:
        raise ValueError(f"Unsupported Bilibili feedback label: {label}")
    if use_for_learning is None:
        use_for_learning = label in {"duplicate", "not_duplicate", "same_topic"}
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "source": source or {"kind": "manual_ui_feedback"},
        "youtube": normalize_youtube_meta(report.get("youtube_meta") or {}, str(report.get("input_youtube_url") or "")),
        "query_plan": report.get("query_plan") or [],
        "candidate": normalize_candidate(candidate),
        "label": label,
        "human_note": str(human_note or "").strip(),
        "use_for_eval": bool(use_for_eval),
        "use_for_learning": bool(use_for_learning) and not bool(use_for_eval),
    }


def upsert_record(path: Path, record: dict, key_func: Callable[[dict], str]) -> dict:
    records = read_jsonl(path)
    key = key_func(record)
    updated = False
    for index, existing in enumerate(records):
        if key_func(existing) == key:
            records[index] = record
            updated = True
            break
    if not updated:
        records.append(record)
    write_jsonl(path, records)
    return {"path": str(path), "updated": updated, "added": not updated, "key": key}


def save_bilibili_feedback_label(
    *,
    report: dict,
    candidate: dict,
    label: str,
    human_note: str = "",
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    source: dict | None = None,
) -> dict:
    paths = ensure_dataset_layout(dataset_dir)
    record = build_bilibili_feedback_record(
        report=report,
        candidate=candidate,
        label=label,
        human_note=human_note,
        source=source,
    )
    result = upsert_record(paths["bilibili_labels"], record, bilibili_record_key)
    result.update({"label": label, "use_for_learning": record["use_for_learning"], "use_for_eval": record["use_for_eval"]})
    return result


def find_manual_ass_path(project: Path) -> Path:
    preferred = project / "08_bilingual_zh_en.ass"
    if preferred.exists():
        return preferred
    for pattern in ("08_bilingual_*.ass", "08_subtitle_*.ass"):
        matches = sorted(project.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"Manual ASS file not found in {project}")


def style_quality_flags(pair: dict, tags: list[str], features: dict) -> list[str]:
    flags: list[str] = []
    if not pair.get("changed"):
        flags.append("unchanged")
    if float(pair.get("overlap_ratio") or 0.0) < 0.5:
        flags.append("low_alignment_overlap")
    if features.get("surface_only"):
        flags.append("surface_only_edit")
    if not str(pair.get("source_text") or "").strip():
        flags.append("empty_source_text")
    if not str(pair.get("machine_target_text") or "").strip():
        flags.append("empty_machine_target_text")
    if not str(pair.get("manual_target_text") or "").strip():
        flags.append("empty_manual_target_text")
    if "manual_linebreak" in tags:
        flags.append("manual_linebreak")
    if pair.get("changed"):
        flags.append("needs_human_acceptance")
    return list(dict.fromkeys(flags))


def classify_style_feedback(pair: dict, tags: list[str], features: dict, operation_summary: dict) -> dict:
    strategies = {str(item) for item in operation_summary.get("strategies") or [] if str(item).strip()}
    feedback_types: list[str] = []
    reasons: list[str] = []
    changed = bool(pair.get("changed"))
    overlap_ratio = float(pair.get("overlap_ratio") or 0.0)
    source = str(pair.get("source_text") or "")
    machine = str(pair.get("machine_target_text") or "")
    manual = str(pair.get("manual_target_text") or "")
    char_delta = int(features.get("char_delta") or 0)

    if not changed:
        feedback_types.append("bad_example")
        reasons.append("machine and manual text are unchanged")
    if overlap_ratio < 0.5:
        feedback_types.append("bad_example")
        reasons.append("subtitle alignment overlap is low")
    if not source.strip() or not machine.strip() or not manual.strip():
        feedback_types.append("bad_example")
        reasons.append("source, machine, or manual text is empty")

    if features.get("surface_only"):
        feedback_types.append("surface_edit")
        reasons.append("manual edit only changes surface formatting or punctuation")
    if "manual_linebreak" in tags or "rebalance_lines" in strategies:
        feedback_types.append("linebreak_fix")
        reasons.append("manual edit adjusts subtitle line breaking")
    if {"compressed", "expanded", "punctuation_tuned"} & set(tags) or {"compress", "expand", "keep_core_clause", "reduce_clause_count"} & strategies:
        feedback_types.append("style_edit")
        reasons.append("manual edit changes subtitle style or density")
    if {"preserve_english", "mixed_naming"} & set(tags) or "preserve_term" in strategies:
        feedback_types.append("term_fix")
        reasons.append("manual edit preserves or changes terminology/entity handling")
    if abs(char_delta) >= 6 and not features.get("surface_only"):
        feedback_types.append("semantic_fix")
        reasons.append("manual edit changes enough text to be useful for translation preference learning")
    if "fixed_open_ending" in tags or "close_open_clause" in strategies or operation_summary.get("drops_open_ending"):
        feedback_types.append("qa_repair")
        reasons.append("manual edit repairs an unfinished subtitle clause")
    if changed and not feedback_types:
        feedback_types.append("style_edit")
        reasons.append("manual edit changes translation wording")

    feedback_types = [item for item in dict.fromkeys(feedback_types) if item in STYLE_FEEDBACK_TYPES]
    if "bad_example" in feedback_types:
        learning_risk = "high"
    elif feedback_types == ["surface_edit"] or set(feedback_types) <= {"surface_edit", "linebreak_fix"}:
        learning_risk = "medium"
    else:
        learning_risk = "low"

    recommendation = "review_only"
    high_signal_types = {"qa_repair", "semantic_fix", "style_edit", "term_fix"}
    if learning_risk == "low" and high_signal_types & set(feedback_types):
        recommendation = "style_prompt_candidate"
    elif learning_risk == "low" and "linebreak_fix" in feedback_types:
        recommendation = "eval_candidate"

    return {
        "feedback_types": feedback_types,
        "learning_risk": learning_risk,
        "learning_recommendation": recommendation,
        "classification_reasons": list(dict.fromkeys(reasons)),
    }


def is_unsafe_style_learning_record(record: dict) -> bool:
    feedback_types = set(str(item) for item in record.get("feedback_types") or [])
    return record.get("learning_risk") == "high" or "bad_example" in feedback_types


def collect_style_project(project: Path, dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict:
    paths = ensure_dataset_layout(dataset_dir)
    project = project.resolve()
    segments_path = project / "05_translated_segments.json"
    if not segments_path.exists():
        raise FileNotFoundError(f"Translated segments not found: {segments_path}")
    ass_path = find_manual_ass_path(project)
    pairs = align_segments_to_manual_ass(segments_path, ass_path)
    project_id = project.name
    records: list[dict] = []
    changed_pairs = [pair for pair in pairs if pair.get("changed")]
    for pair in changed_pairs:
        tags = detect_edit_tags(pair)
        features = build_style_features(pair)
        operation_summary = build_edit_operation_summary(pair)
        classification = classify_style_feedback(pair, tags, features, operation_summary)
        records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "created_at": utc_now(),
                "source": {
                    "kind": "manual_ass_alignment",
                    "project_id": project_id,
                    "project_path": str(project),
                    "segments_path": str(segments_path),
                    "manual_ass_path": str(ass_path),
                    "overlap_ratio": pair.get("overlap_ratio"),
                },
                "project_id": project_id,
                "segment_id": pair.get("segment_id"),
                "start": pair.get("start"),
                "end": pair.get("end"),
                "source_text": pair.get("source_text") or "",
                "machine_target_text": pair.get("machine_target_text") or "",
                "manual_target_text": pair.get("manual_target_text") or "",
                "edit_tags": tags,
                "features": features,
                "operation_summary": operation_summary,
                "quality_flags": style_quality_flags(pair, tags, features),
                **classification,
                "accepted": False,
                "use_for_style_prompt": False,
                "use_for_eval": False,
            }
        )
    result = append_new_records(paths["translation_edits"], records, style_record_key)
    result.update(
        {
            "project": str(project),
            "aligned_pair_count": len(pairs),
            "changed_pair_count": len(changed_pairs),
            "ass_path": str(ass_path),
        }
    )
    return result


def require_fields(record: dict, fields: list[str], path: str, errors: list[str]) -> None:
    for field in fields:
        if field not in record:
            errors.append(f"{path}: missing field {field}")


def validate_bilibili_record(record: dict, path: str, errors: list[str]) -> None:
    require_fields(
        record,
        ["schema_version", "created_at", "source", "youtube", "query_plan", "candidate", "label", "use_for_eval", "use_for_learning"],
        path,
        errors,
    )
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{path}: unsupported schema_version {record.get('schema_version')!r}")
    if record.get("label") not in BILIBILI_LABELS:
        errors.append(f"{path}: invalid label {record.get('label')!r}")
    if not isinstance(record.get("youtube"), dict):
        errors.append(f"{path}: youtube must be an object")
    if not isinstance(record.get("candidate"), dict):
        errors.append(f"{path}: candidate must be an object")
    if not isinstance(record.get("query_plan"), list):
        errors.append(f"{path}: query_plan must be a list")
    if not isinstance(record.get("use_for_eval"), bool):
        errors.append(f"{path}: use_for_eval must be boolean")
    if not isinstance(record.get("use_for_learning"), bool):
        errors.append(f"{path}: use_for_learning must be boolean")
    if record.get("use_for_eval") and record.get("use_for_learning"):
        errors.append(f"{path}: use_for_eval and use_for_learning must stay separate")


def validate_style_record(record: dict, path: str, errors: list[str]) -> None:
    require_fields(
        record,
        [
            "schema_version",
            "created_at",
            "project_id",
            "segment_id",
            "start",
            "end",
            "source_text",
            "machine_target_text",
            "manual_target_text",
            "edit_tags",
            "features",
            "operation_summary",
            "quality_flags",
            "feedback_types",
            "learning_risk",
            "learning_recommendation",
            "classification_reasons",
            "accepted",
            "use_for_style_prompt",
            "use_for_eval",
        ],
        path,
        errors,
    )
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{path}: unsupported schema_version {record.get('schema_version')!r}")
    if not isinstance(record.get("edit_tags"), list):
        errors.append(f"{path}: edit_tags must be a list")
    if not isinstance(record.get("features"), dict):
        errors.append(f"{path}: features must be an object")
    if not isinstance(record.get("operation_summary"), dict):
        errors.append(f"{path}: operation_summary must be an object")
    if not isinstance(record.get("quality_flags"), list):
        errors.append(f"{path}: quality_flags must be a list")
    if not isinstance(record.get("feedback_types"), list):
        errors.append(f"{path}: feedback_types must be a list")
    else:
        invalid_types = [item for item in record.get("feedback_types") or [] if item not in STYLE_FEEDBACK_TYPES]
        if invalid_types:
            errors.append(f"{path}: invalid feedback_types {invalid_types!r}")
    if record.get("learning_risk") not in STYLE_LEARNING_RISKS:
        errors.append(f"{path}: invalid learning_risk {record.get('learning_risk')!r}")
    if record.get("learning_recommendation") not in STYLE_LEARNING_RECOMMENDATIONS:
        errors.append(f"{path}: invalid learning_recommendation {record.get('learning_recommendation')!r}")
    if not isinstance(record.get("classification_reasons"), list):
        errors.append(f"{path}: classification_reasons must be a list")
    for flag in ("accepted", "use_for_style_prompt", "use_for_eval"):
        if not isinstance(record.get(flag), bool):
            errors.append(f"{path}: {flag} must be boolean")
    if record.get("use_for_eval") and record.get("use_for_style_prompt"):
        errors.append(f"{path}: use_for_eval and use_for_style_prompt must stay separate")
    if (record.get("use_for_eval") or record.get("use_for_style_prompt")) and not record.get("accepted"):
        errors.append(f"{path}: accepted must be true before use_for_eval/use_for_style_prompt")
    if is_unsafe_style_learning_record(record) and (record.get("use_for_eval") or record.get("use_for_style_prompt")):
        errors.append(f"{path}: high-risk/bad style samples cannot be used for eval or style prompt")


def validate_dataset(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict:
    paths = ensure_dataset_layout(dataset_dir)
    errors: list[str] = []
    file_specs = [
        ("bilibili_labels", paths["bilibili_labels"], validate_bilibili_record, bilibili_record_key),
        ("bilibili_gold", paths["bilibili_gold"], validate_bilibili_record, bilibili_record_key),
        ("translation_edits", paths["translation_edits"], validate_style_record, style_record_key),
        ("style_gold", paths["style_gold"], validate_style_record, style_record_key),
    ]
    counts: dict[str, int] = {}
    duplicate_counts: dict[str, int] = {}
    for name, path, validator, key_func in file_specs:
        try:
            records = read_jsonl(path)
        except ValueError as exc:
            errors.append(str(exc))
            records = []
        counts[name] = len(records)
        seen: set[str] = set()
        duplicates = 0
        for index, record in enumerate(records, start=1):
            validator(record, f"{path}:{index}", errors)
            key = key_func(record)
            if key in seen:
                duplicates += 1
            seen.add(key)
        duplicate_counts[name] = duplicates
        if duplicates:
            errors.append(f"{path}: contains {duplicates} duplicate records")
    return {
        "ok": not errors,
        "dataset_dir": str(paths["root"]),
        "counts": counts,
        "duplicate_counts": duplicate_counts,
        "errors": errors,
    }


def record_priority(record: dict) -> tuple[int, int, int]:
    has_human_note = bool(str(record.get("human_note") or "").strip())
    has_non_default_label = record.get("label") not in (None, "manual_review")
    has_use_flag = bool(record.get("use_for_eval") or record.get("use_for_learning") or record.get("use_for_style_prompt"))
    return (int(has_use_flag), int(has_non_default_label), int(has_human_note))


def dedupe_file(path: Path, key_func: Callable[[dict], str]) -> dict:
    records = read_jsonl(path)
    selected: dict[str, dict] = {}
    order: list[str] = []
    for record in records:
        key = key_func(record)
        if key not in selected:
            selected[key] = record
            order.append(key)
            continue
        if record_priority(record) > record_priority(selected[key]):
            selected[key] = record
    deduped = [selected[key] for key in order]
    write_jsonl(path, deduped)
    return {"path": str(path), "before": len(records), "after": len(deduped), "removed": len(records) - len(deduped)}


def dedupe_dataset(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict:
    paths = ensure_dataset_layout(dataset_dir)
    return {
        "bilibili_labels": dedupe_file(paths["bilibili_labels"], bilibili_record_key),
        "translation_edits": dedupe_file(paths["translation_edits"], style_record_key),
        "bilibili_gold": dedupe_file(paths["bilibili_gold"], bilibili_record_key),
        "style_gold": dedupe_file(paths["style_gold"], style_record_key),
    }


def build_gold_sets(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict:
    paths = ensure_dataset_layout(dataset_dir)
    bilibili_records = [
        record
        for record in read_jsonl(paths["bilibili_labels"])
        if record.get("use_for_eval") is True and record.get("use_for_learning") is not True and record.get("label") != "manual_review"
    ]
    style_records = [
        record
        for record in read_jsonl(paths["translation_edits"])
        if record.get("use_for_eval") is True and record.get("use_for_style_prompt") is not True and record.get("accepted") is True
        and not is_unsafe_style_learning_record(record)
    ]
    write_jsonl(paths["bilibili_gold"], unique_records(bilibili_records, bilibili_record_key))
    write_jsonl(paths["style_gold"], unique_records(style_records, style_record_key))
    return {
        "bilibili_gold_count": len(read_jsonl(paths["bilibili_gold"])),
        "style_gold_count": len(read_jsonl(paths["style_gold"])),
        "bilibili_gold_path": str(paths["bilibili_gold"]),
        "style_gold_path": str(paths["style_gold"]),
    }


def unique_records(records: list[dict], key_func: Callable[[dict], str]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for record in records:
        key = key_func(record)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def counter_items(counter: Counter, limit: int = 20) -> list[dict]:
    return [{"value": value, "count": count} for value, count in counter.most_common(limit)]


def summarize_learning(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict:
    paths = ensure_dataset_layout(dataset_dir)
    bilibili_records = read_jsonl(paths["bilibili_labels"])
    style_records = read_jsonl(paths["translation_edits"])

    learning_bili = [record for record in bilibili_records if record.get("use_for_learning") and not record.get("use_for_eval")]
    positive_bili = [record for record in learning_bili if record.get("label") == "duplicate"]
    negative_bili = [record for record in learning_bili if record.get("label") == "not_duplicate"]
    same_topic_bili = [record for record in learning_bili if record.get("label") == "same_topic"]

    positive_queries: Counter[str] = Counter()
    positive_reasons: Counter[str] = Counter()
    negative_reasons: Counter[str] = Counter()
    same_topic_reasons: Counter[str] = Counter()
    for record in positive_bili:
        candidate = record.get("candidate") or {}
        positive_queries.update(str(item) for item in candidate.get("matched_queries") or [] if str(item).strip())
        positive_reasons.update(str(item) for item in candidate.get("reason_codes") or [] if str(item).strip())
    for record in negative_bili:
        candidate = record.get("candidate") or {}
        negative_reasons.update(str(item) for item in candidate.get("reason_codes") or [] if str(item).strip())
    for record in same_topic_bili:
        candidate = record.get("candidate") or {}
        same_topic_reasons.update(str(item) for item in candidate.get("reason_codes") or [] if str(item).strip())

    learned_bili = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "mode": "suggestion_layer_only",
        "sample_counts": {
            "learning": len(learning_bili),
            "positive_duplicate": len(positive_bili),
            "negative_not_duplicate": len(negative_bili),
            "same_topic": len(same_topic_bili),
        },
        "positive_query_hints": counter_items(positive_queries),
        "positive_reason_codes": counter_items(positive_reasons),
        "false_positive_reason_codes": counter_items(negative_reasons),
        "same_topic_reason_codes": counter_items(same_topic_reasons),
        "application_note": "Review these hints before wiring them into search; no core scoring code is modified automatically.",
    }
    write_json(paths["learned_bilibili_hints"], learned_bili)

    style_learning = [
        record
        for record in style_records
        if record.get("accepted") is True and record.get("use_for_style_prompt") is True and record.get("use_for_eval") is not True
        and not is_unsafe_style_learning_record(record)
    ]
    tag_counts: Counter[str] = Counter()
    strategy_counts: Counter[str] = Counter()
    feedback_type_counts: Counter[str] = Counter()
    for record in style_learning:
        tag_counts.update(str(item) for item in record.get("edit_tags") or [] if str(item).strip())
        feedback_type_counts.update(str(item) for item in record.get("feedback_types") or [] if str(item).strip())
        operation_summary = record.get("operation_summary") if isinstance(record.get("operation_summary"), dict) else {}
        strategy_counts.update(str(item) for item in operation_summary.get("strategies") or [] if str(item).strip())
    style_guidelines = build_style_guidelines(tag_counts, strategy_counts, feedback_type_counts, len(style_learning))
    paths["learned_style_guidelines"].write_text(style_guidelines, encoding="utf-8")

    summary_text = build_learning_summary(
        bilibili_records=bilibili_records,
        style_records=style_records,
        learned_bili=learned_bili,
        style_learning_count=len(style_learning),
        dataset_dir=paths["root"],
    )
    paths["learning_summary"].write_text(summary_text, encoding="utf-8")
    return {
        "dataset_dir": str(paths["root"]),
        "bilibili_label_count": len(bilibili_records),
        "translation_edit_count": len(style_records),
        "bilibili_learning_count": len(learning_bili),
        "style_learning_count": len(style_learning),
        "learned_bilibili_hints_path": str(paths["learned_bilibili_hints"]),
        "learned_style_guidelines_path": str(paths["learned_style_guidelines"]),
        "learning_summary_path": str(paths["learning_summary"]),
    }


def build_style_guidelines(
    tag_counts: Counter[str],
    strategy_counts: Counter[str],
    feedback_type_counts: Counter[str],
    sample_count: int,
) -> str:
    lines = [
        "# Learned Style Guidelines",
        "",
        "Generated from accepted local feedback samples only.",
        "",
    ]
    if sample_count == 0:
        lines.extend(
            [
                "No accepted style-learning samples are available yet.",
                "",
                "To create one, review `translation_edit_examples.jsonl`, set `accepted=true`, set `use_for_style_prompt=true`, and keep `use_for_eval=false`.",
            ]
        )
        return "\n".join(lines).strip() + "\n"
    lines.extend(["## Observed Signals", ""])
    lines.append(f"- Accepted style samples: {sample_count}")
    for item in counter_items(feedback_type_counts, limit=12):
        lines.append(f"- Feedback type `{item['value']}`: {item['count']}")
    for item in counter_items(tag_counts, limit=12):
        lines.append(f"- Tag `{item['value']}`: {item['count']}")
    for item in counter_items(strategy_counts, limit=12):
        lines.append(f"- Strategy `{item['value']}`: {item['count']}")
    lines.extend(["", "## Suggested Guidelines", ""])
    if tag_counts.get("compressed") or strategy_counts.get("compress"):
        lines.append("- Prefer concise finished-subtitle wording when the machine text is wordy.")
    if tag_counts.get("preserve_english") or strategy_counts.get("preserve_term"):
        lines.append("- Preserve established English names and technical terms when the editor consistently keeps them.")
    if tag_counts.get("manual_linebreak") or strategy_counts.get("rebalance_lines"):
        lines.append("- Treat manual line breaks as timing and readability signals, not mere punctuation edits.")
    if tag_counts.get("fixed_open_ending") or strategy_counts.get("close_open_clause"):
        lines.append("- Avoid unfinished clause endings; close the meaning within the current subtitle when possible.")
    if feedback_type_counts.get("semantic_fix"):
        lines.append("- Prefer the human-edited meaning when machine output was literal, vague, or semantically thin.")
    if not any(line.startswith("- ") for line in lines[-6:]):
        lines.append("- Review accepted examples directly; current tags are too sparse for a strong style rule.")
    return "\n".join(lines).strip() + "\n"


def build_learning_summary(
    *,
    bilibili_records: list[dict],
    style_records: list[dict],
    learned_bili: dict,
    style_learning_count: int,
    dataset_dir: Path,
) -> str:
    eval_bili_count = sum(1 for record in bilibili_records if record.get("use_for_eval"))
    eval_style_count = sum(1 for record in style_records if record.get("use_for_eval"))
    lines = [
        "# Local Feedback Learning Summary",
        "",
        f"Dataset: `{dataset_dir}`",
        "",
        "## Counts",
        "",
        f"- Bilibili feedback records: {len(bilibili_records)}",
        f"- Bilibili learning records: {learned_bili['sample_counts']['learning']}",
        f"- Bilibili eval-marked records: {eval_bili_count}",
        f"- Translation edit records: {len(style_records)}",
        f"- Translation style-learning records: {style_learning_count}",
        f"- Translation eval-marked records: {eval_style_count}",
        "",
        "## Guardrails",
        "",
        "- Small sample counts are not suitable for deep-learning fine-tuning.",
        "- High-quality labels and a stable gold set come before model training.",
        "- Bilibili duplicate search is primarily retrieval and ranking; start with query hints, lexical/semantic features, reranking, and active learning.",
        "- Current subtitle style learning is prompt/RAG-like; keep expanding reusable datasets before training.",
        "- Automatic learning must remain explainable, switchable, and reversible.",
        "- Learning samples and eval samples must stay separate.",
    ]
    return "\n".join(lines).strip() + "\n"


def candidate_eval_key(candidate: dict) -> str:
    return str(candidate.get("bvid") or candidate.get("url") or candidate.get("title") or "").strip()


def youtube_eval_key(youtube: dict) -> str:
    return str(youtube.get("video_id") or youtube.get("url") or youtube.get("title") or "").strip()


def eval_bilibili(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict:
    paths = ensure_dataset_layout(dataset_dir)
    gold_records = read_jsonl(paths["bilibili_gold"])
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in gold_records:
        youtube = record.get("youtube") if isinstance(record.get("youtube"), dict) else {}
        key = youtube_eval_key(youtube)
        if key:
            grouped[key].append(record)

    source_reports: list[dict] = []
    recall_hits = {1: 0, 3: 0, 5: 0}
    positive_source_count = 0
    reciprocal_ranks: list[float] = []
    top_scores: list[int] = []
    false_positive_cases: list[dict] = []
    false_negative_cases: list[dict] = []
    query_hit_counter: Counter[str] = Counter()

    for source_key, records in grouped.items():
        youtube = records[0].get("youtube") or {}
        query_plan = build_bilibili_query_plan(youtube)
        scored: list[dict] = []
        labels_by_candidate: dict[str, str] = {}
        for record in records:
            candidate = dict(record.get("candidate") or {})
            scored_candidate = score_bilibili_candidate(candidate, youtube, query_plan)
            scored.append(scored_candidate)
            labels_by_candidate[candidate_eval_key(scored_candidate)] = str(record.get("label") or "manual_review")
        scored.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
        top_scores.append(int(scored[0].get("score") or 0) if scored else 0)

        positive_keys = {
            candidate_eval_key(record.get("candidate") or {})
            for record in records
            if record.get("label") == "duplicate"
        }
        has_positive = bool(positive_keys)
        if has_positive:
            positive_source_count += 1
            rank = 0
            for index, candidate in enumerate(scored, start=1):
                if candidate_eval_key(candidate) in positive_keys:
                    rank = index
                    query_hit_counter.update(str(item) for item in candidate.get("matched_queries") or [] if str(item).strip())
                    break
            for k in recall_hits:
                if rank and rank <= k:
                    recall_hits[k] += 1
            reciprocal_ranks.append(1.0 / rank if rank else 0.0)
            if not rank or rank > 5:
                false_negative_cases.append(
                    {
                        "source": source_key,
                        "title": youtube.get("title") or "",
                        "positive_candidates": sorted(positive_keys),
                        "top_candidates": [candidate_eval_key(candidate) for candidate in scored[:5]],
                    }
                )

        if scored:
            top = scored[0]
            top_key = candidate_eval_key(top)
            top_label = labels_by_candidate.get(top_key, "manual_review")
            if top_label == "not_duplicate" and int(top.get("score") or 0) >= 60:
                false_positive_cases.append(
                    {
                        "source": source_key,
                        "title": youtube.get("title") or "",
                        "top_candidate": top_key,
                        "top_score": int(top.get("score") or 0),
                        "reason_codes": top.get("reason_codes") or [],
                    }
                )

        source_reports.append(
            {
                "source": source_key,
                "youtube_title": youtube.get("title") or "",
                "candidate_count": len(scored),
                "positive_candidate_count": len(positive_keys),
                "top_score": int(scored[0].get("score") or 0) if scored else 0,
                "top_candidate": candidate_eval_key(scored[0]) if scored else "",
            }
        )

    metrics = {
        "recall@1": safe_ratio(recall_hits[1], positive_source_count),
        "recall@3": safe_ratio(recall_hits[3], positive_source_count),
        "recall@5": safe_ratio(recall_hits[5], positive_source_count),
        "mrr": round(sum(reciprocal_ranks) / len(reciprocal_ranks), 4) if reciprocal_ranks else 0.0,
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "sample_count": len(gold_records),
        "source_count": len(grouped),
        "positive_source_count": positive_source_count,
        "sample_insufficient": positive_source_count < 3,
        "sample_note": (
            "Sample count is too small for stable conclusions; the eval framework is runnable."
            if positive_source_count < 3
            else "Gold set has enough positive sources for a first trend check."
        ),
        "metrics": metrics,
        "top_score_distribution": score_distribution(top_scores),
        "false_positive_cases": false_positive_cases,
        "false_negative_cases": false_negative_cases,
        "query_hit_contribution": counter_items(query_hit_counter),
        "sources": source_reports,
    }
    write_json(paths["latest_bilibili_eval"], report)
    return report


def safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def score_distribution(scores: list[int]) -> dict:
    buckets = {"0-39": 0, "40-59": 0, "60-79": 0, "80-100": 0}
    for score in scores:
        if score < 40:
            buckets["0-39"] += 1
        elif score < 60:
            buckets["40-59"] += 1
        elif score < 80:
            buckets["60-79"] += 1
        else:
            buckets["80-100"] += 1
    return buckets


def style_text_similarity(machine: str, manual: str) -> float:
    machine_chars = [char for char in str(machine or "") if not char.isspace()]
    manual_chars = [char for char in str(manual or "") if not char.isspace()]
    if not machine_chars and not manual_chars:
        return 1.0
    if not machine_chars or not manual_chars:
        return 0.0
    machine_counter = Counter(machine_chars)
    manual_counter = Counter(manual_chars)
    shared = sum((machine_counter & manual_counter).values())
    total = max(sum(machine_counter.values()), sum(manual_counter.values()))
    return round(shared / total, 4) if total else 0.0


def eval_style(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict:
    paths = ensure_dataset_layout(dataset_dir)
    gold_records = read_jsonl(paths["style_gold"])

    tag_counts: Counter[str] = Counter()
    strategy_counts: Counter[str] = Counter()
    feedback_type_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    recommendation_counts: Counter[str] = Counter()
    quality_flag_counts: Counter[str] = Counter()
    similarities: list[float] = []
    char_deltas: list[int] = []
    high_value_cases: list[dict] = []
    unsafe_cases: list[dict] = []

    for record in gold_records:
        tag_counts.update(str(item) for item in record.get("edit_tags") or [] if str(item).strip())
        feedback_types = [str(item) for item in record.get("feedback_types") or [] if str(item).strip()]
        feedback_type_counts.update(feedback_types)
        risk_counts.update([str(record.get("learning_risk") or "unknown")])
        recommendation_counts.update([str(record.get("learning_recommendation") or "unknown")])
        quality_flag_counts.update(str(item) for item in record.get("quality_flags") or [] if str(item).strip())
        operation_summary = record.get("operation_summary") if isinstance(record.get("operation_summary"), dict) else {}
        strategy_counts.update(str(item) for item in operation_summary.get("strategies") or [] if str(item).strip())

        machine = str(record.get("machine_target_text") or "")
        manual = str(record.get("manual_target_text") or "")
        similarities.append(style_text_similarity(machine, manual))
        char_deltas.append(abs(len(manual) - len(machine)))

        case = {
            "project_id": record.get("project_id"),
            "segment_id": record.get("segment_id"),
            "feedback_types": feedback_types,
            "learning_risk": record.get("learning_risk") or "",
            "edit_tags": record.get("edit_tags") or [],
            "strategies": operation_summary.get("strategies") or [],
        }
        if is_unsafe_style_learning_record(record):
            unsafe_cases.append(case)
        elif {"qa_repair", "semantic_fix", "style_edit", "term_fix"} & set(feedback_types):
            high_value_cases.append(case)

    sample_count = len(gold_records)
    metrics = {
        "avg_machine_manual_similarity": round(sum(similarities) / sample_count, 4) if sample_count else 0.0,
        "avg_abs_char_delta": round(sum(char_deltas) / sample_count, 2) if sample_count else 0.0,
        "surface_edit_rate": safe_ratio(feedback_type_counts.get("surface_edit", 0), sample_count),
        "semantic_or_style_signal_rate": safe_ratio(
            feedback_type_counts.get("semantic_fix", 0)
            + feedback_type_counts.get("style_edit", 0)
            + feedback_type_counts.get("term_fix", 0)
            + feedback_type_counts.get("qa_repair", 0),
            sample_count,
        ),
        "unsafe_sample_rate": safe_ratio(len(unsafe_cases), sample_count),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "sample_count": sample_count,
        "sample_insufficient": sample_count < 20,
        "sample_note": (
            "Need at least 20 reviewed subtitle feedback samples before judging translation style trends."
            if sample_count < 20
            else "Gold set is large enough for a first subtitle feedback trend check."
        ),
        "metrics": metrics,
        "feedback_type_counts": counter_items(feedback_type_counts),
        "learning_risk_counts": counter_items(risk_counts),
        "learning_recommendation_counts": counter_items(recommendation_counts),
        "edit_tag_counts": counter_items(tag_counts),
        "strategy_counts": counter_items(strategy_counts),
        "quality_flag_counts": counter_items(quality_flag_counts),
        "high_value_cases": high_value_cases[:20],
        "unsafe_cases": unsafe_cases[:20],
    }
    write_json(paths["latest_style_eval"], report)
    return report


def print_result(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and evaluate the local feedback dataset.")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR), help="Local feedback dataset directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create the local feedback dataset skeleton.")

    collect_bili = subparsers.add_parser("collect-bilibili", help="Collect Bilibili duplicate candidates from one output project.")
    collect_bili.add_argument("--project", required=True, help="Output project directory.")

    collect_style = subparsers.add_parser("collect-style", help="Collect translation edit examples from one output project.")
    collect_style.add_argument("--project", required=True, help="Output project directory.")

    subparsers.add_parser("validate", help="Validate JSONL schemas and train/eval separation.")
    subparsers.add_parser("dedupe", help="Deduplicate dataset JSONL files.")
    subparsers.add_parser("build-gold", help="Copy reviewed eval records into frozen gold-set files.")
    subparsers.add_parser("summarize", help="Generate explainable learned hint files.")
    subparsers.add_parser("eval-style", help="Run offline subtitle translation feedback eval from the gold set.")
    subparsers.add_parser("eval-bilibili", help="Run offline Bilibili replay eval from the gold set.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dataset_dir = Path(args.dataset_dir)
    try:
        if args.command == "init":
            paths = ensure_dataset_layout(dataset_dir)
            print_result({"ok": True, "dataset_dir": str(paths["root"])})
            return 0
        if args.command == "collect-bilibili":
            print_result(collect_bilibili_project(Path(args.project), dataset_dir))
            return 0
        if args.command == "collect-style":
            print_result(collect_style_project(Path(args.project), dataset_dir))
            return 0
        if args.command == "validate":
            result = validate_dataset(dataset_dir)
            print_result(result)
            return 0 if result["ok"] else 1
        if args.command == "dedupe":
            print_result(dedupe_dataset(dataset_dir))
            return 0
        if args.command == "build-gold":
            print_result(build_gold_sets(dataset_dir))
            return 0
        if args.command == "summarize":
            print_result(summarize_learning(dataset_dir))
            return 0
        if args.command == "eval-style":
            print_result(eval_style(dataset_dir))
            return 0
        if args.command == "eval-bilibili":
            print_result(eval_bilibili(dataset_dir))
            return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
