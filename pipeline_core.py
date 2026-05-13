from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Callable
import tempfile

from .asr import transcribe_audio
from .media import extract_audio, merge_video_with_audio, probe_media, run_command
from .models import BilingualSubtitleStyle, Segment
from .qa import qa_check
from .segment_io import load_segments, save_segments
from .subtitle_io import write_bilingual_ass, write_srt
from .timing import refine_timing
from .translate import translate_segments


StageCallback = Callable[[str, dict], None]


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
    args.extend(["-vf", subtitle_filter, "-c:a", "copy", str(output_path)])
    run_command(args)


def create_safe_ass_copy(subtitle_path: Path) -> Path:
    temp_dir = Path(tempfile.gettempdir()) / "autosub_zh_burn"
    temp_dir.mkdir(parents=True, exist_ok=True)
    safe_path = temp_dir / "08_bilingual_safe.ass"
    safe_path.write_text(subtitle_path.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    return safe_path


def resolve_output_dir(input_path: Path, output_root: Path) -> Path:
    stem = input_path.stem
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    if not slug:
        slug = f"video-{abs(hash(stem)) % 10_000_000}"
    output_dir = output_root / slug
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def emit(callback: StageCallback | None, stage: str, payload: dict) -> None:
    if callback:
        callback(stage, payload)


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

    emit(
        callback,
        "init",
        {
            "input": str(input_path),
            "output_dir": str(output_dir),
            "audio_override_path": str(audio_override_path) if audio_override_path else None,
        },
    )

    if load_existing_segments and translated_json_path.exists():
        translated_segments = load_segments(translated_json_path)
        emit(callback, "load_existing_segments", {"path": str(translated_json_path), "count": len(translated_segments)})
    else:
        processing_video_path = input_path
        if audio_override_path:
            merged_video_path = output_dir / "00a_merged_with_external_audio.mp4"
            merge_video_with_audio(input_path, audio_override_path, merged_video_path)
            processing_video_path = merged_video_path
            emit(
                callback,
                "merge_external_audio",
                {
                    "video_path": str(input_path),
                    "audio_path": str(audio_override_path),
                    "merged_path": str(merged_video_path),
                },
            )

        probe = probe_media(processing_video_path)
        write_json(output_dir / "00_media_probe.json", asdict(probe))
        emit(callback, "probe_media", {"path": str(output_dir / '00_media_probe.json')})

        audio_path = extract_audio(processing_video_path, work_dir=output_dir)
        renamed_audio_path = output_dir / "01_audio_16k.wav"
        if audio_path != renamed_audio_path:
            renamed_audio_path.write_bytes(audio_path.read_bytes())
            audio_path = renamed_audio_path
        emit(callback, "extract_audio", {"path": str(audio_path)})

        raw_segments = transcribe_audio(
            audio_path,
            model_name=model,
            language=src_lang,
            device=device,
            compute_type=compute_type,
            beam_size=beam_size,
            vad_filter=True,
        )
        save_segments(raw_segments, output_dir / "02_asr_raw_segments.json")
        emit(callback, "asr_raw", {"path": str(output_dir / '02_asr_raw_segments.json'), "count": len(raw_segments)})

        timed_segments = refine_timing(raw_segments)
        save_segments(timed_segments, output_dir / "03_timed_source_segments.json")
        write_srt(timed_segments, output_dir / "04_source_en.srt")
        emit(callback, "timed_source", {"path": str(output_dir / '03_timed_source_segments.json'), "count": len(timed_segments)})

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
        )
        save_segments(translated_segments, translated_json_path)
        write_srt(translated_segments, output_dir / "06_translated_zh.srt")
        emit(callback, "translated", {"path": str(translated_json_path), "count": len(translated_segments)})

    report = qa_check(translated_segments)
    write_json(
        output_dir / "07_qa_report.json",
        {"errors": report.errors, "warnings": report.warnings},
    )
    emit(callback, "qa", {"path": str(output_dir / '07_qa_report.json'), "errors": len(report.errors), "warnings": len(report.warnings)})
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
    burn_subtitle(
        input_path,
        safe_ass_path,
        output_video_path,
        preview_seconds=preview_seconds,
    )
    emit(callback, "burned_video", {"path": str(output_video_path)})

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
