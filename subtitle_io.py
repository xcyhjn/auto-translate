from __future__ import annotations

from pathlib import Path

from .models import BilingualSubtitleStyle, Segment
from .utils import ensure_parent, format_srt_timestamp


def format_ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    centis = int(round(seconds * 100))
    hours, rem = divmod(centis, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, centis = divmod(rem, 100)
    return f"{hours}:{minutes:02}:{secs:02}.{centis:02}"


def escape_ass_text(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def write_srt(segments: list[Segment], output_path: str | Path) -> None:
    ensure_parent(output_path)
    lines: list[str] = []

    for idx, segment in enumerate(segments, start=1):
        text = segment.target_text or segment.source_text
        lines.extend(
            [
                str(idx),
                f"{format_srt_timestamp(segment.start)} --> {format_srt_timestamp(segment.end)}",
                text,
                "",
            ]
        )

    Path(output_path).write_text("\n".join(lines), encoding="utf-8-sig")


def write_bilingual_ass(
    segments: list[Segment],
    output_path: str | Path,
    style: BilingualSubtitleStyle | None = None,
) -> None:
    ensure_parent(output_path)
    if style is None:
        style = BilingualSubtitleStyle()

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.zh_font_name},{style.zh_font_size},&H00FFFFFF,&H000000FF,&H00141414,&H64000000,0,0,0,0,100,100,0,0,1,2.2,0.6,2,{style.zh_margin_l},{style.zh_margin_r},{style.zh_margin_v},1
Style: EnglishSmall,{style.en_font_name},{style.en_font_size},&H00E8E8E8,&H000000FF,&H00141414,&H50000000,0,0,0,0,100,100,0,0,1,1.6,0.4,2,{style.en_margin_l},{style.en_margin_r},{style.en_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines: list[str] = [header.rstrip()]
    for segment in segments:
        zh_text = escape_ass_text(segment.target_text or segment.source_text)
        en_text = escape_ass_text(segment.source_text)
        start = format_ass_timestamp(segment.start)
        end = format_ass_timestamp(segment.end)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{zh_text}")
        lines.append(f"Dialogue: 1,{start},{end},EnglishSmall,,0,0,0,,{en_text}")

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
