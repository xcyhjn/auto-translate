from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import Segment, Word
from .utils import ensure_parent


def segment_to_dict(segment: Segment) -> dict:
    """把 Segment 数据类转换成可直接写入 JSON 的普通数据。

    内存里保留 Segment 对象，是因为它比原始字典更好操作。
    落盘时则用普通 JSON 更合适：可读、可 diff、也更方便在长流程失败时排查。
    """
    return {
        "id": segment.id,
        "start": segment.start,
        "end": segment.end,
        "source_text": segment.source_text,
        "target_text": segment.target_text,
        "confidence": segment.confidence,
        "source": segment.source,
        "words": [
            {
                "word": word.word,
                "start": word.start,
                "end": word.end,
                "confidence": word.confidence,
            }
            for word in segment.words
        ],
    }


def segment_from_dict(payload: dict) -> Segment:
    words = [
        Word(
            word=str(item["word"]),
            start=float(item["start"]),
            end=float(item["end"]),
            confidence=item.get("confidence"),
        )
        for item in payload.get("words", [])
    ]
    return Segment(
        id=int(payload["id"]),
        start=float(payload["start"]),
        end=float(payload["end"]),
        source_text=str(payload.get("source_text", "")),
        target_text=payload.get("target_text"),
        words=words,
        confidence=payload.get("confidence"),
        source=str(payload.get("source", "asr")),
    )


def save_segments(segments: list[Segment], output_path: str | Path) -> None:
    save_segments_payload(segments, output_path)


def build_segments_payload(
    segments: list[Segment],
    *,
    input_file: str = "",
    summary: dict | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_file": input_file,
        "segment_count": len(segments),
        "summary": summary or {},
        "segments": [segment_to_dict(segment) for segment in segments],
    }


def save_segments_payload(
    segments: list[Segment],
    output_path: str | Path,
    *,
    input_file: str = "",
    summary: dict | None = None,
) -> None:
    ensure_parent(output_path)
    payload = build_segments_payload(
        segments,
        input_file=input_file,
        summary=summary,
    )
    Path(output_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_segments(input_path: str | Path) -> list[Segment]:
    payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [segment_from_dict(item) for item in payload]
    if isinstance(payload, dict) and isinstance(payload.get("segments"), list):
        return [segment_from_dict(item) for item in payload["segments"]]
    raise ValueError(f"Unsupported segments payload format: {input_path}")
