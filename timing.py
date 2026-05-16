from __future__ import annotations

import re

from .models import BilingualSubtitleStyle, Segment, SubtitleRules, Word
from .utils import normalize_text


SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")
CLAUSE_ENDINGS = (",", ";", ":", "，", "；", "：")
SOFT_SPLIT_WORDS = {
    "and",
    "but",
    "or",
    "so",
    "because",
    "when",
    "while",
    "which",
    "that",
    "if",
}
BAD_SPLIT_EDGE_WORDS = {
    "a",
    "an",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}
TARGET_DISPLAY_DURATION = 2.8


def clone_segment(segment: Segment, *, words: list[Word], text: str) -> Segment:
    """Clone a segment after a word-boundary split.

    Word objects are atomic throughout the timing layer. Splits may happen
    between Word items, but never inside ``word.word``.
    """
    return Segment(
        id=segment.id,
        start=float(words[0].start),
        end=float(words[-1].end),
        source_text=normalize_text(text),
        target_text=None,
        words=words,
        confidence=segment.confidence,
        source=segment.source,
    )


def should_split_after_word(
    current_words: list[Word],
    next_word: Word | None,
    rules: SubtitleRules,
) -> bool:
    if not current_words or next_word is None:
        return False

    current_text = normalize_text(" ".join(word.word for word in current_words))
    if not current_text:
        return False

    gap = max(0.0, next_word.start - current_words[-1].end)
    last_word = current_words[-1].word.strip()

    if gap >= rules.strong_pause_split_threshold:
        return True

    if last_word.endswith(SENTENCE_ENDINGS) and len(current_text) >= rules.sentence_split_min_chars and gap >= rules.pause_split_threshold:
        return True

    return False


def split_segment_by_max_duration(segment: Segment, rules: SubtitleRules) -> list[Segment]:
    """Split long segments only at word boundaries."""
    if not segment.words:
        return [segment]

    built_segments: list[Segment] = []
    current_words: list[Word] = []

    for index, word in enumerate(segment.words):
        current_words.append(word)
        current_duration = current_words[-1].end - current_words[0].start
        next_word = segment.words[index + 1] if index + 1 < len(segment.words) else None

        if current_duration < rules.max_duration:
            continue

        if len(current_words) == 1:
            text = current_words[0].word
            built_segments.append(clone_segment(segment, words=current_words[:], text=text))
            current_words = []
            continue

        split_index = len(current_words) - 1
        candidate_words = current_words[:-1]
        candidate_text = normalize_text(" ".join(item.word for item in candidate_words))
        if candidate_text:
            built_segments.append(clone_segment(segment, words=candidate_words, text=candidate_text))
            current_words = [current_words[-1]]

    if current_words:
        text = " ".join(item.word for item in current_words)
        built_segments.append(clone_segment(segment, words=current_words[:], text=text))

    return [item for item in built_segments if normalize_text(item.source_text)]


def visible_source_length(text: str) -> int:
    return len(normalize_text(text))


def words_to_source_text(words: list[Word]) -> str:
    return normalize_text(" ".join(word.word.strip() for word in words if word.word.strip()))


def word_gap(current: Word, next_word: Word | None) -> float:
    if next_word is None:
        return 0.0
    return max(0.0, float(next_word.start) - float(current.end))


