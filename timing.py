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
CONTINUATION_START_WORDS = {
    "and",
    "as",
    "because",
    "but",
    "except",
    "for",
    "from",
    "if",
    "in",
    "of",
    "or",
    "since",
    "that",
    "then",
    "though",
    "to",
    "unless",
    "until",
    "when",
    "where",
    "which",
    "while",
    "who",
    "with",
}
SENTENCE_INITIAL_WORDS = {
    "a",
    "after",
    "all",
    "another",
    "as",
    "at",
    "but",
    "dmitri",
    "he",
    "his",
    "i",
    "if",
    "in",
    "it",
    "it's",
    "meanwhile",
    "now",
    "she",
    "slowly",
    "some",
    "that",
    "the",
    "they",
    "this",
    "we",
    "what",
    "when",
    "while",
    "you",
}
TERMINAL_RE = re.compile(r"[.!?][\"')\]]*$")
ABBREVIATION_END_RE = re.compile(
    r"(?:^|[^A-Za-z])(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e)\.$",
    re.IGNORECASE,
)
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

    if gap >= rules.strong_pause_split_threshold:
        return True

    if (
        word_ends_sentence(current_words[-1])
        and len(current_text) >= rules.sentence_split_min_chars
        and starts_new_sentence(next_word)
        and (
            gap >= rules.sentence_boundary_split_gap
            or next_word.word.strip()[:1].isupper()
        )
    ):
        return True

    if (
        word_ends_sentence(current_words[-1])
        and len(current_text) >= rules.sentence_split_min_chars
        and gap >= rules.pause_split_threshold
    ):
        return True

    return False


def split_segment_by_max_duration(segment: Segment, rules: SubtitleRules) -> list[Segment]:
    """Split long segments only at word boundaries."""
    if not segment.words:
        return [segment]
    segment_duration = float(segment.end) - float(segment.start)
    if segment_duration <= rules.max_duration:
        return [segment]
    if (
        segment_duration <= rules.max_duration + rules.complete_sentence_duration_tolerance
        and ends_with_sentence_terminal(segment.source_text)
    ):
        return [segment]

    built_segments: list[Segment] = []
    remaining_words = segment.words[:]

    while remaining_words:
        duration = float(remaining_words[-1].end) - float(remaining_words[0].start)
        if duration <= rules.max_duration or len(remaining_words) <= 1:
            built_segments.append(clone_segment(segment, words=remaining_words[:], text=words_to_source_text(remaining_words)))
            break

        split_index = choose_duration_split_index(remaining_words, rules)
        if split_index <= 0 or split_index >= len(remaining_words):
            split_index = max(1, len(remaining_words) - 1)
        candidate_words = remaining_words[:split_index]
        built_segments.append(clone_segment(segment, words=candidate_words, text=words_to_source_text(candidate_words)))
        remaining_words = remaining_words[split_index:]

    return [item for item in built_segments if normalize_text(item.source_text)]


def visible_source_length(text: str) -> int:
    return len(normalize_text(text))


def words_to_source_text(words: list[Word]) -> str:
    return normalize_text(" ".join(word.word.strip() for word in words if word.word.strip()))


def clean_source_word(text: str) -> str:
    return re.sub(r"[^A-Za-z']+", "", (text or "").lower())


def source_word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def ends_with_sentence_terminal(text: str) -> bool:
    stripped = (text or "").strip()
    if not TERMINAL_RE.search(stripped):
        return False
    if ABBREVIATION_END_RE.search(stripped):
        return False
    return True


def word_ends_sentence(word: Word) -> bool:
    return ends_with_sentence_terminal(word.word.strip())


def starts_new_sentence(word: Word | None) -> bool:
    if word is None:
        return False
    raw = word.word.strip()
    lowered = raw.lower().strip("\"'([")
    first = clean_source_word(lowered)
    return bool(raw[:1].isupper() or lowered in SENTENCE_INITIAL_WORDS or first in SENTENCE_INITIAL_WORDS)


def is_bad_split_edge(left_words: list[Word], right_words: list[Word]) -> bool:
    if not left_words or not right_words:
        return False
    left_last = clean_source_word(left_words[-1].word)
    right_first = clean_source_word(right_words[0].word)
    return (
        left_last in BAD_SPLIT_EDGE_WORDS
        or right_first in CONTINUATION_START_WORDS
        or right_first in BAD_SPLIT_EDGE_WORDS
    )


