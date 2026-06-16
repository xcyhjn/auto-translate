from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .entity_normalization import load_effective_entity_rules
from .glossary import common_translation_for_term, load_glossary_payload
from .text_quality import TRANSLATABLE_DISCOURSE_MARKERS, contains_chinese, is_chinese_target_language


DEFAULT_PRESERVE_THRESHOLD = 85
DEFAULT_REVIEW_THRESHOLD = 70

LATIN_CANDIDATE_RE = re.compile(
    r"""
    (?:
        https?://[^\s，。！？；：（）《》"']+
        |[A-Za-z]:\\[^\s，。！？；：（）《》"']+
        |[@#][A-Za-z0-9_][A-Za-z0-9_-]*
        |[A-Za-z][A-Za-z0-9_+.-]*(?:\\[A-Za-z0-9_+.-]+)+
        |[A-Za-z][A-Za-z0-9_+.-]*(?:/[A-Za-z0-9_+.-]+)+
        |[A-Za-z][A-Za-z0-9_+.-]*(?:\s+[A-Za-z][A-Za-z0-9_+.-]*)*
    )
    """,
    re.VERBOSE,
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+.-]*")
CODE_LIKE_RE = re.compile(
    r"""
    (?:https?://|[A-Za-z]:\\|[/\\]|`|::|\.[A-Za-z0-9]{1,5}\b|\b[A-Za-z]+[-_][A-Za-z0-9_-]+\b|
    \b[A-Za-z]*\d[A-Za-z0-9_.-]*\b|\b[A-Za-z]+\.[A-Za-z0-9_.-]+\b|\bCtrl\+[A-Za-z0-9]+\b)
    """,
    re.IGNORECASE | re.VERBOSE,
)
ALL_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9&.-]{1,8}$")
TITLE_CONTEXT_RE = re.compile(r"[《「『“\"']\s*$")

COMMON_MUST_TRANSLATE = {
    "america",
    "american",
    "americans",
    "britain",
    "british",
    "chapter",
    "china",
    "chinese",
    "conquistador",
    "europe",
    "european",
    "europeans",
    "france",
    "french",
    "germany",
    "german",
    "god",
    "japan",
    "japanese",
    "mayan",
    "moscow",
    "russia",
    "russian",
    "spanish",
    "tokyo",
    "universe",
    "world war",
    "world war ii",
    "world war 2",
    "wwii",
    "ww2",
    "yucatan",
}
COMMON_PRESERVE_BRANDS = {
    "api",
    "css",
    "ffmpeg",
    "github",
    "html",
    "javascript",
    "node.js",
    "openai",
    "python",
    "typescript",
    "ui",
    "url",
    "youtube",
}
FUNCTION_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "for",
    "from",
    "he",
    "her",
    "his",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "she",
    "that",
    "the",
    "then",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "with",
    "you",
}


@dataclass(slots=True)
class ResidueDecision:
    candidate: str
    category: str
    preserve_score: int
    decision: str
    reason_codes: list[str] = field(default_factory=list)
    suggested_action: str = "translate_to_chinese"
    source_present: bool = False

    def to_dict(self) -> dict:
        return {
            "candidate": self.candidate,
            "category": self.category,
            "preserve_score": self.preserve_score,
            "decision": self.decision,
            "reason_codes": self.reason_codes,
            "suggested_action": self.suggested_action,
            "source_present": self.source_present,
        }


def normalize_candidate(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip(" \t\r\n,.;:!?，。！？；：（）[]{}<>《》\"'“”‘’")).strip()


def normalize_key(text: str) -> str:
    return re.sub(r"[\W_]+", " ", normalize_candidate(text).casefold()).strip()


def contains_candidate(text: str, candidate: str) -> bool:
    if not text or not candidate:
        return False
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(candidate)}(?![A-Za-z0-9])", re.IGNORECASE)
    return bool(pattern.search(text))


