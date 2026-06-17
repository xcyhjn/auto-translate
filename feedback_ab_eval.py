from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .feedback_dataset import (
    SCHEMA_VERSION,
    dataset_paths,
    ensure_dataset_layout,
    read_jsonl,
    span_record_key,
    style_record_key,
    style_text_similarity,
    utc_now,
    write_json,
    write_jsonl,
)
from .models import Segment
from .pipeline_core import build_translation_style_prompt
from .span_translate import DEFAULT_SPAN_EXAMPLE_TOP_K, compact_span_prompt_example, read_span_examples
from .translate import translate_chunk_with_openai


DEFAULT_AB_SAMPLE_COUNT = 5
MAX_AB_SAMPLE_COUNT = 10
MAX_AB_REQUEST_COUNT = 30
DEFAULT_AB_VARIANTS = ["baseline", "style_feedback", "style_span_feedback"]
SUPPORTED_SAMPLE_KINDS = {"style", "span", "mixed"}
SUPPORTED_VARIANTS = set(DEFAULT_AB_VARIANTS)


Translator = Callable[[list[Segment], dict], dict[int, str]]


def read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "error": f"Invalid JSON report: {path}"}
    return payload if isinstance(payload, dict) else {}


def clamp_sample_count(value: object) -> int:
    try:
        count = int(value or DEFAULT_AB_SAMPLE_COUNT)
    except (TypeError, ValueError):
        count = DEFAULT_AB_SAMPLE_COUNT
    return max(1, min(MAX_AB_SAMPLE_COUNT, count))


def normalize_sample_kind(value: object) -> str:
    kind = str(value or "mixed").strip().lower()
    return kind if kind in SUPPORTED_SAMPLE_KINDS else "mixed"


def normalize_variants(values: object) -> list[str]:
    if isinstance(values, list):
        variants = [str(item).strip() for item in values if str(item).strip() in SUPPORTED_VARIANTS]
    else:
        variants = list(DEFAULT_AB_VARIANTS)
    if not variants:
        variants = list(DEFAULT_AB_VARIANTS)
    result: list[str] = []
    for variant in variants:
        if variant not in result:
            result.append(variant)
    return result[: len(DEFAULT_AB_VARIANTS)]


def selectable_style_records(dataset_dir: Path) -> list[dict]:
    paths = ensure_dataset_layout(dataset_dir)
    return read_jsonl(paths["style_gold"])


def selectable_span_records(dataset_dir: Path) -> list[dict]:
    paths = ensure_dataset_layout(dataset_dir)
    return read_jsonl(paths["span_gold"])


def select_eval_samples(dataset_dir: Path, *, sample_kind: str, sample_count: int) -> list[dict]:
    style_records = selectable_style_records(dataset_dir)
    span_records = selectable_span_records(dataset_dir)
    if sample_kind == "style":
        return [style_sample_from_record(record) for record in style_records[:sample_count]]
    if sample_kind == "span":
        return [span_sample_from_record(record) for record in span_records[:sample_count]]

    style_limit = min(len(style_records), math.ceil(sample_count / 2))
    span_limit = min(len(span_records), sample_count - style_limit)
    if span_records and span_limit == 0 and style_limit > 0:
        style_limit -= 1
        span_limit = 1
    samples = [style_sample_from_record(record) for record in style_records[:style_limit]]
    samples.extend(span_sample_from_record(record) for record in span_records[:span_limit])
    if len(samples) < sample_count:
        samples.extend(style_sample_from_record(record) for record in style_records[style_limit:])
    if len(samples) < sample_count:
        samples.extend(span_sample_from_record(record) for record in span_records[span_limit:])
    return samples[:sample_count]


def style_sample_from_record(record: dict) -> dict:
    return {
        "sample_id": style_record_key(record),
        "record_id": style_record_key(record),
        "record_kind": "style",
        "kind": "style",
        "project_id": str(record.get("project_id") or ""),
        "segment_id": record.get("segment_id"),
        "source": str(record.get("source_text") or ""),
        "machine_baseline": str(record.get("machine_target_text") or ""),
        "manual_target": str(record.get("manual_target_text") or ""),
        "start": float(record.get("start") or 0.0),
        "end": float(record.get("end") or 0.0),
        "edit_tags": record.get("edit_tags") if isinstance(record.get("edit_tags"), list) else [],
        "feedback_types": record.get("feedback_types") if isinstance(record.get("feedback_types"), list) else [],
    }


