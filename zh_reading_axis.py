from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .models import BilingualSubtitleStyle, Segment, Word
from .subtitle_io import (
    DisplayCue,
    ass_color,
    clamp_float,
    contains_chinese,
    escape_ass_text,
    format_ass_timestamp,
    normalize_inline_text,
    normalize_reference_text,
    split_chinese_for_parts,
    visible_text_cps,
    visible_text_length,
    wrap_chinese_text,
)
from .utils import ensure_parent


SENTENCE_END_RE = re.compile(r"[.!?。！？…]+[\"'”’»）\])]*$")
CLAUSE_END_RE = re.compile(r"[,，;；:：、]+[\"'”’»）\])]*$")
TRAILING_FUNCTION_WORDS = {
    "a",
    "and",
    "as",
    "at",
    "because",
    "but",
    "for",
    "from",
    "if",
    "in",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "to",
    "when",
    "while",
    "with",
    "а",
    "в",
    "во",
    "где",
    "до",
    "за",
    "и",
    "как",
    "к",
    "когда",
    "на",
    "но",
    "о",
    "об",
    "от",
    "по",
    "потому",
    "с",
    "со",
    "у",
    "что",
    "чтобы",
}
SOURCE_FUNCTION_EDGE_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "for",
    "from",
    "if",
    "in",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "to",
    "when",
    "while",
    "with",
}
SOURCE_CONTINUATION_EDGE_WORDS = {
    "and",
    "as",
    "because",
    "but",
    "for",
    "from",
    "if",
    "in",
    "of",
    "or",
    "so",
    "that",
    "then",
    "to",
    "when",
    "while",
    "with",
}


@dataclass(slots=True)
class ZhReadingAxisConfig:
    target_min_duration: float = 3.5
    target_max_duration: float = 7.5
    hard_max_duration: float = 8.5
    min_duration: float = 2.2
    merge_gap_threshold: float = 0.45
    strong_gap_threshold: float = 1.0
    zh_max_cps: float = 18.0
    max_display_parts: int = 3


@dataclass(slots=True)
class ZhReadingGroup:
    id: int
    start: float
    end: float
    source_segment_ids: list[int]
    source_text_joined: str
    source_words: list[Word] = field(default_factory=list)
    target_text: str | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def segment_word_start(segment: Segment) -> float:
    if segment.words:
        return float(segment.words[0].start)
    return float(segment.start)


def segment_word_end(segment: Segment) -> float:
    if segment.words:
        return float(segment.words[-1].end)
    return float(segment.end)


def segment_words(segment: Segment) -> list[Word]:
    return list(segment.words or [])


def clean_last_token(text: str) -> str:
    tokens = re.findall(r"[\w\u0400-\u04ff']+", text.lower(), flags=re.UNICODE)
    return tokens[-1] if tokens else ""


def ends_sentence(text: str) -> bool:
    return bool(SENTENCE_END_RE.search(normalize_inline_text(text)))


def ends_clause(text: str) -> bool:
    text = normalize_inline_text(text)
    return bool(CLAUSE_END_RE.search(text)) or ends_sentence(text)


def has_dangling_tail(text: str) -> bool:
    return clean_last_token(text) in TRAILING_FUNCTION_WORDS


def has_source_function_edge(text: str) -> bool:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9']*", normalize_inline_text(text).lower())
    return bool(tokens and (tokens[0] in SOURCE_CONTINUATION_EDGE_WORDS or tokens[-1] in SOURCE_FUNCTION_EDGE_WORDS))


def joined_source_text(segments: list[Segment]) -> str:
    return normalize_inline_text(" ".join(segment.source_text or "" for segment in segments))


def group_start(segments: list[Segment]) -> float:
    return segment_word_start(segments[0])


def group_end(segments: list[Segment]) -> float:
    return segment_word_end(segments[-1])


def should_close_group(
    current: list[Segment],
    next_segment: Segment | None,
    *,
    config: ZhReadingAxisConfig,
) -> bool:
    if not current:
        return False
    if next_segment is None:
        return True

    text = joined_source_text(current)
    duration = max(0.0, group_end(current) - group_start(current))
    gap = max(0.0, segment_word_start(next_segment) - group_end(current))
    next_duration = max(0.0, segment_word_end(next_segment) - segment_word_start(next_segment))
    would_duration = max(0.0, segment_word_end(next_segment) - group_start(current))

    if duration >= config.hard_max_duration:
        return True
    if would_duration > config.hard_max_duration and duration >= config.min_duration:
        return True
    if has_dangling_tail(text):
        return False
    if gap >= config.strong_gap_threshold and duration >= config.min_duration:
        return True
    if ends_sentence(text) and duration >= config.target_min_duration:
        return True
    if ends_sentence(text) and gap >= config.merge_gap_threshold and duration >= config.min_duration:
        return True
    if duration >= config.target_max_duration and (ends_clause(text) or gap >= config.merge_gap_threshold):
        return True
    if duration >= config.target_max_duration and next_duration > 0:
        return True
    return False


