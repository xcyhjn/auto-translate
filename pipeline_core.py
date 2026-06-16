from __future__ import annotations

import errno
import json
import math
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import tempfile

from .asr import transcribe_audio
from .bilingual_postprocess import postprocess_bilingual_segments
from .difficult_spans import detect_difficult_spans
from .display_rewrite import rewrite_display_segments
from .entity_normalization import audit_ass_entities, build_entity_metrics, build_entity_review_rows, normalize_entities
from .english_residue_policy import build_english_residue_report
from .glossary import (
    apply_glossary_alias_corrections,
    apply_translate_policy_corrections,
    ensure_project_glossary,
    glossary_from_terms,
    glossary_to_prompt_text,
    merge_term_item,
    write_asr_terms,
    write_resolved_glossary,
)
from .media import (
    enhance_audio_for_asr,
    extract_audio,
    merge_video_with_audio,
    probe_media,
    run_ffmpeg_command,
    suggest_hwaccel_decoder,
)
from .models import BilingualSubtitleStyle, Segment, SubtitleRules
from .qa import build_quality_metrics, qa_ass_entity_audit, qa_check, qa_difficult_spans, qa_display_cues, qa_final_ass_file, qa_glossary_consistency
from .qa_outputs import (
    build_blocker_report,
    build_display_qa_rows,
    build_editor_review_rows,
    build_entity_qa_rows,
    build_glossary_qa_rows,
    write_tsv,
)
from .segment_io import load_segments, save_segments, save_segments_payload
from .segmentation_qa import build_segmentation_qa_metrics
from .semantic_allocation import build_semantic_allocation_report
from .source_repair import repair_source_segments
from .source_spans import detect_source_spans
from .span_repair import repair_difficult_spans
from .span_translate import translate_source_spans
from .subtitle_io import (
    prepare_bilingual_ass_segments,
    write_bilingual_ass_from_display_cues,
    write_srt,
    write_source_ass,
    write_zh_ass,
)
from .terminology import apply_terminology_short_circuit
from .text_quality import find_text_pollution, format_pollution_issues
from .timing import refine_timing
from .translate import load_glossary, translate_segments
from .style_rules import load_style_prompt_text
from .workflow_profiles import load_dataset_glossary_terms, load_dataset_profile, write_dataset_profile_assets, build_subtitle_output_plan
from .zh_reading_axis import (
    ZhReadingAxisConfig,
    build_zh_display_cues,
    build_zh_reading_groups,
    group_short_complete_sentence_cues,
    merge_orphan_tail_display_cues,
    reading_groups_to_segments,
    save_zh_reading_groups,
    source_reference_cues_from_segments,
    write_dual_axis_ass,
    write_zh_ass_from_display_cues,
)


StageCallback = Callable[[str, dict], None]
ControlCallback = Callable[[str, dict | None], None]

VIDEO_ENCODER = "h264_nvenc"
VIDEO_ENCODER_FALLBACK = "libx264"
VIDEO_PRESET = "p4"
VIDEO_QUALITY = "25"
TARGET_MAX_HEIGHT = 1080
def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def build_stage_metadata(
    *,
    input_path: Path,
    segment_count: int = 0,
    summary: dict | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_file": str(input_path),
        "segment_count": int(segment_count),
        "summary": summary or {},
    }


def write_stage_json(
    path: Path,
    payload: dict,
    *,
    input_path: Path,
    segment_count: int = 0,
) -> None:
    wrapped = dict(payload)
    wrapped.setdefault("schema_version", 1)
    wrapped.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    wrapped.setdefault("input_file", str(input_path))
    wrapped.setdefault("segment_count", int(segment_count))
    wrapped.setdefault("summary", {})
    write_json(path, wrapped)


def empty_terminology_report(segment_count: int) -> dict:
    return {
        "schema_version": 1,
        "summary": {
            "segment_count": segment_count,
            "rule_count": 0,
            "locked_segment_count": 0,
            "action_count": 0,
        },
        "actions": [],
    }


def empty_span_translation_report() -> dict:
    return {
        "schema_version": 1,
        "summary": {
            "eligible_span_count": 0,
            "attempted_count": 0,
            "translated_span_count": 0,
            "translated_segment_count": 0,
            "failed_count": 0,
        },
        "results": [],
    }


def load_span_translation_checkpoint(
    path: Path,
    expected_segments: list[Segment],
) -> tuple[list[Segment], set[int]] | None:
    if not path.exists():
        return None
    try:
        checkpoint_segments = load_segments(path)
    except Exception:
        return None
    if [segment.id for segment in checkpoint_segments] != [segment.id for segment in expected_segments]:
        return None
    locked_ids = {
        segment.id
        for segment in checkpoint_segments
        if segment.target_text and segment.target_text.strip()
    }
    return checkpoint_segments, locked_ids


def translated_segments_match_timing_mode(path: Path, *, dual_axis_mode: bool) -> bool:
    if not path.exists():
        return False
    try:
        segments = load_segments(path)
    except Exception:
        return False
    if not segments or any(not (segment.target_text or "").strip() for segment in segments):
        return False
    if not dual_axis_mode:
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return str(summary.get("timing_mode") or "").strip().lower() == "dual_axis"


def write_dataset_glossary_bundle(
    output_dir: Path,
    dataset_profile: str,
) -> tuple[Path | None, Path | None]:
    dataset_terms = load_dataset_glossary_terms(dataset_profile)
    if not dataset_terms:
        return (None, None)

    terms: dict[str, object] = {}
    for item in dataset_terms:
        merge_term_item(terms, item)
    glossary = glossary_from_terms(terms, strategy=f"dataset:{dataset_profile}")
    json_path = output_dir / "00_profile_glossary.json"
    prompt_path = output_dir / "00_profile_glossary_prompt.txt"
    json_path.write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt_path.write_text(glossary_to_prompt_text(glossary), encoding="utf-8")
    return (json_path, prompt_path)


def build_subtitle_filter_path(subtitle_path: Path) -> str:
    resolved = subtitle_path.resolve().as_posix()
    resolved = resolved.replace("\\", "/")
    resolved = resolved.replace(":", "\\:")
    resolved = resolved.replace(",", "\\,")
    return resolved


def needs_downscale(video_path: Path, *, target_max_height: int = TARGET_MAX_HEIGHT) -> bool:
    probe = probe_media(video_path)
    return bool(probe.video_height and probe.video_height > target_max_height)