def span_sample_from_record(record: dict) -> dict:
    raw_machine_by_id = record.get("machine_target_by_id") if isinstance(record.get("machine_target_by_id"), dict) else {}
    raw_manual_by_id = record.get("manual_target_by_id") if isinstance(record.get("manual_target_by_id"), dict) else {}
    machine_by_id = {str(key): value for key, value in raw_machine_by_id.items()}
    manual_by_id = {str(key): value for key, value in raw_manual_by_id.items()}
    segment_ids = [str(item) for item in record.get("segment_ids") or []]
    machine_joined = " ".join(str(machine_by_id.get(key, "")) for key in segment_ids if str(machine_by_id.get(key, "")).strip())
    manual_joined = " ".join(str(manual_by_id.get(key, "")) for key in segment_ids if str(manual_by_id.get(key, "")).strip())
    record_id = span_record_key(record)
    return {
        "sample_id": record_id,
        "record_id": record_id,
        "record_kind": "span",
        "kind": "span",
        "project_id": str(record.get("project_id") or ""),
        "span_id": str(record.get("span_id") or ""),
        "segment_ids": segment_ids,
        "source": str(record.get("source_joined") or ""),
        "machine_baseline": machine_joined,
        "manual_target": manual_joined,
        "start": 0.0,
        "end": 1.0,
        "risk_reasons": record.get("risk_reasons") if isinstance(record.get("risk_reasons"), dict) else {},
        "edit_tags": record.get("edit_tags") if isinstance(record.get("edit_tags"), list) else [],
    }


def estimate_tokens_for_prompt(text: str) -> int:
    return max(1, math.ceil(len(text or "") / 3.2)) if text else 0


def build_span_feedback_block(dataset_dir: Path) -> str:
    paths = dataset_paths(dataset_dir)
    guidelines = paths["learned_span_guidelines"].read_text(encoding="utf-8", errors="replace").strip() if paths["learned_span_guidelines"].exists() else ""
    examples = [compact_span_prompt_example(record) for record in read_span_examples(paths["span_translation_examples"])[:DEFAULT_SPAN_EXAMPLE_TOP_K]]
    parts = []
    if guidelines:
        parts.append("Span pre-translation learned guidelines:\n" + guidelines)
    if examples:
        parts.append("Compact span examples:\n" + json.dumps(examples, ensure_ascii=False))
    return "\n\n".join(parts).strip()


def build_variant_style_prompt(
    variant: str,
    *,
    dataset_dir: Path,
    translation_prompt: str,
    project_style_prompt_path: str | Path | None = None,
) -> str:
    paths = dataset_paths(dataset_dir)
    if variant == "baseline":
        return build_translation_style_prompt(
            translation_prompt=translation_prompt,
            project_style_prompt_path=project_style_prompt_path,
            enable_local_translation_feedback=False,
            local_feedback_style_path=paths["learned_style_guidelines"],
        )
    style_prompt = build_translation_style_prompt(
        translation_prompt=translation_prompt,
        project_style_prompt_path=project_style_prompt_path,
        enable_local_translation_feedback=True,
        local_feedback_style_path=paths["learned_style_guidelines"],
    )
    if variant != "style_span_feedback":
        return style_prompt
    span_block = build_span_feedback_block(dataset_dir)
    return "\n\n".join(item for item in [style_prompt, span_block] if item.strip())


def build_ab_eval_preview(
    dataset_dir: Path,
    *,
    sample_count: int = DEFAULT_AB_SAMPLE_COUNT,
    sample_kind: str = "mixed",
    variants: list[str] | None = None,
    translation_prompt: str = "",
) -> dict:
    dataset_dir = Path(dataset_dir)
    paths = ensure_dataset_layout(dataset_dir)
    sample_count = clamp_sample_count(sample_count)
    sample_kind = normalize_sample_kind(sample_kind)
    variants = normalize_variants(variants)
    eligible_style_count = len(read_jsonl(paths["style_gold"]))
    eligible_span_count = len(read_jsonl(paths["span_gold"]))
    selected = select_eval_samples(dataset_dir, sample_kind=sample_kind, sample_count=sample_count)
    estimated_request_count = len(selected) * len(variants)
    warnings: list[str] = []
    if not eligible_style_count and sample_kind in {"style", "mixed"}:
        warnings.append("没有可评估的 ASS gold 样本；请先审核 Eval 样本并运行 build-gold。")
    if not eligible_span_count and sample_kind in {"span", "mixed"}:
        warnings.append("没有可评估的 Span gold 样本；本轮会跳过 Span 或提示样本不足。")
    if estimated_request_count > MAX_AB_REQUEST_COUNT:
        warnings.append(f"预计请求数 {estimated_request_count} 超过上限 {MAX_AB_REQUEST_COUNT}。")
    style_prompt_chars = sum(
        len(build_variant_style_prompt(variant, dataset_dir=dataset_dir, translation_prompt=translation_prompt))
        for variant in variants
    )
    return {
        "ok": True,
        "dataset_dir": str(dataset_dir),
        "eligible_style_count": eligible_style_count,
        "eligible_span_count": eligible_span_count,
        "default_sample_count": DEFAULT_AB_SAMPLE_COUNT,
        "sample_count": sample_count,
        "sample_kind": sample_kind,
        "variants": variants,
        "selected_sample_count": len(selected),
        "estimated_request_count": estimated_request_count,
        "estimated_prompt_tokens": estimate_tokens_for_prompt("x" * style_prompt_chars) * max(1, len(selected)),
        "max_request_count": MAX_AB_REQUEST_COUNT,
        "can_run": bool(selected) and estimated_request_count <= MAX_AB_REQUEST_COUNT,
        "warnings": warnings,
        "sample_preview": [
            {
                "sample_id": sample.get("sample_id"),
                "kind": sample.get("kind"),
                "project_id": sample.get("project_id"),
                "source": str(sample.get("source") or "")[:180],
            }
            for sample in selected[:5]
        ],
        "latest_report_available": paths["latest_translation_ab_eval"].exists(),
    }


