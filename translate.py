from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any
from typing import Callable

from .models import Segment
from .style_rules import build_style_guidance, load_style_prompt_text
from .text_quality import (
    TRANSLATABLE_DISCOURSE_MARKERS,
    find_short_english_leaks,
    find_text_pollution,
)

TranslationProgressCallback = Callable[[str, dict], None]
TRANSLATABLE_FUNCTION_WORDS = {
    "am",
    "and",
    "are",
    "been",
    "being",
    "but",
    "can",
    "could",
    "did",
    "does",
    "had",
    "has",
    "have",
    "im",
    "is",
    "might",
    "must",
    "should",
    "that",
    "thats",
    "then",
    "these",
    "they",
    "this",
    "those",
    "was",
    "were",
    "will",
    "would",
    "you",
}
FIRST_PERSON_I_RE = re.compile(r"(?<![A-Za-z])i(?=(?:['’`](?:m|d|ll|ve|re)\b)|\b)", re.IGNORECASE)


@dataclass(slots=True)
class TranslationAttemptLog:
    attempt: int
    error_type: str
    message: str
    retry_after_seconds: float


class TranslationValidationError(RuntimeError):
    def __init__(self, issues: dict[str, list[int]]) -> None:
        self.issues = {key: value for key, value in issues.items() if value}
        details = ", ".join(f"{key}={value}" for key, value in self.issues.items())
        super().__init__(f"Translation validation failed: {details}")


def short_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def classify_retry(exc: Exception, attempt: int, max_retries: int) -> tuple[float, str]:
    message = short_error_message(exc).lower()
    if "rate limit" in message or "429" in message:
        return (min(120.0, 20.0 * (attempt + 1)), "rate_limit")
    if "timed out" in message or "timeout" in message:
        return (min(90.0, 10.0 * (attempt + 1)), "timeout")
    if "connection" in message or "handshake" in message:
        return (min(60.0, 8.0 * (attempt + 1)), "network")
    return (min(45.0, 5.0 * (attempt + 1)), "generic")


def load_glossary(glossary: str | None) -> str:
    """如果用户提供了纯文本术语表，就把它读进来。

    这里先刻意保持简单。以后如果需要，可以再扩展 CSV/YAML 解析；
    目前纯文本已经足够承载固定人名、术语和偏好译法。
    """
    if not glossary:
        return ""
    with open(glossary, "r", encoding="utf-8") as file:
        raw_text = file.read().strip()
    if not raw_text:
        return ""
    if glossary.lower().endswith(".json"):
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return raw_text
        return render_structured_glossary(payload)
    return raw_text


def render_structured_glossary(payload: object) -> str:
    if isinstance(payload, dict):
        terms = payload.get("terms")
    else:
        terms = payload
    if not isinstance(terms, list):
        return json.dumps(payload, ensure_ascii=False)

    lines: list[str] = []
    for item in terms:
        if not isinstance(item, dict):
            continue
        canonical = str(item.get("canonical") or "").strip()
        if not canonical:
            continue
        zh = str(item.get("zh") or canonical).strip()
        policy = str(item.get("policy") or "preserve").strip()
        term_type = str(item.get("type") or "term").strip()
        aliases = [str(value).strip() for value in item.get("aliases") or [] if str(value).strip()]
        bad_aliases = [str(value).strip() for value in item.get("bad_aliases") or [] if str(value).strip()]
        line = f"- {canonical} | zh={zh} | type={term_type} | policy={policy}"
        if aliases:
            line += f" | aliases={'; '.join(aliases)}"
        if bad_aliases:
            line += f" | correct_bad_aliases={'; '.join(bad_aliases)} -> {canonical}"
        lines.append(line)
    return "\n".join(lines)