def is_orphan_fragment(words: list[Word], rules: SubtitleRules) -> bool:
    if not words:
        return False
    text = words_to_source_text(words)
    count = source_word_count(text)
    duration = max(0.0, float(words[-1].end) - float(words[0].start))
    first = clean_source_word(words[0].word)
    last = clean_source_word(words[-1].word)
    if count <= 1:
        return True
    if count <= rules.orphan_word_threshold and not ends_with_sentence_terminal(text):
        return True
    if count <= rules.orphan_word_threshold and duration < rules.orphan_duration_threshold:
        return True
    if first in CONTINUATION_START_WORDS and count <= rules.orphan_word_threshold + 2:
        return True
    if last in BAD_SPLIT_EDGE_WORDS:
        return True
    return False


def is_open_fragment(segment: Segment) -> bool:
    text = normalize_text(segment.source_text)
    if not text:
        return False
    if ends_with_sentence_terminal(text):
        return False
    if segment.words and clean_source_word(segment.words[-1].word) in BAD_SPLIT_EDGE_WORDS:
        return True
    return True


def starts_with_continuation_fragment(segment: Segment) -> bool:
    if not segment.words:
        return False
    return clean_source_word(segment.words[0].word) in CONTINUATION_START_WORDS


def merge_segments(left: Segment, right: Segment) -> Segment:
    words = [*left.words, *right.words]
    text = words_to_source_text(words) if words else normalize_text(f"{left.source_text} {right.source_text}")
    return Segment(
        id=left.id,
        start=float(left.start),
        end=float(right.end),
        source_text=text,
        target_text=None,
        words=words,
        confidence=left.confidence if left.confidence is not None else right.confidence,
        source=left.source,
    )


def should_merge_adjacent(left: Segment, right: Segment, rules: SubtitleRules) -> bool:
    if not left.words or not right.words:
        return False
    gap = max(0.0, float(right.start) - float(left.end))
    merged_duration = float(right.end) - float(left.start)
    merged_text = words_to_source_text([*left.words, *right.words])
    merged_len = visible_source_length(merged_text)
    if ends_with_sentence_terminal(left.source_text) and starts_new_sentence(right.words[0]):
        return False
    if merged_duration > rules.max_duration + 0.35:
        return False
    if merged_duration > rules.max_duration and merged_len > rules.max_chars_per_line * 2:
        return False
    if is_orphan_fragment(left.words, rules) and gap <= rules.pause_split_threshold:
        return True
    if (
        is_orphan_fragment(right.words, rules)
        and not ends_with_sentence_terminal(right.source_text)
        and gap <= rules.pause_split_threshold
    ):
        return True
    if is_open_fragment(left) and starts_with_continuation_fragment(right) and gap <= rules.pause_split_threshold:
        return True
    if is_open_fragment(left) and gap <= rules.sentence_boundary_split_gap:
        return True
    if clean_source_word(left.words[-1].word) in BAD_SPLIT_EDGE_WORDS and gap <= rules.strong_pause_split_threshold:
        return True
    return False


def merge_incomplete_fragments(segments: list[Segment], rules: SubtitleRules) -> list[Segment]:
    merged: list[Segment] = []
    for segment in segments:
        if not merged:
            merged.append(segment)
            continue
        if should_merge_adjacent(merged[-1], segment, rules):
            merged[-1] = merge_segments(merged[-1], segment)
        else:
            merged.append(segment)
    return merged


def split_segment_on_sentence_boundaries(segment: Segment, rules: SubtitleRules) -> list[Segment]:
    if not segment.words or len(segment.words) <= 1:
        return [segment]

    groups: list[list[Word]] = []
    current_words: list[Word] = []
    for index, word in enumerate(segment.words):
        current_words.append(word)
        next_word = segment.words[index + 1] if index + 1 < len(segment.words) else None
        if not next_word:
            continue
        if not word_ends_sentence(word) or not starts_new_sentence(next_word):
            continue
        current_text = words_to_source_text(current_words)
        next_count = len(segment.words) - index - 1
        current_duration = float(current_words[-1].end) - float(current_words[0].start)
        next_duration = float(segment.words[-1].end) - float(next_word.start)
        gap = word_gap(word, next_word)
        if len(current_text) < rules.sentence_split_min_chars:
            continue
        if next_count < rules.sentence_boundary_min_next_words:
            continue
        if current_duration < 0.75 or next_duration < 0.75:
            continue
        if gap < rules.sentence_boundary_split_gap and not next_word.word.strip()[:1].isupper():
            continue
        groups.append(current_words[:])
        current_words = []

    if current_words:
        groups.append(current_words[:])
    if len(groups) <= 1:
        return [segment]
    return [
        clone_segment(segment, words=group, text=words_to_source_text(group))
        for group in groups
        if words_to_source_text(group)
    ]


