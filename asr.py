from __future__ import annotations

import gc
import os
from pathlib import Path
import tempfile
from typing import Callable
import wave

from .models import Segment, Word
from .utils import normalize_text


CUDA_BIN_DIR = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin"
MAX_AUDIO_CHUNK_SECONDS = 8 * 60
CHUNK_OVERLAP_SECONDS = 1.0
GPU_FALLBACK_COMPUTE_TYPE = "int8_float16"
CPU_FALLBACK_COMPUTE_TYPE = "int8"
VALID_ASR_DEVICES = {"auto", "cpu", "cuda"}
VALID_ASR_COMPUTE_TYPES = {"default", "float16", "int8_float16", "int8"}
AsrProgressCallback = Callable[[dict], None]


def ensure_cuda_runtime_on_path() -> None:
    if os.path.isdir(CUDA_BIN_DIR):
        current_path = os.environ.get("PATH", "")
        if CUDA_BIN_DIR not in current_path.split(";"):
            os.environ["PATH"] = CUDA_BIN_DIR + ";" + current_path


def is_cuda_out_of_memory(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "cuda" in message and "out of memory" in message


def is_asr_backend_failure(exc: BaseException) -> bool:
    message = str(exc).lower()
    return is_cuda_out_of_memory(exc) or any(
        token in message
        for token in (
            "cublas",
            "cudnn",
            "cannot be loaded",
            "no kernel image",
            "cuda error",
            "unsupported compute type",
            "invalid compute type",
            "compute type",
        )
    )


def release_accelerator_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass


def append_unique_attempt(attempts: list[dict], attempt: dict) -> None:
    key = (
        str(attempt.get("device", "")).lower(),
        str(attempt.get("compute_type", "")).lower(),
        int(attempt.get("beam_size", 0) or 0),
    )
    for existing in attempts:
        existing_key = (
            str(existing.get("device", "")).lower(),
            str(existing.get("compute_type", "")).lower(),
            int(existing.get("beam_size", 0) or 0),
        )
        if existing_key == key:
            return
    attempts.append(attempt)


def normalize_asr_device(device: str) -> str:
    normalized = (device or "auto").strip().lower()
    if normalized not in VALID_ASR_DEVICES:
        raise ValueError(
            f"Unsupported ASR device: {device!r}. Expected one of: {sorted(VALID_ASR_DEVICES)}."
        )
    return normalized


def normalize_asr_compute_type(compute_type: str) -> str:
    normalized = (compute_type or "default").strip().lower()
    if normalized not in VALID_ASR_COMPUTE_TYPES:
        raise ValueError(
            f"Unsupported ASR compute_type: {compute_type!r}. Expected one of: {sorted(VALID_ASR_COMPUTE_TYPES)}."
        )
    return normalized


def build_asr_attempts(device: str, compute_type: str, beam_size: int) -> list[dict]:
    normalized_device = normalize_asr_device(device)
    normalized_compute = normalize_asr_compute_type(compute_type)
    attempts: list[dict] = []
    append_unique_attempt(
        attempts,
        {
            "device": device,
            "compute_type": compute_type,
            "beam_size": beam_size,
            "reason": "configured",
        },
    )
    if normalized_device == "cpu":
        append_unique_attempt(
            attempts,
            {
                "device": "cpu",
                "compute_type": CPU_FALLBACK_COMPUTE_TYPE,
                "beam_size": beam_size,
                "reason": "cpu_fallback",
            },
        )
        return attempts

    if normalized_compute not in {GPU_FALLBACK_COMPUTE_TYPE, "int8"}:
        append_unique_attempt(
            attempts,
            {
                "device": "cuda",
                "compute_type": GPU_FALLBACK_COMPUTE_TYPE,
                "beam_size": min(beam_size, 1),
                "reason": "gpu_fallback",
            },
        )
    append_unique_attempt(
        attempts,
        {
            "device": "cpu",
            "compute_type": CPU_FALLBACK_COMPUTE_TYPE,
            "beam_size": beam_size,
            "reason": "cpu_fallback",
        },
    )
    return attempts


def emit_asr_fallback(
    progress_callback: AsrProgressCallback | None,
    *,
    failed_attempt: dict,
    next_attempt: dict,
    error: BaseException,
) -> None:
    if not progress_callback:
        return
    progress_callback(
        {
            "event": "fallback",
            "segment_count": 0,
            "processed_seconds": 0.0,
            "failed_device": failed_attempt.get("device"),
            "failed_compute_type": failed_attempt.get("compute_type"),
            "failed_beam_size": failed_attempt.get("beam_size"),
            "device": next_attempt.get("device"),
            "compute_type": next_attempt.get("compute_type"),
            "beam_size": next_attempt.get("beam_size"),
            "reason": next_attempt.get("reason"),
            "message": (
                "GPU backend failed during ASR; retrying with a safer backend "
                f"({next_attempt.get('device')}/{next_attempt.get('compute_type')})."
            ),
            "raw_error": str(error),
        }
    )


def build_wave_chunk_plan(
    audio_path: str | Path,
    temp_dir: str | Path,
    *,
    chunk_seconds: int = MAX_AUDIO_CHUNK_SECONDS,
    overlap_seconds: float = CHUNK_OVERLAP_SECONDS,
) -> list[dict]:
    chunk_path_root = Path(temp_dir)
    chunk_path_root.mkdir(parents=True, exist_ok=True)

    try:
        source = wave.open(str(audio_path), "rb")
    except wave.Error as exc:
        raise RuntimeError(
            f"Unable to read WAV audio for ASR chunking: {audio_path}"
        ) from exc

    with source:
        frame_rate = source.getframerate()
        total_frames = source.getnframes()
        if frame_rate <= 0 or total_frames <= 0:
            return []

        total_seconds = total_frames / frame_rate
        if total_seconds <= chunk_seconds:
            return []

        chunk_frames = max(1, int(chunk_seconds * frame_rate))
        overlap_frames = max(0, int(overlap_seconds * frame_rate))
        params = source.getparams()
        chunk_records: list[dict] = []

        core_start_frame = 0
        chunk_index = 0
        while core_start_frame < total_frames:
            core_end_frame = min(total_frames, core_start_frame + chunk_frames)
            file_start_frame = max(
                0,
                core_start_frame - overlap_frames if core_start_frame > 0 else 0,
            )
            file_end_frame = min(total_frames, core_end_frame + overlap_frames)

            source.setpos(file_start_frame)
            frames = source.readframes(file_end_frame - file_start_frame)

            chunk_path = chunk_path_root / f"chunk_{chunk_index:03d}.wav"
            with wave.open(str(chunk_path), "wb") as target:
                target.setparams(params)
                target.writeframes(frames)

            chunk_records.append(
                {
                    "path": chunk_path,
                    "file_start_seconds": file_start_frame / frame_rate,
                    "core_start_seconds": core_start_frame / frame_rate,
                    "core_end_seconds": core_end_frame / frame_rate,
                    "is_last": core_end_frame >= total_frames,
                }
            )

            core_start_frame = core_end_frame
            chunk_index += 1

    return chunk_records


def segment_midpoint_belongs_to_chunk(
    start_seconds: float,
    end_seconds: float,
    *,
    core_start_seconds: float,
    core_end_seconds: float,
    is_last: bool,
) -> bool:
    midpoint = (float(start_seconds) + float(end_seconds)) / 2.0
    if is_last:
        return core_start_seconds <= midpoint <= core_end_seconds
    return core_start_seconds <= midpoint < core_end_seconds


def transcribe_audio_chunks(
    model: object,
    chunk_plan: list[dict],
    *,
    language: str | None,
    task: str,
    word_timestamps: bool,
    beam_size: int,
    vad_filter: bool,
    progress_callback: AsrProgressCallback | None,
) -> list[Segment]:
    segments: list[Segment] = []
    for chunk in chunk_plan:
        result_segments, _info = model.transcribe(
            str(chunk["path"]),
            language=language,
            task=task,
            beam_size=beam_size,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
        )

        for item in result_segments:
            absolute_start = float(chunk["file_start_seconds"]) + float(item.start)
            absolute_end = float(chunk["file_start_seconds"]) + float(item.end)
            if not segment_midpoint_belongs_to_chunk(
                absolute_start,
                absolute_end,
                core_start_seconds=float(chunk["core_start_seconds"]),
                core_end_seconds=float(chunk["core_end_seconds"]),
                is_last=bool(chunk["is_last"]),
            ):
                continue

            words = [
                Word(
                    word=word.word.strip(),
                    start=float(chunk["file_start_seconds"]) + float(word.start),
                    end=float(chunk["file_start_seconds"]) + float(word.end),
                    confidence=word.probability,
                )
                for word in item.words or []
                if word.word.strip()
            ]
            text = normalize_text(item.text)
            if not text:
                continue
            segments.append(
                Segment(
                    id=len(segments) + 1,
                    start=absolute_start,
                    end=absolute_end,
                    source_text=text,
                    words=words,
                    confidence=getattr(item, "avg_logprob", None),
                    source="asr",
                )
            )
            if progress_callback:
                progress_callback(
                    {
                        "segment_count": len(segments),
                        "processed_seconds": absolute_end,
                    }
                )

        if progress_callback:
            progress_callback(
                {
                    "segment_count": len(segments),
                    "processed_seconds": float(chunk["core_end_seconds"]),
                }
            )

    return segments


def transcribe_audio(
    audio_path: str | Path,
    *,
    model_name: str = "base",
    language: str | None = None,
    task: str = "transcribe",
    word_timestamps: bool = True,
    device: str = "auto",
    compute_type: str = "default",
    beam_size: int = 5,
    vad_filter: bool = True,
    progress_callback: AsrProgressCallback | None = None,
) -> list[Segment]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed in this Python environment. "
            "Install it with: python -m pip install faster-whisper"
        ) from exc

    normalized_device = normalize_asr_device(device)
    normalized_compute_type = normalize_asr_compute_type(compute_type)
    with tempfile.TemporaryDirectory(prefix="autosub_asr_chunks_") as temp_dir:
        chunk_plan = build_wave_chunk_plan(audio_path, temp_dir)
        if not chunk_plan:
            chunk_plan = [
                {
                    "path": Path(audio_path),
                    "file_start_seconds": 0.0,
                    "core_start_seconds": 0.0,
                    "core_end_seconds": float("inf"),
                    "is_last": True,
                }
            ]

        attempts = build_asr_attempts(normalized_device, normalized_compute_type, beam_size)
        if normalized_device != "cpu":
            ensure_cuda_runtime_on_path()
        for attempt_index, attempt in enumerate(attempts):
            attempt_device = str(attempt["device"])
            attempt_compute_type = str(attempt["compute_type"])
            attempt_beam_size = int(attempt["beam_size"])

            model = None
            try:
                if progress_callback:
                    progress_callback(
                        {
                            "event": "attempt_start",
                            "segment_count": 0,
                            "processed_seconds": 0.0,
                            "device": attempt_device,
                            "compute_type": attempt_compute_type,
                            "beam_size": attempt_beam_size,
                            "reason": attempt.get("reason"),
                        }
                    )
                model = WhisperModel(
                    model_name,
                    device=attempt_device,
                    compute_type=attempt_compute_type,
                )
                return transcribe_audio_chunks(
                    model,
                    chunk_plan,
                    language=language,
                    task=task,
                    word_timestamps=word_timestamps,
                    beam_size=attempt_beam_size,
                    vad_filter=vad_filter,
                    progress_callback=progress_callback,
                )
            except (RuntimeError, ValueError) as exc:
                if not is_asr_backend_failure(exc):
                    raise
                next_attempt = attempts[attempt_index + 1] if attempt_index + 1 < len(attempts) else None
                if not next_attempt:
                    raise RuntimeError(
                        "GPU backend failed during ASR and no safer fallback remained. "
                        "Try device=cpu, compute_type=int8, a smaller Whisper model, or check the CUDA runtime."
                    ) from exc
                emit_asr_fallback(
                    progress_callback,
                    failed_attempt=attempt,
                    next_attempt=next_attempt,
                    error=exc,
                )
            finally:
                del model
                release_accelerator_memory()

    return []