def style_glossary_hints(glossary_text: str) -> str:
    if not glossary_text.strip():
        return (
            "Glossary handling:\n"
            "- Chinese localization comes first: translate common proper nouns into established Simplified Chinese names.\n"
            "- Countries, cities, regions, peoples/languages, historical events, wars, and famous institutions should normally be Chinese, e.g. Japan=日本, Tokyo=东京, World War II=二战, Europe=欧洲, America=美国.\n"
            "- Keep English only when the item is a channel name, sponsor/brand, software/library name, code/UI label, album/title with no common Chinese rendering, or a niche name whose Chinese translation is uncertain.\n"
        )
    return (
        "Glossary handling:\n"
        "- Follow every glossary line as the source of truth.\n"
        "- If zh differs from the canonical term, use zh in the Chinese subtitle.\n"
        "- If policy=preserve, keep the canonical English term exactly.\n"
        "- If policy=translate, the Chinese subtitle must use zh and must not keep the English canonical form unless the glossary explicitly says mixed.\n"
        "- Correct aliases and ASR-looking name variants to the canonical term before translating.\n"
        "- For unlisted but well-known names, prefer the established Simplified Chinese name unless the context is a channel, sponsor, UI label, code term, software/library, product name, or niche creative title that should stay English.\n"
        "- The localization goal is Chinese readability: common terms like Japan, Tokyo, World War II, Europe, America, Japanese should be 日本、东京、二战、欧洲、美国、日本人/日本的, not left as English in Chinese subtitles.\n"
    )


