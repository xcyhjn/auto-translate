from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Callable
import tempfile

from .asr import transcribe_audio
from .media import extract_audio, merge_video_with_audio, probe_media, run_ffmpeg_command
from .models import BilingualSubtitleStyle, Segment
from .qa import qa_check
from .segment_io import load_segments, save_segments
from .subtitle_io import write_bilingual_ass, write_srt
from .timing import refine_timing
from .translate import translate_segments


StageCallback = Callable[[str, dict], None]

VIDEO_ENCODER = "h264_nvenc"
VIDEO_ENCODER_FALLBACK = "libx264"


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_subtitle_filter_path(subtitle_path: Path) -> str:
    resolved = subtitle_path.resolve().as_posix()
    resolved = resolved.replace("\\", "/")
    resolved = resolved.replace(":", "\\:")
    resolved = resolved.replace(",", "\\,")
    return resolved


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
    subtitle_filter_path = build_subtitle_filter_path(subtitle_path)
    subtitle_filter = f"ass='{subtitle_filter_path}'"
    args = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
    ]
    if preview_seconds is not None:
        args.extend(["-t", str(preview_seconds)])
    args.extend(
        [
            "-vf",
            subtitle_filter,
            "-c:v",
            VIDEO_ENCODER,
            "-preset",
            "p5",
            "-cq",
            "25",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(output_path),
        ]
    )
    def emit_progress(progress_payload: dict) -> None:
        if progress_callback is None:
            return
        payload = dict(progress_payload)
        if total_duration:
            processed_seconds = float(payload.get("out_time_seconds", 0.0))
            progress_ratio = max(0.0, min(1.0, processed_seconds / total_duration))
            payload["duration_seconds"] = total_duration
            payload["progress"] = round(progress_ratio * 100, 2)
            payload["remaining_seconds"] = max(0.0, total_duration - processed_seconds)
            size_bytes = int(payload.get("size_bytes", 0) or 0)
            if progress_ratio > 0.02 and size_bytes > 0:
                payload["estimated_final_size"] = int(size_bytes / progress_ratio)
        emit(progress_callback, "burn_progress", payload)

    try:
        run_ffmpeg_command(args, progress_callback=emit_progress if progress_callback else None)
    except RuntimeError:
        if output_path.exists():
            output_path.unlink()
        fallback_args = list(args)
        encoder_index = fallback_args.index("-c:v") + 1
        fallback_args[encoder_index] = VIDEO_ENCODER_FALLBACK
        preset_index = fallback_args.index("-preset") + 1
        fallback_args[preset_index] = "medium"
        cq_index = fallback_args.index("-cq")
        fallback_args[cq_index : cq_index + 2] = ["-crf", "25"]
        run_ffmpeg_command(fallback_args, progress_callback=emit_progress if progress_callback else None)


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


def emit(callback: StageCallback | None, stage: str, payload: dict) -> None:
    if callback:
        callback(stage, payload)


