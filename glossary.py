from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .evidence_sidecar import build_evidence_record, write_evidence_sidecar
from .models import Segment
from .youtube_meta import YouTubeMeta


TERM_STOPWORDS = {
    "A",
    "An",
    "And",
    "Are",
    "Be",
    "For",
    "From",
    "Guide",
    "How",
    "In",
    "Into",
    "Is",
    "It",
    "My",
    "Of",
    "On",
    "Or",
    "Thanks",
    "The",
    "This",
    "To",
    "Video",
    "We",
    "With",
    "You",
}
ASR_NOISE_TERMS = {
    "As the",
    "Despite",
    "His",
    "I'm",
    "I've",
    "In",
    "In the",
    "Instead of",
    "It",
    "It's",
    "Let's",
    "Now",
    "One",
    "That",
    "They",
    "This",
    "When the",
    "Various",
}

URL_BRAND_RE = re.compile(r"https?://[^\s)]+")
MENTION_RE = re.compile(r"[@#][A-Za-z0-9_][A-Za-z0-9_-]*")
TITLE_CASE_WORD_RE = r"(?:[A-Z][A-Za-z0-9&'.-]*|[A-Z]{2,})"
CONNECTOR_RE = r"(?:from|of|the|and|to|up|there|new|road|country|for|first|time)"
TITLE_CASE_RE = re.compile(rf"\b{TITLE_CASE_WORD_RE}(?:\s+(?:{TITLE_CASE_WORD_RE}|{CONNECTOR_RE}))*")
TITLE_SUBJECT_PATTERNS = (
    re.compile(r"^(?:an?|the)\s+.+?\s+guide\s+to\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(.+?)\s+iceberg(?:\s*[-:]\s*.+)?$", re.IGNORECASE),
    re.compile(r"^(.+?)(?:\s+iceberg)?\s*[-:]?\s+explained$", re.IGNORECASE),
)
NOISY_LINE_RE = re.compile(
    r"\b(?:http|affiliate|patreon|discord|instagram|twitter|reddit|spotify|apple|soundcloud|link|subscribe|sponsor|supports the channel)\b",
    re.IGNORECASE,
)
NOISY_CANDIDATE_RE = re.compile(
    r"^(?:my|thanks|remove|join|new reddit|animations and illustrations)\b|(?:\bfor|\band|\bto)$",
    re.IGNORECASE,
)
ASR_TERM_RE = re.compile(rf"\b{TITLE_CASE_WORD_RE}(?:\s+(?:{TITLE_CASE_WORD_RE}|{CONNECTOR_RE}))*")
POSSESSIVE_SUFFIX_RE = re.compile(r"(?:['’]s|s['’])$", re.IGNORECASE)

COMMON_TRANSLATABLE_TERMS = {
    "america": "美国",
    "american": "美国",
    "americans": "美国人",
    "berlin": "柏林",
    "britain": "英国",
    "british": "英国",
    "china": "中国",
    "chinese": "中国",
    "edo": "江户",
    "europe": "欧洲",
    "european": "欧洲",
    "europeans": "欧洲人",
    "france": "法国",
    "french": "法国",
    "germany": "德国",
    "german": "德国",
    "japan": "日本",
    "japanese": "日本",
    "london": "伦敦",
    "meiji": "明治",
    "pacific ring of fire": "环太平洋火山地震带",
    "paris": "巴黎",
    "shibuya": "涩谷",
    "shinjuku": "新宿",
    "tokyo": "东京",
    "tokyo olympics": "东京奥运会",
    "uncle sam": "山姆大叔",
    "united states": "美国",
    "world war ii": "二战",
    "world war 2": "二战",
    "wwii": "二战",
    "ww2": "二战",
}

COMMON_TRANSLATABLE_ALIASES = {
    "america": ["United States", "U.S.", "USA", "U.S.A."],
    "japan": ["Japan's"],
    "tokyo": ["Tokyo's"],
    "europe": ["Europe's"],
    "world war ii": ["World War 2", "WWII", "WW2"],
}


@dataclass(slots=True)
class GlossaryTerm:
    canonical: str
    type: str = "term"
    aliases: list[str] = field(default_factory=list)
    bad_aliases: list[str] = field(default_factory=list)
    zh: str = ""
    policy: str = "preserve"
    confidence: float = 0.5
    priority: str = ""
    short_name: str = ""
    sources: list[str] = field(default_factory=list)