def make_group(group_id: int, segments: list[Segment]) -> ZhReadingGroup:
    words: list[Word] = []
    for segment in segments:
        words.extend(segment_words(segment))
    return ZhReadingGroup(
        id=group_id,
        start=group_start(segments),
        end=group_end(segments),
        source_segment_ids=[segment.id for segment in segments],
        source_text_joined=joined_source_text(segments),
        source_words=words,
    )


def build_zh_reading_groups(
    segments: list[Segment],
    *,
    config: ZhReadingAxisConfig | None = None,
) -> list[ZhReadingGroup]:
    config = config or ZhReadingAxisConfig()
    groups: list[ZhReadingGroup] = []
    current: list[Segment] = []

    source_segments = [segment for segment in segments if normalize_inline_text(segment.source_text)]
    for index, segment in enumerate(source_segments):
        current.append(segment)
        next_segment = source_segments[index + 1] if index + 1 < len(source_segments) else None
        if should_close_group(current, next_segment, config=config):
            groups.append(make_group(len(groups) + 1, current))
            current = []

    if current:
        groups.append(make_group(len(groups) + 1, current))

    return groups


def reading_group_to_segment(group: ZhReadingGroup) -> Segment:
    return Segment(
        id=group.id,
        start=group.start,
        end=group.end,
        source_text=group.source_text_joined,
        target_text=group.target_text,
        words=group.source_words[:],
        source="zh_reading_group",
    )


def reading_groups_to_segments(groups: list[ZhReadingGroup]) -> list[Segment]:
    return [reading_group_to_segment(group) for group in groups]


def reading_group_to_dict(group: ZhReadingGroup) -> dict:
    return {
        "id": group.id,
        "start": group.start,
        "end": group.end,
        "source_segment_ids": group.source_segment_ids,
        "source_text_joined": group.source_text_joined,
        "target_text": group.target_text,
        "source_words": [asdict(word) for word in group.source_words],
    }


def save_zh_reading_groups(
    groups: list[ZhReadingGroup],
    output_path: str | Path,
    *,
    input_file: str = "",
    summary: dict | None = None,
) -> None:
    payload = {
        "schema_version": 1,
        "input_file": input_file,
        "group_count": len(groups),
        "summary": summary or {},
        "groups": [reading_group_to_dict(group) for group in groups],
    }
    ensure_parent(output_path)
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def source_reference_cues_from_segments(
    segments: list[Segment],
    *,
    reference_lang: str = "ru",
) -> list[DisplayCue]:
    cues: list[DisplayCue] = []
    previous_end = 0.0
    for segment in segments:
        text = normalize_reference_text(segment.reference_text or segment.source_text, lang=reference_lang)
        if not text:
            continue
        start = segment_word_start(segment)
        end = segment_word_end(segment)
        if end <= start:
            start = float(segment.start)
            end = float(segment.end)
        if cues and start < previous_end:
            start = previous_end
        if end <= start:
            end = start + 0.01
        cues.append(
            DisplayCue(
                start=start,
                end=end,
                en_text=text,
                zh_text=None,
                words=segment.words,
                source_segment_id=segment.id,
                rewrite_action="source_reference_strict",
            )
        )
        previous_end = end
    return cues


def should_split_zh_display_cue(
    segment: Segment,
    *,
    style: BilingualSubtitleStyle,
    config: ZhReadingAxisConfig,
) -> bool:
    text = normalize_inline_text(segment.target_text or "")
    if not text:
        return False
    duration = max(0.001, float(segment.end) - float(segment.start))
    max_chars = max(1, int(style.zh_max_chars_per_line or 28) * max(1, int(style.zh_max_lines or 2)))
    return (
        duration > config.hard_max_duration
        or visible_text_length(text) > max_chars
        or visible_text_cps(text, duration) > config.zh_max_cps
    )


