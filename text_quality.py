from __future__ import annotations

import re
import unicodedata


TRANSLATABLE_DISCOURSE_MARKERS = {
    "actually",
    "again",
    "alright",
    "and",
    "anyway",
    "basically",
    "because",
    "but",
    "cause",
    "exactly",
    "honestly",
    "i",
    "i'd",
    "i'll",
    "i'm",
    "i've",
    "im",
    "just",
    "like",
    "literally",
    "maybe",
    "okay",
    "ok",
    "right",
    "see",
    "seriously",
    "so",
    "sure",
    "that's",
    "thats",
    "then",
    "though",
    "well",
    "yeah",
    "yep",
    "yes",
}
DISCOURSE_MARKER_RE = re.compile(
    rf"(?<![A-Za-z0-9_.-])({'|'.join(sorted(map(re.escape, TRANSLATABLE_DISCOURSE_MARKERS), key=len, reverse=True))})(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)

ASMR_PET_CONTEXT_RE = re.compile(
    r"\b(?:good\s+boy|puppy|pup|pet|pat|rub|cuddle|comfort|darling|feel\s+good|head|hair|forever)\b",
    re.IGNORECASE,
)
SOURCE_ASR_SUSPICION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(?:i(?:'|’)?ll|i\s+will|when\s+i|while\s+i|if\s+i)\s+bet\s+you\b", re.IGNORECASE),
        "possible_pet_bet_misrecognition",
    ),
    (
        re.compile(r"\bfeel\s+good\s+good\b", re.IGNORECASE),
        "duplicated_source_word",
    ),
    (
        re.compile(r"\byou\s+don'?t\s+need\s+me\s+to\s+give\s+me\s+the\s+world\b", re.IGNORECASE),
        "probable_inserted_pronoun",
    ),
    (
        re.compile(r"\bi\s+love\s*\.?\s*$", re.IGNORECASE),
        "truncated_i_love_you",
    ),
)
LITERAL_CHINESE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"让我安慰"), "comfort_you_literal_as_let_me_be_comforted"),
    (re.compile(r"让我抚摸"), "pet_you_literal_as_let_me_pet"),
    (re.compile(r"我就完整"), "complete_literal_as_whole"),
    (re.compile(r"我很完整"), "complete_literal_as_whole"),
    (re.compile(r"把世界给我"), "give_me_the_world_literal"),
)
SENTENCE_SPLIT_RE = re.compile(r"[.!?。！？]+")
LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'.-]*")


DISALLOWED_SCRIPT_RANGES = (
    (0x0370, 0x03FF, "Greek"),
    (0x0400, 0x052F, "Cyrillic"),
    (0x0590, 0x05FF, "Hebrew"),
    (0x0600, 0x06FF, "Arabic"),
    (0x0700, 0x074F, "Syriac"),
    (0x0780, 0x07BF, "Thaana"),
    (0x0900, 0x097F, "Devanagari"),
    (0x0980, 0x09FF, "Bengali"),
    (0x0A00, 0x0A7F, "Gurmukhi"),
    (0x0A80, 0x0AFF, "Gujarati"),
    (0x0B00, 0x0B7F, "Oriya"),
    (0x0B80, 0x0BFF, "Tamil"),
    (0x0C00, 0x0C7F, "Telugu"),
    (0x0C80, 0x0CFF, "Kannada"),
    (0x0D00, 0x0D7F, "Malayalam"),
    (0x0E00, 0x0E7F, "Thai"),
    (0x0E80, 0x0EFF, "Lao"),
    (0x1100, 0x11FF, "Hangul Jamo"),
    (0xAC00, 0xD7AF, "Hangul"),
)

KNOWN_MOJIBAKE_PATTERNS = (
    (re.compile(r"�"), "replacement character"),
    (re.compile(r"锟斤拷"), "UTF-8 replacement mojibake"),
    (re.compile(r"(?:â€™|â€œ|â€�|â€“|â€”|â€¦|Â\xa0|ï¼|ã€)"), "Latin mojibake"),
)

CJK_MOJIBAKE_STRONG_PATTERNS = (
    "銆",
    "锛",
    "鐨勬",
    "涓嶅",
    "浠栧",
    "杩欐",
    "鏄",
)

CJK_MOJIBAKE_HINTS = (
    "鐨",
    "浠",
    "涓",
    "鍦",
    "鏄",
    "杩",
    "瀹",
    "緇",
    "絜",
    "嬪",
    "勬",
    "堕",
    "戣",
)


def script_name_for_char(char: str) -> str | None:
    codepoint = ord(char)
    for start, end, script_name in DISALLOWED_SCRIPT_RANGES:
        if start <= codepoint <= end:
            return script_name
    return None


def looks_like_cjk_mojibake(text: str) -> bool:
    if any(pattern in text for pattern in CJK_MOJIBAKE_STRONG_PATTERNS):
        return True
    hit_count = sum(1 for token in CJK_MOJIBAKE_HINTS if token in text)
    return hit_count >= 4


