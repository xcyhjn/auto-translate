from __future__ import annotations

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
AsrProgressCallback = Callable[[dict], None]


def ensure_cuda_runtime_on_path() -> None:
    if os.path.isdir(CUDA_BIN_DIR):
        current_path = os.environ.get("PATH", "")
        if CUDA_BIN_DIR not in current_path.split(";"):
            os.environ["PATH"] = CUDA_BIN_DIR + ";" + current_path


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
            file_start_frame = max(0, core_start_frame - overlap_frames if core_start_frame > 0 else 0)
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
    if device == "cuda":
        ensure_cuda_runtime_on_path()

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed in this Python environment. "
            "Install it with: python -m pip install faster-whisper"
        ) from exc

    # faster-whisper 会按需把模型加载到指定后端。
    # device='auto' 会让 CTranslate2 在可用时优先选择 CUDA，否则回落到 CPU。
    # compute_type='default' 比较保守；GPU 上通常可以用 float16，
    # CPU 上则常常以 int8 最实用。
    model = WhisperModel(model_name, device=device, compute_type=compute_type)

    segments: list[Segment] = []
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