def extract_latin_residue(text: str, *, dst_lang: str | None = None) -> list[str]:
    if not text or not is_chinese_target_language(dst_lang):
        return []
    results: list[str] = []
    seen: set[str] = set()
    for match in LATIN_CANDIDATE_RE.finditer(text):
        candidate = normalize_candidate(match.group(0))
        if not candidate:
            continue
        if candidate.isdigit():
            continue
        words = WORD_RE.findall(candidate)
        if not words:
            continue
        key = normalize_key(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        results.append(candidate)
    return results


def _load_glossary_policy_maps(glossary_path: str | Path | None = None, glossary_text: str = "") -> tuple[set[str], set[str], set[str], dict[str, str]]:
    hard_preserve: set[str] = set()
    soft_preserve: set[str] = set()
    translate: set[str] = set()
    zh_by_key: dict[str, str] = {}

    def add_item(item: dict) -> None:
        canonical = normalize_candidate(str(item.get("canonical") or ""))
        if not canonical:
            return
        key = normalize_key(canonical)
        policy = str(item.get("policy") or "preserve").strip().lower()
        priority = str(item.get("priority") or "").strip().lower()
        sources = [str(value).strip().lower() for value in item.get("sources") or [] if str(value).strip()]
        zh = str(item.get("zh") or "").strip()
        forms = [canonical, *[str(value) for value in item.get("aliases") or [] if str(value).strip()]]
        auto_sources = {"youtube_description", "youtube_title", "asr_fuzzy_alias"}
        is_auto_candidate = any(source.startswith("asr_count:") or source in auto_sources for source in sources)
        if policy in {"preserve", "preserve_en"} and (priority == "hard" or not is_auto_candidate):
            target = hard_preserve
        elif policy in {"preserve", "preserve_en"}:
            target = soft_preserve
        else:
            target = translate
        for form in forms:
            form_key = normalize_key(form)
            if form_key:
                target.add(form_key)
                if zh:
                    zh_by_key[form_key] = zh

    if glossary_path:
        path = Path(glossary_path)
        if path.exists() and path.suffix.lower() == ".json":
            try:
                for item in load_glossary_payload(path).get("terms", []):
                    if isinstance(item, dict):
                        add_item(item)
            except Exception:
                pass
    for line in (glossary_text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        parts = [part.strip() for part in stripped[2:].split("|")]
        if not parts or not parts[0]:
            continue
        item = {"canonical": parts[0], "aliases": []}
        for part in parts[1:]:
            if "=" not in part:
                continue
            key, value = [piece.strip() for piece in part.split("=", 1)]
            if key == "policy":
                item["policy"] = value
            elif key == "zh":
                item["zh"] = value
            elif key == "aliases":
                item["aliases"] = [piece.strip() for piece in value.split(";") if piece.strip()]
            elif key == "sources":
                item["sources"] = [piece.strip() for piece in value.split(";") if piece.strip()]
        add_item(item)
    return hard_preserve, soft_preserve, translate, zh_by_key


def _load_entity_translate_keys(project_dir: str | Path | None = None) -> dict[str, str]:
    keys: dict[str, str] = {}
    for rule in load_effective_entity_rules(project_dir=project_dir):
        if rule.policy in {"preserve", "preserve_en"}:
            continue
        for surface in rule.surface_forms:
            key = normalize_key(surface)
            if key:
                keys[key] = rule.canonical_zh
    return keys


def _category_for_candidate(candidate: str, key: str, words: list[str], *, hard_preserve_keys: set[str], soft_preserve_keys: set[str], translate_keys: set[str], entity_keys: dict[str, str]) -> str:
    if key in translate_keys or key in entity_keys:
        return "known_translate_entity"
    if common_translation_for_term(candidate) or key in COMMON_MUST_TRANSLATE:
        return "common_translatable"
    if key in hard_preserve_keys:
        return "explicit_preserve"
    if CODE_LIKE_RE.search(candidate):
        return "code_or_identifier"
    if key in COMMON_PRESERVE_BRANDS:
        return "brand_or_software"
    if key in soft_preserve_keys:
        return "glossary_soft_preserve"
    if len(words) == 1 and (words[0].casefold() in FUNCTION_WORDS or words[0].casefold() in TRANSLATABLE_DISCOURSE_MARKERS):
        return "function_or_discourse"
    if len(words) == 1 and ALL_CAPS_RE.match(candidate):
        return "abbreviation"
    if len(words) >= 2 and all(word[:1].isupper() or word.isupper() for word in words):
        return "proper_name"
    if len(words) == 1 and words[0][:1].isupper():
        return "single_title_word"
    return "ordinary_english"


def score_english_residue(
    candidate: str,
    *,
    source_text: str = "",
    reference_text: str = "",
    target_text: str = "",
    glossary_path: str | Path | None = None,
    glossary_text: str = "",
    project_dir: str | Path | None = None,
    preserve_threshold: int = DEFAULT_PRESERVE_THRESHOLD,
    review_threshold: int = DEFAULT_REVIEW_THRESHOLD,
) -> ResidueDecision:
    candidate = normalize_candidate(candidate)
    key = normalize_key(candidate)
    words = WORD_RE.findall(candidate)
    hard_preserve_keys, soft_preserve_keys, translate_keys, zh_by_key = _load_glossary_policy_maps(glossary_path, glossary_text)
    entity_keys = _load_entity_translate_keys(project_dir)
    category = _category_for_candidate(
        candidate,
        key,
        words,
        hard_preserve_keys=hard_preserve_keys,
        soft_preserve_keys=soft_preserve_keys,
        translate_keys=translate_keys,
        entity_keys=entity_keys,
    )
    reason_codes: list[str] = []
    source_present = contains_candidate(source_text, candidate) or contains_candidate(reference_text, candidate)

    base_scores = {
        "explicit_preserve": 100,
        "code_or_identifier": 94,
        "brand_or_software": 88,
        "abbreviation": 78,
        "glossary_soft_preserve": 62,
        "proper_name": 55,
        "single_title_word": 35,
        "known_translate_entity": 25,
        "common_translatable": 20,
        "function_or_discourse": 0,
        "ordinary_english": 15,
    }
    score = base_scores.get(category, 15)
    reason_codes.append(category)

    if category == "explicit_preserve":
        reason_codes.append("glossary_policy_preserve")
    if category == "glossary_soft_preserve":
        reason_codes.append("auto_glossary_preserve_needs_review")
    if key in translate_keys:
        reason_codes.append("glossary_policy_translate")
        score = min(score, 30)
    if key in entity_keys:
        reason_codes.append("entity_has_canonical_zh")
        score = min(score, 35)
    if common_translation_for_term(candidate):
        reason_codes.append("common_zh_name")
        score = min(score, 35)
    if key in COMMON_MUST_TRANSLATE:
        reason_codes.append("must_translate_common_term")
        score = min(score, 25)
    if category in {"function_or_discourse", "ordinary_english"} and len(words) == 1:
        reason_codes.append("single_word_in_chinese_line")
        score = max(0, score - 25)
    if target_text and contains_chinese(target_text) and len(words) == 1 and category not in {"code_or_identifier", "explicit_preserve", "brand_or_software"}:
        reason_codes.append("mixed_single_english_word")
        score = max(0, score - 25)
    if not source_present and category != "explicit_preserve":
        reason_codes.append("not_found_in_source_or_reference")
        score = min(score, 50)
    if TITLE_CONTEXT_RE.search(target_text[: max(0, target_text.find(candidate))]) and category in {"proper_name", "single_title_word"}:
        reason_codes.append("quoted_title_context")
        score = min(84, score + 20)
    if key in zh_by_key and zh_by_key[key] and category != "explicit_preserve":
        reason_codes.append("known_zh_available")
        score = min(score, 35)

    score = max(0, min(100, int(score)))
    if score >= preserve_threshold:
        decision = "preserve"
        suggested_action = "keep_english"
    elif score >= review_threshold:
        decision = "review"
        suggested_action = "translate_or_confirm_preserve"
    else:
        decision = "translate"
        suggested_action = "translate_to_chinese"
    return ResidueDecision(
        candidate=candidate,
        category=category,
        preserve_score=score,
        decision=decision,
        reason_codes=reason_codes,
        suggested_action=suggested_action,
        source_present=source_present,
    )


def analyze_english_residue(
    target_text: str,
    *,
    source_text: str = "",
    reference_text: str = "",
    dst_lang: str | None = None,
    glossary_path: str | Path | None = None,
    glossary_text: str = "",
    project_dir: str | Path | None = None,
    preserve_threshold: int = DEFAULT_PRESERVE_THRESHOLD,
    review_threshold: int = DEFAULT_REVIEW_THRESHOLD,
) -> list[ResidueDecision]:
    decisions: list[ResidueDecision] = []
    for candidate in extract_latin_residue(target_text, dst_lang=dst_lang):
        decisions.append(
            score_english_residue(
                candidate,
                source_text=source_text,
                reference_text=reference_text,
                target_text=target_text,
                glossary_path=glossary_path,
                glossary_text=glossary_text,
                project_dir=project_dir,
                preserve_threshold=preserve_threshold,
                review_threshold=review_threshold,
            )
        )
    return decisions


def build_english_residue_report(
    segments,
    *,
    dst_lang: str | None = None,
    glossary_path: str | Path | None = None,
    glossary_text: str = "",
    project_dir: str | Path | None = None,
    preserve_threshold: int = DEFAULT_PRESERVE_THRESHOLD,
    review_threshold: int = DEFAULT_REVIEW_THRESHOLD,
    sample_limit: int = 30,
) -> dict:
    items: list[dict] = []
    for segment in segments:
        for decision in analyze_english_residue(
            segment.target_text or "",
            source_text=segment.source_text or "",
            reference_text=segment.reference_text or segment.source_text or "",
            dst_lang=dst_lang,
            glossary_path=glossary_path,
            glossary_text=glossary_text,
            project_dir=project_dir,
            preserve_threshold=preserve_threshold,
            review_threshold=review_threshold,
        ):
            items.append(
                {
                    "segment_id": segment.id,
                    "source_text": segment.source_text or "",
                    "reference_text": segment.reference_text or segment.source_text or "",
                    "target_text": segment.target_text or "",
                    **decision.to_dict(),
                }
            )

    blocking = [item for item in items if item["decision"] == "translate"]
    review = [item for item in items if item["decision"] == "review"]
    preserved = [item for item in items if item["decision"] == "preserve"]
    return {
        "schema_version": 1,
        "config": {
            "preserve_threshold": int(preserve_threshold),
            "review_threshold": int(review_threshold),
        },
        "summary": {
            "english_residue_total_count": len(items),
            "english_residue_blocking_count": len(blocking),
            "english_residue_preserved_count": len(preserved),
            "english_residue_review_count": len(review),
            "pass": len(blocking) == 0,
        },
        "items": items,
        "blocking_samples": blocking[:sample_limit],
        "review_samples": review[:sample_limit],
        "preserved_samples": preserved[:sample_limit],
    }
