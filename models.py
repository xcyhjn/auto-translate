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
    words: list[Word] = field(default_factory=list)
    confidence: float | None = None
    source: str = "asr"


@dataclass(slots=True)
class SubtitleRules:
    min_duration: float = 1.0
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
    zh_font_name: str = "Microsoft YaHei"
    zh_font_size: int = 64
    zh_margin_l: int = 90
    zh_margin_r: int = 90
    zh_margin_v: int = 94
    en_font_name: str = "Arial"
    en_font_size: int = 40
    en_margin_l: int = 80
    en_margin_r: int = 100
    en_margin_v: int = 44


@dataclass(slots=True)
class MediaInfo:
    path: str
    duration: float | None
    has_audio: bool
    text_subtitle_streams: list[dict]
    image_subtitle_streams: list[dict]

    @property
    def has_text_subtitle(self) -> bool:
        return bool(self.text_subtitle_streams)