def find_text_pollution(text: str, *, dst_lang: str | None = None, sample_limit: int = 5) -> list[str]:
    if not text:
        return []

    issues: list[str] = []
    for pattern, label in KNOWN_MOJIBAKE_PATTERNS:
        if pattern.search(text):
            issues.append(label)

    if looks_like_cjk_mojibake(text):
        issues.append("probable UTF-8 mojibake")

    seen_chars: set[str] = set()
    for char in text:
        if char in seen_chars:
            continue
        seen_chars.add(char)
        script_name = script_name_for_char(char)
        if not script_name:
            continue
        codepoint = f"U+{ord(char):04X}"
        unicode_name = unicodedata.name(char, "UNKNOWN")
        issues.append(f"{script_name} character {codepoint} {unicode_name}")
        if len(issues) >= sample_limit:
            break

    return issues[:sample_limit]


def is_chinese_target_language(dst_lang: str | None) -> bool:
    normalized = (dst_lang or "").strip().lower()
    return normalized.startswith("zh") or "chinese" in normalized


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def normalize_latin_phrase(text: str) -> str:
    return " ".join(word.casefold().strip(".'’") for word in LATIN_WORD_RE.findall(text or ""))


def find_source_asr_suspicions(text: str, *, context_text: str | None = None) -> list[str]:
    if not text:
        return []
    haystack = f"{context_text or ''} {text}"
    issues: list[str] = []
    seen: set[str] = set()
    for pattern, label in SOURCE_ASR_SUSPICION_PATTERNS:
        if not pattern.search(text):
            continue
        if label == "possible_pet_bet_misrecognition" and not ASMR_PET_CONTEXT_RE.search(haystack):
            continue
        if label not in seen:
            seen.add(label)
            issues.append(label)
    return issues


def find_repeated_short_source_phrases(text: str, *, min_words: int = 2, max_words: int = 6) -> list[str]:
    if not text:
        return []
    phrases: list[str] = []
    for part in SENTENCE_SPLIT_RE.split(text):
        normalized = normalize_latin_phrase(part)
        if not normalized:
            continue
        word_count = len(normalized.split())
        if min_words <= word_count <= max_words:
            phrases.append(normalized)
    counts: dict[str, int] = {}
    repeated: list[str] = []
    for phrase in phrases:
        counts[phrase] = counts.get(phrase, 0) + 1
        if counts[phrase] == 2:
            repeated.append(phrase)
    return repeated


def find_literal_chinese_artifacts(target_text: str, *, source_text: str | None = None) -> list[str]:
    if not target_text:
        return []
    issues: list[str] = []
    source = source_text or ""
    for pattern, label in LITERAL_CHINESE_PATTERNS:
        if not pattern.search(target_text):
            continue
        if label == "pet_you_literal_as_let_me_pet" and not re.search(r"\b(?:have\s+you\s+to\s+pet|pet\s+you)\b", source, re.IGNORECASE):
            continue
        if label == "comfort_you_literal_as_let_me_be_comforted" and not re.search(r"\b(?:have\s+you\s+to\s+comfort|comfort\s+you)\b", source, re.IGNORECASE):
            continue
        if label == "complete_literal_as_whole" and not re.search(r"\bcomplete\b", source, re.IGNORECASE):
            continue
        issues.append(label)
    return issues


def find_source_target_semantic_conflicts(source_text: str, target_text: str) -> list[str]:
    if not source_text or not target_text:
        return []
    issues: list[str] = []
    if re.search(r"\bbet\s+you\b", source_text, re.IGNORECASE) and re.search(r"抚摸|摸摸|宠", target_text):
        issues.append("target_implies_pet_but_source_says_bet")
    if re.search(r"\bpet\s+you\b", source_text, re.IGNORECASE) and re.search(r"打赌|赌你|押", target_text):
        issues.append("target_implies_bet_but_source_says_pet")
    if re.search(r"\bhave\s+you\s+to\s+comfort\b", source_text, re.IGNORECASE) and "让我安慰" in target_text:
        issues.append("comfort_direction_reversed")
    return issues


def find_untranslated_discourse_markers(
    text: str,
    *,
    dst_lang: str | None = None,
    sample_limit: int = 5,
) -> list[str]:
    if not text or not is_chinese_target_language(dst_lang):
        return []
    if not contains_chinese(text):
        return []
    scan_text = text.replace("`", "'").replace("’", "'")
    markers: list[str] = []
    seen: set[str] = set()
    for match in DISCOURSE_MARKER_RE.finditer(scan_text):
        marker = match.group(1)
        key = marker.casefold()
        if key in seen:
            continue
        seen.add(key)
        markers.append(marker)
        if len(markers) >= sample_limit:
            break
    return markers


def has_untranslated_discourse_marker(text: str, *, dst_lang: str | None = None) -> bool:
    return bool(find_untranslated_discourse_markers(text, dst_lang=dst_lang, sample_limit=1))


def find_short_english_leaks(
    text: str,
    *,
    dst_lang: str | None = None,
    sample_limit: int = 5,
) -> list[str]:
    return find_untranslated_discourse_markers(text, dst_lang=dst_lang, sample_limit=sample_limit)


def has_short_english_leak(text: str, *, dst_lang: str | None = None) -> bool:
    return bool(find_short_english_leaks(text, dst_lang=dst_lang, sample_limit=1))


def has_text_pollution(text: str, *, dst_lang: str | None = None) -> bool:
    return bool(find_text_pollution(text, dst_lang=dst_lang, sample_limit=1))


def format_pollution_issues(issues: list[str], *, max_items: int = 3) -> str:
    shown = issues[:max_items]
    suffix = "" if len(issues) <= max_items else f"; +{len(issues) - max_items} more"
    return "; ".join(shown) + suffix
