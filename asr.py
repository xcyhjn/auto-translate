from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .models import Segment, Word
from .utils import normalize_text


CUDA_BIN_DIR = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin"
AsrProgressCallback = Callable[[dict], None]


def ensure_cuda_runtime_on_path() -> None:
    if os.path.isdir(CUDA_BIN_DIR):
        current_path = os.environ.get("PATH", "")
        if CUDA_BIN_DIR not in current_path.split(";"):
            os.environ["PATH"] = CUDA_BIN_DIR + ";" + current_path


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

    # transcribe() 会返回一个 Segment 生成器和一个 info 对象。
    # 这里将生成器落地，是因为后续流程需要查看并可能重写整份字幕列表。
    result_segments, _info = model.transcribe(
        str(audio_path),
        language=language,
        task=task,
        beam_size=beam_size,
        vad_filter=vad_filter,
        word_timestamps=word_timestamps,
    )

    segments: list[Segment] = []
    for idx, item in enumerate(result_segments, start=1):
        words = [
            Word(
                word=word.word.strip(),
                start=float(word.start),
                end=float(word.end),
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
                id=idx,
                start=float(item.start),
                end=float(item.end),
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
                    "processed_seconds": float(item.end),
                }
            )

    return segments