def split_mixed_sentence_segments(segments: list[Segment], rules: SubtitleRules) -> list[Segment]:
    split_segments: list[Segment] = []
    for segment in segments:
        split_segments.extend(split_segment_on_sentence_boundaries(segment, rules))
    return split_segments


def word_gap(current: Word, next_word: Word | None) -> float:
    if next_word is None:
        return 0.0
    return max(0.0, float(next_word.start) - float(current.end))


def count_source_lines(text: str, max_chars: int) -> int:
    length = max(0, visible_source_length(text))
    if length == 0:
        return 0
    return max(1, (length + max_chars - 1) // max_chars)


def score_duration_split(words: list[Word], split_index: int, rules: SubtitleRules) -> float:
    left_words = words[:split_index]
    right_words = words[split_index:]
    if not left_words or not right_words:
        return 1_000_000.0

    left_text = words_to_source_text(left_words)
    right_text = words_to_source_text(right_words)
    left_duration = max(0.001, float(left_words[-1].end) - float(left_words[0].start))
    right_duration = max(0.001, float(right_words[-1].end) - float(right_words[0].start))
    gap = word_gap(left_words[-1], right_words[0])
    score = 0.0

    if left_duration > rules.max_duration:
        score += (left_duration - rules.max_duration) * 180
    if right_duration > rules.max_duration:
        score += (right_duration - rules.max_duration) * 140
    if left_duration < rules.min_duration:
        score += (rules.min_duration - left_duration) * 90
    if right_duration < rules.min_duration:
        score += (rules.min_duration - right_duration) * 120

    if is_orphan_fragment(left_words, rules):
        score += 280
    if is_orphan_fragment(right_words, rules):
        score += 360
    if is_bad_split_edge(left_words, right_words):
        score += 180

    left_len = visible_source_length(left_text)
    right_len = visible_source_length(right_text)
    score += abs(left_duration - min(rules.max_duration, TARGET_DISPLAY_DURATION + 1.5)) * 8
    score += abs(left_len - right_len) * 0.5

    if word_ends_sentence(left_words[-1]) and starts_new_sentence(right_words[0]):
        score -= 220
    elif left_words[-1].word.strip().endswith(CLAUSE_ENDINGS):
        score -= 80
    elif clean_source_word(right_words[0].word) in SOFT_SPLIT_WORDS:
        score -= 35

    if gap >= rules.strong_pause_split_threshold:
        score -= 160
    elif gap >= rules.pause_split_threshold:
        score -= 90
    elif gap >= rules.sentence_boundary_split_gap:
        score -= 35

    return score


def choose_duration_split_index(words: list[Word], rules: SubtitleRules) -> int:
    if len(words) <= 1:
        return 1

    viable: list[int] = []
    for index in range(1, len(words)):
        left_duration = float(words[index - 1].end) - float(words[0].start)
        if left_duration <= rules.max_duration + 0.4:
            viable.append(index)
    if not viable:
        viable = list(range(1, len(words)))

    return min(viable, key=lambda index: score_duration_split(words, index, rules))


def is_soft_boundary(word: Word, next_word: Word | None, rules: SubtitleRules) -> bool:
    cleaned = word.word.strip()
    lowered_next = re.sub(r"[^A-Za-z']+", "", (next_word.word if next_word else "").lower())
    if word_ends_sentence(word):
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
        duration_penalty += (rules.min_duration - left_duration) * 120
    if right_duration < rules.min_duration:
        duration_penalty += (rules.min_duration - right_duration) * 150
    if left_duration > rules.max_duration:
        duration_penalty += (left_duration - rules.max_duration) * 140
    if right_duration > rules.max_duration:
        duration_penalty += (right_duration - rules.max_duration) * 140

    balance = abs(left_len - right_len)
    short_text_penalty = 0.0
    if left_len < min_readable_chars and left_duration < 1.4:
        short_text_penalty += (min_readable_chars - left_len) * 18
    if right_len < min_readable_chars and right_duration < 1.4:
        short_text_penalty += (min_readable_chars - right_len) * 24
    if is_orphan_fragment(left_words, rules):
        short_text_penalty += 260
    if is_orphan_fragment(right_words, rules):
        short_text_penalty += 360
    bad_edge_penalty = 0.0
    if left_last_word in BAD_SPLIT_EDGE_WORDS:
        bad_edge_penalty += 180
    if right_first_word in CONTINUATION_START_WORDS or right_first_word in BAD_SPLIT_EDGE_WORDS:
        bad_edge_penalty += 160
    line_penalty = max(0, left_line_count - rules.max_lines) * 120 + max(0, right_line_count - rules.max_lines) * 120
    overflow_penalty = (left_overflow + right_overflow) * 12
    boundary_bonus = -60 if is_soft_boundary(left_words[-1], right_words[0], rules) else 0
    if word_ends_sentence(left_words[-1]) and starts_new_sentence(right_words[0]):
        boundary_bonus -= 180
    pause_bonus = -45 if word_gap(left_words[-1], right_words[0]) >= rules.pause_split_threshold else 0
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

    score += overflow * 90
    score += max(0, line_count - rules.max_lines) * 200
    score += abs(duration - TARGET_DISPLAY_DURATION) * 4
    if duration < rules.min_duration:
        score += (rules.min_duration - duration) * 150
    if duration > rules.max_duration:
        score += (duration - rules.max_duration) * 180
    if cps > 24.0:
        score += (cps - 24.0) * 18
    if length < min(18, max(8, max_chars // 4)) and duration < 1.4:
        score += (min(18, max(8, max_chars // 4)) - length) * 20
    if is_orphan_fragment(group, rules):
        score += 300

    last_word = re.sub(r"[^A-Za-z']+", "", group[-1].word.lower())
    if last_word in BAD_SPLIT_EDGE_WORDS and end_index < len(words):
        score += 180

    next_word = words[end_index] if end_index < len(words) else None
    if end_index < len(words):
        next_clean = clean_source_word(next_word.word if next_word else "")
        if next_clean in CONTINUATION_START_WORDS or next_clean in BAD_SPLIT_EDGE_WORDS:
            score += 160
        if is_soft_boundary(group[-1], next_word, rules):
            score -= 60
        if word_ends_sentence(group[-1]) and starts_new_sentence(next_word):
            score -= 180
        if word_gap(group[-1], next_word) >= rules.pause_split_threshold:
            score -= 45
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
            if duration > rules.max_duration + 1.2 and length > max_chars * rules.display_overflow_tolerance:
                break
            if length > max_chars * 2.0:
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
    max_total_chars = int(max_chars * rules.display_overflow_tolerance)
    text = normalize_text(segment.source_text)
    duration = max(0.0, segment.end - segment.start)
    line_count = count_source_lines(text, max_chars)
    length = visible_source_length(text)
    cps = length / max(duration, 0.001)
    should_split = (
        length > max_total_chars
        or line_count > rules.max_lines
        or duration > rules.max_duration
        or (cps > 28.0 and length > max_chars)
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
            pre_split.append(pause_split)

    regrouped = split_mixed_sentence_segments(merge_incomplete_fragments(pre_split, rules), rules)
    duration_limited: list[Segment] = []
    for segment in regrouped:
        duration_limited.extend(split_segment_by_max_duration(segment, rules))

    display_limited: list[Segment] = []
    for segment in split_mixed_sentence_segments(merge_incomplete_fragments(duration_limited, rules), rules):
        display_limited.extend(split_segment_for_display_limits(segment, rules=rules, style=style))

    pre_split = split_mixed_sentence_segments(merge_incomplete_fragments(display_limited, rules), rules)

    cleaned: list[Segment] = []
    previous_end = 0.0

    for segment in pre_split:
        text = normalize_text(segment.source_text)
        if not text:
            continue

        start = max(segment.start, previous_end + rules.min_gap if cleaned else segment.start)
        end = max(segment.end, start + 0.05)

        segment.start = start
        segment.end = end
        segment.source_text = text
        cleaned.append(segment)
        previous_end = end

    for idx, segment in enumerate(cleaned, start=1):
        segment.id = idx

    return cleaned