def chunk_segments(segments: list[Segment], chunk_size: int) -> list[list[Segment]]:
    """把字幕分块，保证模型还能看到上下文。

    一条一条翻译会丢掉代词、说话人和术语上下文。
    分块可以把相邻句子放在一起，同时在某次 API 调用失败时也更容易重试。
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")
    return [segments[index : index + chunk_size] for index in range(0, len(segments), chunk_size)]


def chunk_segments_with_indexes(segments: list[Segment], chunk_size: int) -> list[tuple[int, int, list[Segment]]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")
    return [
        (index, min(index + chunk_size, len(segments)), segments[index : index + chunk_size])
        for index in range(0, len(segments), chunk_size)
    ]


def parse_json_payload(raw_text: str) -> list[dict]:
    """解析模型返回的 JSON，并提供一个轻量的代码块包裹兜底。

    提示词要求严格 JSON，但模型有时会把结果包在 Markdown 代码块里。
    这个兜底可以让流水线更宽容，但不会过度猜测损坏内容。
    """
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("translations"), list):
        return payload["translations"]
    raise ValueError("Translation response JSON must be a list or an object with a translations list.")


def normalize_for_equality(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def is_chinese_target_language(dst_lang: str | None) -> bool:
    normalized = (dst_lang or "").strip().lower()
    return normalized.startswith("zh") or "chinese" in normalized


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def normalize_term_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").casefold())


def is_likely_proper_name_only(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'’]*", cleaned)
    if not words or len(words) > 5:
        return False
    lowered = [word.casefold().strip("'’") for word in words]
    if any(word in TRANSLATABLE_FUNCTION_WORDS or word in TRANSLATABLE_DISCOURSE_MARKERS for word in lowered):
        return False
    if FIRST_PERSON_I_RE.search(cleaned):
        return False
    if re.search(r"\d", cleaned):
        return True
    return all(word[:1].isupper() or word.isupper() for word in words)


def extract_preserve_terms(glossary_text: str) -> set[str]:
    preserved: set[str] = set()
    for line in (glossary_text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        canonical = stripped[2:].split("|", 1)[0].strip()
        if not canonical:
            continue
        if "policy=preserve" not in stripped:
            continue
        normalized = normalize_term_text(canonical)
        if normalized in TRANSLATABLE_DISCOURSE_MARKERS:
            continue
        if normalized:
            preserved.add(normalized)
    return preserved


def extract_preserve_term_phrases(glossary_text: str) -> set[str]:
    phrases: set[str] = set()
    for line in (glossary_text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- ") or "policy=preserve" not in stripped:
            continue
        canonical = stripped[2:].split("|", 1)[0].strip()
        if re.search(r"\s", canonical):
            phrases.add(normalize_for_equality(canonical))
    return phrases


def extract_preserve_term_map(glossary_text: str) -> dict[str, str]:
    preserved: dict[str, str] = {}
    for line in (glossary_text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        canonical = stripped[2:].split("|", 1)[0].strip()
        if not canonical or "policy=preserve" not in stripped:
            continue
        normalized = normalize_term_text(canonical)
        if normalized in TRANSLATABLE_DISCOURSE_MARKERS:
            continue
        if normalized and normalized not in preserved:
            preserved[normalized] = canonical
    return preserved


def is_allowable_non_chinese_translation(source_text: str, translated_text: str, preserved_terms: set[str]) -> bool:
    if not source_text or not translated_text:
        return False
    normalized_source = normalize_term_text(source_text)
    normalized_target = normalize_term_text(translated_text)
    if not normalized_source or not normalized_target:
        return False
    if is_likely_proper_name_only(source_text) and is_likely_proper_name_only(translated_text):
        return True
    if normalized_target not in preserved_terms and not is_likely_proper_name_only(source_text):
        return False
    return normalized_target == normalized_source or normalized_target in normalized_source or normalized_source in normalized_target


def resolve_preserve_only_translation(source_text: str, preserve_term_map: dict[str, str]) -> str | None:
    normalized_source = normalize_term_text(source_text)
    if not normalized_source:
        return None
    for normalized_term, canonical in preserve_term_map.items():
        if normalized_source == normalized_term or normalized_source in normalized_term or normalized_term in normalized_source:
            return canonical
    return None


def filter_allowed_short_english_leaks(
    leaks: list[str],
    translated_text: str,
    source_text: str,
    preserved_phrases: set[str],
) -> list[str]:
    if not leaks:
        return leaks
    normalized_text = normalize_for_equality(translated_text)
    normalized_source = normalize_for_equality(source_text)
    return [
        leak
        for leak in leaks
        if not (
            any(
                normalize_for_equality(leak) in phrase
                and (phrase in normalized_text or phrase in normalized_source)
                for phrase in preserved_phrases
            )
            or is_leak_part_of_source_proper_phrase(leak, source_text)
        )
    ]


def is_leak_part_of_source_proper_phrase(leak: str, source_text: str) -> bool:
    leak_key = normalize_for_equality(leak)
    if not leak_key:
        return False
    for phrase in re.findall(r"\b[A-Z][A-Za-z'’.-]*(?:\s+[A-Z][A-Za-z'’.-]*)+\b", source_text or ""):
        words = [word.casefold().strip(".'’") for word in re.findall(r"[A-Za-z][A-Za-z'’.-]*", phrase)]
        if leak_key in words:
            return True
    return False


def has_translatable_alpha_text(text: str) -> bool:
    words = [word.casefold() for word in re.findall(r"[A-Za-z]{2,}", text or "")]
    if FIRST_PERSON_I_RE.search(text or ""):
        return True
    if len(words) < 2:
        return bool(words and words[0] in TRANSLATABLE_FUNCTION_WORDS)
    if re.search(r"[.!?]", text or "") and len(words) >= 3:
        return True
    if any(word in TRANSLATABLE_FUNCTION_WORDS for word in words):
        return True
    return len(words) >= 7


def validate_translations(
    chunk: list[Segment],
    translations: dict[int, str],
    *,
    dst_lang: str | None,
    preserved_terms: set[str] | None = None,
    preserved_phrases: set[str] | None = None,
) -> dict[str, list[int]]:
    expected_ids = {segment.id for segment in chunk}
    returned_ids = set(translations)
    source_by_id = {segment.id: segment.source_text for segment in chunk}
    preserved_terms = preserved_terms or set()
    preserved_phrases = preserved_phrases or set()

    issues: dict[str, list[int]] = {
        "missing": sorted(expected_ids - returned_ids),
        "extra": sorted(returned_ids - expected_ids),
        "empty": [],
        "source_echo": [],
        "target_without_chinese": [],
        "text_pollution": [],
        "short_english_leak": [],
    }
    for segment_id in sorted(expected_ids & returned_ids):
        translated_text = translations.get(segment_id, "").strip()
        source_text = source_by_id.get(segment_id, "").strip()
        if not translated_text:
            issues["empty"].append(segment_id)
            continue
        if (
            is_chinese_target_language(dst_lang)
            and normalize_for_equality(translated_text) == normalize_for_equality(source_text)
            and has_translatable_alpha_text(source_text)
        ):
            issues["source_echo"].append(segment_id)
        if (
            is_chinese_target_language(dst_lang)
            and not contains_chinese(translated_text)
            and has_translatable_alpha_text(source_text)
            and not is_allowable_non_chinese_translation(source_text, translated_text, preserved_terms)
        ):
            issues["target_without_chinese"].append(segment_id)
        pollution_issues = find_text_pollution(translated_text, dst_lang=dst_lang)
        if pollution_issues:
            issues["text_pollution"].append(segment_id)
        short_english_leaks = filter_allowed_short_english_leaks(
            find_short_english_leaks(translated_text, dst_lang=dst_lang),
            translated_text,
            source_text,
            preserved_phrases,
        )
        if short_english_leaks:
            issues["short_english_leak"].append(segment_id)
    return {key: value for key, value in issues.items() if value}


def sanitize_base_url(base_url: str | None) -> str | None:
    """清理并校验 base_url，避免传入空串或前后空白。"""
    if base_url is None:
        return None
    cleaned = base_url.strip()
    return cleaned or None


def resolve_openai_base_url(explicit_base_url: str | None = None) -> str | None:
    """解析 OpenAI 的 base_url，优先使用显式传入值。

    这个位置专门给中转站/网关留接口。你可以通过 CLI 传入，
    也可以设置环境变量 `OPENAI_BASE_URL` 或 `OPENAI_API_BASE`。
    """
    return (
        sanitize_base_url(explicit_base_url)
        or os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
    )


def build_translation_prompt(
    chunk: list[Segment],
    *,
    src_lang: str | None,
    dst_lang: str,
    glossary_text: str,
    style_prompt_text: str = "",
    context_before: list[Segment] | None = None,
    context_after: list[Segment] | None = None,
) -> str:
    payload = [
        {
            "id": segment.id,
            "start": segment.start,
            "end": segment.end,
            "source_text": segment.source_text,
        }
        for segment in chunk
    ]
    before_payload = [
        {
            "id": segment.id,
            "source_text": segment.source_text,
        }
        for segment in context_before or []
    ]
    after_payload = [
        {
            "id": segment.id,
            "source_text": segment.source_text,
        }
        for segment in context_after or []
    ]

    glossary_block = glossary_text or "No glossary provided."
    style_guidance = build_style_guidance(style_prompt_text)
    return (
        "You are a professional subtitle translator.\n"
        f"Translate subtitles from {src_lang or 'auto-detected source language'} "
        f"to {dst_lang}.\n\n"
        "Rules:\n"
        "- Translate naturally for on-screen subtitles.\n"
        "- Keep the translation concise; avoid explanatory expansion.\n"
        "- If the target language is Chinese, every translatable English fragment must contain Chinese words, not only punctuation.\n"
        "- Preserve names, numbers, and domain terms according to the glossary.\n\n"
        "- Chinese localization priority: translate common proper nouns with established Chinese names. Countries, cities, regions, peoples/languages, historical events, wars, and famous public institutions should be Chinese by default.\n"
        "- Examples: Japan=日本, Tokyo=东京, World War II=二战, Europe=欧洲, America/the United States=美国, Japanese=日本人/日本的 according to context.\n"
        "- Preserve English only for channel names, sponsors/brands, software/library names, code/UI labels, album/title names without a common Chinese rendering, or niche names where a Chinese name would be guesswork.\n\n"
        "- Do not treat conversational discourse markers as glossary terms or proper nouns. Words like because, maybe, right, well, okay, so, actually, basically, just, like, yeah, and sure must be translated or naturally absorbed into the Chinese line.\n"
        "- For ambiguous discourse markers, choose the Chinese rendering from context: right can mean 对吧/是吧/好了/正确/右边, maybe can mean 也许/可能/要不, because can mean 因为/是因为/毕竟. Do not leave them in English unless they are part of a literal UI/code label.\n"
        "- Short function words and pronouns such as and, but, then, I, I'm, and that's must also be translated or absorbed. Never leave mixed Chinese like And I love it, Then我觉得, I'm可以, That's问题, or And I他妈太喜欢了.\n"
        "- Do not add manual line breaks, markdown, bullets, or numbering inside target_text.\n"
        "- Preserve the input IDs exactly; each ID must return one complete translation.\n"
        "- Translate each input ID as its own on-screen subtitle; do not omit it or merge its meaning into another ID.\n"
        "- Do not split, truncate, or rearrange technical words, names, commands, paths, or identifiers.\n"
        "- Treat every word/token in the source as atomic; never break a word into pieces for layout.\n\n"
        "- Use the surrounding context only to resolve pronouns, terminology, and continuity.\n"
        "- Return translations only for Input JSON items; never return context item IDs.\n\n"
        "ASMR / whisper subtitle guidance:\n"
        "- In intimate ASMR contexts, pet means 抚摸/摸摸/宠爱, and Whisper may misrecognize pet as bet. If context mentions good boy, puppy, comfort, or feeling good, prefer the pet/抚摸 meaning over gambling.\n"
        "- If the source says have you to comfort, the speaker is comforting the listener; translate as 我还能安慰你/陪着你, not 让我安慰.\n"
        "- I am complete usually means 我就满足了/我就圆满了, not 我很完整.\n"
        "- Avoid stiff literal Chinese such as 让我安慰, 让我抚摸, 我就完整了, 把世界给我 when a natural subtitle phrasing is available.\n\n"
        f"Style guidance:\n{style_guidance}\n\n"
        f"{style_glossary_hints(glossary_text)}\n"
        f"Glossary:\n{glossary_block}\n\n"
        "Previous context JSON (read-only, do not translate in output):\n"
        f"{json.dumps(before_payload, ensure_ascii=False)}\n\n"
        "Input JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        "Next context JSON (read-only, do not translate in output):\n"
        f"{json.dumps(after_payload, ensure_ascii=False)}\n\n"
        "The output must follow the supplied JSON schema exactly."
    )


def build_translation_schema() -> dict:
    """为字幕翻译生成严格的 JSON Schema。

    这里故意用顶层 object 包一层 translations 数组，便于以后扩展
    元信息，比如语言、警告或审核标记。
    """
    return {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "target_text": {"type": "string"},
                    },
                    "required": ["id", "target_text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["translations"],
        "additionalProperties": False,
    }


def translate_chunk_with_openai(
    chunk: list[Segment],
    *,
    src_lang: str | None,
    dst_lang: str,
    glossary_text: str,
    model: str,
    style_prompt_text: str = "",
    base_url: str | None = None,
    max_retries: int = 2,
    retry_invalid_individually: bool = True,
    context_before: list[Segment] | None = None,
    context_after: list[Segment] | None = None,
) -> dict[int, str]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The OpenAI Python SDK is not installed. Install it with: "
            "python -m pip install openai"
        ) from exc

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Set it before using --translate-provider openai."
        )

    client_kwargs = {"timeout": 600.0}
    if base_url:
        # 如果你使用 GPTCodePlan 这类中转站，就在这里把 base_url 传给 SDK。
        client_kwargs["base_url"] = base_url

    client = OpenAI(**client_kwargs)
    prompt = build_translation_prompt(
        chunk,
        src_lang=src_lang,
        dst_lang=dst_lang,
        glossary_text=glossary_text,
        style_prompt_text=style_prompt_text,
        context_before=context_before,
        context_after=context_after,
    )
    if not retry_invalid_individually:
        prompt += (
            "\n\nQuality repair mode:\n"
            "- The previous translation for this exact subtitle failed validation.\n"
            "- Return clean Simplified Chinese subtitle text only, except established names or titles.\n"
            "- Do not output mojibake, replacement characters, phonetic gibberish, or text in Greek, Cyrillic, Hebrew, Arabic, Korean, Indic, or other unrelated scripts.\n"
            "- Do not leave short English function words mixed into Chinese.\n"
            "- If the source is a sentence fragment, translate it as a natural standalone subtitle fragment in Chinese."
        )
    translation_schema = build_translation_schema()
    preserved_terms = extract_preserve_terms(glossary_text)
    preserved_phrases = extract_preserve_term_phrases(glossary_text)

    raw_text = ""
    last_error: Exception | None = None
    attempt_logs: list[TranslationAttemptLog] = []
    for attempt in range(max_retries + 1):
        try:
            # OpenAI 的 Responses 接口更适合做文本生成。
            # 这里使用 Structured Outputs，让返回值严格对齐 JSON Schema。
            response = client.responses.create(
                model=model,
                input=prompt,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "subtitle_translation",
                        "strict": True,
                        "schema": translation_schema,
                    },
                    "verbosity": "low",
                },
            )
            raw_text = response.output_text.strip()
            payload = parse_json_payload(raw_text)
            break
        except Exception as exc:
            last_error = exc
            wait_seconds, retry_category = classify_retry(exc, attempt, max_retries)
            attempt_logs.append(
                TranslationAttemptLog(
                    attempt=attempt + 1,
                    error_type=retry_category,
                    message=short_error_message(exc),
                    retry_after_seconds=wait_seconds if attempt < max_retries else 0.0,
                )
            )
            if attempt >= max_retries:
                log_lines = "\n".join(
                    f"attempt {item.attempt}: [{item.error_type}] {item.message}"
                    for item in attempt_logs
                )
                raise RuntimeError(
                    "OpenAI translation failed after retries.\n"
                    f"attempt_logs:\n{log_lines}\n"
                    f"last_raw_output:\n{raw_text}"
                ) from last_error
            time.sleep(wait_seconds)

    translations: dict[int, str] = {}
    if isinstance(payload, dict):
        payload = payload["translations"]
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeError(f"Invalid translation item: {item!r}")
        if "id" not in item or "target_text" not in item:
            raise RuntimeError(f"Translation item missing id or target_text: {item!r}")
        translations[int(item["id"])] = str(item["target_text"]).strip()

    expected_ids = {segment.id for segment in chunk}
    extra_ids = sorted(set(translations) - expected_ids)
    for segment_id in extra_ids:
        translations.pop(segment_id, None)

    issues = validate_translations(
        chunk,
        translations,
        dst_lang=dst_lang,
        preserved_terms=preserved_terms,
        preserved_phrases=preserved_phrases,
    )
    retryable_ids = sorted(
        set(issues.get("missing", []))
        | set(issues.get("empty", []))
        | set(issues.get("source_echo", []))
        | set(issues.get("target_without_chinese", []))
        | set(issues.get("text_pollution", []))
        | set(issues.get("short_english_leak", []))
    )
    if retryable_ids and retry_invalid_individually and len(chunk) > 1:
        segment_by_id = {segment.id: segment for segment in chunk}
        for segment_id in retryable_ids:
            single_segment = segment_by_id[segment_id]
            single_translation = translate_chunk_with_openai(
                [single_segment],
                src_lang=src_lang,
                dst_lang=dst_lang,
                glossary_text=glossary_text,
                style_prompt_text=style_prompt_text,
                model=model,
                base_url=base_url,
                max_retries=max_retries,
                retry_invalid_individually=False,
                context_before=context_before,
                context_after=context_after,
            )
            translations[segment_id] = single_translation[segment_id]
        issues = validate_translations(
            chunk,
            translations,
            dst_lang=dst_lang,
            preserved_terms=preserved_terms,
            preserved_phrases=preserved_phrases,
        )

    if issues and not retry_invalid_individually and len(chunk) == 1:
        segment = chunk[0]
        for repair_attempt in range(max_retries):
            repair_prompt = (
                f"{prompt}\n\nValidation failure repair attempt {repair_attempt + 1}/{max_retries}:\n"
                f"- Failed issues: {json.dumps(issues, ensure_ascii=False)}\n"
                f"- Previous invalid target_text: {json.dumps(translations.get(segment.id, ''), ensure_ascii=False)}\n"
                "- Return a new clean target_text for this same ID that fixes every listed issue."
            )
            try:
                response = client.responses.create(
                    model=model,
                    input=repair_prompt,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "subtitle_translation",
                            "strict": True,
                            "schema": translation_schema,
                        },
                        "verbosity": "low",
                    },
                )
                raw_text = response.output_text.strip()
                repaired_payload = parse_json_payload(raw_text)
                repaired_translations = {
                    int(item["id"]): str(item["target_text"]).strip()
                    for item in repaired_payload
                    if isinstance(item, dict) and "id" in item and "target_text" in item
                }
                if segment.id in repaired_translations:
                    translations[segment.id] = repaired_translations[segment.id]
                issues = validate_translations(
                    chunk,
                    translations,
                    dst_lang=dst_lang,
                    preserved_terms=preserved_terms,
                    preserved_phrases=preserved_phrases,
                )
                if not issues:
                    break
            except Exception as exc:
                if repair_attempt >= max_retries - 1:
                    raise RuntimeError(
                        "OpenAI translation validation repair failed after retries.\n"
                        f"issues={json.dumps(issues, ensure_ascii=False)}\n"
                        f"last_raw_output:\n{raw_text}"
                    ) from exc
                wait_seconds, _ = classify_retry(exc, repair_attempt, max_retries)
                time.sleep(wait_seconds)

    if issues:
        raise TranslationValidationError(issues)

    return translations


def dry_run_openai_translation(
    *,
    model: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    """做一次最小化连通性检查，便于确认 key、模型和网关是否可用。

    这里不依赖字幕输入，只发一个极小请求，适合在正式跑长视频前做验证。
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "The OpenAI Python SDK is not installed. Install it with: "
            "python -m pip install openai"
        ) from exc

    resolved_base_url = resolve_openai_base_url(base_url)
    client_kwargs = {"timeout": 600.0}
    if resolved_base_url:
        client_kwargs["base_url"] = resolved_base_url

    client = OpenAI(**client_kwargs)
    response = client.responses.create(
        model=model,
        input="Reply with a single word: ok",
    )
    return {
        "model": model,
        "base_url": resolved_base_url,
        "output_text": response.output_text.strip(),
    }


