from __future__ import annotations

import re

TERMINAL_RE = re.compile(r"[.!?][\"')\]]*$")

TERMINAL_SHORT_NOT = "not_terminal_short"
TERMINAL_CONTENT_TAIL = "content_tail"
TERMINAL_STANDALONE_PARTICLE = "standalone_particle"
TERMINAL_AMBIGUOUS_PARTICLE = "ambiguous_particle"

STRONG_DISCOURSE_PARTICLES = {
    "ah",
    "all right",
    "alright",
    "hey",
    "hmm",
    "huh",
    "no",
    "nope",
    "oh",
    "ok",
    "okay",
    "uh",
    "um",
    "whoa",
    "wow",
    "yeah",
    "yep",
    "yes",
    "you know",
    "yup",
}

AMBIGUOUS_DISCOURSE_PARTICLES = {
    "fine",
    "please",
    "right",
    "sure",
    "thanks",
    "well",
}

OPEN_TAIL_WORDS = {
    "a",
    "am",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "being",
    "but",
    "by",
    "called",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "made",
    "named",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "when",
    "while",
    "with",
}

QUESTION_RESPONSE_PARTICLES = {"ok", "okay", "right", "sure"}


def terminal_tail_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", text or "")


def terminal_tail_word_count(text: str) -> int:
    return len(terminal_tail_tokens(text))


def first_terminal_tail_token(text: str) -> str:
    tokens = terminal_tail_tokens(text)
    return tokens[0].lower() if tokens else ""


def terminal_tail_phrase(text: str) -> str:
    return " ".join(token.lower() for token in terminal_tail_tokens(text))


def has_ascii_terminal(text: str) -> bool:
    return bool(TERMINAL_RE.search((text or "").strip()))


def left_is_open_for_tail(text: str) -> bool:
    tokens = terminal_tail_tokens(text)
    if not tokens:
        return False
    if not has_ascii_terminal(text):
        return True
    return tokens[-1].lower() in OPEN_TAIL_WORDS


def classify_terminal_short_text(
    left_text: str,
    right_text: str,
    *,
    gap: float | None = None,
    independent_gap: float = 0.18,
) -> str:
    right_text = (right_text or "").strip()
    if not right_text or terminal_tail_word_count(right_text) > 2 or not has_ascii_terminal(right_text):
        return TERMINAL_SHORT_NOT

    if left_is_open_for_tail(left_text):
        return TERMINAL_CONTENT_TAIL

    phrase = terminal_tail_phrase(right_text)
    first = first_terminal_tail_token(right_text)

    if phrase in STRONG_DISCOURSE_PARTICLES:
        if gap is None or gap >= independent_gap:
            return TERMINAL_STANDALONE_PARTICLE
        return TERMINAL_AMBIGUOUS_PARTICLE

    if (left_text or "").strip().endswith("?") and first in QUESTION_RESPONSE_PARTICLES:
        return TERMINAL_STANDALONE_PARTICLE

    if phrase in AMBIGUOUS_DISCOURSE_PARTICLES:
        return TERMINAL_AMBIGUOUS_PARTICLE

    if right_text[:1].islower():
        return TERMINAL_CONTENT_TAIL
    return TERMINAL_SHORT_NOT