def count_source_lines(text: str, max_chars: int) -> int:
    length = max(0, visible_source_length(text))
    if length == 0:
        return 0
    return max(1, (length + max_chars - 1) // max_chars)


def is_soft_boundary(word: Word, next_word: Word | None, rules: SubtitleRules) -> bool:
    cleaned = word.word.strip()
    lowered_next = re.sub(r"[^A-Za-z']+", "", (next_word.word if next_word else "").lower())
    if cleaned.endswith(SENTENCE_ENDINGS):
        return True
    if cleaned.endswith(CLAUSE_ENDINGS):
        return True
    if lowered_next in SOFT_SPLIT_WORDS:
        return True
    if word_gap(word, next_word) >= rules.pause_split_threshold:
        return True
    return False


def score_display_split(
    words: list[Word],
    split_index: int,
    *,
    max_chars: int,
    rules: SubtitleRules,
) -> float:
    left_words = words[:split_index]
    right_words = words[split_index:]
    left_text = words_to_source_text(left_words)
    right_text = words_to_source_text(right_words)
    if not left_text or not right_text:
        return 1_000_000.0

    left_duration = float(left_words[-1].end) - float(left_words[0].start)
    right_duration = float(right_words[-1].end) - float(right_words[0].start)
    left_len = visible_source_length(left_text)
    right_len = visible_source_length(right_text)
    left_overflow = max(0, left_len - max_chars)
    right_overflow = max(0, right_len - max_chars)
    left_line_count = count_source_lines(left_text, max_chars)
    right_line_count = count_source_lines(right_text, max_chars)
    min_readable_chars = min(18, max(8, max_chars // 4))
    left_last_word = re.sub(r"[^A-Za-z']+", "", left_words[-1].word.lower())
    right_first_word = re.sub(r"[^A-Za-z']+", "", right_words[0].word.lower())
    duration_penalty = 0.0
    if left_duration < rules.min_duration:
        duration_penalty += (rules.min_duration - left_duration) * 90
    if right_duration < rules.min_duration:
        duration_penalty += (rules.min_duration - right_duration) * 90
    if left_duration > rules.max_duration:
        duration_penalty += (left_duration - rules.max_duration) * 80
    if right_duration > rules.max_duration:
        duration_penalty += (right_duration - rules.max_duration) * 80

    balance = abs(left_len - right_len)
    short_text_penalty = 0.0
    if left_len < min_readable_chars and left_duration < 1.4:
        short_text_penalty += (min_readable_chars - left_len) * 8
    if right_len < min_readable_chars and right_duration < 1.4:
        short_text_penalty += (min_readable_chars - right_len) * 8
    bad_edge_penalty = 0.0
    if left_last_word in BAD_SPLIT_EDGE_WORDS:
        bad_edge_penalty += 80
    if right_first_word in {"of", "from", "to", "with", "for"}:
        bad_edge_penalty += 45
    line_penalty = max(0, left_line_count - rules.max_lines) * 120 + max(0, right_line_count - rules.max_lines) * 120
    overflow_penalty = (left_overflow + right_overflow) * 12
    boundary_bonus = -45 if is_soft_boundary(left_words[-1], right_words[0], rules) else 0
    pause_bonus = -30 if word_gap(left_words[-1], right_words[0]) >= rules.pause_split_threshold else 0
    return duration_penalty + line_penalty + overflow_penalty + short_text_penalty + bad_edge_penalty + balance + boundary_bonus + pause_bonus


def choose_display_split_index(words: list[Word], *, max_chars: int, rules: SubtitleRules) -> int:
    if len(words) <= 1:
        return 1
    candidates = range(1, len(words))
    return min(candidates, key=lambda index: score_display_split(words, index, max_chars=max_chars, rules=rules))


def score_display_group(
    words: list[Word],
    start_index: int,
    end_index: int,
    *,
    max_chars: int,
    rules: SubtitleRules,
) -> float:
    group = words[start_index:end_index]
    if not group:
        return 1_000_000.0

    text = words_to_source_text(group)
    duration = max(0.001, float(group[-1].end) - float(group[0].start))
    length = visible_source_length(text)
    overflow = max(0, length - max_chars)
    line_count = count_source_lines(text, max_chars)
    cps = length / duration
    score = 0.0

    score += overflow * 180
    score += max(0, line_count - 1) * 240
    score += abs(duration - TARGET_DISPLAY_DURATION) * 8
    if duration < rules.min_duration:
        score += (rules.min_duration - duration) * 130
    if duration > rules.max_duration:
        score += (duration - rules.max_duration) * 130
    if cps > 24.0:
        score += (cps - 24.0) * 18
    if length < min(18, max(8, max_chars // 4)) and duration < 1.4:
        score += (min(18, max(8, max_chars // 4)) - length) * 10

    last_word = re.sub(r"[^A-Za-z']+", "", group[-1].word.lower())
    if last_word in BAD_SPLIT_EDGE_WORDS and end_index < len(words):
        score += 80

    next_word = words[end_index] if end_index < len(words) else None
    if end_index < len(words):
        if is_soft_boundary(group[-1], next_word, rules):
            score -= 45
        if word_gap(group[-1], next_word) >= rules.pause_split_threshold:
            score -= 35
    return score


def choose_display_word_groups(
    words: list[Word],
    *,
    max_chars: int,
    rules: SubtitleRules,
) -> list[list[Word]]:
    count = len(words)
    if count <= 1:
        return [words]

    best: list[float] = [1_000_000_000.0] * (count + 1)
    previous: list[int | None] = [None] * (count + 1)
    best[0] = 0.0

    for start_index in range(count):
        if best[start_index] >= 1_000_000_000.0:
            continue
        for end_index in range(start_index + 1, count + 1):
            group = words[start_index:end_index]
            duration = float(group[-1].end) - float(group[0].start)
            text = words_to_source_text(group)
            length = visible_source_length(text)
            if duration > rules.max_duration + 1.2 and length > max_chars:
                break
            if length > max_chars * 1.6:
                break
            score = best[start_index] + score_display_group(
                words,
                start_index,
                end_index,
                max_chars=max_chars,
                rules=rules,
            )
            if start_index > 0:
                score += 10
            if score < best[end_index]:
                best[end_index] = score
                previous[end_index] = start_index

    if previous[count] is None:
        return []

    ranges: list[tuple[int, int]] = []
    end_index = count
    while end_index > 0:
        start_index = previous[end_index]
        if start_index is None:
            return []
        ranges.append((start_index, end_index))
        end_index = start_index
    ranges.reverse()
    return [words[start:end] for start, end in ranges]


def split_segment_for_display_limits(
    segment: Segment,
    *,
    rules: SubtitleRules,
    style: BilingualSubtitleStyle,
) -> list[Segment]:
    if not segment.words or len(segment.words) <= 1:
        return [segment]

    max_chars = max(20, int(style.en_max_single_line_chars or rules.max_chars_per_line))
    max_total_chars = max_chars
    text = normalize_text(segment.source_text)
    duration = max(0.0, segment.end - segment.start)
    line_count = count_source_lines(text, max_chars)
    should_split = (
        visible_source_length(text) > max_total_chars
        or line_count > 1
        or duration > rules.max_duration
    )
    if not should_split:
        return [segment]

    word_groups = choose_display_word_groups(segment.words, max_chars=max_chars, rules=rules)
    if not word_groups or len(word_groups) <= 1:
        split_index = choose_display_split_index(segment.words, max_chars=max_chars, rules=rules)
        if split_index <= 0 or split_index >= len(segment.words):
            return [segment]
        word_groups = [segment.words[:split_index], segment.words[split_index:]]

    return [
        clone_segment(segment, words=group, text=words_to_source_text(group))
        for group in word_groups
        if words_to_source_text(group)
    ]


def split_segment_on_pause(segment: Segment, rules: SubtitleRules) -> list[Segment]:
    """Split on pauses only after a complete Word item."""
    if not segment.words:
        return [segment]

    built_segments: list[Segment] = []
    current_words: list[Word] = []

    for index, word in enumerate(segment.words):
        current_words.append(word)
        next_word = segment.words[index + 1] if index + 1 < len(segment.words) else None
        if should_split_after_word(current_words, next_word, rules):
            text = " ".join(item.word for item in current_words)
            built_segments.append(clone_segment(segment, words=current_words[:], text=text))
            current_words = []

    if current_words:
        text = " ".join(item.word for item in current_words)
        built_segments.append(clone_segment(segment, words=current_words[:], text=text))

    return [item for item in built_segments if normalize_text(item.source_text)]


def refine_timing(
    segments: list[Segment],
    *,
    rules: SubtitleRules | None = None,
    style: BilingualSubtitleStyle | None = None,
) -> list[Segment]:
    if rules is None:
        rules = SubtitleRules()
    if style is None:
        style = BilingualSubtitleStyle()

    pre_split: list[Segment] = []
    for segment in segments:
        text = normalize_text(segment.source_text)
        if not text:
            continue
        segment.source_text = text
        for pause_split in split_segment_on_pause(segment, rules):
            for duration_split in split_segment_by_max_duration(pause_split, rules):
                pre_split.extend(split_segment_for_display_limits(duration_split, rules=rules, style=style))

    cleaned: list[Segment] = []
    previous_end = 0.0

    for segment in pre_split:
        text = normalize_text(segment.source_text)
        if not text:
            continue

        start = max(segment.start, previous_end + rules.min_gap if cleaned else 0.0)
        end = max(segment.end, start + rules.min_duration)
        if end - start > rules.max_duration:
            end = start + rules.max_duration

        segment.start = start
        segment.end = end
        segment.source_text = text
        cleaned.append(segment)
        previous_end = end

    for idx, segment in enumerate(cleaned, start=1):
        segment.id = idx

    return cleaned