def read_ab_eval_history(dataset_dir: Path, *, limit: int = 10) -> list[dict]:
    paths = dataset_paths(Path(dataset_dir))
    try:
        rows = read_jsonl(paths["translation_ab_eval_history"])
    except Exception:
        return []
    return rows[-max(1, limit) :][::-1]


def build_ab_eval_history_summary(dataset_dir: Path, *, limit: int = 10) -> dict:
    paths = dataset_paths(Path(dataset_dir))
    try:
        rows = read_jsonl(paths["translation_ab_eval_history"])
    except Exception:
        rows = []
    latest_rows = rows[-max(1, limit) :][::-1]
    recommendation_counts: Counter[str] = Counter()
    style_deltas: list[float] = []
    span_deltas: list[float] = []
    for row in rows:
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        recommendation_counts.update([str(summary.get("recommendation") or "unknown")])
        try:
            style_deltas.append(float(summary.get("avg_style_feedback_delta") or 0.0))
        except (TypeError, ValueError):
            pass
        try:
            span_deltas.append(float(summary.get("avg_style_span_feedback_delta") or 0.0))
        except (TypeError, ValueError):
            pass
    return {
        "total_recorded_runs": len(rows),
        "latest_runs": latest_rows,
        "recommendation_counts": dict(recommendation_counts),
        "avg_style_feedback_delta": round(sum(style_deltas) / len(style_deltas), 4) if style_deltas else 0.0,
        "avg_style_span_feedback_delta": round(sum(span_deltas) / len(span_deltas), 4) if span_deltas else 0.0,
        "history_path": str(paths["translation_ab_eval_history"]),
    }


def ab_eval_action_recommendation_codes(preview: dict, latest_report: dict | None = None) -> list[str]:
    latest_report = latest_report or {}
    codes: list[str] = []
    if not preview.get("can_run"):
        codes.append("build_gold_or_review_eval")
    elif not latest_report.get("available"):
        codes.append("run_first_small_eval")

    summary = latest_report.get("summary") if isinstance(latest_report.get("summary"), dict) else {}
    recommendation = str(summary.get("recommendation") or "")
    if recommendation == "local_feedback_helpful":
        codes.append("keep_feedback_enabled_collect_more_gold")
    elif recommendation == "neutral":
        codes.append("review_high_signal_samples")
    elif recommendation == "possibly_harmful":
        codes.append("inspect_prompt_samples_before_more_runs")
    elif recommendation == "insufficient_samples":
        codes.append("increase_eval_sample_count")

    if int(preview.get("eligible_span_count") or 0) <= 0:
        codes.append("add_span_eval_samples")
    if int(preview.get("eligible_style_count") or 0) <= 0:
        codes.append("add_style_eval_samples")

    result: list[str] = []
    for code in codes:
        if code not in result:
            result.append(code)
    return result


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def english_residue_rate(text: str) -> float:
    chars = [char for char in str(text or "") if not char.isspace()]
    if not chars:
        return 0.0
    alpha = sum(1 for char in chars if char.isascii() and char.isalpha())
    return round(alpha / len(chars), 4)