def translate_segments(
    segments: list[Segment],
    *,
    src_lang: str | None,
    dst_lang: str | None,
    glossary: str | None = None,
    enabled: bool = False,
    provider: str = "copy",
    model: str = "gpt-5-mini",
    chunk_size: int = 40,
    max_retries: int = 2,
    openai_base_url: str | None = None,
    context_window: int = 4,
    locked_segment_ids: set[int] | None = None,
    style_prompt_path: str | None = None,
    style_prompt_text: str | None = None,
    progress_callback: TranslationProgressCallback | None = None,
) -> list[Segment]:
    if not enabled:
        for segment in segments:
            segment.target_text = segment.source_text
        return segments

    if provider != "openai":
        raise ValueError(f"Unsupported translation provider: {provider}")

    if not dst_lang:
        raise ValueError("dst_lang is required when translation is enabled.")

    glossary_text = load_glossary(glossary)
    loaded_style_prompt_text = load_style_prompt_text(style_prompt_path)
    style_prompt_text = "\n\n".join(
        item for item in [style_prompt_text or "", loaded_style_prompt_text] if item.strip()
    )
    preserve_term_map = extract_preserve_term_map(glossary_text)
    resolved_base_url = resolve_openai_base_url(openai_base_url)
    locked_segment_ids = locked_segment_ids or set()
    chunks = chunk_segments_with_indexes(segments, chunk_size)
    for chunk_index, (start_index, end_index, chunk) in enumerate(chunks, start=1):
        direct_translations = {
            segment.id: preserve_only
            for segment in chunk
            if (preserve_only := resolve_preserve_only_translation(segment.source_text, preserve_term_map))
        }
        locked_translations = {
            segment.id: segment.target_text.strip()
            for segment in chunk
            if segment.id in locked_segment_ids and segment.target_text and segment.target_text.strip()
        }
        direct_translations.update(locked_translations)
        chunk_for_model = [segment for segment in chunk if segment.id not in direct_translations]
        context_window = max(0, int(context_window or 0))
        context_before = segments[max(0, start_index - context_window) : start_index]
        context_after = segments[end_index : min(len(segments), end_index + context_window)]
        if progress_callback:
            progress_callback(
                "translation_chunk_start",
                {
                    "chunk_index": chunk_index,
                    "chunk_total": len(chunks),
                    "segment_count": len(chunk),
                    "direct_count": len(direct_translations),
                    "locked_count": len(locked_translations),
                    "context_before": len(context_before),
                    "context_after": len(context_after),
                },
            )
        print(f"Translating chunk {chunk_index}/{len(chunks)} with {len(chunk)} segments.")
        started_at = time.time()
        translations = dict(direct_translations)
        if chunk_for_model:
            try:
                model_translations = translate_chunk_with_openai(
                    chunk_for_model,
                    src_lang=src_lang,
                    dst_lang=dst_lang,
                    glossary_text=glossary_text,
                    style_prompt_text=style_prompt_text,
                    model=model,
                    base_url=resolved_base_url,
                    max_retries=max_retries,
                    context_before=context_before,
                    context_after=context_after,
                )
                translations.update(model_translations)
            except Exception as exc:
                chunk_summary = (
                    f"chunk {chunk_index}/{len(chunks)} failed after {round(time.time() - started_at, 2)}s; "
                    f"segment_ids={chunk[0].id}-{chunk[-1].id}; count={len(chunk)}"
                )
                raise RuntimeError(f"{chunk_summary}\n{exc}") from exc
        fallback_count = 0
        for segment in chunk:
            translated_text = translations.get(segment.id, "").strip()
            if translated_text == segment.source_text.strip():
                fallback_count += 1
            segment.target_text = translated_text
        if progress_callback:
            progress_callback(
                "translation_chunk_complete",
                {
                    "chunk_index": chunk_index,
                    "chunk_total": len(chunks),
                    "segment_count": len(chunk),
                    "direct_count": len(direct_translations),
                    "locked_count": len(locked_translations),
                    "fallback_count": fallback_count,
                    "elapsed_seconds": round(time.time() - started_at, 2),
                    "context_before": len(context_before),
                    "context_after": len(context_after),
                },
            )

    return segments
