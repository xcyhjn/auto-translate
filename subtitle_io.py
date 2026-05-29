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
    source_segment_id: int | None = None
    group_index: int = 1
    group_total: int = 1
    rewrite_action: str = "none"


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


def normalize_hex_color(value: object, fallback: str = "#FFFFFF") -> str:
    raw = str(value or "").strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 3 and re.fullmatch(r"[0-9a-fA-F]{3}", raw):
        raw = "".join(ch * 2 for ch in raw)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raw = fallback.lstrip("#")
    return f"#{raw.upper()}"


def clamp_int(value: object, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def clamp_float(value: object, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def ass_color(hex_color: object, opacity_percent: object = 100, fallback: str = "#FFFFFF") -> str:
    normalized = normalize_hex_color(hex_color, fallback=fallback).lstrip("#")
    opacity = clamp_int(opacity_percent, 0, 100, 100)
    alpha = round(255 * (100 - opacity) / 100)
    red = normalized[0:2]
    green = normalized[2:4]
    blue = normalized[4:6]
    return f"&H{alpha:02X}{blue}{green}{red}"


def normalize_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def capitalize_first_person_i(text: str) -> str:
    """Capitalize standalone first-person English i in subtitle text."""
    return re.sub(r"(?<![A-Za-z])i(?=(?:['’](?:m|d|ll|ve|re)\b)|\b)", "I", text or "", flags=re.IGNORECASE)


def normalize_english_reference_text(text: str) -> str:
    return capitalize_first_person_i(normalize_inline_text(text))


def visible_text_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def visible_text_cps(text: str, duration: float) -> float:
    return visible_text_length(text) / max(0.001, float(duration))


def compact_reference_text(text: str, max_chars: int) -> str:
    normalized = normalize_inline_text(text)
    max_chars = max(8, int(max_chars or 78))
    if len(normalized) <= max_chars:
        return normalized

    words = normalized.split()
    if len(words) <= 1:
        return normalized[: max(1, max_chars - 1)].rstrip() + "…"

    pieces: list[str] = []
    current_length = 0
    for word in words:
        next_length = current_length + (1 if pieces else 0) + len(word)
        if next_length + 1 > max_chars:
            break
        pieces.append(word)
        current_length = next_length

    if not pieces:
        return normalized[: max(1, max_chars - 1)].rstrip() + "…"

    return " ".join(pieces) + "…"


def apply_reference_mode_to_cue(cue: DisplayCue, style: BilingualSubtitleStyle) -> None:
    mode = normalize_inline_text(style.reference_mode or "compact").lower()
    if mode == "full":
        return

    max_chars = int(style.en_max_single_line_chars or 78)
    zh_limit = max(1, int(style.zh_max_chars_per_line or 28) * max(1, int(style.zh_max_lines or 2)))
    duration = max(0.001, float(cue.end) - float(cue.start))
    zh_text = cue.zh_text or ""
    zh_overflow = visible_text_length(zh_text) > zh_limit or visible_text_cps(zh_text, duration) > 18.0
    en_overflow = len(normalize_inline_text(cue.en_text)) > max_chars

    if mode == "hide_when_overflow":
        if zh_overflow or en_overflow:
            cue.en_text = ""
            cue.rewrite_action = "reference_hidden"
        return

    if mode == "compact" and en_overflow:
        compacted = compact_reference_text(cue.en_text, max_chars)
        if compacted != cue.en_text:
            cue.en_text = compacted
            cue.rewrite_action = "reference_compact"


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


def score_grouping_quality(groups: list[str], *, max_chars: int) -> float:
    if not groups:
        return 1_000_000
    overflow = sum(max(0, visible_text_length(group) - max_chars) for group in groups)
    short_penalty = sum(1 for group in groups if visible_text_length(group) < max(6, max_chars // 4))
    variance = 0.0
    lengths = [visible_text_length(group) for group in groups]
    avg = sum(lengths) / len(lengths)
    variance = sum((length - avg) ** 2 for length in lengths)
    return overflow * 100 + short_penalty * 25 + variance


def merge_english_groups_for_alignment(
    groups: list[str],
    *,
    max_chars: int,
    target_group_count: int,
) -> list[str]:
    groups = [normalize_inline_text(group) for group in groups if normalize_inline_text(group)]
    target_group_count = max(1, target_group_count)
    soft_limit = int(max_chars * 1.28)
    while len(groups) > target_group_count:
        best_index = None
        best_score = None
        for index in range(len(groups) - 1):
            merged = normalize_inline_text(f"{groups[index]} {groups[index + 1]}")
            merged_length = visible_text_length(merged)
            overflow_penalty = max(0, merged_length - soft_limit) * 100
            split_penalty = abs(visible_text_length(groups[index]) - visible_text_length(groups[index + 1]))
            score = overflow_penalty + split_penalty + score_grouping_quality(
                groups[:index] + [merged] + groups[index + 2 :],
                max_chars=max_chars,
            )
            if best_score is None or score < best_score:
                best_score = score
                best_index = index
        if best_index is None:
            break
        merged = normalize_inline_text(f"{groups[best_index]} {groups[best_index + 1]}")
        groups[best_index : best_index + 2] = [merged]
    return groups


def count_adjacent_repeats(items: list[str]) -> int:
    return sum(1 for previous, current in zip(items, items[1:]) if previous and current and previous == current)


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

    # 中文语义块少于英文拆分段时，尽量把中文按顺序再细分，
    # 而不是简单重复整句去填满后续英文子段。
    if len(chunks) == 1:
        return split_single_chinese_chunk(chunks[0], part_count)

    if len(chunks) < part_count:
        expanded: list[str] = []
        base_weights = [visible_text_length(chunk) for chunk in chunks]
        total_weight = max(1, sum(base_weights))
        for chunk_index, chunk in enumerate(chunks):
            weight = base_weights[chunk_index]
            allocated = max(1, round(part_count * weight / total_weight))
            split_parts = split_single_chinese_chunk(chunk, allocated)
            expanded.extend(split_parts)
        return [part for part in expanded if part]

    parts: list[str] = []
    for index in range(part_count):
        mapped_index = min(len(chunks) - 1, round(index * (len(chunks) - 1) / max(1, part_count - 1)))
        parts.append(chunks[mapped_index])
    return parts


def split_single_chinese_chunk(text: str, part_count: int) -> list[str]:
    text = normalize_inline_text(text)
    if part_count <= 1 or not text:
        return [text] if text else []

    tokens = [token for token in tokenize_mixed_text(text) if token]
    if not tokens:
        return [text]

    total_visible = max(1, visible_text_length(text))
    target_visible = max(1, total_visible // part_count)
    parts: list[str] = []
    current = ""

    for token_index, token in enumerate(tokens):
        candidate = f"{current}{token}" if current else token
        remaining_tokens = len(tokens) - (token_index + 1)
        remaining_parts = part_count - len(parts) - 1
        if (
            current.strip()
            and visible_text_length(candidate) > target_visible
            and remaining_tokens >= remaining_parts
        ):
            parts.append(current.strip())
            current = token
        else:
            current = candidate

    if current.strip():
        parts.append(current.strip())

    while len(parts) < part_count and parts:
        longest_index = max(range(len(parts)), key=lambda idx: visible_text_length(parts[idx]))
        longest = parts.pop(longest_index)
        split_parts = split_long_chinese_chunk(longest, max(1, visible_text_length(longest) // 2))
        if len(split_parts) <= 1:
            parts.insert(longest_index, longest)
            break
        for offset, part in enumerate(split_parts):
            parts.insert(longest_index + offset, part)

    while len(parts) > part_count:
        tail = parts.pop()
        parts[-1] = f"{parts[-1]}{tail}".strip()

    return parts[:part_count]


def build_chinese_groups_for_english(text: str, english_groups: list[str]) -> list[str]:
    text = normalize_inline_text(text)
    if not english_groups:
        return []
    if len(english_groups) == 1 or not text:
        return [text] if text else [""]

    base_chunks = [normalize_inline_text(chunk) for chunk in split_by_meaning(text) if normalize_inline_text(chunk)]
    target_count = len(english_groups)
    if not base_chunks:
        return []

    while len(base_chunks) < target_count:
        split_index = max(range(len(base_chunks)), key=lambda idx: visible_text_length(base_chunks[idx]))
        split_parts = split_single_chinese_chunk(base_chunks[split_index], 2)
        split_parts = [normalize_inline_text(part) for part in split_parts if normalize_inline_text(part)]
        if len(split_parts) <= 1:
            break
        base_chunks[split_index : split_index + 1] = split_parts

    if len(base_chunks) == target_count:
        return [normalize_inline_text(chunk) for chunk in base_chunks]

    if len(base_chunks) > target_count:
        weights = [max(1, visible_text_length(group)) for group in english_groups]
        total_weight = sum(weights)
        total_chars = max(1, sum(visible_text_length(chunk) for chunk in base_chunks))
        target_chars = [max(1, round(total_chars * weight / total_weight)) for weight in weights]
        groups: list[str] = []
        chunk_index = 0
        for group_index, target_char in enumerate(target_chars):
            remaining_groups = target_count - group_index - 1
            current_chunks: list[str] = []
            current_chars = 0
            while chunk_index < len(base_chunks) - remaining_groups:
                if current_chunks and current_chars >= target_char:
                    break
                chunk = base_chunks[chunk_index]
                current_chunks.append(chunk)
                current_chars += visible_text_length(chunk)
                chunk_index += 1
            groups.append(normalize_inline_text("".join(current_chunks)))
        if chunk_index < len(base_chunks) and groups:
            groups[-1] = normalize_inline_text(groups[-1] + "".join(base_chunks[chunk_index:]))
        groups = [normalize_inline_text(group) for group in groups]
        if len(groups) == target_count and all(groups):
            return groups
        return []

    expanded = base_chunks[:]
    while len(expanded) < target_count:
        split_index = max(range(len(expanded)), key=lambda idx: visible_text_length(expanded[idx]))
        split_parts = split_single_chinese_chunk(expanded[split_index], 2)
        split_parts = [normalize_inline_text(part) for part in split_parts if normalize_inline_text(part)]
        if len(split_parts) <= 1:
            break
        expanded[split_index : split_index + 1] = split_parts
    expanded = [normalize_inline_text(chunk) for chunk in expanded if normalize_inline_text(chunk)]
    if len(expanded) == target_count and all(expanded):
        return expanded
    return []


def duration_for_split(segment: Segment, part_count: int, index: int) -> tuple[float, float]:
    duration = max(0.0, segment.end - segment.start)
    start = segment.start + duration * index / part_count
    end = segment.start + duration * (index + 1) / part_count
    return start, end


def split_segment_for_bilingual_ass(
    segment: Segment,
    style: BilingualSubtitleStyle,
    *,
    split_long_source: bool = False,
) -> tuple[list[DisplayCue], dict]:
    source_text = normalize_english_reference_text(segment.source_text)
    target_text = normalize_inline_text(segment.target_text or "")
    max_chars = int(style.en_max_single_line_chars or 78)
    max_parts = int(style.en_max_split_parts or 3)

    if not split_long_source or english_fits_single_line(source_text, max_chars):
        cues = [
            DisplayCue(
                start=segment.start,
                end=segment.end,
                en_text=source_text,
                zh_text=target_text or None,
                words=segment.words,
                source_segment_id=segment.id,
                group_index=1,
                group_total=1,
                rewrite_action="reference_full",
            )
        ]
        for cue in cues:
            apply_reference_mode_to_cue(cue, style)
        return cues, build_alignment_debug(segment, [source_text], [target_text or ""], cues, merged=False, style=style)

    text_parts = split_english_text(source_text, max_chars, max_parts=max_parts)
    merged = False
    base_target_groups = max(1, len(split_by_meaning(target_text))) if target_text else 1
    max_allowed_groups = min(max_parts, max(len(text_parts), base_target_groups))
    chosen_english_parts: list[str] | None = None
    chosen_zh_parts: list[str] | None = None

    for candidate_count in range(max_allowed_groups, 0, -1):
        english_candidate = merge_english_groups_for_alignment(
            text_parts,
            max_chars=max_chars,
            target_group_count=candidate_count,
        )
        zh_candidate = build_chinese_groups_for_english(target_text, english_candidate)
        if len(english_candidate) != len(zh_candidate):
            continue
        if any(not item.strip() for item in zh_candidate):
            continue
        if count_adjacent_repeats(zh_candidate) > 0 and candidate_count > 1:
            continue
        chosen_english_parts = english_candidate
        chosen_zh_parts = zh_candidate
        merged = merged or (english_candidate != text_parts)
        break

    if not chosen_english_parts or not chosen_zh_parts:
        cues = [
            DisplayCue(
                start=segment.start,
                end=segment.end,
                en_text=source_text,
                zh_text=target_text or None,
                words=segment.words,
                source_segment_id=segment.id,
                group_index=1,
                group_total=1,
            )
        ]
        for cue in cues:
            apply_reference_mode_to_cue(cue, style)
        return cues, build_alignment_debug(segment, [source_text], [target_text or ""], cues, merged=merged, style=style)

    text_parts = chosen_english_parts
    zh_parts = chosen_zh_parts
    word_groups = split_words_by_english_parts(segment.words, text_parts) if segment.words else []

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
                source_segment_id=segment.id,
                group_index=index + 1,
                group_total=len(text_parts),
                rewrite_action="reference_split" if len(text_parts) > 1 else "reference_full",
            )
        )

    cues = enforce_minimum_split_durations(split_segments, segment, style.min_split_duration)
    for cue in cues:
        apply_reference_mode_to_cue(cue, style)
    return cues, build_alignment_debug(segment, text_parts, zh_parts, cues, merged=merged, style=style)


def enforce_minimum_split_durations(
    segments: list[DisplayCue],
    original: Segment,
    min_duration: float,
) -> list[DisplayCue]:
    if len(segments) <= 1:
        return segments

    min_duration = max(2.0, float(min_duration or 2.0))
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
    *,
    split_long_source: bool = False,
) -> tuple[list[DisplayCue], list[dict]]:
    prepared: list[DisplayCue] = []
    debug_rows: list[dict] = []
    for segment in segments:
        cues, debug_row = split_segment_for_bilingual_ass(segment, style, split_long_source=split_long_source)
        prepared.extend(cues)
        debug_rows.append(debug_row)

    return prepared, debug_rows


def build_alignment_debug(
    segment: Segment,
    english_groups: list[str],
    chinese_groups: list[str],
    cues: list[DisplayCue],
    *,
    merged: bool,
    style: BilingualSubtitleStyle,
) -> dict:
    duration = max(0.001, float(segment.end) - float(segment.start))
    zh_joined = normalize_inline_text(" ".join(part for part in chinese_groups if part))
    rendered_lines = [
        wrap_chinese_text(
            cue.zh_text or "",
            trigger_chars=style.zh_wrap_trigger_chars,
            max_chars=style.zh_max_chars_per_line,
            max_lines=style.zh_max_lines,
        )
        for cue in cues
        if cue.zh_text
    ]
    line_counts = [len(rendered.splitlines() or [rendered]) for rendered in rendered_lines if rendered]
    cue_actions = sorted({cue.rewrite_action for cue in cues if cue.rewrite_action and cue.rewrite_action != "none"})
    rewrite_action: str | list[str]
    if not cue_actions:
        rewrite_action = "none"
    elif len(cue_actions) == 1:
        rewrite_action = cue_actions[0]
    else:
        rewrite_action = cue_actions
    return {
        "segment_id": segment.id,
        "source_segment_id": segment.id,
        "start": segment.start,
        "end": segment.end,
        "duration": round(duration, 3),
        "source_text": segment.source_text,
        "target_text": segment.target_text or "",
        "english_groups": english_groups,
        "chinese_groups": chinese_groups,
        "english_group_count": len(english_groups),
        "chinese_group_count": len(chinese_groups),
        "english_merged_for_alignment": merged,
        "reference_mode": normalize_inline_text(style.reference_mode or "compact").lower(),
        "zh_cps": round(visible_text_cps(zh_joined, duration), 2) if zh_joined else 0.0,
        "zh_line_count": max(line_counts) if line_counts else 0,
        "rewrite_action": rewrite_action,
        "cues": [
            {
                "group_index": cue.group_index,
                "group_total": cue.group_total,
                "start": cue.start,
                "end": cue.end,
                "en_text": cue.en_text,
                "zh_text": cue.zh_text or "",
                "rewrite_action": cue.rewrite_action,
            }
            for cue in cues
        ],
        "group_pairings": [
            {
                "index": cue.group_index,
                "english": english_groups[cue.group_index - 1] if cue.group_index - 1 < len(english_groups) else "",
                "chinese": chinese_groups[cue.group_index - 1] if cue.group_index - 1 < len(chinese_groups) else "",
                "rewrite_action": cue.rewrite_action,
            }
            for cue in cues
        ],
    }


def write_srt(segments: list[Segment], output_path: str | Path) -> None:
    ensure_parent(output_path)
    lines: list[str] = []

    for idx, segment in enumerate(segments, start=1):
        text = segment.target_text or segment.source_text
        if segment.target_text is None:
            text = capitalize_first_person_i(text)
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
    *,
    split_long_source: bool = False,
) -> list[dict]:
    ensure_parent(output_path)
    if style is None:
        style = BilingualSubtitleStyle()
    zh_primary = ass_color(style.zh_primary_color, style.zh_primary_opacity, fallback="#FFFFFF")
    zh_outline = ass_color(style.zh_outline_color, style.zh_outline_opacity, fallback="#141414")
    zh_shadow = ass_color(style.zh_shadow_color, style.zh_shadow_opacity, fallback="#000000")
    zh_outline_width = clamp_float(style.zh_outline_width, 0.0, 12.0, 2.2)
    zh_shadow_depth = clamp_float(style.zh_shadow_depth, 0.0, 12.0, 0.6)

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
Style: EnglishSmall,{style.en_font_name},{style.en_font_size},&H00E8E8E8,&H000000FF,&H00141414,&H50000000,0,0,0,0,100,100,0,0,1,1.6,0.4,2,{style.en_margin_l},{style.en_margin_r},{style.en_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines: list[str] = [header.rstrip()]
    cues, debug_rows = prepare_bilingual_ass_segments(segments, style, split_long_source=split_long_source)
    for cue in cues:
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

        en_text = escape_ass_text(normalize_english_reference_text(cue.en_text))
        if en_text:
            lines.append(f"Dialogue: 1,{start},{end},EnglishSmall,,0,0,0,,{en_text}")

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return debug_rows


def write_zh_ass(
    segments: list[Segment],
    output_path: str | Path,
    style: BilingualSubtitleStyle | None = None,
) -> None:
    ensure_parent(output_path)
    if style is None:
        style = BilingualSubtitleStyle()
    zh_primary = ass_color(style.zh_primary_color, style.zh_primary_opacity, fallback="#FFFFFF")
    zh_outline = ass_color(style.zh_outline_color, style.zh_outline_opacity, fallback="#141414")
    zh_shadow = ass_color(style.zh_shadow_color, style.zh_shadow_opacity, fallback="#000000")
    zh_outline_width = clamp_float(style.zh_outline_width, 0.0, 12.0, 2.2)
    zh_shadow_depth = clamp_float(style.zh_shadow_depth, 0.0, 12.0, 0.6)

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
