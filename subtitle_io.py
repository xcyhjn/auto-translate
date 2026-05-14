from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from .models import BilingualSubtitleStyle, Segment, Word
from .utils import ensure_parent, format_srt_timestamp


SEMANTIC_SPLIT_PATTERN = re.compile(r"[，,、；;：:。.!！？?]\s*")
EN_SOFT_SPLIT_WORDS = {
    "and",
    "but",
    "or",
    "so",
    "because",
    "when",
    "while",
    "which",
    "that",
    "to",
    "for",
    "with",
    "from",
    "as",
    "if",
}
ZH_SOFT_SPLIT_WORDS = (
    "然后",
    "但是",
    "不过",
    "因为",
    "所以",
    "以及",
    "并且",
    "或者",
    "如果",
    "当你",
    "这样",
)


@dataclass(slots=True)
class DisplayCue:
    start: float
    end: float
    en_text: str
    zh_text: str | None = None
    words: list[Word] | None = None


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


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


def normalize_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def visible_text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def tokenize_mixed_text(text: str) -> list[str]:
    """Tokenize CJK subtitle text without breaking embedded Latin words.

    The subtitle layout layer treats every Latin word, command, path,
    file name, and identifier as atomic. Chinese characters may wrap
    individually, but tokens such as ``HyperLand`` or ``theme.conf`` may not
    be split in the middle.
    """
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9_./:\\+~#@%&=-]*|[.][A-Za-z0-9_./:\\+~#@%&=-]+|\s+|.", text or "")


def split_by_meaning(text: str) -> list[str]:
    normalized = normalize_inline_text(text)
    if not normalized:
        return []

    chunks: list[str] = []
    start = 0
    for match in SEMANTIC_SPLIT_PATTERN.finditer(normalized):
        separator = normalized[match.start()]
        previous_char = normalized[match.start() - 1] if match.start() > 0 else ""
        next_char = normalized[match.start() + 1] if match.start() + 1 < len(normalized) else ""
        if separator == "." and previous_char.isalnum() and next_char.isalnum():
            continue
        if separator == ":" and previous_char.isalpha() and next_char in {"\\", "/"}:
            continue
        end = match.end()
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end

    tail = normalized[start:].strip()
    if tail:
        chunks.append(tail)
    return chunks or [normalized]


def split_long_chinese_chunk(chunk: str, max_chars: int) -> list[str]:
    if visible_text_length(chunk) <= max_chars:
        return [chunk]

    parts: list[str] = []
    current = ""
    for token in tokenize_mixed_text(chunk):
        candidate = f"{current}{token}" if current else token
        if current.strip() and visible_text_length(candidate) > max_chars:
            parts.append(current.strip())
            current = token
        else:
            current = candidate
    if current.strip():
        parts.append(current.strip())
    return parts


def split_chinese_at_soft_word(text: str, max_chars: int) -> list[str]:
    if visible_text_length(text) <= max_chars:
        return [text]

    center = len(text) / 2
    candidates: list[tuple[float, int]] = []
    for word in ZH_SOFT_SPLIT_WORDS:
        for match in re.finditer(re.escape(word), text):
            split_at = match.start()
            if split_at <= 0:
                continue
            left = text[:split_at].strip()
            right = text[split_at:].strip()
            if left and right:
                candidates.append((abs(split_at - center), split_at))

    if not candidates:
        return [text]

    _, split_at = min(candidates)
    return [text[:split_at].strip(), text[split_at:].strip()]


def wrap_chinese_text(
    text: str,
    *,
    trigger_chars: int = 32,
    max_chars: int = 28,
    max_lines: int = 2,
) -> str:
    text = normalize_inline_text(text)
    trigger_chars = max(8, int(trigger_chars or 32))
    max_chars = max(8, int(max_chars or 28))
    max_lines = max(1, int(max_lines or 2))

    if visible_text_length(text) <= trigger_chars:
        return text

    chunks: list[str] = []
    for chunk in split_by_meaning(text):
        for soft_chunk in split_chinese_at_soft_word(chunk, max_chars):
            chunks.extend(split_long_chinese_chunk(soft_chunk, max_chars))

    lines: list[str] = []
    current = ""
    for chunk in chunks:
        candidate = f"{current}{chunk}" if current else chunk
        if current and visible_text_length(candidate) > max_chars:
            lines.append(current.strip())
            current = chunk
        else:
            current = candidate

    if current.strip():
        lines.append(current.strip())

    if len(lines) <= max_lines:
        return "\n".join(lines)

    balanced = balance_lines(text, max_lines=max_lines, max_chars=max_chars)
    return "\n".join(balanced)