def output_issue_flags(output: str, manual_target: str) -> list[str]:
    text = str(output or "").strip()
    flags: list[str] = []
    if not text:
        flags.append("empty_output")
    if text.count("{") or text.count("}"):
        flags.append("json_artifact")
    if len(text) > max(20, len(str(manual_target or "")) * 2.2):
        flags.append("too_long")
    if english_residue_rate(text) > 0.45 and contains_cjk(str(manual_target or "")):
        flags.append("english_residue")
    if "\ufffd" in text:
        flags.append("replacement_character")
    return flags


def score_variant(output: str, manual_target: str) -> dict:
    flags = output_issue_flags(output, manual_target)
    similarity = style_text_similarity(output, manual_target)
    length_delta = abs(len(str(output or "")) - len(str(manual_target or "")))
    penalty = len(flags) * 0.08 + min(0.2, length_delta / max(len(str(manual_target or "")), 1) * 0.1)
    adjusted = round(max(0.0, similarity - penalty), 4)
    return {
        "manual_similarity": similarity,
        "length_delta": length_delta,
        "english_residue_rate": english_residue_rate(output),
        "issue_flags": flags,
        "adjusted_score": adjusted,
    }


def sample_to_segment(sample: dict) -> Segment:
    return Segment(
        id=1,
        start=float(sample.get("start") or 0.0),
        end=float(sample.get("end") or 1.0),
        source_text=str(sample.get("source") or ""),
        target_text=None,
    )


def default_translator(chunk: list[Segment], kwargs: dict) -> dict[int, str]:
    return translate_chunk_with_openai(chunk, **kwargs)