def normalize_term_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def normalize_common_term_key(text: str) -> str:
    cleaned = clean_candidate(text)
    cleaned = POSSESSIVE_SUFFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"[\W_]+", " ", cleaned.casefold())
    return re.sub(r"\s+", " ", cleaned).strip()


def common_translation_for_term(text: str) -> tuple[str, str, list[str]] | None:
    common_key = normalize_common_term_key(text)
    if not common_key:
        return None
    zh = COMMON_TRANSLATABLE_TERMS.get(common_key)
    if not zh:
        return None
    aliases = COMMON_TRANSLATABLE_ALIASES.get(common_key, [])
    return zh, "common_zh_name", aliases


def clean_candidate(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip(" \t\r\n.,;:!?()[]{}<>\"'“”‘’"))
    return cleaned.strip()


def common_term_surface_forms() -> list[str]:
    forms: set[str] = set(COMMON_TRANSLATABLE_TERMS)
    for aliases in COMMON_TRANSLATABLE_ALIASES.values():
        forms.update(alias for alias in aliases if alias)
    return sorted(forms, key=len, reverse=True)


def common_surface_pattern(surface: str) -> re.Pattern[str]:
    escaped = re.escape(surface).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?:['’]s|s['’])?(?![A-Za-z0-9])", re.IGNORECASE)