def seconds_to_virtual_chunks(processed_seconds: float, total_seconds: float, chunk_span: int = 30) -> tuple[int, int]:
    if total_seconds <= 0:
        return (0, 0)
    total_chunks = max(1, int((total_seconds + chunk_span - 1) // chunk_span))
    current_chunk = max(0, min(total_chunks, int(processed_seconds // chunk_span) + (1 if processed_seconds > 0 else 0)))
    return current_chunk, total_chunks


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
    translation_model: str = "gpt-5.4-mini",
    translation_chunk_size: int = 40,
    translation_retries: int = 2,
    openai_base_url: str | None = None,
    audio_override_path: str | Path | None = None,
    load_existing_segments: bool = False,
    preview_seconds: int | None = None,
    bilingual_style: BilingualSubtitleStyle | None = None,
    callback: StageCallback | None = None,
) -> dict:
    input_path = Path(input_path)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = resolve_output_dir(input_path, output_root)
    translated_json_path = output_dir / "05_translated_segments.json"
    timed_json_path = output_dir / "03_timed_source_segments.json"
    processing_video_path = input_path

    emit(
        callback,
        "init",
        {
            "input": str(input_path),
            "output_dir": str(output_dir),
            "audio_override_path": str(audio_override_path) if audio_override_path else None,
        },
    )

    input_probe = probe_media(input_path)
    if audio_override_path:
        merged_video_path = output_dir / "00a_merged_with_external_audio.mp4"
        emit(
            callback,
            "merge_audio_start",
            {
                "video_path": str(input_path),
                "audio_path": str(audio_override_path),
                "merged_path": str(merged_video_path),
                "duration_seconds": input_probe.duration,
            },
        )

        def on_merge_progress(progress_payload: dict) -> None:
            payload = dict(progress_payload)
            if input_probe.duration:
                processed_seconds = float(payload.get("out_time_seconds", 0.0))
                payload["duration_seconds"] = input_probe.duration
                payload["progress"] = round(max(0.0, min(1.0, processed_seconds / input_probe.duration)) * 100, 2)
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
    write_json(output_dir / "00_media_probe.json", asdict(probe))
    emit(
        callback,
        "probe_media",
        {
            "path": str(output_dir / "00_media_probe.json"),
            "duration_seconds": probe.duration,
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

    if load_existing_segments and translated_json_path.exists():
        translated_segments = load_segments(translated_json_path)
        emit(
            callback,
            "load_existing_segments",
            {
                "path": str(translated_json_path),
                "count": len(translated_segments),
                "duration_seconds": probe.duration,
            },
        )
    else:
        if load_existing_segments and timed_json_path.exists():
            timed_segments = load_segments(timed_json_path)
            emit(
                callback,
                "timing_complete",
                {
                    "path": str(timed_json_path),
                    "count": len(timed_segments),
                    "source_count": len(timed_segments),
                    "reused": True,
                },
            )
        else:
            def on_extract_progress(progress_payload: dict) -> None:
                payload = dict(progress_payload)
                if probe.duration:
                    processed_seconds = float(payload.get("out_time_seconds", 0.0))
                    payload["duration_seconds"] = probe.duration
                    payload["progress"] = round(max(0.0, min(1.0, processed_seconds / probe.duration)) * 100, 2)
                emit(callback, "extract_audio_progress", payload)

            emit(
                callback,
                "extract_audio_start",
                {
                    "input_path": str(processing_video_path),
                    "duration_seconds": probe.duration,
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
                    "duration_seconds": probe.duration,
                },
            )

            emit(
                callback,
                "asr_start",
                {
                    "audio_path": str(audio_path),
                    "duration_seconds": probe.duration,
                },
            )
            raw_segments = transcribe_audio(
                audio_path,
                model_name=model,
                language=src_lang,
                device=device,
                compute_type=compute_type,
                beam_size=beam_size,
                vad_filter=True,
                progress_callback=lambda progress: emit(
                    callback,
                    "asr_progress",
                    {
                        **progress,
                        "duration_seconds": probe.duration,
                        "virtual_chunk_current": seconds_to_virtual_chunks(
                            float(progress.get("processed_seconds", 0.0)),
                            float(probe.duration or 0.0),
                        )[0],
                        "virtual_chunk_total": seconds_to_virtual_chunks(
                            float(progress.get("processed_seconds", 0.0)),
                            float(probe.duration or 0.0),
                        )[1],
                    },
                ),
            )
            save_segments(raw_segments, output_dir / "02_asr_raw_segments.json")
            emit(
                callback,
                "asr_complete",
                {
                    "path": str(output_dir / "02_asr_raw_segments.json"),
                    "count": len(raw_segments),
                    "duration_seconds": probe.duration,
                },
            )

            emit(
                callback,
                "timing_start",
                {
                    "segment_count": len(raw_segments),
                },
            )
            timed_segments = refine_timing(raw_segments)
            save_segments(timed_segments, timed_json_path)
            write_srt(timed_segments, output_dir / "04_source_en.srt")
            emit(
                callback,
                "timing_complete",
                {
                    "path": str(timed_json_path),
                    "count": len(timed_segments),
                    "source_count": len(raw_segments),
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
        translated_segments = translate_segments(
            timed_segments,
            src_lang=src_lang,
            dst_lang=dst_lang,
            enabled=True,
            provider="openai",
            model=translation_model,
            chunk_size=translation_chunk_size,
            max_retries=translation_retries,
            openai_base_url=openai_base_url,
            progress_callback=lambda stage, progress: emit(callback, stage, progress),
        )
        save_segments(translated_segments, translated_json_path)
        write_srt(translated_segments, output_dir / "06_translated_zh.srt")
        emit(
            callback,
            "translation_complete",
            {
                "path": str(translated_json_path),
                "count": len(translated_segments),
            },
        )

    report = qa_check(translated_segments)
    write_json(
        output_dir / "07_qa_report.json",
        {"errors": report.errors, "warnings": report.warnings},
    )
    emit(
        callback,
        "qa_complete",
        {
            "path": str(output_dir / "07_qa_report.json"),
            "errors": len(report.errors),
            "warnings": len(report.warnings),
        },
    )
    if report.has_blocking_errors:
        raise RuntimeError("QA failed. See 07_qa_report.json")

    ass_path = output_dir / "08_bilingual_zh_en.ass"
    write_bilingual_ass(translated_segments, ass_path, style=bilingual_style)
    safe_ass_path = create_safe_ass_copy(ass_path)
    output_video_name = (
        f"09_burned_bilingual_preview_{preview_seconds}s.mp4"
        if preview_seconds is not None
        else "09_burned_bilingual_video.mp4"
    )
    output_video_path = output_dir / output_video_name
    burn_duration = float(preview_seconds) if preview_seconds is not None else probe.duration
    emit(
        callback,
        "burn_start",
        {
            "path": str(output_video_path),
            "duration_seconds": burn_duration,
            "encoder": VIDEO_ENCODER,
            "quality": 25,
            "preset": "p5",
        },
    )
    burn_subtitle(
        processing_video_path,
        safe_ass_path,
        output_video_path,
        preview_seconds=preview_seconds,
        progress_callback=callback,
        total_duration=burn_duration,
    )
    emit(
        callback,
        "burn_complete",
        {
            "path": str(output_video_path),
            "size_bytes": output_video_path.stat().st_size if output_video_path.exists() else 0,
            "duration_seconds": burn_duration,
        },
    )

    manifest = {
        "input_video": str(input_path),
        "output_root": str(output_root),
        "output_dir": str(output_dir),
        "files": [
            "00_media_probe.json",
            "00a_merged_with_external_audio.mp4" if audio_override_path else None,
            "01_audio_16k.wav",
            "02_asr_raw_segments.json",
            "03_timed_source_segments.json",
            "04_source_en.srt",
            "05_translated_segments.json",
            "06_translated_zh.srt",
            "07_qa_report.json",
            "08_bilingual_zh_en.ass",
            "08_bilingual_safe.ass",
            output_video_name,
        ],
    }
    manifest["files"] = [item for item in manifest["files"] if item]
    write_json(output_dir / "10_manifest_bilingual.json", manifest)
    emit(callback, "complete", manifest)
    return manifest