def run_translation_ab_eval(
    dataset_dir: Path,
    *,
    sample_kind: str = "mixed",
    sample_count: int = DEFAULT_AB_SAMPLE_COUNT,
    variants: list[str] | None = None,
    model: str = "",
    translation_prompt: str = "",
    src_lang: str | None = "en",
    dst_lang: str = "zh-Hans",
    glossary_text: str = "",
    base_url: str | None = None,
    translator: Translator | None = None,
) -> dict:
    dataset_dir = Path(dataset_dir)
    paths = ensure_dataset_layout(dataset_dir)
    sample_kind = normalize_sample_kind(sample_kind)
    sample_count = clamp_sample_count(sample_count)
    variants = normalize_variants(variants)
    selected = select_eval_samples(dataset_dir, sample_kind=sample_kind, sample_count=sample_count)
    request_count = len(selected) * len(variants)
    if not selected:
        raise ValueError("没有可评估的 gold 样本；请先审核 Eval 样本并运行 build-gold。")
    if request_count > MAX_AB_REQUEST_COUNT:
        raise ValueError(f"A/B 评估请求数 {request_count} 超过上限 {MAX_AB_REQUEST_COUNT}。")
    if not model:
        raise ValueError("translation model is required for A/B eval.")

    translator = translator or default_translator
    started_at = datetime.now(timezone.utc).isoformat()
    sample_reports: list[dict] = []
    variant_wins: Counter[str] = Counter()
    failure_count = 0
    unsafe_count = 0

    for sample in selected:
        segment = sample_to_segment(sample)
        outputs: dict[str, str] = {}
        metrics: dict[str, dict] = {}
        errors: dict[str, str] = {}
        for variant in variants:
            style_prompt = build_variant_style_prompt(
                variant,
                dataset_dir=dataset_dir,
                translation_prompt=translation_prompt,
            )
            try:
                translated = translator(
                    [segment],
                    {
                        "src_lang": src_lang,
                        "dst_lang": dst_lang,
                        "glossary_text": glossary_text,
                        "model": model,
                        "style_prompt_text": style_prompt,
                        "base_url": base_url,
                        "max_retries": 1,
                        "retry_invalid_individually": False,
                    },
                )
                output = str(translated.get(segment.id) or "").strip()
                outputs[variant] = output
                metrics[variant] = score_variant(output, str(sample.get("manual_target") or ""))
                unsafe_count += int(bool(metrics[variant].get("issue_flags")))
            except Exception as exc:
                failure_count += 1
                outputs[variant] = ""
                errors[variant] = str(exc)
                metrics[variant] = {
                    "manual_similarity": 0.0,
                    "length_delta": len(str(sample.get("manual_target") or "")),
                    "english_residue_rate": 0.0,
                    "issue_flags": ["translation_failed"],
                    "adjusted_score": 0.0,
                }
        best_variant = max(metrics, key=lambda key: float(metrics[key].get("adjusted_score") or 0.0)) if metrics else ""
        if best_variant:
            variant_wins.update([best_variant])
        baseline_score = float(metrics.get("baseline", {}).get("adjusted_score") or 0.0)
        best_score = float(metrics.get(best_variant, {}).get("adjusted_score") or 0.0) if best_variant else 0.0
        sample_reports.append(
            {
                "sample_id": sample.get("sample_id"),
                "record_id": sample.get("record_id") or sample.get("sample_id"),
                "record_kind": sample.get("record_kind") or sample.get("kind"),
                "kind": sample.get("kind"),
                "project_id": sample.get("project_id"),
                "source": sample.get("source"),
                "manual_target": sample.get("manual_target"),
                "machine_baseline": sample.get("machine_baseline"),
                "outputs": outputs,
                "metrics": metrics,
                "best_variant": best_variant,
                "best_score_delta_vs_baseline": round(best_score - baseline_score, 4),
                "errors": errors,
            }
        )

    baseline_scores = [
        float(sample.get("metrics", {}).get("baseline", {}).get("adjusted_score") or 0.0)
        for sample in sample_reports
        if "baseline" in sample.get("metrics", {})
    ]

    def avg_delta(variant: str) -> float:
        deltas: list[float] = []
        for sample in sample_reports:
            sample_metrics = sample.get("metrics", {})
            if "baseline" not in sample_metrics or variant not in sample_metrics:
                continue
            deltas.append(float(sample_metrics[variant].get("adjusted_score") or 0.0) - float(sample_metrics["baseline"].get("adjusted_score") or 0.0))
        return round(sum(deltas) / len(deltas), 4) if deltas else 0.0

    style_delta = avg_delta("style_feedback")
    span_delta = avg_delta("style_span_feedback")
    if len(sample_reports) < DEFAULT_AB_SAMPLE_COUNT:
        recommendation = "insufficient_samples"
    elif style_delta > 0.03 or span_delta > 0.03:
        recommendation = "local_feedback_helpful"
    elif style_delta < -0.03 and span_delta < -0.03:
        recommendation = "possibly_harmful"
    else:
        recommendation = "neutral"

    report = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "started_at": started_at,
        "dataset_dir": str(dataset_dir),
        "sample_kind": sample_kind,
        "sample_count": len(sample_reports),
        "requested_sample_count": sample_count,
        "variants": variants,
        "model": model,
        "estimated_request_count": request_count,
        "actual_request_count": request_count,
        "summary": {
            "variant_wins": {variant: int(variant_wins.get(variant, 0)) for variant in variants},
            "baseline_win_count": int(variant_wins.get("baseline", 0)),
            "style_feedback_win_count": int(variant_wins.get("style_feedback", 0)),
            "style_span_feedback_win_count": int(variant_wins.get("style_span_feedback", 0)),
            "avg_baseline_score": round(sum(baseline_scores) / len(baseline_scores), 4) if baseline_scores else 0.0,
            "avg_style_feedback_delta": style_delta,
            "avg_style_span_feedback_delta": span_delta,
            "unsafe_output_rate": round(unsafe_count / max(1, request_count), 4),
            "json_or_format_failure_count": failure_count,
            "recommendation": recommendation,
        },
        "samples": sample_reports,
        "warnings": build_ab_eval_preview(
            dataset_dir,
            sample_count=sample_count,
            sample_kind=sample_kind,
            variants=variants,
            translation_prompt=translation_prompt,
        ).get("warnings", []),
        "notes": [
            "05/05a only serve as machine baselines; this report does not modify learning JSONL.",
            "This A/B eval is manual and does not run the full subtitle pipeline.",
        ],
    }
    write_json(paths["latest_translation_ab_eval"], report)
    history = read_jsonl(paths["translation_ab_eval_history"])
    history.append(
        {
            "schema_version": SCHEMA_VERSION,
            "created_at": report["created_at"],
            "sample_kind": sample_kind,
            "sample_count": len(sample_reports),
            "variants": variants,
            "model": model,
            "summary": report["summary"],
        }
    )
    write_jsonl(paths["translation_ab_eval_history"], history[-100:])
    return report


def read_latest_ab_eval_report(dataset_dir: Path) -> dict:
    paths = dataset_paths(Path(dataset_dir))
    report = read_json_file(paths["latest_translation_ab_eval"])
    if not report:
        return {
            "ok": True,
            "available": False,
            "path": str(paths["latest_translation_ab_eval"]),
            "message": "暂无 A/B 小样本评估报告。",
        }
    if report.get("ok") is False and "schema_version" not in report:
        report.setdefault("available", False)
        report.setdefault("path", str(paths["latest_translation_ab_eval"]))
        return report
    report["available"] = True
    report["path"] = str(paths["latest_translation_ab_eval"])
    return report
