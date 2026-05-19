from __future__ import annotations

import re
import unicodedata


TRANSLATABLE_DISCOURSE_MARKERS = {
    "actually",
    "again",
    "alright",
    "anyway",
    "basically",
    "because",
    "cause",
    "exactly",
    "honestly",
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
    markers: list[str] = []
    seen: set[str] = set()
    for match in DISCOURSE_MARKER_RE.finditer(text):
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


def has_text_pollution(text: str, *, dst_lang: str | None = None) -> bool:
    return bool(find_text_pollution(text, dst_lang=dst_lang, sample_limit=1))


def format_pollution_issues(issues: list[str], *, max_items: int = 3) -> str:
    shown = issues[:max_items]
    suffix = "" if len(issues) <= max_items else f"; +{len(issues) - max_items} more"
    return "; ".join(shown) + suffix