def burn_subtitle(
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    preview_seconds: int | None = None,
    *,
    progress_callback: StageCallback | None = None,
    total_duration: float | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_name(
        f".{output_path.stem}.{uuid.uuid4().hex}.tmp{output_path.suffix}"
    )
    subtitle_filter_path = build_subtitle_filter_path(subtitle_path)
    filter_chain: list[str] = []
    subtitle_filter = f"ass='{subtitle_filter_path}'"
    if needs_downscale(video_path):
        filter_chain.append("scale=-2:1080:flags=lanczos")
    filter_chain.append(subtitle_filter)
    video_filter = ",".join(filter_chain)
    args = [
        "ffmpeg",
        "-y",
    ]
    hwaccel, decoder = suggest_hwaccel_decoder(video_path)
    if hwaccel and decoder:
        args.extend(["-hwaccel", hwaccel, "-c:v", decoder])
    args.extend(["-i", str(video_path)])
    if preview_seconds is not None:
        args.extend(["-t", str(preview_seconds)])
    args.extend(
        [
            "-vf",
            video_filter,
            "-c:v",
            VIDEO_ENCODER,
            "-preset",
            VIDEO_PRESET,
            "-cq",
            VIDEO_QUALITY,
            "-pix_fmt",
            "yuv420p",
                "-c:a",
                "copy",
                str(temp_output_path),
            ]
    )
    def emit_progress(progress_payload: dict) -> None:
        if progress_callback is None:
            return
        payload = dict(progress_payload)
        duration = safe_duration_seconds(total_duration)
        if duration > 0:
            processed_seconds = max(0.0, finite_float(payload.get("out_time_seconds"), 0.0))
            progress_ratio = max(0.0, min(1.0, processed_seconds / duration))
            payload["out_time_seconds"] = processed_seconds
            payload["duration_seconds"] = duration
            payload["progress"] = round(progress_ratio * 100, 2)
            payload["remaining_seconds"] = max(0.0, duration - processed_seconds)
            size_bytes = max(0, int(finite_float(payload.get("size_bytes"), 0.0)))
            if progress_ratio > 0.02 and size_bytes > 0:
                payload["estimated_final_size"] = int(size_bytes / progress_ratio)
        else:
            payload["duration_seconds"] = 0.0
        emit(progress_callback, "burn_progress", payload)

    try:
        run_ffmpeg_command(args, progress_callback=emit_progress if progress_callback else None)
    except RuntimeError:
        if temp_output_path.exists():
            temp_output_path.unlink()
        fallback_args = list(args)
        if "-hwaccel" in fallback_args and decoder:
            hwaccel_index = fallback_args.index("-hwaccel")
            del fallback_args[hwaccel_index : hwaccel_index + 4]
        encoder_index = fallback_args.index("-c:v") + 1
        fallback_args[encoder_index] = VIDEO_ENCODER_FALLBACK
        preset_index = fallback_args.index("-preset") + 1
        fallback_args[preset_index] = "medium"
        cq_index = fallback_args.index("-cq")
        fallback_args[cq_index : cq_index + 2] = ["-crf", "25"]
        run_ffmpeg_command(fallback_args, progress_callback=emit_progress if progress_callback else None)
    final_output_path = output_path
    if temp_output_path.exists():
        try:
            temp_output_path.replace(output_path)
        except PermissionError as exc:
            fallback_output_path = output_path.with_name(
                f"{output_path.stem}.reburned.{uuid.uuid4().hex[:8]}{output_path.suffix}"
            )
            temp_output_path.replace(fallback_output_path)
            final_output_path = fallback_output_path
            raise PermissionError(
                errno.EACCES,
                (
                    "Target output video is currently in use and could not be replaced. "
                    f"A new burned video was saved as: {fallback_output_path}"
                ),
                str(output_path),
            ) from exc
    return {
        "hwaccel": hwaccel or "",
        "decoder": decoder or "default",
        "output_path": str(final_output_path),
        "replaced_primary_output": final_output_path == output_path,
    }


def create_safe_ass_copy(subtitle_path: Path) -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "autosub_zh_burn"
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe_path = temp_dir / "08_bilingual_safe.ass"
    safe_path.write_text(subtitle_path.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    return safe_path


def build_output_slug(input_path: Path) -> str:
    stem = input_path.stem
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    if not slug:
        slug = f"video-{abs(hash(stem)) % 10_000_000}"
    return slug


def resolve_output_dir(input_path: Path, output_root: Path) -> Path:
    slug = build_output_slug(input_path)
    output_dir = output_root / slug
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def get_glossary_json_path(output_dir: Path) -> Path | None:
    for candidate in (output_dir / "03_glossary_resolved.json", output_dir / "00_glossary_auto.json"):
        if candidate.exists():
            return candidate
    return None


def emit(callback: StageCallback | None, stage: str, payload: dict) -> None:
    if callback:
        callback(stage, payload)


def checkpoint(control_callback: ControlCallback | None, stage: str, payload: dict | None = None) -> None:
    if control_callback:
        control_callback(stage, payload or {})


def finite_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def safe_duration_seconds(value: object) -> float:
    return max(0.0, finite_float(value, 0.0))


def seconds_to_virtual_chunks(processed_seconds: float, total_seconds: float, chunk_span: int = 30) -> tuple[int, int]:
    processed_seconds = max(0.0, finite_float(processed_seconds, 0.0))
    total_seconds = safe_duration_seconds(total_seconds)
    chunk_span = max(1, int(finite_float(chunk_span, 30.0)))
    if total_seconds <= 0:
        return (0, 0)
    total_chunks = max(1, int((total_seconds + chunk_span - 1) // chunk_span))
    current_chunk = max(0, min(total_chunks, int(processed_seconds // chunk_span) + (1 if processed_seconds > 0 else 0)))
    return current_chunk, total_chunks


def build_asr_progress_payload(progress: dict, duration_seconds: object) -> dict:
    processed_seconds = max(0.0, finite_float(progress.get("processed_seconds"), 0.0))
    progress_percent = max(0.0, min(100.0, finite_float(progress.get("progress"), 0.0)))
    duration = safe_duration_seconds(duration_seconds)
    if progress_percent == 0 and duration > 0:
        progress_percent = round(max(0.0, min(1.0, processed_seconds / duration)) * 100, 2)
    current_chunk, total_chunks = seconds_to_virtual_chunks(processed_seconds, duration)
    return {
        **progress,
        "progress": progress_percent,
        "processed_seconds": processed_seconds,
        "duration_seconds": duration,
        "virtual_chunk_current": current_chunk,
        "virtual_chunk_total": total_chunks,
    }


def build_asr_state_stage(progress: dict) -> tuple[str, dict]:
    event = str(progress.get("event") or "").strip().lower()
    if event == "attempt_start":
        return "asr_attempt_start", {
            "device": progress.get("device"),
            "compute_type": progress.get("compute_type"),
            "beam_size": progress.get("beam_size"),
            "reason": progress.get("reason"),
        }
    if event == "fallback":
        return "asr_fallback", {
            "message": progress.get("message"),
            "failed_device": progress.get("failed_device"),
            "failed_compute_type": progress.get("failed_compute_type"),
            "device": progress.get("device"),
            "compute_type": progress.get("compute_type"),
            "beam_size": progress.get("beam_size"),
            "reason": progress.get("reason"),
        }
    return "asr_progress", build_asr_progress_payload(progress, progress.get("duration_seconds"))


def assert_no_target_text_pollution(segments: list[Segment], *, dst_lang: str | None) -> None:
    polluted: list[str] = []
    for segment in segments:
        issues = find_text_pollution(segment.target_text or "", dst_lang=dst_lang)
        if issues:
            polluted.append(
                f"Segment {segment.id}: {format_pollution_issues(issues)}"
            )
        if len(polluted) >= 10:
            break
    if polluted:
        details = "; ".join(polluted)
        raise RuntimeError(f"Refusing to write ASS because target text contains suspicious polluted text. {details}")


def run_pipeline(
    *,
    input_path: Path,
    output_root: Path,
    src_lang: str = "en",
    dst_lang: str = "zh-Hans",
    model: str = "distil-large-v3",
    device: str = "cpu",
    compute_type: str = "int8",
    beam_size: int = 5,
    asr_audio_mode: str = "off",
    asr_audio_gain_db: float = 6.0,
    asr_vad_mode: str = "auto",
    translation_model: str = "gpt-5.4",
    translation_prompt: str = "",
    translation_chunk_size: int = 40,
    translation_retries: int = 2,
    openai_base_url: str | None = None,
    audio_override_path: str | Path | None = None,
    load_existing_segments: bool = False,
    force_retranslate_existing_segments: bool = False,
    preview_seconds: int | None = None,
    skip_burn: bool = False,
    repair_high_risk_spans: bool = True,
    span_translation_max_spans: int = 16,
    span_repair_max_spans: int = 12,
    semantic_zh_allocation_enabled: bool = True,
    semantic_zh_allocation_max_spans: int = 16,
    short_complete_sentence_display_grouping: bool = True,
    english_residue_validation_enabled: bool = True,
    english_residue_preserve_threshold: int = 85,
    english_residue_review_threshold: int = 70,
    enable_ai_display_rewrite: bool = False,
    display_rewrite_max_ai_segments: int = 12,
    bootstrap_entity_decisions: str | bool = "high_confidence_only",
    subtitle_mode: str = "bilingual_source_reference",
    source_reference_label: str = "",
    dataset_profile: str = "",
    bilingual_style: BilingualSubtitleStyle | None = None,
    subtitle_timing_mode: str = "bound",
    zh_semantic_merge: bool = False,
    zh_target_min_duration: float = 3.5,
    zh_target_max_duration: float = 7.5,
    zh_hard_max_duration: float = 8.5,
    zh_min_duration: float = 2.2,
    callback: StageCallback | None = None,
    control_callback: ControlCallback | None = None,
) -> dict:
    input_path = Path(input_path)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = resolve_output_dir(input_path, output_root)
    translated_json_path = output_dir / "05_translated_segments.json"
    timed_json_path = output_dir / "03_timed_source_segments.json"
    zh_reading_groups_path = output_dir / "04b_zh_reading_groups.json"
    style_prompt_path = output_dir / "06d_style_rewrite_prompt.txt"
    learned_style_prompt = load_style_prompt_text(style_prompt_path)
    translation_prompt = str(translation_prompt or "").strip()
    style_prompt_for_translation = "\n\n".join(
        item for item in [translation_prompt, learned_style_prompt] if item.strip()
    )
    processing_video_path = input_path
    auto_glossary_path = ensure_project_glossary(output_dir)
    effective_style = bilingual_style if bilingual_style is not None else BilingualSubtitleStyle()
    dual_axis_mode = (
        str(subtitle_timing_mode or "").strip().lower() == "dual_axis"
        and bool(zh_semantic_merge)
        and str(src_lang or "").strip().lower().startswith("ru")
    )
    zh_axis_config = ZhReadingAxisConfig(
        target_min_duration=float(zh_target_min_duration or 3.5),
        target_max_duration=float(zh_target_max_duration or 7.5),
        hard_max_duration=float(zh_hard_max_duration or 8.5),
        min_duration=float(zh_min_duration or 2.2),
        zh_max_cps=18.0,
    )
    source_axis_segments: list[Segment] = []
    source_repair_report = {
        "schema_version": 1,
        "summary": {
            "segment_count": 0,
            "rule_count": 0,
            "candidate_count": 0,
            "review_count": 0,
            "repaired_segment_count": 0,
            "replacement_count": 0,
            "term_hit_count": {},
        },
        "candidates": [],
        "repairs": [],
    }
    semantic_allocation_report = {
        "schema_version": 1,
        "summary": {
            "enabled": bool(semantic_zh_allocation_enabled),
            "segment_count": 0,
            "allocation_count": 0,
            "applied_count": 0,
            "review_count": 0,
            "translated_span_count": 0,
            "flagged_segment_count": 0,
            "adjacent_duplicate_target_count": 0,
            "flag_counts": {},
        },
        "allocations": [],
    }
    display_group_report = {
        "schema_version": 1,
        "summary": {
            "group_count": 0,
            "merged_short_complete_sentence_count": 0,
        },
        "groups": [],
    }
    orphan_tail_display_report = {
        "schema_version": 1,
        "summary": {
            "group_count": 0,
            "merged_orphan_tail_count": 0,
        },
        "groups": [],
    }
    dataset_bundle = load_dataset_profile(dataset_profile)
    dataset_assets = write_dataset_profile_assets(dataset_profile, output_dir) if dataset_profile else {}
    dataset_glossary_json_path, dataset_glossary_prompt_path = (
        write_dataset_glossary_bundle(output_dir, dataset_profile) if dataset_profile else (None, None)
    )
    plan = build_subtitle_output_plan(
        src_lang=source_reference_label or src_lang,
        dst_lang=dst_lang,
        subtitle_mode=subtitle_mode,
        preview_seconds=preview_seconds,
    )

    emit(
        callback,
        "init",
        {
            "input": str(input_path),
            "output_dir": str(output_dir),
            "audio_override_path": str(audio_override_path) if audio_override_path else None,
            "glossary_path": str(auto_glossary_path) if auto_glossary_path else "",
            "dataset_glossary_path": str(dataset_glossary_prompt_path) if dataset_glossary_prompt_path else "",
            "dataset_profile": dataset_profile,
            "dataset_assets": dataset_assets,
        },
    )

    checkpoint(control_callback, "probe_media", {"path": str(input_path)})
    input_probe = probe_media(input_path)
    input_duration = safe_duration_seconds(input_probe.duration)
    if audio_override_path:
        checkpoint(control_callback, "merge_audio_start", {"video_path": str(input_path), "audio_path": str(audio_override_path)})
        merged_video_path = output_dir / "00a_merged_with_external_audio.mp4"
        emit(
            callback,
            "merge_audio_start",
            {
                "video_path": str(input_path),
                "audio_path": str(audio_override_path),
                "merged_path": str(merged_video_path),
                "duration_seconds": input_duration,
            },
        )

        def on_merge_progress(progress_payload: dict) -> None:
            payload = dict(progress_payload)
            duration = input_duration
            if duration:
                processed_seconds = max(0.0, finite_float(payload.get("out_time_seconds"), 0.0))
                payload["out_time_seconds"] = processed_seconds
                payload["duration_seconds"] = duration
                payload["progress"] = round(max(0.0, min(1.0, processed_seconds / duration)) * 100, 2)
            emit(callback, "merge_audio_progress", payload)

        merge_video_with_audio(
            input_path,
            audio_override_path,
            merged_video_path,
            progress_callback=on_merge_progress,
        )
        processing_video_path = merged_video_path
        emit(
            callback,
            "merge_audio_complete",
            {
                "video_path": str(input_path),
                "audio_path": str(audio_override_path),
                "merged_path": str(merged_video_path),
                "size_bytes": merged_video_path.stat().st_size if merged_video_path.exists() else 0,
            },
        )

    checkpoint(control_callback, "probe_media", {"path": str(processing_video_path)})
    probe = probe_media(processing_video_path)
    probe_duration = safe_duration_seconds(probe.duration)
    write_json(output_dir / "00_media_probe.json", asdict(probe))
    emit(
        callback,
        "probe_media",
        {
            "path": str(output_dir / "00_media_probe.json"),
            "duration_seconds": probe_duration,
            "has_audio": probe.has_audio,
            "subtitle_streams": len(probe.text_subtitle_streams) + len(probe.image_subtitle_streams),
        },
    )
    if not probe.has_audio:
        if audio_override_path:
            raise RuntimeError("合并外部音频后仍未检测到可用音轨，请检查附加音频文件是否有效。")
        raise RuntimeError(
            "当前视频没有检测到音轨，无法直接提取音频。"
            "请先为该视频附加外部 MP3，再启动流程。"
        )

    if (
        load_existing_segments
        and not force_retranslate_existing_segments
        and translated_segments_match_timing_mode(translated_json_path, dual_axis_mode=dual_axis_mode)
        and (not dual_axis_mode or timed_json_path.exists())
    ):
        checkpoint(control_callback, "load_existing_segments", {"path": str(translated_json_path)})
        translated_segments = load_segments(translated_json_path)
        source_axis_segments = load_segments(timed_json_path) if dual_axis_mode and timed_json_path.exists() else translated_segments
        postprocess_stats = postprocess_bilingual_segments(translated_segments)
        source_repair_report = repair_source_segments(translated_segments, get_glossary_json_path(output_dir))
        write_stage_json(
            output_dir / "02b_asr_source_repair_candidates.json",
            {
                "schema_version": 1,
                "summary": {
                    "segment_count": len(translated_segments),
                    "candidate_count": 0,
                    "review_count": 0,
                    "reused_translated_segments": True,
                },
                "candidates": [],
            },
            input_path=input_path,
            segment_count=len(translated_segments),
        )
        save_segments_payload(
            translated_segments,
            output_dir / "03b_source_repaired_segments.json",
            input_file=str(input_path),
            summary={**source_repair_report["summary"], "bilingual_postprocess": postprocess_stats},
        )
        write_stage_json(
            output_dir / "03b_source_repair_report.json",
            source_repair_report,
            input_path=input_path,
            segment_count=len(translated_segments),
        )
        source_spans = detect_source_spans(translated_segments)
        write_stage_json(
            output_dir / "04a_source_spans.json",
            source_spans,
            input_path=input_path,
            segment_count=len(translated_segments),
        )
        if source_repair_report["summary"]["replacement_count"] or postprocess_stats["total_replacements"]:
            save_segments(translated_segments, translated_json_path)
            write_srt(translated_segments, output_dir / plan.source_srt_name)
        if not (output_dir / "05b_terminology_actions.json").exists():
            write_json(output_dir / "05b_terminology_actions.json", empty_terminology_report(len(translated_segments)))
        if not (output_dir / "05a_span_translation_report.json").exists():
            save_segments_payload(
                translated_segments,
                output_dir / "05a_span_translated_segments.json",
                input_file=str(input_path),
                summary=empty_span_translation_report()["summary"],
            )
            write_stage_json(
                output_dir / "05a_span_translation_report.json",
                empty_span_translation_report(),
                input_path=input_path,
                segment_count=len(translated_segments),
            )
        emit(
            callback,
            "load_existing_segments",
            {
                "path": str(translated_json_path),
                "count": len(translated_segments),
                "duration_seconds": probe_duration,
                "note": "loaded translated display segments; rerun timing/translation if these were generated before display-level timing was introduced",
                "source_repairs": source_repair_report["summary"],
                "bilingual_postprocess": postprocess_stats,
                "source_spans": source_spans["summary"],
            },
        )
    else:
        if (load_existing_segments or force_retranslate_existing_segments) and timed_json_path.exists():
            checkpoint(control_callback, "timing_start", {"reused": True, "path": str(timed_json_path)})
            timed_segments = load_segments(timed_json_path)
            source_axis_segments = timed_segments
            source_repair_report = repair_source_segments(timed_segments, get_glossary_json_path(output_dir))
            write_stage_json(
                output_dir / "02b_asr_source_repair_candidates.json",
                {
                    "schema_version": 1,
                    "summary": {
                        "segment_count": len(timed_segments),
                        "candidate_count": 0,
                        "review_count": 0,
                        "reused_timed_segments": True,
                    },
                    "candidates": [],
                },
                input_path=input_path,
                segment_count=len(timed_segments),
            )
            alias_stats = apply_glossary_alias_corrections(timed_segments, get_glossary_json_path(output_dir))
            save_segments_payload(
                timed_segments,
                output_dir / "03b_source_repaired_segments.json",
                input_file=str(input_path),
                summary=source_repair_report["summary"],
            )
            if source_repair_report["summary"]["replacement_count"] or alias_stats["total_replacements"]:
                save_segments_payload(
                    timed_segments,
                    timed_json_path,
                    input_file=str(input_path),
                    summary={"stage": "timed_source"},
                )
                write_srt(timed_segments, output_dir / plan.source_srt_name)
            write_stage_json(
                output_dir / "03b_source_repair_report.json",
                source_repair_report,
                input_path=input_path,
                segment_count=len(timed_segments),
            )
            source_spans = detect_source_spans(timed_segments)
            write_stage_json(
                output_dir / "04a_source_spans.json",
                source_spans,
                input_path=input_path,
                segment_count=len(timed_segments),
            )
            emit(
                callback,
                "timing_complete",
                {
                    "path": str(timed_json_path),
                    "count": len(timed_segments),
                    "source_count": len(timed_segments),
                    "reused": True,
                    "force_retranslate": bool(force_retranslate_existing_segments),
                    "alias_corrections": alias_stats,
                    "source_repairs": source_repair_report["summary"],
                    "source_spans": source_spans["summary"],
                },
            )
        else:
            def on_extract_progress(progress_payload: dict) -> None:
                payload = dict(progress_payload)
                duration = probe_duration
                if duration:
                    processed_seconds = max(0.0, finite_float(payload.get("out_time_seconds"), 0.0))
                    payload["out_time_seconds"] = processed_seconds
                    payload["duration_seconds"] = duration
                    payload["progress"] = round(max(0.0, min(1.0, processed_seconds / duration)) * 100, 2)
                emit(callback, "extract_audio_progress", payload)

            emit(
                callback,
                "extract_audio_start",
                {
                    "input_path": str(processing_video_path),
                    "duration_seconds": probe_duration,
                },
            )
            checkpoint(control_callback, "extract_audio_start", {"input_path": str(processing_video_path)})
            audio_path = extract_audio(
                processing_video_path,
                work_dir=output_dir,
                progress_callback=on_extract_progress,
            )
            renamed_audio_path = output_dir / "01_audio_16k.wav"
            if audio_path != renamed_audio_path:
                renamed_audio_path.write_bytes(audio_path.read_bytes())
                audio_path = renamed_audio_path
            emit(
                callback,
                "extract_audio_complete",
                {
                    "path": str(audio_path),
                    "size_bytes": audio_path.stat().st_size,
                    "duration_seconds": probe_duration,
                },
            )

            asr_input_path = audio_path
            asr_audio_mode_normalized = str(asr_audio_mode or "off").strip().lower().replace("-", "_")
            asr_vad_mode_normalized = str(asr_vad_mode or "auto").strip().lower().replace("-", "_")
            if asr_audio_mode_normalized not in {"off", "whisper", "strong_whisper"}:
                asr_audio_mode_normalized = "off"
            if asr_vad_mode_normalized == "on":
                asr_vad_filter = True
            elif asr_vad_mode_normalized == "off":
                asr_vad_filter = False
            else:
                asr_vad_filter = asr_audio_mode_normalized == "off"
            if asr_audio_mode_normalized != "off":
                enhanced_audio_path = output_dir / "01b_audio_asr_enhanced.wav"
                checkpoint(control_callback, "enhance_audio_start", {"path": str(enhanced_audio_path)})

                def on_enhance_progress(progress_payload: dict) -> None:
                    payload = dict(progress_payload)
                    duration = probe_duration
                    if duration:
                        processed_seconds = max(0.0, finite_float(payload.get("out_time_seconds"), 0.0))
                        payload["out_time_seconds"] = processed_seconds
                        payload["duration_seconds"] = duration
                        payload["progress"] = round(max(0.0, min(1.0, processed_seconds / duration)) * 100, 2)
                    payload["enhancement_mode"] = asr_audio_mode_normalized
                    payload["gain_db"] = float(asr_audio_gain_db or 0.0)
                    emit(callback, "enhance_audio_progress", payload)

                emit(
                    callback,
                    "enhance_audio_start",
                    {
                        "path": str(enhanced_audio_path),
                        "source_path": str(audio_path),
                        "duration_seconds": probe_duration,
                        "enhancement_mode": asr_audio_mode_normalized,
                        "gain_db": float(asr_audio_gain_db or 0.0),
                    },
                )
                asr_input_path = enhance_audio_for_asr(
                    audio_path,
                    enhanced_audio_path,
                    mode=asr_audio_mode_normalized,
                    gain_db=float(asr_audio_gain_db or 0.0),
                    progress_callback=on_enhance_progress,
                )
                emit(
                    callback,
                    "enhance_audio_complete",
                    {
                        "path": str(asr_input_path),
                        "source_path": str(audio_path),
                        "size_bytes": asr_input_path.stat().st_size,
                        "duration_seconds": probe_duration,
                        "enhancement_mode": asr_audio_mode_normalized,
                        "gain_db": float(asr_audio_gain_db or 0.0),
                    },
                )

            emit(
                callback,
                "asr_start",
                {
                    "audio_path": str(asr_input_path),
                    "source_audio_path": str(audio_path),
                    "enhanced_audio_path": str(asr_input_path) if asr_input_path != audio_path else "",
                    "duration_seconds": probe_duration,
                    "audio_mode": asr_audio_mode_normalized,
                    "vad_mode": asr_vad_mode_normalized,
                    "vad_filter": asr_vad_filter,
                },
            )
            checkpoint(control_callback, "asr_start", {"audio_path": str(asr_input_path)})
            raw_segments = transcribe_audio(
                asr_input_path,
                model_name=model,
                language=src_lang,
                device=device,
                compute_type=compute_type,
                beam_size=beam_size,
                vad_filter=asr_vad_filter,
                progress_callback=lambda progress: emit(
                    callback,
                    *build_asr_state_stage({**progress, "duration_seconds": probe_duration}),
                ),
            )
            save_segments_payload(
                raw_segments,
                output_dir / "02_asr_raw_segments.json",
                input_file=str(input_path),
                summary={"stage": "asr_raw"},
            )
            asr_terms_path = write_asr_terms(output_dir, raw_segments)
            resolved_glossary_path = write_resolved_glossary(output_dir)
            if resolved_glossary_path:
                auto_glossary_path = resolved_glossary_path
            raw_source_repair_report = repair_source_segments(raw_segments, get_glossary_json_path(output_dir))
            write_stage_json(
                output_dir / "02b_asr_source_repair_candidates.json",
                {
                    "schema_version": 1,
                    "summary": raw_source_repair_report["summary"],
                    "candidates": raw_source_repair_report.get("candidates", []),
                },
                input_path=input_path,
                segment_count=len(raw_segments),
            )
            emit(
                callback,
                "asr_complete",
                {
                    "path": str(output_dir / "02_asr_raw_segments.json"),
                    "count": len(raw_segments),
                    "duration_seconds": probe_duration,
                    "terms_path": str(asr_terms_path),
                    "glossary_path": str(auto_glossary_path) if auto_glossary_path else "",
                    "source_repair_candidates": raw_source_repair_report["summary"],
                },
            )
            checkpoint(control_callback, "asr_complete", {"path": str(output_dir / "02_asr_raw_segments.json")})

            emit(
                callback,
                "timing_start",
                {
                    "segment_count": len(raw_segments),
                },
            )
            checkpoint(control_callback, "timing_start", {"segment_count": len(raw_segments)})
            timed_segments = refine_timing(raw_segments, style=effective_style)
            source_axis_segments = timed_segments
            source_repair_report = repair_source_segments(timed_segments, get_glossary_json_path(output_dir))
            alias_stats = apply_glossary_alias_corrections(timed_segments, get_glossary_json_path(output_dir))
            save_segments_payload(
                timed_segments,
                timed_json_path,
                input_file=str(input_path),
                summary={"stage": "timed_source"},
            )
            save_segments_payload(
                timed_segments,
                output_dir / "03b_source_repaired_segments.json",
                input_file=str(input_path),
                summary=source_repair_report["summary"],
            )
            write_stage_json(
                output_dir / "03b_source_repair_report.json",
                source_repair_report,
                input_path=input_path,
                segment_count=len(timed_segments),
            )
            source_spans = detect_source_spans(timed_segments)
            write_stage_json(
                output_dir / "04a_source_spans.json",
                source_spans,
                input_path=input_path,
                segment_count=len(timed_segments),
            )
            write_srt(timed_segments, output_dir / plan.source_srt_name)
            emit(
                callback,
                "timing_complete",
                {
                    "path": str(timed_json_path),
                    "count": len(timed_segments),
                    "source_count": len(raw_segments),
                    "timing_mode": "display_level",
                    "alias_corrections": alias_stats,
                    "source_repairs": source_repair_report["summary"],
                    "source_spans": source_spans["summary"],
                },
            )

        emit(
            callback,
            "translation_start",
            {
                "segment_count": len(timed_segments),
                "chunk_size": translation_chunk_size,
            },
        )
        checkpoint(control_callback, "translation_start", {"segment_count": len(timed_segments)})
        glossary_json_path = get_glossary_json_path(output_dir)
        if dual_axis_mode:
            zh_groups = build_zh_reading_groups(timed_segments, config=zh_axis_config)
            save_zh_reading_groups(
                zh_groups,
                zh_reading_groups_path,
                input_file=str(input_path),
                summary={
                    "stage": "zh_reading_groups",
                    "source_segment_count": len(timed_segments),
                    "timing_mode": "dual_axis",
                },
            )
            translation_segments = reading_groups_to_segments(zh_groups)
            locked_translation_ids: set[int] = set()
            terminology_report = empty_terminology_report(len(translation_segments))
            write_json(output_dir / "05b_terminology_actions.json", terminology_report)
            span_translation_report = empty_span_translation_report()
            save_segments_payload(
                translation_segments,
                output_dir / "05a_span_translated_segments.json",
                input_file=str(input_path),
                summary=span_translation_report["summary"],
            )
            write_stage_json(
                output_dir / "05a_span_translation_report.json",
                span_translation_report,
                input_path=input_path,
                segment_count=len(translation_segments),
            )
            emit(
                callback,
                "zh_reading_groups_complete",
                {
                    "path": str(zh_reading_groups_path),
                    "group_count": len(translation_segments),
                    "source_segment_count": len(timed_segments),
                },
            )
        else:
            translation_segments = timed_segments
            locked_translation_ids, terminology_report = apply_terminology_short_circuit(
                translation_segments,
                glossary_json_path,
            )
        write_stage_json(
            output_dir / "05b_terminology_actions.json",
            terminology_report,
            input_path=input_path,
            segment_count=len(translation_segments),
        )
        emit(
            callback,
            "terminology_short_circuit_complete",
            {
                "path": str(output_dir / "05b_terminology_actions.json"),
                **terminology_report["summary"],
            },
        )
        if not dual_axis_mode:
            source_spans_path = output_dir / "04a_source_spans.json"
            source_spans_for_translation = (
                json.loads(source_spans_path.read_text(encoding="utf-8"))
                if source_spans_path.exists()
                else detect_source_spans(translation_segments)
            )
            span_checkpoint = (
                load_span_translation_checkpoint(output_dir / "05a_span_translated_segments.json", translation_segments)
                if (load_existing_segments or force_retranslate_existing_segments)
                else None
            )
            if span_checkpoint:
                translation_segments, span_translated_ids = span_checkpoint
                span_translation_report_path = output_dir / "05a_span_translation_report.json"
                span_translation_report = (
                    json.loads(span_translation_report_path.read_text(encoding="utf-8"))
                    if span_translation_report_path.exists()
                    else empty_span_translation_report()
                )
                emit(
                    callback,
                    "span_translation_done",
                    {
                        "segments_path": str(output_dir / "05a_span_translated_segments.json"),
                        "report_path": str(output_dir / "05a_span_translation_report.json"),
                        "reused": True,
                        **span_translation_report.get("summary", {}),
                    },
                )
            else:
                span_translated_ids, span_translation_report = translate_source_spans(
                    translation_segments,
                    source_spans_for_translation,
                    src_lang=src_lang,
                    dst_lang=dst_lang,
                    glossary_text=(
                        "\n\n".join(
                            item
                            for item in [
                                dataset_bundle.get("glossary_text", ""),
                                load_glossary(str(auto_glossary_path)) if auto_glossary_path else "",
                            ]
                            if item.strip()
                        )
                    ),
                    model=translation_model,
                    style_prompt_text=style_prompt_for_translation,
                    base_url=openai_base_url,
                    max_retries=translation_retries,
                    max_spans=span_translation_max_spans,
                    english_residue_validation_enabled=english_residue_validation_enabled,
                    english_residue_preserve_threshold=english_residue_preserve_threshold,
                    english_residue_review_threshold=english_residue_review_threshold,
                    locked_ids=locked_translation_ids,
                    progress_callback=lambda stage, progress: (
                        checkpoint(control_callback, stage, progress),
                        emit(callback, stage, progress),
                    ),
                )
            locked_translation_ids.update(span_translated_ids)
            save_segments_payload(
                translation_segments,
                output_dir / "05a_span_translated_segments.json",
                input_file=str(input_path),
                summary=span_translation_report["summary"],
            )
            write_stage_json(
                output_dir / "05a_span_translation_report.json",
                span_translation_report,
                input_path=input_path,
                segment_count=len(translation_segments),
            )
            emit(
                callback,
                "span_translation_done",
                {
                    "segments_path": str(output_dir / "05a_span_translated_segments.json"),
                    "report_path": str(output_dir / "05a_span_translation_report.json"),
                    **span_translation_report["summary"],
                },
            )
        translated_segments = translate_segments(
            translation_segments,
            src_lang=src_lang,
            dst_lang=dst_lang,
            glossary=str(auto_glossary_path) if auto_glossary_path else None,
            enabled=True,
            provider="openai",
            model=translation_model,
            chunk_size=translation_chunk_size,
            max_retries=translation_retries,
            openai_base_url=openai_base_url,
            context_window=4,
            locked_segment_ids=locked_translation_ids,
            style_prompt_text=style_prompt_for_translation,
            glossary_text_override=dataset_bundle.get("glossary_text", ""),
            progress_callback=lambda stage, progress: (
                checkpoint(control_callback, stage, progress),
                emit(callback, stage, progress),
            ),
            checkpoint_path=str(translated_json_path),
            checkpoint_input_file=str(input_path),
            resume_from_checkpoint=bool(load_existing_segments and not force_retranslate_existing_segments),
            english_residue_validation_enabled=english_residue_validation_enabled,
            english_residue_preserve_threshold=english_residue_preserve_threshold,
            english_residue_review_threshold=english_residue_review_threshold,
        )
        glossary_json_path = get_glossary_json_path(output_dir)
        alias_stats = apply_glossary_alias_corrections(translated_segments, glossary_json_path)
        translate_policy_stats = apply_translate_policy_corrections(translated_segments, glossary_json_path)
        save_segments_payload(
            translated_segments,
            translated_json_path,
            input_file=str(input_path),
            summary={
                "stage": "translated_segments",
                "timing_mode": "dual_axis" if dual_axis_mode else "bound",
                "alias_corrections": alias_stats,
                "translate_policy_corrections": translate_policy_stats,
            },
        )
        write_srt(translated_segments, output_dir / plan.translated_srt_name)
        emit(
            callback,
            "translation_complete",
            {
                "path": str(translated_json_path),
                "count": len(translated_segments),
                "alias_corrections": alias_stats,
                "translate_policy_corrections": translate_policy_stats,
            },
        )

    glossary_json_path = get_glossary_json_path(output_dir)
    alias_stats = apply_glossary_alias_corrections(translated_segments, glossary_json_path)
    translate_policy_stats = apply_translate_policy_corrections(translated_segments, glossary_json_path)
    if alias_stats["total_replacements"] or translate_policy_stats["target_text_replacements"]:
        save_segments_payload(
            translated_segments,
            translated_json_path,
            input_file=str(input_path),
            summary={
                "stage": "translated_segments",
                "alias_corrections": alias_stats,
                "translate_policy_corrections": translate_policy_stats,
            },
        )
        write_srt(translated_segments, output_dir / plan.translated_srt_name)
        emit(
            callback,
            "glossary_alias_corrections",
            {
                "path": str(translated_json_path),
                **alias_stats,
                "translate_policy_corrections": translate_policy_stats,
            },
        )

    checkpoint(control_callback, "display_rewrite_start", {"segment_count": len(translated_segments)})
    display_rewrite_report = rewrite_display_segments(
        translated_segments,
        effective_style,
        style_prompt_path=style_prompt_path if style_prompt_path.exists() else None,
        enable_ai_rewrite=enable_ai_display_rewrite,
        ai_model=translation_model,
        openai_base_url=openai_base_url,
        max_retries=translation_retries,
        max_ai_segments=display_rewrite_max_ai_segments,
    )
    save_segments_payload(
        translated_segments,
        output_dir / "06b_display_rewritten_segments.json",
        input_file=str(input_path),
        summary=display_rewrite_report["summary"],
    )
    write_stage_json(
        output_dir / "06c_display_rewrite_report.json",
        display_rewrite_report,
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    translate_policy_stats = apply_translate_policy_corrections(translated_segments, get_glossary_json_path(output_dir))
    if translate_policy_stats["target_text_replacements"]:
        display_rewrite_report["summary"]["post_display_translate_policy_corrections"] = translate_policy_stats
    if display_rewrite_report["summary"]["changed_count"] or translate_policy_stats["target_text_replacements"]:
        save_segments_payload(
            translated_segments,
            translated_json_path,
            input_file=str(input_path),
            summary={
                "stage": "translated_segments",
                "display_rewrite": display_rewrite_report["summary"],
                "translate_policy_corrections": translate_policy_stats,
            },
        )
        write_srt(translated_segments, output_dir / plan.translated_srt_name)
    emit(
        callback,
        "display_rewrite_complete",
        {
            "segments_path": str(output_dir / "06b_display_rewritten_segments.json"),
            "report_path": str(output_dir / "06c_display_rewrite_report.json"),
            **display_rewrite_report["summary"],
        },
    )

    checkpoint(control_callback, "entity_normalization_start", {"segment_count": len(translated_segments)})
    entity_report = normalize_entities(
        translated_segments,
        project_dir=output_dir,
        bootstrap_project_decisions=bootstrap_entity_decisions,
    )
    save_segments_payload(
        translated_segments,
        output_dir / "06g_entity_normalized_segments.json",
        input_file=str(input_path),
        summary={
            "stage": "entity_normalized_segments",
            "entity_normalization": entity_report["summary"],
        },
    )
    write_stage_json(
        output_dir / "06e_entity_decisions.json",
        entity_report,
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    write_tsv(
        output_dir / "06f_entity_review.tsv",
        ["segment_id", "candidate", "entity_type", "source_text", "reference_text", "target_text", "reason"],
        build_entity_review_rows(
            translated_segments,
            project_dir=output_dir,
            glossary_path=get_glossary_json_path(output_dir),
        ),
    )
    if entity_report["summary"]["segments_changed"]:
        save_segments_payload(
            translated_segments,
            translated_json_path,
            input_file=str(input_path),
            summary={
                "stage": "translated_segments",
                "display_rewrite": display_rewrite_report["summary"],
                "translate_policy_corrections": translate_policy_stats,
                "entity_normalization": entity_report["summary"],
            },
        )
        write_srt(translated_segments, output_dir / plan.translated_srt_name)
    emit(
        callback,
        "entity_normalization_complete",
        {
            "path": str(output_dir / "06e_entity_decisions.json"),
            **entity_report["summary"],
        },
    )

    difficult_spans_initial = detect_difficult_spans(
        translated_segments,
        zh_max_cps=18.0,
        zh_max_chars=effective_style.zh_max_chars_per_line,
    )
    write_stage_json(
        output_dir / "07b_difficult_spans_initial.json",
        difficult_spans_initial,
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    emit(
        callback,
        "difficult_spans_detected",
        {
            "path": str(output_dir / "07b_difficult_spans_initial.json"),
            **difficult_spans_initial["summary"],
        },
    )

    span_repair_report = {
        "summary": {
            "candidate_count": 0,
            "attempted_count": 0,
            "repaired_segment_count": 0,
            "failed_count": 0,
            "enabled": bool(repair_high_risk_spans),
        },
        "results": [],
    }
    repair_candidate_count = int(difficult_spans_initial["summary"].get("needs_ai_repair_count") or 0)
    if repair_high_risk_spans and repair_candidate_count > 0:
        checkpoint(control_callback, "span_repair_start", {"candidate_count": repair_candidate_count})
        span_repair_report = repair_difficult_spans(
            translated_segments,
            difficult_spans_initial,
            src_lang=src_lang,
            dst_lang=dst_lang,
            glossary_text=(
                "\n\n".join(
                    item
                    for item in [
                        dataset_bundle.get("glossary_text", ""),
                        load_glossary(str(auto_glossary_path)) if auto_glossary_path else "",
                    ]
                    if item.strip()
                )
            ),
            model=translation_model,
            style_prompt_text=style_prompt_for_translation,
            base_url=openai_base_url,
            max_retries=translation_retries,
            max_spans=span_repair_max_spans,
            min_severity="medium",
            progress_callback=lambda stage, progress: (
                checkpoint(control_callback, stage, progress),
                emit(callback, stage, progress),
            ),
        )
        span_repair_report["summary"]["enabled"] = True
        glossary_json_path = get_glossary_json_path(output_dir)
        alias_stats = apply_glossary_alias_corrections(translated_segments, glossary_json_path)
        translate_policy_stats = apply_translate_policy_corrections(translated_segments, glossary_json_path)
        if alias_stats["total_replacements"]:
            span_repair_report["summary"]["post_repair_alias_corrections"] = alias_stats
        if translate_policy_stats["target_text_replacements"]:
            span_repair_report["summary"]["post_repair_translate_policy_corrections"] = translate_policy_stats
        save_segments_payload(
            translated_segments,
            translated_json_path,
            input_file=str(input_path),
            summary={
                "stage": "translated_segments",
                "span_repair": span_repair_report["summary"],
                "alias_corrections": alias_stats,
                "translate_policy_corrections": translate_policy_stats,
            },
        )
        write_srt(translated_segments, output_dir / plan.translated_srt_name)
    write_stage_json(
        output_dir / "07c_span_repair_report.json",
        span_repair_report,
        input_path=input_path,
        segment_count=len(translated_segments),
    )

    difficult_spans_final = detect_difficult_spans(
        translated_segments,
        zh_max_cps=18.0,
        zh_max_chars=effective_style.zh_max_chars_per_line,
    )
    write_stage_json(
        output_dir / "07b_difficult_spans.json",
        difficult_spans_final,
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    emit(
        callback,
        "difficult_spans_final",
        {
            "path": str(output_dir / "07b_difficult_spans.json"),
            "repair_path": str(output_dir / "07c_span_repair_report.json"),
            **difficult_spans_final["summary"],
        },
    )

    source_spans_path = output_dir / "04a_source_spans.json"
    source_spans_for_allocation = (
        json.loads(source_spans_path.read_text(encoding="utf-8"))
        if source_spans_path.exists()
        else detect_source_spans(translated_segments)
    )
    semantic_allocation_report = build_semantic_allocation_report(
        translated_segments,
        source_spans_for_allocation,
        span_translation_report if "span_translation_report" in locals() else None,
        enabled=semantic_zh_allocation_enabled,
        max_spans=semantic_zh_allocation_max_spans,
    )
    write_stage_json(
        output_dir / "05a_semantic_allocation_report.json",
        semantic_allocation_report,
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    save_segments_payload(
        translated_segments,
        output_dir / "05a_semantic_allocated_segments.json",
        input_file=str(input_path),
        summary=semantic_allocation_report["summary"],
    )
    save_segments_payload(
        translated_segments,
        translated_json_path,
        input_file=str(input_path),
        summary={
            "stage": "translated_segments",
            "semantic_allocation": semantic_allocation_report["summary"],
        },
    )

    checkpoint(control_callback, "ass_write_start", {"subtitle_mode": plan.subtitle_mode})
    assert_no_target_text_pollution(translated_segments, dst_lang=dst_lang)
    report = qa_check(translated_segments, dst_lang=dst_lang)
    ass_path = output_dir / plan.ass_name
    if dual_axis_mode and plan.subtitle_mode in {"target_only", "bilingual_source_reference"}:
        zh_display_cues = build_zh_display_cues(
            translated_segments,
            style=effective_style,
            config=zh_axis_config,
        )
        source_cues = (
            source_reference_cues_from_segments(source_axis_segments, reference_lang=src_lang)
            if plan.subtitle_mode == "bilingual_source_reference"
            else []
        )
        if plan.subtitle_mode == "target_only":
            write_zh_ass_from_display_cues(zh_display_cues, ass_path, style=effective_style)
            alignment_debug = [
                {
                    "mode": "dual_axis_target_only",
                    "zh_cue_count": len(zh_display_cues),
                    "source_segment_count": len(source_axis_segments),
                }
            ]
        else:
            alignment_debug = write_dual_axis_ass(
                source_cues,
                zh_display_cues,
                ass_path,
                style=effective_style,
                reference_lang=src_lang,
            )
        display_cues = [*zh_display_cues, *source_cues]
    elif plan.subtitle_mode == "target_only":
        write_zh_ass(translated_segments, ass_path, style=effective_style)
        display_cues, alignment_debug = prepare_bilingual_ass_segments(
            translated_segments,
            effective_style,
            reference_lang=src_lang,
        )
        for cue in display_cues:
            cue.en_text = ""
    elif plan.subtitle_mode == "source_review":
        alignment_debug = write_source_ass(
            translated_segments,
            ass_path,
            style=effective_style,
            reference_lang=src_lang,
        )
        display_cues, _ = prepare_bilingual_ass_segments(
            translated_segments,
            effective_style,
            reference_lang=src_lang,
        )
        for cue in display_cues:
            cue.zh_text = ""
        skip_burn = True
    else:
        display_cues, alignment_debug = prepare_bilingual_ass_segments(
            translated_segments,
            effective_style,
            reference_lang=src_lang,
        )
        if short_complete_sentence_display_grouping:
            display_cues, display_group_report = group_short_complete_sentence_cues(
                display_cues,
                zh_max_chars=max(1, int(effective_style.zh_max_chars_per_line or 28) * max(1, int(effective_style.zh_max_lines or 2))),
            )
            alignment_debug.append(
                {
                    "mode": "display_short_sentence_grouping",
                    **display_group_report["summary"],
                }
            )
        display_cues, orphan_tail_display_report = merge_orphan_tail_display_cues(
            display_cues,
            max_gap=SubtitleRules().strong_pause_split_threshold,
            en_max_chars=max(42, int(effective_style.en_max_single_line_chars or 42) * 2 + 8),
        )
        if orphan_tail_display_report["summary"]["group_count"]:
            alignment_debug.append(
                {
                    "mode": "display_orphan_tail_merge",
                    **orphan_tail_display_report["summary"],
                }
            )
        write_bilingual_ass_from_display_cues(
            display_cues,
            ass_path,
            style=effective_style,
            reference_lang=src_lang,
        )
    if plan.ass_name != plan.legacy_ass_name:
        legacy_ass_path = output_dir / plan.legacy_ass_name
        legacy_ass_path.write_text(ass_path.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    display_report = qa_display_cues(
        display_cues,
        dst_lang=dst_lang,
        zh_max_line_chars=effective_style.zh_max_chars_per_line,
        en_max_line_chars=effective_style.en_max_single_line_chars,
        zh_wrap_trigger_chars=effective_style.zh_wrap_trigger_chars,
        zh_max_lines=effective_style.zh_max_lines,
        require_bound_zh=not dual_axis_mode,
    )
    final_ass_report = qa_final_ass_file(
        ass_path,
        dst_lang=dst_lang,
    )
    ass_entity_audit = audit_ass_entities(ass_path, project_dir=output_dir)
    ass_entity_report = qa_ass_entity_audit(ass_entity_audit)
    write_stage_json(
        output_dir / "08b_ass_entity_audit.json",
        ass_entity_audit,
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    glossary_json_path = get_glossary_json_path(output_dir)
    glossary_report = qa_glossary_consistency(
        translated_segments,
        glossary_json_path,
    )
    difficult_span_report = qa_difficult_spans(difficult_spans_final)
    quality_metrics = build_quality_metrics(
        translated_segments,
        display_cues,
        dst_lang=dst_lang,
        glossary_path=glossary_json_path,
        zh_max_line_chars=effective_style.zh_max_chars_per_line,
        en_max_line_chars=effective_style.en_max_single_line_chars,
        zh_wrap_trigger_chars=effective_style.zh_wrap_trigger_chars,
        zh_max_lines=effective_style.zh_max_lines,
        require_bound_zh=not dual_axis_mode,
        english_residue_preserve_threshold=english_residue_preserve_threshold,
        english_residue_review_threshold=english_residue_review_threshold,
    )
    segmentation_metrics = build_segmentation_qa_metrics(
        translated_segments,
        display_cues,
        allocation_report=semantic_allocation_report,
        display_group_report=display_group_report,
        orphan_tail_display_report=orphan_tail_display_report,
        source_repair_report=source_repair_report,
    )
    english_residue_report = build_english_residue_report(
        translated_segments,
        dst_lang=dst_lang,
        glossary_path=glossary_json_path,
        project_dir=output_dir,
        preserve_threshold=english_residue_preserve_threshold,
        review_threshold=english_residue_review_threshold,
    )
    quality_metrics["segmentation"] = segmentation_metrics.get("segmentation", {})
    quality_metrics["semantic_allocation"] = segmentation_metrics.get("allocation", {})
    quality_metrics["source_repair"] = segmentation_metrics.get("source_repair", {})
    quality_metrics["display_grouping"] = segmentation_metrics.get("display_grouping", {})
    quality_metrics["english_residue"] = english_residue_report.get("summary", {})
    quality_metrics["summary"]["segmentation_blocking_issue_count"] = segmentation_metrics["summary"]["blocking_issue_count"]
    quality_metrics["summary"]["semantic_allocation_review_count"] = segmentation_metrics["allocation"]["review_count"]
    quality_metrics["summary"]["display_short_sentence_group_count"] = segmentation_metrics["display_grouping"]["group_count"]
    quality_metrics["summary"]["english_residue_blocking_count"] = english_residue_report["summary"]["english_residue_blocking_count"]
    quality_metrics["summary"]["english_residue_review_count"] = english_residue_report["summary"]["english_residue_review_count"]
    quality_metrics["summary"]["english_residue_preserved_count"] = english_residue_report["summary"]["english_residue_preserved_count"]
    report.errors.extend(display_report.errors)
    report.errors.extend(final_ass_report.errors)
    report.errors.extend(glossary_report.errors)
    report.errors.extend(difficult_span_report.errors)
    report.errors.extend(ass_entity_report.errors)
    report.warnings.extend(ass_entity_report.warnings)
    report.warnings.extend(display_report.warnings)
    report.warnings.extend(final_ass_report.warnings)
    report.warnings.extend(glossary_report.warnings)
    report.warnings.extend(difficult_span_report.warnings)
    write_stage_json(
        output_dir / "07_qa_report.json",
        build_blocker_report(report.errors, quality_metrics["summary"], report.warnings),
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    write_stage_json(
        output_dir / "07a_quality_metrics.json",
        quality_metrics,
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    write_stage_json(
        output_dir / "07j_segmentation_qa_metrics.json",
        segmentation_metrics,
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    write_stage_json(
        output_dir / "07k_english_residue_report.json",
        english_residue_report,
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    write_tsv(
        output_dir / "07k_english_residue_review.tsv",
        ["segment_id", "candidate", "category", "preserve_score", "decision", "reason_codes", "suggested_action", "source_text", "reference_text", "target_text"],
        [
            {
                **item,
                "reason_codes": ", ".join(item.get("reason_codes") or []),
            }
            for item in english_residue_report.get("items") or []
        ],
    )
    write_tsv(
        output_dir / "07d_editor_review.tsv",
        ["segment_id", "severity", "risk_type", "risk_score", "source_text", "reference_text", "target_text", "note"],
        build_editor_review_rows(translated_segments, difficult_spans_final, display_rewrite_report, quality_metrics),
    )
    write_tsv(
        output_dir / "07e_glossary_qa.tsv",
        ["issue_type", "segment_id", "canonical", "bad_alias"],
        build_glossary_qa_rows(quality_metrics),
    )
    write_tsv(
        output_dir / "07f_display_qa.tsv",
        [
            "cue_index",
            "source_segment_id",
            "start",
            "end",
            "duration",
            "zh_cps",
            "zh_line_count",
            "zh_max_line_length",
            "issues",
            "zh_text",
            "rendered_zh",
            "en_text",
            "rewrite_action",
        ],
        build_display_qa_rows(
            display_cues,
            zh_max_line_chars=effective_style.zh_max_chars_per_line,
            zh_wrap_trigger_chars=effective_style.zh_wrap_trigger_chars,
            zh_max_lines=effective_style.zh_max_lines,
        ),
    )
    write_tsv(
        output_dir / "07h_entity_qa.tsv",
        ["issue_type", "segment_id", "entity_type", "layer", "style", "start", "end", "text", "canonical_en", "canonical_native", "line_text"],
        build_entity_qa_rows(ass_entity_audit, quality_metrics),
    )
    write_stage_json(
        output_dir / "07i_entity_metrics.json",
        build_entity_metrics(entity_report, ass_entity_audit, quality_metrics),
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    write_stage_json(
        output_dir / "07g_final_ass_qa.json",
        build_blocker_report(final_ass_report.errors, {}, final_ass_report.warnings),
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    write_stage_json(
        output_dir / plan.alignment_debug_name,
        build_stage_metadata(
            input_path=input_path,
            segment_count=len(translated_segments),
            summary={"entry_count": len(alignment_debug)},
        ) | {"entries": alignment_debug},
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    emit(
        callback,
        "qa_complete",
        {
            "path": str(output_dir / "07_qa_report.json"),
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "metrics_summary": quality_metrics["summary"],
        },
    )
    qa_summary = {
        "pass": not report.has_blocking_errors,
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "metrics_summary": quality_metrics["summary"],
    }
    if report.has_blocking_errors and not skip_burn:
        emit(
            callback,
            "qa_blocking_bypassed",
            {
                "path": str(output_dir / "07_qa_report.json"),
                "errors": len(report.errors),
                "warnings": len(report.warnings),
                "note": "QA reported blocking issues, but output generation will continue.",
            },
        )

    if skip_burn:
        checkpoint(control_callback, "complete", {"skip_burn": True})
        manifest = {
            "input_video": str(input_path),
            "output_root": str(output_root),
            "output_dir": str(output_dir),
            "qa": qa_summary,
            "burn_plan": {"skipped": True, "reason": "skip_burn"},
            "files": [
                "00_media_probe.json",
                "00a_merged_with_external_audio.mp4" if audio_override_path else None,
                "01_audio_16k.wav",
                "01b_audio_asr_enhanced.wav" if (output_dir / "01b_audio_asr_enhanced.wav").exists() else None,
                "02_asr_raw_segments.json",
                "02b_asr_source_repair_candidates.json",
                "02_terms_from_asr.json" if (output_dir / "02_terms_from_asr.json").exists() else None,
                "03_timed_source_segments.json",
                "03b_source_repaired_segments.json",
                "03b_source_repair_report.json",
                "03_glossary_resolved.json" if (output_dir / "03_glossary_resolved.json").exists() else None,
                "03_glossary_resolved_prompt.txt" if (output_dir / "03_glossary_resolved_prompt.txt").exists() else None,
                plan.source_srt_name,
                "04a_source_spans.json",
                "04b_zh_reading_groups.json" if (output_dir / "04b_zh_reading_groups.json").exists() else None,
                "05a_span_translated_segments.json",
                "05a_span_translation_report.json",
                "05a_semantic_allocated_segments.json",
                "05a_semantic_allocation_report.json",
                "05b_terminology_actions.json",
                "05_translated_segments.json",
                plan.translated_srt_name,
                "06b_display_rewritten_segments.json",
                "06c_display_rewrite_report.json",
                "06e_entity_decisions.json",
                "06f_entity_review.tsv",
                "06g_entity_normalized_segments.json",
                "07_qa_report.json",
                "07a_quality_metrics.json",
                "07b_difficult_spans_initial.json",
                "07b_difficult_spans.json",
                "07c_span_repair_report.json",
                "07d_editor_review.tsv",
                "07e_glossary_qa.tsv",
                "07f_display_qa.tsv",
                "07g_final_ass_qa.json",
                "07h_entity_qa.tsv",
                "07i_entity_metrics.json",
                "07j_segmentation_qa_metrics.json",
                "07k_english_residue_report.json",
                "07k_english_residue_review.tsv",
                "08b_ass_entity_audit.json",
                "00_entity_decisions.json" if (output_dir / "00_entity_decisions.json").exists() else None,
                plan.ass_name,
                plan.legacy_ass_name if plan.ass_name != plan.legacy_ass_name else None,
                plan.alignment_debug_name,
            ],
        }
        manifest["subtitle_mode"] = plan.subtitle_mode
        manifest["subtitle_output"] = {
            "mode": plan.subtitle_mode,
            "ass_path": str(ass_path),
            "ass_name": plan.ass_name,
            "source_srt_name": plan.source_srt_name,
            "translated_srt_name": plan.translated_srt_name,
        }
        manifest["ass_path"] = str(ass_path)
        manifest["output_video"] = ""
        manifest["files"] = [item for item in manifest["files"] if item]
        write_json(output_dir / plan.manifest_name, manifest)
        if plan.manifest_name != "10_manifest_bilingual.json":
            write_json(output_dir / "10_manifest_bilingual.json", manifest)
        emit(callback, "complete", manifest)
        return manifest

    safe_ass_path = create_safe_ass_copy(ass_path)
    output_video_name = plan.output_video_name
    output_video_path = output_dir / output_video_name
    burn_duration = (
        safe_duration_seconds(preview_seconds)
        if preview_seconds is not None
        else probe_duration
    )
    emit(
        callback,
        "burn_start",
        {
            "path": str(output_video_path),
            "duration_seconds": burn_duration,
            "encoder": VIDEO_ENCODER,
            "quality": int(VIDEO_QUALITY),
            "preset": VIDEO_PRESET,
            "decoder": "pending",
            "hwaccel": "pending",
        },
    )
    checkpoint(control_callback, "burn_start", {"path": str(output_video_path)})
    burn_plan = burn_subtitle(
        processing_video_path,
        safe_ass_path,
        output_video_path,
        preview_seconds=preview_seconds,
        progress_callback=callback,
        total_duration=burn_duration,
    )
    burn_size_bytes = output_video_path.stat().st_size if output_video_path.exists() else 0
    burn_plan = {
        **burn_plan,
        "skipped": False,
        "output_path": str(output_video_path),
        "size_bytes": burn_size_bytes,
        "duration_seconds": burn_duration,
    }
    emit(
        callback,
        "burn_complete",
        {
            "path": str(output_video_path),
            "size_bytes": burn_size_bytes,
            "duration_seconds": burn_duration,
        },
    )

    manifest = {
        "input_video": str(input_path),
        "output_root": str(output_root),
        "output_dir": str(output_dir),
        "qa": qa_summary,
        "burn_plan": burn_plan,
        "files": [
            "00_media_probe.json",
            "00a_merged_with_external_audio.mp4" if audio_override_path else None,
            "01_audio_16k.wav",
            "01b_audio_asr_enhanced.wav" if (output_dir / "01b_audio_asr_enhanced.wav").exists() else None,
            "02_asr_raw_segments.json",
            "02b_asr_source_repair_candidates.json",
            "03_timed_source_segments.json",
            "03b_source_repaired_segments.json",
            "03b_source_repair_report.json",
            plan.source_srt_name,
            "04a_source_spans.json",
            "04b_zh_reading_groups.json" if (output_dir / "04b_zh_reading_groups.json").exists() else None,
            "05a_span_translated_segments.json",
            "05a_span_translation_report.json",
            "05a_semantic_allocated_segments.json",
            "05a_semantic_allocation_report.json",
            "05b_terminology_actions.json",
            "05_translated_segments.json",
            plan.translated_srt_name,
            "06b_display_rewritten_segments.json",
            "06c_display_rewrite_report.json",
            "06e_entity_decisions.json",
            "06f_entity_review.tsv",
            "06g_entity_normalized_segments.json",
            "07_qa_report.json",
            "07a_quality_metrics.json",
            "07b_difficult_spans_initial.json",
            "07b_difficult_spans.json",
            "07c_span_repair_report.json",
            "07d_editor_review.tsv",
            "07e_glossary_qa.tsv",
            "07f_display_qa.tsv",
            "07g_final_ass_qa.json",
            "07h_entity_qa.tsv",
            "07i_entity_metrics.json",
            "07j_segmentation_qa_metrics.json",
            "07k_english_residue_report.json",
            "07k_english_residue_review.tsv",
            "08b_ass_entity_audit.json",
            plan.ass_name,
            plan.legacy_ass_name if plan.ass_name != plan.legacy_ass_name else None,
            plan.alignment_debug_name,
            "08_bilingual_safe.ass",
            "00_glossary_auto.json" if (output_dir / "00_glossary_auto.json").exists() else None,
            "00_glossary_prompt.txt" if (output_dir / "00_glossary_prompt.txt").exists() else None,
            "00_glossary_review.tsv" if (output_dir / "00_glossary_review.tsv").exists() else None,
            "00_entity_decisions.json" if (output_dir / "00_entity_decisions.json").exists() else None,
            "02_terms_from_asr.json" if (output_dir / "02_terms_from_asr.json").exists() else None,
            "03_glossary_resolved.json" if (output_dir / "03_glossary_resolved.json").exists() else None,
            "03_glossary_resolved_prompt.txt" if (output_dir / "03_glossary_resolved_prompt.txt").exists() else None,
            output_video_name,
        ],
    }
    manifest["subtitle_mode"] = plan.subtitle_mode
    manifest["subtitle_output"] = {
        "mode": plan.subtitle_mode,
        "ass_path": str(ass_path),
        "ass_name": plan.ass_name,
        "source_srt_name": plan.source_srt_name,
        "translated_srt_name": plan.translated_srt_name,
    }
    manifest["ass_path"] = str(ass_path)
    manifest["output_video"] = str(output_video_path)
    manifest["files"] = [item for item in manifest["files"] if item]
    write_json(output_dir / plan.manifest_name, manifest)
    if plan.manifest_name != "10_manifest_bilingual.json":
        write_json(output_dir / "10_manifest_bilingual.json", manifest)
    emit(callback, "complete", manifest)
    return manifest
