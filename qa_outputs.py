from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import Segment
from .subtitle_io import DisplayCue, wrap_chinese_text
from .utils import ensure_parent


def write_tsv(path: str | Path, fieldnames: list[str], rows: list[dict]) -> None:
    ensure_parent(path)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            delimiter="\t",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_blocker_report(errors: list[str], metrics_summary: dict, warnings: list[str] | None = None) -> dict:
    warnings = warnings or []
    return {
        "schema_version": 1,
        "summary": {
            **(metrics_summary or {}),
            "blocker_count": len(errors),
            "warning_count": len(warnings),
            "pass": not errors,
        },
        "errors": errors,
        "warnings": warnings,
        "blockers": [
            {
                "index": index,
                "message": message,
            }
            for index, message in enumerate(errors, start=1)
        ],
        "warning_items": [
            {
                "index": index,
                "message": message,
            }
            for index, message in enumerate(warnings, start=1)
        ],
    }


def build_editor_review_rows(
    segments: list[Segment],
    difficult_spans: dict | None,
    display_rewrite_report: dict | None,
    quality_metrics: dict | None = None,
) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, int]] = set()

    def add_row(
        *,
        segment_id: int,
        risk_type: str,
        severity: str,
        risk_score: int,
        source_text: str,
        target_text: str,
        note: str,
    ) -> None:
        key = (risk_type, segment_id)
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "segment_id": segment_id,
                "severity": severity,
                "risk_type": risk_type,
                "risk_score": risk_score,
                "source_text": source_text,
                "target_text": target_text,
                "note": note,
            }
        )

    segment_by_id = {segment.id: segment for segment in segments}
    for span in (difficult_spans or {}).get("spans") or []:
        severity = str(span.get("severity") or "low")
        if severity not in {"high", "medium"}:
            continue
        reason_counts = span.get("reason_counts") if isinstance(span.get("reason_counts"), dict) else {}
        note = ", ".join(f"{key} x{value}" for key, value in sorted(reason_counts.items()))
        for item in span.get("segments") or []:
            segment_id = int(item.get("id") or 0)
            segment = segment_by_id.get(segment_id)
            if not segment:
                continue
            add_row(
                segment_id=segment_id,
                risk_type="difficult_span",
                severity=severity,
                risk_score=int(item.get("risk_score") or span.get("score") or 0),
                source_text=segment.source_text,
                target_text=segment.target_text or "",
                note=note,
            )

    for item in (display_rewrite_report or {}).get("changes") or []:
        if not isinstance(item, dict):
            continue
        segment_id = int(item.get("segment_id") or 0)
        actions = [str(value) for value in item.get("actions") or []]
        review_actions = [action for action in actions if action.startswith("review_")]
        if not actions:
            continue
        severity = "medium" if review_actions else "low"
        add_row(
            segment_id=segment_id,
            risk_type="display_rewrite",
            severity=severity,
            risk_score=len(review_actions) * 2 + (1 if item.get("changed") else 0),
            source_text=str(item.get("source_text") or ""),
            target_text=str(item.get("rewritten_target_text") or ""),
            note=", ".join(actions),
        )

    display_metrics = (quality_metrics or {}).get("display") if isinstance(quality_metrics, dict) else {}
    if isinstance(display_metrics, dict):
        for key, severity, risk_score, sample_suffix in (
            ("chinese_line_hard_over_samples", "high", 9, "_samples"),
            ("chinese_cps_hard_over_samples", "high", 9, "_samples"),
            ("chinese_line_soft_over_samples", "medium", 4, "_samples"),
            ("chinese_cps_soft_over_samples", "medium", 4, "_samples"),
            ("empty_chinese_cue_indexes", "high", 10, "_indexes"),
        ):
            for sample in display_metrics.get(key) or []:
                if isinstance(sample, dict):
                    cue_label = sample.get("cue_index", "")
                    text = str(sample.get("text") or "")
                    note = f"{key.removesuffix('_samples')}; cue={cue_label}"
                else:
                    cue_label = sample
                    text = ""
                    note = f"{key}; cue={cue_label}"
                add_row(
                    segment_id=-int(cue_label or 0),
                    risk_type="display_qa",
                    severity=severity,
                    risk_score=risk_score,
                    source_text="",
                    target_text=text,
                    note=note.replace(sample_suffix, ""),
                )

    translation_metrics = (quality_metrics or {}).get("translation") if isinstance(quality_metrics, dict) else {}
    if isinstance(translation_metrics, dict):
        for sample in translation_metrics.get("untranslated_discourse_marker_samples") or []:
            if not isinstance(sample, dict):
                continue
            markers = ", ".join(str(value) for value in sample.get("markers") or [])
            add_row(
                segment_id=int(sample.get("segment_id") or 0),
                risk_type="untranslated_discourse_marker",
                severity="high",
                risk_score=10,
                source_text=str(sample.get("source_text") or ""),
                target_text=str(sample.get("target_text") or ""),
                note=f"Translate discourse marker(s) according to context: {markers}",
            )

    rows.sort(key=lambda row: (-int(row["risk_score"]), row["severity"], int(row["segment_id"])))
    return rows


