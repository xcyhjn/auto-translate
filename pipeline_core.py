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
from .difficult_spans import detect_difficult_spans
from .display_rewrite import rewrite_display_segments
from .glossary import (
    apply_glossary_alias_corrections,
    ensure_project_glossary,
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
from .models import BilingualSubtitleStyle, Segment
from .qa import build_quality_metrics, qa_check, qa_difficult_spans, qa_display_cues, qa_final_ass_file, qa_glossary_consistency
from .qa_outputs import (
    build_blocker_report,
    build_display_qa_rows,
    build_editor_review_rows,
    build_glossary_qa_rows,
    write_tsv,
)
from .segment_io import load_segments, save_segments, save_segments_payload
from .source_repair import repair_source_segments
from .source_spans import detect_source_spans
from .span_repair import repair_difficult_spans
from .span_translate import translate_source_spans
from .subtitle_io import prepare_bilingual_ass_segments, write_bilingual_ass, write_srt
from .terminology import apply_terminology_short_circuit
from .text_quality import find_text_pollution, format_pollution_issues
from .timing import refine_timing
from .translate import load_glossary, translate_segments
from .style_rules import load_style_prompt_text


StageCallback = Callable[[str, dict], None]

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
    span_repair_max_spans: int = 12,
    enable_ai_display_rewrite: bool = False,
    display_rewrite_max_ai_segments: int = 12,
    bilingual_style: BilingualSubtitleStyle | None = None,
    callback: StageCallback | None = None,
) -> dict:
    input_path = Path(input_path)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = resolve_output_dir(input_path, output_root)
    translated_json_path = output_dir / "05_translated_segments.json"
    timed_json_path = output_dir / "03_timed_source_segments.json"
    style_prompt_path = output_dir / "06d_style_rewrite_prompt.txt"
    learned_style_prompt = load_style_prompt_text(style_prompt_path)
    translation_prompt = str(translation_prompt or "").strip()
    style_prompt_for_translation = "\n\n".join(
        item for item in [translation_prompt, learned_style_prompt] if item.strip()
    )
    processing_video_path = input_path
    auto_glossary_path = ensure_project_glossary(output_dir)
    effective_style = bilingual_style if bilingual_style is not None else BilingualSubtitleStyle()

    emit(
        callback,
        "init",
        {
            "input": str(input_path),
            "output_dir": str(output_dir),
            "audio_override_path": str(audio_override_path) if audio_override_path else None,
            "glossary_path": str(auto_glossary_path) if auto_glossary_path else "",
        },
    )

    input_probe = probe_media(input_path)
    input_duration = safe_duration_seconds(input_probe.duration)
    if audio_override_path:
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

    if load_existing_segments and not force_retranslate_existing_segments and translated_json_path.exists():
        translated_segments = load_segments(translated_json_path)
        source_repair_report = repair_source_segments(translated_segments, get_glossary_json_path(output_dir))
        save_segments_payload(
            translated_segments,
            output_dir / "03b_source_repaired_segments.json",
            input_file=str(input_path),
            summary=source_repair_report["summary"],
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
        if source_repair_report["summary"]["replacement_count"]:
            save_segments(translated_segments, translated_json_path)
            write_srt(translated_segments, output_dir / "04_source_en.srt")
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
                "source_spans": source_spans["summary"],
            },
        )
    else:
        if (load_existing_segments or force_retranslate_existing_segments) and timed_json_path.exists():
            timed_segments = load_segments(timed_json_path)
            source_repair_report = repair_source_segments(timed_segments, get_glossary_json_path(output_dir))
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
                write_srt(timed_segments, output_dir / "04_source_en.srt")
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
            emit(
                callback,
                "asr_complete",
                {
                    "path": str(output_dir / "02_asr_raw_segments.json"),
                    "count": len(raw_segments),
                    "duration_seconds": probe_duration,
                    "terms_path": str(asr_terms_path),
                    "glossary_path": str(auto_glossary_path) if auto_glossary_path else "",
                },
            )

            emit(
                callback,
                "timing_start",
                {
                    "segment_count": len(raw_segments),
                },
            )
            timed_segments = refine_timing(raw_segments, style=effective_style)
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
            write_srt(timed_segments, output_dir / "04_source_en.srt")
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
        glossary_json_path = get_glossary_json_path(output_dir)
        locked_translation_ids, terminology_report = apply_terminology_short_circuit(
            timed_segments,
            glossary_json_path,
        )
        write_stage_json(
            output_dir / "05b_terminology_actions.json",
            terminology_report,
            input_path=input_path,
            segment_count=len(timed_segments),
        )
        emit(
            callback,
            "terminology_short_circuit_complete",
            {
                "path": str(output_dir / "05b_terminology_actions.json"),
                **terminology_report["summary"],
            },
        )
        source_spans_path = output_dir / "04a_source_spans.json"
        source_spans_for_translation = (
            json.loads(source_spans_path.read_text(encoding="utf-8"))
            if source_spans_path.exists()
            else detect_source_spans(timed_segments)
        )
        span_translated_ids, span_translation_report = translate_source_spans(
            timed_segments,
            source_spans_for_translation,
            src_lang=src_lang,
            dst_lang=dst_lang,
            glossary_text=load_glossary(str(auto_glossary_path)) if auto_glossary_path else "",
            model=translation_model,
            style_prompt_text=style_prompt_for_translation,
            base_url=openai_base_url,
            max_retries=translation_retries,
            locked_ids=locked_translation_ids,
            progress_callback=lambda stage, progress: emit(callback, stage, progress),
        )
        locked_translation_ids.update(span_translated_ids)
        save_segments_payload(
            timed_segments,
            output_dir / "05a_span_translated_segments.json",
            input_file=str(input_path),
            summary=span_translation_report["summary"],
        )
        write_stage_json(
            output_dir / "05a_span_translation_report.json",
            span_translation_report,
            input_path=input_path,
            segment_count=len(timed_segments),
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
            timed_segments,
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
            progress_callback=lambda stage, progress: emit(callback, stage, progress),
        )
        alias_stats = apply_glossary_alias_corrections(translated_segments, get_glossary_json_path(output_dir))
        save_segments_payload(
            translated_segments,
            translated_json_path,
            input_file=str(input_path),
            summary={"stage": "translated_segments"},
        )
        write_srt(translated_segments, output_dir / "06_translated_zh.srt")
        emit(
            callback,
            "translation_complete",
            {
                "path": str(translated_json_path),
                "count": len(translated_segments),
                "alias_corrections": alias_stats,
            },
        )

    alias_stats = apply_glossary_alias_corrections(translated_segments, get_glossary_json_path(output_dir))
    if alias_stats["total_replacements"]:
        save_segments_payload(
            translated_segments,
            translated_json_path,
            input_file=str(input_path),
            summary={"stage": "translated_segments"},
        )
        write_srt(translated_segments, output_dir / "06_translated_zh.srt")
        emit(
            callback,
            "glossary_alias_corrections",
            {
                "path": str(translated_json_path),
                **alias_stats,
            },
        )

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
    if display_rewrite_report["summary"]["changed_count"]:
        save_segments_payload(
            translated_segments,
            translated_json_path,
            input_file=str(input_path),
            summary={"stage": "translated_segments"},
        )
        write_srt(translated_segments, output_dir / "06_translated_zh.srt")
    emit(
        callback,
        "display_rewrite_complete",
        {
            "segments_path": str(output_dir / "06b_display_rewritten_segments.json"),
            "report_path": str(output_dir / "06c_display_rewrite_report.json"),
            **display_rewrite_report["summary"],
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
    if repair_high_risk_spans and difficult_spans_initial["summary"]["needs_ai_repair_count"] > 0:
        span_repair_report = repair_difficult_spans(
            translated_segments,
            difficult_spans_initial,
            src_lang=src_lang,
            dst_lang=dst_lang,
            glossary_text=load_glossary(str(auto_glossary_path)) if auto_glossary_path else "",
            model=translation_model,
            style_prompt_text=style_prompt_for_translation,
            base_url=openai_base_url,
            max_retries=translation_retries,
            max_spans=span_repair_max_spans,
            progress_callback=lambda stage, progress: emit(callback, stage, progress),
        )
        span_repair_report["summary"]["enabled"] = True
        alias_stats = apply_glossary_alias_corrections(translated_segments, get_glossary_json_path(output_dir))
        if alias_stats["total_replacements"]:
            span_repair_report["summary"]["post_repair_alias_corrections"] = alias_stats
        save_segments_payload(
            translated_segments,
            translated_json_path,
            input_file=str(input_path),
            summary={"stage": "translated_segments"},
        )
        write_srt(translated_segments, output_dir / "06_translated_zh.srt")
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

    assert_no_target_text_pollution(translated_segments, dst_lang=dst_lang)
    report = qa_check(translated_segments, dst_lang=dst_lang)
    ass_path = output_dir / "08_bilingual_zh_en.ass"
    alignment_debug = write_bilingual_ass(translated_segments, ass_path, style=effective_style)
    display_cues, _ = prepare_bilingual_ass_segments(translated_segments, effective_style)
    display_report = qa_display_cues(
        display_cues,
        dst_lang=dst_lang,
        zh_max_line_chars=effective_style.zh_max_chars_per_line,
        en_max_line_chars=effective_style.en_max_single_line_chars,
        zh_wrap_trigger_chars=effective_style.zh_wrap_trigger_chars,
        zh_max_lines=effective_style.zh_max_lines,
    )
    final_ass_report = qa_final_ass_file(
        ass_path,
        dst_lang=dst_lang,
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
    )
    report.errors.extend(display_report.errors)
    report.errors.extend(final_ass_report.errors)
    report.errors.extend(glossary_report.errors)
    report.errors.extend(difficult_span_report.errors)
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
    write_tsv(
        output_dir / "07d_editor_review.tsv",
        ["segment_id", "severity", "risk_type", "risk_score", "source_text", "target_text", "note"],
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
    write_stage_json(
        output_dir / "07g_final_ass_qa.json",
        build_blocker_report(final_ass_report.errors, {}, final_ass_report.warnings),
        input_path=input_path,
        segment_count=len(translated_segments),
    )
    write_stage_json(
        output_dir / "08a_bilingual_alignment_debug.json",
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
                "02_terms_from_asr.json" if (output_dir / "02_terms_from_asr.json").exists() else None,
                "03_timed_source_segments.json",
                "03b_source_repaired_segments.json",
                "03b_source_repair_report.json",
                "03_glossary_resolved.json" if (output_dir / "03_glossary_resolved.json").exists() else None,
                "03_glossary_resolved_prompt.txt" if (output_dir / "03_glossary_resolved_prompt.txt").exists() else None,
                "04_source_en.srt",
                "04a_source_spans.json",
                "05a_span_translated_segments.json",
                "05a_span_translation_report.json",
                "05b_terminology_actions.json",
                "05_translated_segments.json",
                "06_translated_zh.srt",
                "06b_display_rewritten_segments.json",
                "06c_display_rewrite_report.json",
                "07_qa_report.json",
                "07a_quality_metrics.json",
                "07b_difficult_spans_initial.json",
                "07b_difficult_spans.json",
                "07c_span_repair_report.json",
                "07d_editor_review.tsv",
                "07e_glossary_qa.tsv",
                "07f_display_qa.tsv",
                "07g_final_ass_qa.json",
                "08_bilingual_zh_en.ass",
                "08a_bilingual_alignment_debug.json",
            ],
        }
        manifest["files"] = [item for item in manifest["files"] if item]
        write_json(output_dir / "10_manifest_bilingual.json", manifest)
        emit(callback, "complete", manifest)
        return manifest

    safe_ass_path = create_safe_ass_copy(ass_path)
    output_video_name = (
        f"09_burned_bilingual_preview_{preview_seconds}s.mp4"
        if preview_seconds is not None
        else "09_burned_bilingual_video.mp4"
    )
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
            "03_timed_source_segments.json",
            "03b_source_repaired_segments.json",
            "03b_source_repair_report.json",
            "04_source_en.srt",
            "04a_source_spans.json",
            "05a_span_translated_segments.json",
            "05a_span_translation_report.json",
            "05b_terminology_actions.json",
            "05_translated_segments.json",
            "06_translated_zh.srt",
            "06b_display_rewritten_segments.json",
            "06c_display_rewrite_report.json",
            "07_qa_report.json",
            "07a_quality_metrics.json",
            "07b_difficult_spans_initial.json",
            "07b_difficult_spans.json",
            "07c_span_repair_report.json",
            "07d_editor_review.tsv",
            "07e_glossary_qa.tsv",
            "07f_display_qa.tsv",
            "07g_final_ass_qa.json",
            "08_bilingual_zh_en.ass",
            "08a_bilingual_alignment_debug.json",
            "08_bilingual_safe.ass",
            "00_glossary_auto.json" if (output_dir / "00_glossary_auto.json").exists() else None,
            "00_glossary_prompt.txt" if (output_dir / "00_glossary_prompt.txt").exists() else None,
            "00_glossary_review.tsv" if (output_dir / "00_glossary_review.tsv").exists() else None,
            "02_terms_from_asr.json" if (output_dir / "02_terms_from_asr.json").exists() else None,
            "03_glossary_resolved.json" if (output_dir / "03_glossary_resolved.json").exists() else None,
            "03_glossary_resolved_prompt.txt" if (output_dir / "03_glossary_resolved_prompt.txt").exists() else None,
            output_video_name,
        ],
    }
    manifest["files"] = [item for item in manifest["files"] if item]
    write_json(output_dir / "10_manifest_bilingual.json", manifest)
    emit(callback, "complete", manifest)
    return manifest
