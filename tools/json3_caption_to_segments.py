from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def normalize_caption_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def parse_json3_events(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(events, list):
        raise ValueError(f"JSON3 file has no events list: {path}")

    rows: list[dict] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        segs = event.get("segs")
        if not isinstance(segs, list):
            continue
        text = normalize_caption_text("".join(str(seg.get("utf8") or "") for seg in segs if isinstance(seg, dict)))
        if not text:
            continue
        start = float(event.get("tStartMs") or 0) / 1000.0
        duration = float(event.get("dDurationMs") or 0) / 1000.0
        if duration <= 0:
            duration = 2.0
        rows.append(
            {
                "start": start,
                "end": start + duration,
                "text": text,
            }
        )
    rows.sort(key=lambda item: (item["start"], item["end"], item["text"]))
    return rows


def deoverlap_rows(rows: list[dict], *, min_duration: float = 0.7, max_duration: float = 6.0) -> list[dict]:
    cleaned: list[dict] = []
    for index, row in enumerate(rows):
        text = row["text"]
        start = float(row["start"])
        next_start = float(rows[index + 1]["start"]) if index + 1 < len(rows) else None
        end = float(row["end"])
        if next_start is not None:
            end = min(end, max(start + min_duration, next_start - 0.04))
        end = min(end, start + max_duration)
        if end <= start:
            end = start + min_duration
        if cleaned and start < cleaned[-1]["end"]:
            start = cleaned[-1]["end"] + 0.04
            end = max(end, start + min_duration)
        if cleaned and text == cleaned[-1]["source_text"] and start - float(cleaned[-1]["start"]) < 1.0:
            continue
        cleaned.append(
            {
                "id": len(cleaned) + 1,
                "start": round(start, 3),
                "end": round(end, 3),
                "source_text": text,
                "target_text": None,
                "reference_text": None,
                "confidence": None,
                "source": "youtube_json3",
                "words": [],
            }
        )
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert YouTube JSON3 captions to autosub_zh segment JSON.")
    parser.add_argument("json3_path", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--input-file", default="")
    args = parser.parse_args()

    rows = parse_json3_events(args.json3_path)
    segments = deoverlap_rows(rows)
    payload = {
        "schema_version": 1,
        "input_file": args.input_file,
        "segment_count": len(segments),
        "summary": {
            "stage": "timed_source",
            "source": "youtube_json3",
            "raw_event_count": len(rows),
        },
        "segments": segments,
    }
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"] | {"segment_count": len(segments)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
