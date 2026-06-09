from __future__ import annotations

import json
from pathlib import Path

from autosub_zh.segment_io import load_segments, save_segments_payload
from autosub_zh.models import BilingualSubtitleStyle
from autosub_zh.subtitle_io import write_bilingual_ass, write_srt


BASE = Path(r"D:\autosub_zh\output\ru_xiu_xiu_preview_60s")


def main() -> None:
    translated_segments_path = BASE / "05_translated_segments.json"
    segments = load_segments(translated_segments_path)

    segment_11 = next(segment for segment in segments if segment.id == 11)
    segment_12 = next(segment for segment in segments if segment.id == 12)

    segment_11.source_text = "года «Xiu Xiu: The Sent-Down Girl»."
    segment_11.target_text = "那是 1999 年的电影《天浴》。"

    segment_12.source_text = ""
    segment_12.target_text = ""

    payload = json.loads(translated_segments_path.read_text(encoding="utf-8"))
    summary = payload.get("summary") if isinstance(payload, dict) else {}
    save_segments_payload(
        segments,
        translated_segments_path,
        input_file=str(payload.get("input_file") or ""),
        summary=summary if isinstance(summary, dict) else {},
    )

    write_srt(segments, BASE / "06_translated_zh.srt")

    style = BilingualSubtitleStyle(en_font_name="Huiwen-HKHei", en_max_single_line_chars=58, reference_mode="compact")
    write_bilingual_ass(segments, BASE / "08_bilingual_zh_ru_huiwenhkhei.ass", style=style)


if __name__ == "__main__":
    main()
