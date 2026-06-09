from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Word:
    word: str
    start: float
    end: float
    confidence: float | None = None


@dataclass(slots=True)
class Segment:
    id: int
    start: float
    end: float
    source_text: str
    target_text: str | None = None
    reference_text: str | None = None
    words: list[Word] = field(default_factory=list)
    confidence: float | None = None
    source: str = "asr"


@dataclass(slots=True)
class SubtitleRules:
    min_duration: float = 2.0
    max_duration: float = 6.5
    min_gap: float = 0.08
    max_chars_per_line: int = 42
    max_lines: int = 2
    pause_split_threshold: float = 0.55
    strong_pause_split_threshold: float = 1.2
    sentence_split_min_chars: int = 8
    max_internal_silence: float = 1.2


@dataclass(slots=True)
class BilingualSubtitleStyle:
    zh_font_name: str = "Maple Mono NF CN"
    zh_font_size: int = 64
    zh_primary_color: str = "#FFF2A6"
    zh_primary_opacity: int = 100
    zh_outline_color: str = "#202020"
    zh_outline_opacity: int = 45
    zh_shadow_color: str = "#000000"
    zh_shadow_opacity: int = 35
    zh_outline_width: float = 1.8
    zh_shadow_depth: float = 0.4
    zh_margin_l: int = 90
    zh_margin_r: int = 90
    zh_margin_v: int = 94
    zh_wrap_trigger_chars: int = 32
    zh_max_chars_per_line: int = 28
    zh_max_lines: int = 2
    en_font_name: str = "Maple Mono NF CN"
    en_font_size: int = 40
    en_margin_l: int = 80
    en_margin_r: int = 100
    en_margin_v: int = 44
    en_max_single_line_chars: int = 78
    en_max_split_parts: int = 3
    min_split_duration: float = 2.0
    reference_mode: str = "compact"


@dataclass(slots=True)
class MediaInfo:
    path: str
    duration: float | None
    has_audio: bool
    video_width: int | None
    video_height: int | None
    text_subtitle_streams: list[dict]
    image_subtitle_streams: list[dict]

    @property
    def has_text_subtitle(self) -> bool:
        return bool(self.text_subtitle_streams)