def extract_common_translatable_terms(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for surface in common_term_surface_forms():
        for match in common_surface_pattern(surface).finditer(text or ""):
            candidate = clean_candidate(match.group(0))
            key = normalize_term_key(candidate)
            if not candidate or key in seen:
                continue
            if common_translation_for_term(candidate) is None:
                continue
            seen.add(key)
            found.append(candidate)
    return found


def looks_like_term(text: str) -> bool:
    cleaned = clean_candidate(text)
    if len(cleaned) < 3 or len(cleaned) > 80:
        return False
    if cleaned in TERM_STOPWORDS:
        return False
    words = cleaned.split()
    if all(word in TERM_STOPWORDS for word in words):
        return False
    if any(word.lower().startswith("http") for word in words):
        return False
    if NOISY_CANDIDATE_RE.search(cleaned):
        return False
    return any(char.isupper() for char in cleaned) or any(char.isdigit() for char in cleaned)


def looks_like_asr_term(text: str, count: int) -> bool:
    cleaned = clean_candidate(text)
    if not looks_like_term(cleaned):
        return False
    if cleaned in ASR_NOISE_TERMS:
        return False
    words = cleaned.split()
    if len(words) == 1:
        token = words[0]
        if token.isupper() and len(token) >= 2:
            return True
        return count >= 4 and len(token) >= 5 and token not in ASR_NOISE_TERMS
    lowered_words = [word.lower() for word in words]
    if lowered_words[-1] in {"the", "of", "to", "for", "and"}:
        return False
    if lowered_words[0] in {"as", "when", "instead"} and len(words) <= 2:
        return False
    if any(word in ASR_NOISE_TERMS for word in words):
        return False
    return count >= 2


def add_candidate(
    terms: dict[str, GlossaryTerm],
    text: str,
    *,
    source: str,
    term_type: str = "term",
    confidence: float = 0.5,
    policy: str = "preserve",
    priority: str = "",
    short_name: str = "",
) -> None:
    canonical = clean_candidate(text)
    if not looks_like_term(canonical):
        return
    common_translation = common_translation_for_term(canonical)
    aliases: list[str] = []
    if common_translation is not None:
        zh, term_type, aliases = common_translation
        policy = "translate"
        priority = "hard"
        confidence = max(confidence, 0.98)
        if not short_name:
            short_name = zh
    else:
        zh = canonical
        term_type = term_type
    key = normalize_term_key(canonical)
    existing = terms.get(key)
    if existing is None:
        terms[key] = GlossaryTerm(
            canonical=canonical,
            type=term_type,
            aliases=aliases,
            zh=canonical,
            policy=policy,
            confidence=confidence,
            priority=priority,
            short_name=short_name,
            sources=[source],
        )
        if common_translation is not None:
            terms[key].zh = zh
        return
    if common_translation is not None:
        existing.type = term_type
        existing.zh = zh
        existing.policy = "translate"
        existing.priority = "hard"
        existing.short_name = existing.short_name or zh
        for alias in aliases:
            if alias not in existing.aliases:
                existing.aliases.append(alias)
    existing.confidence = max(existing.confidence, confidence)
    if priority and not existing.priority:
        existing.priority = priority
    if short_name and not existing.short_name:
        existing.short_name = short_name
    if source not in existing.sources:
        existing.sources.append(source)


def extract_title_case_terms(text: str, *, source: str, confidence: float) -> list[tuple[str, str, float]]:
    terms: list[tuple[str, str, float]] = []
    for raw_line in (text or "").splitlines():
        line = URL_BRAND_RE.sub(" ", raw_line)
        if not line.strip() or NOISY_LINE_RE.search(line):
            continue
        for chunk in re.split(r"[|/·•;:()\[\]{}]+", line):
            for match in TITLE_CASE_RE.finditer(chunk):
                candidate = clean_candidate(match.group(0))
                if looks_like_term(candidate):
                    terms.append((candidate, source, confidence))
    return terms


def extract_title_subject_terms(title: str) -> list[tuple[str, str, float]]:
    terms: list[tuple[str, str, float]] = []
    cleaned_title = clean_candidate(title)
    for pattern in TITLE_SUBJECT_PATTERNS:
        match = pattern.match(cleaned_title)
        if not match:
            continue
        subject = clean_candidate(match.group(1))
        if looks_like_term(subject):
            terms.append((subject, "youtube_title_subject", 0.98))
    return terms


def extract_url_terms(text: str) -> list[tuple[str, str, float]]:
    terms: list[tuple[str, str, float]] = []
    for match in URL_BRAND_RE.finditer(text or ""):
        url = match.group(0)
        host = urlparse(url).netloc.lower()
        host = host.removeprefix("www.")
        if not host:
            continue
        brand = host.split(".")[0]
        if brand:
            terms.append((brand, "youtube_description_url", 0.35))
    return terms


def extract_mention_terms(text: str) -> list[tuple[str, str, float]]:
    terms: list[tuple[str, str, float]] = []
    for match in MENTION_RE.finditer(text or ""):
        token = match.group(0)
        cleaned = token[1:].replace("_", " ").replace("-", " ")
        if token.startswith("#"):
            terms.append((cleaned, "youtube_description_hashtag", 0.35))
        else:
            terms.append((cleaned, "youtube_description_mention", 0.45))
    return terms


def generate_youtube_glossary(meta: YouTubeMeta) -> dict:
    terms: dict[str, GlossaryTerm] = {}
    for candidate in extract_common_translatable_terms(f"{meta.title}\n{meta.description}"):
        add_candidate(
            terms,
            candidate,
            source="common_zh_name",
            confidence=0.99,
            priority="hard",
            policy="translate",
        )
    for candidate, source, confidence in extract_title_subject_terms(meta.title):
        add_candidate(
            terms,
            candidate,
            source=source,
            confidence=confidence,
            priority="hard",
        )
    if meta.author:
        add_candidate(
            terms,
            meta.author,
            source="youtube_author",
            term_type="channel",
            confidence=0.7,
            priority="hard",
        )
    for candidate, source, confidence in extract_title_case_terms(
        meta.description,
        source="youtube_description",
        confidence=0.45,
    ):
        add_candidate(terms, candidate, source=source, confidence=confidence)
    for candidate, source, confidence in extract_url_terms(meta.description):
        add_candidate(terms, candidate, source=source, term_type="brand", confidence=confidence)
    for candidate, source, confidence in extract_mention_terms(meta.description):
        add_candidate(terms, candidate, source=source, confidence=confidence)

    return {
        "version": 1,
        "strategy": "youtube_metadata_seed",
        "terms": [asdict(term) for term in sorted(terms.values(), key=lambda item: (-item.confidence, item.canonical.lower()))],
    }


def glossary_to_prompt_text(glossary: dict) -> str:
    lines: list[str] = []
    for item in glossary.get("terms", []):
        canonical = str(item.get("canonical") or "").strip()
        if not canonical:
            continue
        zh = str(item.get("zh") or canonical).strip()
        policy = str(item.get("policy") or "preserve").strip()
        aliases = [str(value).strip() for value in item.get("aliases") or [] if str(value).strip()]
        bad_aliases = [str(value).strip() for value in item.get("bad_aliases") or [] if str(value).strip()]
        line = f"- {canonical} => {zh}; policy={policy}"
        if aliases:
            line += f"; aliases={'; '.join(aliases)}"
        if bad_aliases:
            line += f"; correct_bad_aliases={'; '.join(bad_aliases)}"
        lines.append(line)
    return "\n".join(lines)


def glossary_from_terms(terms: dict[str, GlossaryTerm], *, strategy: str) -> dict:
    return {
        "version": 1,
        "strategy": strategy,
        "terms": [asdict(term) for term in sorted(terms.values(), key=lambda item: (-item.confidence, item.canonical.lower()))],
    }


def youtube_metadata_evidence(
    meta: YouTubeMeta,
    *,
    project_id: str = "unknown",
    input_fingerprint: str = "unknown",
    fetched_at: str = "unknown",
) -> dict:
    """Convert already-fetched metadata to advisory review context.

    This record does not participate in glossary resolution.  Callers must
    explicitly request sidecar publication and keep human-confirmed glossary
    rules authoritative.
    """

    return build_evidence_record(
        source="youtube_metadata",
        title=meta.title,
        url=meta.video_url,
        summary=meta.description,
        fetched_at=fetched_at,
        confidence=0.7,
        project_id=project_id,
        input_fingerprint=input_fingerprint,
        evidence_level="advisory",
        metadata={
            "video_id": meta.video_id,
            "author": meta.author,
            "published_at": meta.published_at,
        },
    )


def write_youtube_glossary(
    output_dir: Path,
    meta: YouTubeMeta,
    *,
    evidence_sidecar_path: str | Path | None = None,
    project_id: str = "unknown",
    input_fingerprint: str = "unknown",
    evidence_fetched_at: str = "unknown",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    glossary = generate_youtube_glossary(meta)
    raw_path = output_dir / "00_glossary_auto.json"
    prompt_path = output_dir / "00_glossary_prompt.txt"
    review_path = output_dir / "00_glossary_review.tsv"
    raw_path.write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt_path.write_text(glossary_to_prompt_text(glossary), encoding="utf-8")
    review_lines = ["canonical\ttype\tzh\tpolicy\tconfidence\tsources"]
    for item in glossary.get("terms", []):
        review_lines.append(
            "\t".join(
                [
                    str(item.get("canonical") or ""),
                    str(item.get("type") or ""),
                    str(item.get("zh") or ""),
                    str(item.get("policy") or ""),
                    str(item.get("confidence") or ""),
                    ";".join(str(value) for value in item.get("sources") or []),
                ]
            )
        )
    review_path.write_text("\n".join(review_lines) + "\n", encoding="utf-8")
    if evidence_sidecar_path is not None:
        write_evidence_sidecar(
            evidence_sidecar_path,
            [youtube_metadata_evidence(
                meta,
                project_id=project_id,
                input_fingerprint=input_fingerprint,
                fetched_at=evidence_fetched_at,
            )],
            project_id=project_id,
            input_fingerprint=input_fingerprint,
        )
    return raw_path


def generate_asr_terms(segments: list[Segment], *, min_count: int = 2) -> dict:
    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    for segment in segments:
        text = URL_BRAND_RE.sub(" ", segment.source_text or "")
        for candidate in extract_common_translatable_terms(text):
            key = normalize_term_key(candidate)
            counts[key] += 1
            first_seen.setdefault(key, candidate)
        for match in ASR_TERM_RE.finditer(text):
            candidate = clean_candidate(match.group(0))
            if not looks_like_term(candidate):
                continue
            key = normalize_term_key(candidate)
            counts[key] += 1
            first_seen.setdefault(key, candidate)

    terms: dict[str, GlossaryTerm] = {}
    for key, count in counts.items():
        if count < min_count:
            continue
        canonical = first_seen[key]
        confidence = min(0.82, 0.45 + count * 0.05)
        common_translation = common_translation_for_term(canonical)
        if common_translation is None and not looks_like_asr_term(canonical, count):
            continue
        if common_translation is not None:
            zh, term_type, aliases = common_translation
            terms[key] = GlossaryTerm(
                canonical=canonical,
                type=term_type,
                aliases=aliases,
                zh=zh,
                policy="translate",
                confidence=max(confidence, 0.98),
                priority="hard",
                short_name=zh,
                sources=[f"asr_count:{count}", "common_zh_name"],
            )
        else:
            terms[key] = GlossaryTerm(
                canonical=canonical,
                type="asr_candidate",
                zh=canonical,
                policy="preserve",
                confidence=confidence,
                short_name=canonical.split()[0] if " " in canonical else canonical,
                sources=[f"asr_count:{count}"],
            )
    return glossary_from_terms(terms, strategy="asr_term_discovery")


def write_asr_terms(output_dir: Path, segments: list[Segment]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "02_terms_from_asr.json"
    path.write_text(json.dumps(generate_asr_terms(segments), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_glossary_payload(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "strategy": "empty", "terms": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("terms"), list):
        return payload
    return {"version": 1, "strategy": "unknown", "terms": []}


def term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term)
    if term.lower().endswith("twin"):
        escaped = f"{escaped}(?:s['’]?|['’]s)?"
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


def translatable_term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(clean_candidate(term))
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?:['’]s|s['’])?(?![A-Za-z0-9])", re.IGNORECASE)


def replace_bad_aliases(text: str, replacements: list[tuple[str, str]]) -> tuple[str, int]:
    if not text or not replacements:
        return text, 0

    replaced = text
    count = 0
    for bad_alias, canonical in replacements:
        replaced, hits = term_pattern(bad_alias).subn(canonical, replaced)
        count += hits
    return replaced, count


def replace_translatable_terms(text: str, replacements: list[tuple[str, str]]) -> tuple[str, int]:
    if not text or not replacements:
        return text, 0

    replaced = text
    count = 0
    for source_form, zh in replacements:
        if not source_form or not zh:
            continue
        replaced, hits = translatable_term_pattern(source_form).subn(zh, replaced)
        count += hits
    return replaced, count


def build_alias_replacements(glossary_path: str | Path | None) -> list[tuple[str, str]]:
    if not glossary_path:
        return []
    path = Path(glossary_path)
    if not path.exists() or path.suffix.lower() != ".json":
        return []

    payload = load_glossary_payload(path)
    replacements: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.get("terms", []):
        if not isinstance(item, dict):
            continue
        canonical = clean_candidate(str(item.get("canonical") or ""))
        if len(canonical) < 3:
            continue
        for raw_alias in item.get("bad_aliases") or []:
            bad_alias = clean_candidate(str(raw_alias))
            if len(bad_alias) < 3:
                continue
            if normalize_term_key(bad_alias) == normalize_term_key(canonical):
                continue
            key = (normalize_term_key(bad_alias), canonical)
            if key in seen:
                continue
            seen.add(key)
            replacements.append((bad_alias, canonical))

    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    return replacements


def build_translate_policy_replacements(glossary_path: str | Path | None) -> list[tuple[str, str]]:
    if not glossary_path:
        return []
    path = Path(glossary_path)
    if not path.exists() or path.suffix.lower() != ".json":
        return []

    payload = load_glossary_payload(path)
    replacements: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in payload.get("terms", []):
        if not isinstance(item, dict):
            continue
        policy = str(item.get("policy") or "").strip()
        if policy != "translate":
            continue
        zh = str(item.get("zh") or "").strip()
        if not zh:
            continue
        forms = [
            clean_candidate(str(item.get("canonical") or "")),
            *[clean_candidate(str(value)) for value in item.get("aliases") or []],
            *[clean_candidate(str(value)) for value in item.get("bad_aliases") or []],
        ]
        for form in forms:
            if len(form) < 2 or form == zh:
                continue
            key = (normalize_term_key(form), zh)
            if key in seen:
                continue
            seen.add(key)
            replacements.append((form, zh))

    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    return replacements


def apply_glossary_alias_corrections(
    segments: list[Segment],
    glossary_path: str | Path | None,
) -> dict:
    replacements = build_alias_replacements(glossary_path)
    stats = {
        "segments_changed": 0,
        "source_text_replacements": 0,
        "target_text_replacements": 0,
        "total_replacements": 0,
        "replacement_count": len(replacements),
    }
    if not replacements:
        return stats

    for segment in segments:
        changed = False
        source_text, source_count = replace_bad_aliases(segment.source_text or "", replacements)
        if source_count:
            segment.source_text = source_text
            stats["source_text_replacements"] += source_count
            changed = True

        if segment.target_text is not None:
            target_text, target_count = replace_bad_aliases(segment.target_text, replacements)
            if target_count:
                segment.target_text = target_text
                stats["target_text_replacements"] += target_count
                changed = True

        if changed:
            stats["segments_changed"] += 1

    stats["total_replacements"] = stats["source_text_replacements"] + stats["target_text_replacements"]
    return stats


def apply_translate_policy_corrections(
    segments: list[Segment],
    glossary_path: str | Path | None,
) -> dict:
    replacements = build_translate_policy_replacements(glossary_path)
    stats = {
        "segments_changed": 0,
        "target_text_replacements": 0,
        "replacement_count": len(replacements),
    }
    if not replacements:
        return stats

    for segment in segments:
        if segment.target_text is None:
            continue
        target_text, target_count = replace_translatable_terms(segment.target_text, replacements)
        if not target_count:
            continue
        segment.target_text = target_text
        stats["target_text_replacements"] += target_count
        stats["segments_changed"] += 1

    return stats


def merge_term_item(terms: dict[str, GlossaryTerm], item: dict) -> None:
    canonical = clean_candidate(str(item.get("canonical") or ""))
    if not canonical:
        return
    common_translation = common_translation_for_term(canonical)
    if common_translation is not None:
        common_zh, common_type, common_aliases = common_translation
        item = {
            **item,
            "type": common_type,
            "zh": common_zh,
            "policy": "translate",
            "priority": "hard",
            "confidence": max(float(item.get("confidence") or 0.5), 0.98),
            "short_name": str(item.get("short_name") or common_zh),
            "aliases": [*(item.get("aliases") or []), *common_aliases],
        }
    key = normalize_term_key(canonical)
    aliases = [clean_candidate(str(value)) for value in item.get("aliases") or [] if clean_candidate(str(value))]
    bad_aliases = [clean_candidate(str(value)) for value in item.get("bad_aliases") or [] if clean_candidate(str(value))]
    sources = [str(value) for value in item.get("sources") or []]
    confidence = float(item.get("confidence") or 0.5)
    existing = terms.get(key)
    if existing is None:
        terms[key] = GlossaryTerm(
            canonical=canonical,
            type=str(item.get("type") or "term"),
            aliases=aliases,
            bad_aliases=bad_aliases,
            zh=str(item.get("zh") or canonical),
            policy=str(item.get("policy") or "preserve"),
            confidence=confidence,
            priority=str(item.get("priority") or ""),
            short_name=str(item.get("short_name") or ""),
            sources=sources,
        )
        return
    if common_translation is not None:
        existing.type = str(item.get("type") or existing.type)
        existing.zh = str(item.get("zh") or existing.zh)
        existing.policy = "translate"
        existing.priority = "hard"
        existing.short_name = existing.short_name or str(item.get("short_name") or existing.zh)
    existing.confidence = max(existing.confidence, confidence)
    if not existing.zh and item.get("zh"):
        existing.zh = str(item.get("zh"))
    if not existing.priority and item.get("priority"):
        existing.priority = str(item.get("priority"))
    if not existing.short_name and item.get("short_name"):
        existing.short_name = str(item.get("short_name"))
    for alias in aliases:
        if alias not in existing.aliases:
            existing.aliases.append(alias)
    for bad_alias in bad_aliases:
        if bad_alias not in existing.bad_aliases:
            existing.bad_aliases.append(bad_alias)
    for source in sources:
        if source not in existing.sources:
            existing.sources.append(source)


def find_similar_existing_term(terms: dict[str, GlossaryTerm], canonical: str) -> GlossaryTerm | None:
    candidate_key = normalize_term_key(canonical)
    for existing in terms.values():
        existing_key = normalize_term_key(existing.canonical)
        if likely_bad_alias(candidate_key, existing_key):
            return existing
    return None


def merge_asr_candidate_item(terms: dict[str, GlossaryTerm], item: dict) -> None:
    canonical = clean_candidate(str(item.get("canonical") or ""))
    if not canonical:
        return
    existing = find_similar_existing_term(terms, canonical)
    if existing is not None:
        if canonical != existing.canonical and canonical not in existing.bad_aliases:
            existing.bad_aliases.append(canonical)
        for source in item.get("sources") or []:
            source_text = str(source)
            if source_text not in existing.sources:
                existing.sources.append(source_text)
        if "asr_fuzzy_alias" not in existing.sources:
            existing.sources.append("asr_fuzzy_alias")
        return
    merge_term_item(terms, item)


def add_fuzzy_bad_aliases(terms: dict[str, GlossaryTerm]) -> None:
    values = list(terms.values())
    for canonical_term in values:
        canonical_key = normalize_term_key(canonical_term.canonical)
        if len(canonical_term.canonical) < 6:
            continue
        for candidate in values:
            if candidate is canonical_term:
                continue
            candidate_key = normalize_term_key(candidate.canonical)
            if candidate_key == canonical_key:
                continue
            if len(candidate.canonical) < 6:
                continue
            if likely_bad_alias(candidate_key, canonical_key) and candidate.canonical not in canonical_term.bad_aliases:
                canonical_term.bad_aliases.append(candidate.canonical)
                if "asr_fuzzy_alias" not in canonical_term.sources:
                    canonical_term.sources.append("asr_fuzzy_alias")


def likely_bad_alias(candidate_key: str, canonical_key: str) -> bool:
    candidate_words = candidate_key.split()
    canonical_words = canonical_key.split()
    if len(candidate_words) != len(canonical_words):
        return False
    if len(candidate_words) < 2:
        return False
    matches = sum(1 for left, right in zip(candidate_words, canonical_words) if left == right)
    if matches < len(canonical_words) - 1:
        return False
    first_left = candidate_words[0]
    first_right = canonical_words[0]
    if len(first_left) < 4 or len(first_right) < 4:
        return False
    return first_left[0] == first_right[0] and abs(len(first_left) - len(first_right)) <= 2


def write_resolved_glossary(output_dir: Path) -> Path | None:
    terms: dict[str, GlossaryTerm] = {}
    loaded_any = False

    profile_path = output_dir / "00_profile_glossary.json"
    if profile_path.exists():
        loaded_any = True
        payload = load_glossary_payload(profile_path)
        for item in payload.get("terms", []):
            if isinstance(item, dict):
                merge_term_item(terms, item)

    youtube_path = output_dir / "00_glossary_auto.json"
    if youtube_path.exists():
        loaded_any = True
        payload = load_glossary_payload(youtube_path)
        for item in payload.get("terms", []):
            if isinstance(item, dict):
                merge_term_item(terms, item)

    asr_path = output_dir / "02_terms_from_asr.json"
    if asr_path.exists():
        loaded_any = True
        payload = load_glossary_payload(asr_path)
        for item in payload.get("terms", []):
            if isinstance(item, dict):
                merge_asr_candidate_item(terms, item)

    if not loaded_any:
        return None
    add_fuzzy_bad_aliases(terms)
    glossary = glossary_from_terms(terms, strategy="resolved_project_glossary")
    json_path = output_dir / "03_glossary_resolved.json"
    prompt_path = output_dir / "03_glossary_resolved_prompt.txt"
    json_path.write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")
    prompt_path.write_text(glossary_to_prompt_text(glossary), encoding="utf-8")
    return prompt_path


def ensure_project_glossary(output_dir: Path) -> Path | None:
    resolved_prompt_path = output_dir / "03_glossary_resolved_prompt.txt"
    if resolved_prompt_path.exists():
        return resolved_prompt_path

    prompt_path = output_dir / "00_glossary_prompt.txt"
    if prompt_path.exists():
        return prompt_path

    meta_path = output_dir / "00_youtube_meta.json"
    if not meta_path.exists():
        return None

    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    meta = YouTubeMeta(
        video_id=str(payload.get("video_id") or ""),
        video_url=str(payload.get("video_url") or ""),
        author=str(payload.get("author") or ""),
        published_at=str(payload.get("published_at") or ""),
        title=str(payload.get("title") or ""),
        description=str(payload.get("description") or ""),
        cover_url=str(payload.get("cover_url") or ""),
        cover_path=payload.get("cover_path"),
    )
    write_youtube_glossary(output_dir, meta)
    return prompt_path if prompt_path.exists() else None
