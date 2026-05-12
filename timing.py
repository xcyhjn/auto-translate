from __future__ import annotations

from .models import Segment, SubtitleRules, Word
from .utils import normalize_text


SENTENCE_ENDINGS = (".", "!", "?", "。", "！", "？")


def clone_segment(segment: Segment, *, words: list[Word], text: str) -> Segment:
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


def split_segment_on_pause(segment: Segment, rules: SubtitleRules) -> list[Segment]:
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
) -> list[Segment]:
    if rules is None:
        rules = SubtitleRules()

    pre_split: list[Segment] = []
    for segment in segments:
        text = normalize_text(segment.source_text)
        if not text:
            continue
        segment.source_text = text
        for pause_split in split_segment_on_pause(segment, rules):
            pre_split.extend(split_segment_by_max_duration(pause_split, rules))

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