def choose_zh_part_count(
    segment: Segment,
    *,
    style: BilingualSubtitleStyle,
    config: ZhReadingAxisConfig,
) -> int:
    text = normalize_inline_text(segment.target_text or "")
    duration = max(0.001, float(segment.end) - float(segment.start))
    max_chars = max(1, int(style.zh_max_chars_per_line or 28) * max(1, int(style.zh_max_lines or 2)))
    by_duration = int((duration + config.target_max_duration - 0.001) // config.target_max_duration)
    by_length = int((visible_text_length(text) + max_chars - 1) // max_chars)
    by_cps = int((visible_text_cps(text, duration) + config.zh_max_cps - 0.001) // config.zh_max_cps)
    wanted = max(1, min(max(1, config.max_display_parts), max(by_duration, by_length, by_cps)))
    max_by_min_duration = max(1, int(duration // max(0.1, config.min_duration)))
    return max(1, min(wanted, max_by_min_duration))


def build_zh_display_cues(
    segments: list[Segment],
    *,
    style: BilingualSubtitleStyle,
    config: ZhReadingAxisConfig | None = None,
) -> list[DisplayCue]:
    config = config or ZhReadingAxisConfig()
    cues: list[DisplayCue] = []
    for segment in segments:
        text = normalize_inline_text(segment.target_text or "")
        if not text:
            continue

        if should_split_zh_display_cue(segment, style=style, config=config):
            part_count = choose_zh_part_count(segment, style=style, config=config)
        else:
            part_count = 1

        parts = split_chinese_for_parts(text, part_count) if part_count > 1 else [text]
        parts = [normalize_inline_text(part) for part in parts if normalize_inline_text(part)]
        if not parts:
            continue

        total_duration = max(0.001, float(segment.end) - float(segment.start))
        for index, part in enumerate(parts):
            start = float(segment.start) + total_duration * index / len(parts)
            end = float(segment.start) + total_duration * (index + 1) / len(parts)
            cues.append(
                DisplayCue(
                    start=start,
                    end=end,
                    en_text="",
                    zh_text=part,
                    words=segment.words,
                    source_segment_id=segment.id,
                    group_index=index + 1,
                    group_total=len(parts),
                    rewrite_action="zh_reading_split" if len(parts) > 1 else "zh_reading_full",
                )
            )
    return cues


def cue_is_short_complete_sentence(
    cue: DisplayCue,
    *,
    max_duration: float,
) -> bool:
    duration = max(0.0, float(cue.end) - float(cue.start))
    if duration <= 0 or duration > max_duration:
        return False
    source_text = normalize_inline_text(cue.en_text)
    if not source_text or not ends_sentence(source_text):
        return False
    if has_source_function_edge(source_text):
        return False
    if cue.rewrite_action and "review" in cue.rewrite_action:
        return False
    return True


def group_short_complete_sentence_cues(
    cues: list[DisplayCue],
    *,
    max_single_duration: float = 1.2,
    max_gap: float = 0.35,
    max_group_duration: float = 3.5,
    zh_max_chars: int = 56,
) -> tuple[list[DisplayCue], dict]:
    if not cues:
        return [], {
            "schema_version": 1,
            "summary": {
                "group_count": 0,
                "merged_short_complete_sentence_count": 0,
            },
            "groups": [],
        }

    merged: list[DisplayCue] = []
    groups: list[dict] = []
    index = 0
    sorted_cues = sorted(cues, key=lambda item: (item.start, item.end))
    while index < len(sorted_cues):
        current = sorted_cues[index]
        run = [current]
        while index + len(run) < len(sorted_cues):
            next_cue = sorted_cues[index + len(run)]
            gap = max(0.0, float(next_cue.start) - float(run[-1].end))
            group_duration = max(0.0, float(next_cue.end) - float(run[0].start))
            zh_text = normalize_inline_text("".join(item.zh_text or "" for item in [*run, next_cue]))
            if not cue_is_short_complete_sentence(run[-1], max_duration=max_single_duration):
                break
            if not cue_is_short_complete_sentence(next_cue, max_duration=max_single_duration):
                break
            if gap > max_gap or group_duration > max_group_duration:
                break
            if visible_text_length(zh_text) > zh_max_chars:
                break
            run.append(next_cue)

        if len(run) <= 1:
            merged.append(current)
            index += 1
            continue

        merged_cue = DisplayCue(
            start=run[0].start,
            end=run[-1].end,
            en_text=normalize_inline_text(" ".join(item.en_text for item in run if item.en_text)),
            zh_text=normalize_inline_text("".join(item.zh_text or "" for item in run if item.zh_text)) or None,
            words=[word for item in run for word in (item.words or [])],
            source_segment_id=run[0].source_segment_id,
            group_index=1,
            group_total=1,
            rewrite_action="display_short_sentence_group",
        )
        merged.append(merged_cue)
        groups.append(
            {
                "source_segment_ids": [item.source_segment_id for item in run],
                "start": merged_cue.start,
                "end": merged_cue.end,
                "duration": round(max(0.0, merged_cue.end - merged_cue.start), 3),
                "en_text": merged_cue.en_text,
                "zh_text": merged_cue.zh_text or "",
            }
        )
        index += len(run)

    report = {
        "schema_version": 1,
        "summary": {
            "group_count": len(groups),
            "merged_short_complete_sentence_count": sum(len(group["source_segment_ids"]) for group in groups),
        },
        "groups": groups,
    }
    return merged, report


def write_zh_ass_from_display_cues(
    cues: list[DisplayCue],
    output_path: str | Path,
    *,
    style: BilingualSubtitleStyle | None = None,
) -> None:
    ensure_parent(output_path)
    if style is None:
        style = BilingualSubtitleStyle()

    zh_primary = ass_color(style.zh_primary_color, style.zh_primary_opacity, fallback="#FFF2A6")
    zh_outline = ass_color(style.zh_outline_color, style.zh_outline_opacity, fallback="#202020")
    zh_shadow = ass_color(style.zh_shadow_color, style.zh_shadow_opacity, fallback="#000000")
    zh_outline_width = clamp_float(style.zh_outline_width, 0.0, 12.0, 1.8)
    zh_shadow_depth = clamp_float(style.zh_shadow_depth, 0.0, 12.0, 0.4)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.zh_font_name},{style.zh_font_size},{zh_primary},&H000000FF,{zh_outline},{zh_shadow},0,0,0,0,100,100,0,0,1,{zh_outline_width:.1f},{zh_shadow_depth:.1f},2,{style.zh_margin_l},{style.zh_margin_r},{style.zh_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = [header.rstrip()]
    for cue in sorted(cues, key=lambda item: (item.start, item.end)):
        if not cue.zh_text or not contains_chinese(cue.zh_text):
            continue
        text = escape_ass_text(
            wrap_chinese_text(
                cue.zh_text,
                trigger_chars=style.zh_wrap_trigger_chars,
                max_chars=style.zh_max_chars_per_line,
                max_lines=style.zh_max_lines,
            )
        )
        lines.append(
            f"Dialogue: 0,{format_ass_timestamp(cue.start)},{format_ass_timestamp(cue.end)},Default,,0,0,0,,{text}"
        )
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def write_dual_axis_ass(
    source_cues: list[DisplayCue],
    zh_cues: list[DisplayCue],
    output_path: str | Path,
    *,
    style: BilingualSubtitleStyle | None = None,
    reference_lang: str = "ru",
) -> list[dict]:
    ensure_parent(output_path)
    if style is None:
        style = BilingualSubtitleStyle()

    zh_primary = ass_color(style.zh_primary_color, style.zh_primary_opacity, fallback="#FFF2A6")
    zh_outline = ass_color(style.zh_outline_color, style.zh_outline_opacity, fallback="#202020")
    zh_shadow = ass_color(style.zh_shadow_color, style.zh_shadow_opacity, fallback="#000000")
    zh_outline_width = clamp_float(style.zh_outline_width, 0.0, 12.0, 1.8)
    zh_shadow_depth = clamp_float(style.zh_shadow_depth, 0.0, 12.0, 0.4)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
WrapStyle: 2
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.zh_font_name},{style.zh_font_size},{zh_primary},&H000000FF,{zh_outline},{zh_shadow},0,0,0,0,100,100,0,0,1,{zh_outline_width:.1f},{zh_shadow_depth:.1f},2,{style.zh_margin_l},{style.zh_margin_r},{style.zh_margin_v},1
Style: EnglishSmall,{style.en_font_name},{style.en_font_size},&H00E8E8E8,&H000000FF,&H5A202020,&HA6000000,0,0,0,0,100,100,0,0,1,1.2,0.3,2,{style.en_margin_l},{style.en_margin_r},{style.en_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines: list[str] = [header.rstrip()]
    for cue in sorted(zh_cues, key=lambda item: (item.start, item.end)):
        if not cue.zh_text or not contains_chinese(cue.zh_text):
            continue
        text = escape_ass_text(
            wrap_chinese_text(
                cue.zh_text,
                trigger_chars=style.zh_wrap_trigger_chars,
                max_chars=style.zh_max_chars_per_line,
                max_lines=style.zh_max_lines,
            )
        )
        lines.append(
            f"Dialogue: 0,{format_ass_timestamp(cue.start)},{format_ass_timestamp(cue.end)},Default,,0,0,0,,{text}"
        )

    for cue in sorted(source_cues, key=lambda item: (item.start, item.end)):
        text = escape_ass_text(normalize_reference_text(cue.en_text, lang=reference_lang))
        if not text:
            continue
        lines.append(
            f"Dialogue: 1,{format_ass_timestamp(cue.start)},{format_ass_timestamp(cue.end)},EnglishSmall,,0,0,0,,{text}"
        )

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return [
        {
            "mode": "dual_axis",
            "source_cue_count": len(source_cues),
            "zh_cue_count": len(zh_cues),
            "source_start": source_cues[0].start if source_cues else None,
            "source_end": source_cues[-1].end if source_cues else None,
            "zh_start": zh_cues[0].start if zh_cues else None,
            "zh_end": zh_cues[-1].end if zh_cues else None,
        }
    ]