def build_display_qa_rows(
    cues: list[DisplayCue],
    *,
    zh_max_line_chars: int,
    zh_wrap_trigger_chars: int,
    zh_max_lines: int,
    zh_soft_max_line_chars: int = 33,
    zh_hard_max_line_chars: int = 36,
    zh_soft_max_cps: float = 18.0,
    zh_hard_max_cps: float = 22.0,
) -> list[dict]:
    rows: list[dict] = []
    for index, cue in enumerate(cues, start=1):
        zh_text = cue.zh_text or ""
        if not zh_text:
            continue
        duration = max(0.001, float(cue.end) - float(cue.start))
        rendered = wrap_chinese_text(
            zh_text,
            trigger_chars=zh_wrap_trigger_chars,
            max_chars=zh_max_line_chars,
            max_lines=zh_max_lines,
        )
        lines = rendered.splitlines() or [rendered]
        max_line_len = max((len(re.sub(r"\s+", "", line)) for line in lines), default=0)
        cps = len(re.sub(r"\s+", "", zh_text)) / duration
        issues: list[str] = []
        if len(lines) > zh_max_lines:
            issues.append("too_many_lines")
        if max_line_len > max(zh_hard_max_line_chars, zh_max_line_chars):
            issues.append("line_too_long_hard")
        elif max_line_len > max(zh_soft_max_line_chars, zh_max_line_chars):
            issues.append("line_too_long_soft")
        if cps > max(zh_hard_max_cps, zh_soft_max_cps):
            issues.append("cps_high_hard")
        elif cps > zh_soft_max_cps:
            issues.append("cps_high_soft")
        if not issues:
            continue
        rows.append(
            {
                "cue_index": index,
                "source_segment_id": cue.source_segment_id or "",
                "start": round(cue.start, 3),
                "end": round(cue.end, 3),
                "duration": round(duration, 3),
                "zh_cps": round(cps, 2),
                "zh_line_count": len(lines),
                "zh_max_line_length": max_line_len,
                "issues": ",".join(issues),
                "zh_text": zh_text,
                "rendered_zh": rendered.replace("\n", "\\N"),
                "en_text": cue.en_text,
                "rewrite_action": cue.rewrite_action,
            }
        )
    rows.sort(key=lambda row: (-float(row["zh_cps"]), -int(row["zh_max_line_length"])))
    return rows


def build_glossary_qa_rows(quality_metrics: dict) -> list[dict]:
    rows: list[dict] = []
    glossary = quality_metrics.get("glossary") if isinstance(quality_metrics, dict) else {}
    if not isinstance(glossary, dict):
        return rows

    for key in ("bad_alias_in_target_samples", "bad_alias_in_source_samples", "preserve_missing_samples"):
        for sample in glossary.get(key) or []:
            if not isinstance(sample, dict):
                continue
            rows.append(
                {
                    "issue_type": key.removesuffix("_samples"),
                    "segment_id": sample.get("segment_id", ""),
                    "canonical": sample.get("canonical", ""),
                    "bad_alias": sample.get("bad_alias", "") or sample.get("expected_zh", ""),
                }
            )
    return rows