def balance_lines(text: str, *, max_lines: int, max_chars: int) -> list[str]:
    tokens = tokenize_mixed_text(text)
    total_visible = visible_text_length(text)
    target = max(1, min(max_chars, (total_visible + max_lines - 1) // max_lines))
    lines: list[str] = []
    current = ""

    for token in tokens:
        current = f"{current}{token}" if current else token
        if len(lines) < max_lines - 1 and visible_text_length(current) >= target:
            lines.append(current.strip())
            current = ""

    if current.strip():
        lines.append(current.strip())
    return lines[:max_lines]


def english_fits_single_line(text: str, max_chars: int) -> bool:
    return len(normalize_inline_text(text)) <= max(20, int(max_chars or 78))


def word_text(word: Word) -> str:
    return normalize_inline_text(word.word)


def words_to_text(words: list[Word]) -> str:
    return normalize_inline_text(" ".join(word_text(word) for word in words))


def score_english_split(words: list[str], index: int, max_chars: int) -> float:
    left = " ".join(words[:index]).strip()
    right = " ".join(words[index:]).strip()
    if not left or not right:
        return 1_000_000

    left_len = len(left)
    right_len = len(right)
    overflow = max(0, left_len - max_chars) + max(0, right_len - max_chars)
    balance = abs(left_len - right_len)
    word = re.sub(r"[^A-Za-z']+", "", words[index].lower())
    semantic_bonus = -18 if word in EN_SOFT_SPLIT_WORDS else 0
    punctuation_bonus = -24 if words[index - 1].rstrip().endswith((",", ";", ":", ".", "!", "?")) else 0
    return overflow * 100 + balance + semantic_bonus + punctuation_bonus


def choose_english_split_index(words: list[str], max_chars: int) -> int:
    if len(words) <= 1:
        return 1

    candidates = range(1, len(words))
    return min(candidates, key=lambda index: score_english_split(words, index, max_chars))


def split_english_text(text: str, max_chars: int, max_parts: int = 3) -> list[str]:
    text = normalize_inline_text(text)
    if english_fits_single_line(text, max_chars):
        return [text] if text else []

    max_parts = max(1, int(max_parts or 3))
    parts = [text]
    while len(parts) < max_parts:
        long_indexes = [
            index
            for index, part in enumerate(parts)
            if not english_fits_single_line(part, max_chars) and len(part.split()) > 1
        ]
        if not long_indexes:
            break

        part_index = max(long_indexes, key=lambda index: len(parts[index]))
        words = parts[part_index].split()
        split_index = choose_english_split_index(words, max_chars)
        left = " ".join(words[:split_index]).strip()
        right = " ".join(words[split_index:]).strip()
        if not left or not right:
            break
        parts[part_index : part_index + 1] = [left, right]

    if len(parts) == 1:
        return [text]
    return [part for part in parts if part]


def split_words_by_english_parts(words: list[Word], text_parts: list[str]) -> list[list[Word]]:
    if not words or not text_parts:
        return []

    remaining_words = words[:]
    groups: list[list[Word]] = []
    for index, part in enumerate(text_parts):
        if index == len(text_parts) - 1:
            groups.append(remaining_words)
            break

        target_count = max(1, len(part.split()))
        group = remaining_words[:target_count]
        groups.append(group)
        remaining_words = remaining_words[target_count:]

    return [group for group in groups if group]


def split_chinese_for_parts(text: str, part_count: int) -> list[str]:
    text = normalize_inline_text(text)
    if part_count <= 1 or not text:
        return [text] if text else []

    chunks = split_by_meaning(text)
    if len(chunks) == part_count:
        return chunks

    if len(chunks) > part_count:
        groups: list[str] = []
        current_chunks: list[str] = []
        total_length = sum(visible_text_length(chunk) for chunk in chunks)
        target_length = max(1, (total_length + part_count - 1) // part_count)
        remaining_chunks = len(chunks)
        for chunk in chunks:
            remaining_chunks -= 1
            current_chunks.append(chunk)
            remaining_groups = part_count - len(groups) - 1
            if remaining_groups <= 0:
                continue
            current_text = "".join(current_chunks).strip()
            if visible_text_length(current_text) >= target_length and remaining_chunks >= remaining_groups:
                groups.append(current_text)
                current_chunks = []

        if current_chunks:
            groups.append("".join(current_chunks).strip())

        while len(groups) > part_count:
            tail = groups.pop()
            groups[-1] = f"{groups[-1]}{tail}".strip()
        return [group for group in groups if group]

    # 中文语义块少于英文拆分段时，不再留空子段。
    # 我们按顺序继承最近的中文语义，让每个英文子段都有中文字幕对应。
    if len(chunks) == 1:
        return [chunks[0]] * part_count

    parts: list[str] = []
    for index in range(part_count):
        mapped_index = min(len(chunks) - 1, round(index * (len(chunks) - 1) / max(1, part_count - 1)))
        parts.append(chunks[mapped_index])
    return parts


def duration_for_split(segment: Segment, part_count: int, index: int) -> tuple[float, float]:
    duration = max(0.0, segment.end - segment.start)
    start = segment.start + duration * index / part_count
    end = segment.start + duration * (index + 1) / part_count
    return start, end


def split_segment_for_bilingual_ass(
    segment: Segment,
    style: BilingualSubtitleStyle,
) -> list[DisplayCue]:
    source_text = normalize_inline_text(segment.source_text)
    target_text = normalize_inline_text(segment.target_text or "")
    max_chars = int(style.en_max_single_line_chars or 78)
    max_parts = int(style.en_max_split_parts or 3)

    if english_fits_single_line(source_text, max_chars):
        return [
            DisplayCue(
                start=segment.start,
                end=segment.end,
                en_text=source_text,
                zh_text=target_text or None,
                words=segment.words,
            )
        ]

    text_parts = split_english_text(source_text, max_chars, max_parts=max_parts)
    if len(text_parts) <= 1:
        return [
            DisplayCue(
                start=segment.start,
                end=segment.end,
                en_text=source_text,
                zh_text=target_text or None,
                words=segment.words,
            )
        ]

    word_groups = split_words_by_english_parts(segment.words, text_parts) if segment.words else []
    zh_parts = split_chinese_for_parts(target_text, len(text_parts))
    if len(zh_parts) < len(text_parts):
        zh_parts.extend([""] * (len(text_parts) - len(zh_parts)))

    split_segments: list[DisplayCue] = []
    for index, english_part in enumerate(text_parts):
        if word_groups and index < len(word_groups) and word_groups[index]:
            group = word_groups[index]
            start = float(group[0].start)
            end = float(group[-1].end)
            words = group
        else:
            start, end = duration_for_split(segment, len(text_parts), index)
            words = []

        if end <= start:
            start, end = duration_for_split(segment, len(text_parts), index)

        split_segments.append(
            DisplayCue(
                start=start,
                end=end,
                en_text=english_part,
                zh_text=zh_parts[index] if index < len(zh_parts) else None,
                words=words,
            )
        )

    return enforce_minimum_split_durations(split_segments, segment, style.min_split_duration)


def enforce_minimum_split_durations(
    segments: list[DisplayCue],
    original: Segment,
    min_duration: float,
) -> list[DisplayCue]:
    if len(segments) <= 1:
        return segments

    min_duration = max(0.2, float(min_duration or 0.9))
    total_duration = max(0.0, original.end - original.start)
    if total_duration < len(segments) * min_duration:
        return segments

    fixed: list[DisplayCue] = []
    start = original.start
    remaining = total_duration
    for index, segment in enumerate(segments):
        remaining_parts = len(segments) - index
        duration = max(segment.end - segment.start, min_duration)
        max_duration = remaining - min_duration * (remaining_parts - 1)
        duration = min(duration, max_duration)
        end = start + duration
        fixed.append(replace(segment, start=start, end=end))
        start = end
        remaining = max(0.0, original.end - start)
    fixed[-1].end = original.end
    return fixed


def prepare_bilingual_ass_segments(
    segments: list[Segment],
    style: BilingualSubtitleStyle,
) -> list[DisplayCue]:
    prepared: list[DisplayCue] = []
    for segment in segments:
        prepared.extend(split_segment_for_bilingual_ass(segment, style))

    return prepared


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
    for cue in prepare_bilingual_ass_segments(segments, style):
        start = format_ass_timestamp(cue.start)
        end = format_ass_timestamp(cue.end)

        if cue.zh_text and contains_chinese(cue.zh_text):
            zh_text = escape_ass_text(
                wrap_chinese_text(
                    cue.zh_text,
                    trigger_chars=style.zh_wrap_trigger_chars,
                    max_chars=style.zh_max_chars_per_line,
                    max_lines=style.zh_max_lines,
                )
            )
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{zh_text}")

        en_text = escape_ass_text(normalize_inline_text(cue.en_text))
        if en_text:
            lines.append(f"Dialogue: 1,{start},{end},EnglishSmall,,0,0,0,,{en_text}")

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def write_zh_ass(
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

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines: list[str] = [header.rstrip()]
    for segment in segments:
        text = escape_ass_text(
            wrap_chinese_text(
                segment.target_text or segment.source_text,
                trigger_chars=style.zh_wrap_trigger_chars,
                max_chars=style.zh_max_chars_per_line,
                max_lines=style.zh_max_lines,
            )
        )
        start = format_ass_timestamp(segment.start)
        end = format_ass_timestamp(segment.end)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
