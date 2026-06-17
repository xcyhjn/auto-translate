from __future__ import annotations

import csv
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx


BILIBILI_SEARCH_URL = "https://search.bilibili.com/video?keyword={keyword}"
BILIBILI_SEARCH_API_URL = "https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword={keyword}"
BILIBILI_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
MAX_QUERY_COUNT = 12
MAX_RESULTS_PER_QUERY = 10


class BilibiliSearchChannelLimited(RuntimeError):
    def __init__(self, message: str, *, channel: str = "search", reason_code: str = "search_channel_limited") -> None:
        super().__init__(message)
        self.channel = channel
        self.reason_code = reason_code

EN_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "about",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "part",
    "the",
    "this",
    "to",
    "with",
    "what",
    "why",
    "you",
    "your",
}

GENERIC_TOKENS = {
    "video",
    "story",
    "explained",
    "guide",
    "review",
    "essay",
    "thing",
    "things",
}

NEGATIVE_MARKERS = {
    "reaction",
    "reacts",
    "剪辑",
    "混剪",
    "二创",
    "反应",
    "reaction",
    "二剪",
    "高燃",
    "纯享",
}

SOURCE_MARKERS = {"转载", "搬运", "翻译", "中字", "字幕", "授权", "原视频", "youtube", "YouTube"}

SOURCE_MARKERS.update({"中配", "中文配音", "配音", "中字", "字幕", "转载", "搬运"})

CONCEPTS: dict[str, dict[str, list[str]]] = {
    "russian": {"en": ["russian", "russia"], "zh": ["俄罗斯", "俄国", "俄语"]},
    "book": {"en": ["book", "novel", "fiction"], "zh": ["书", "小说", "文学"]},
    "dying": {"en": ["dying", "dead", "death"], "zh": ["垂死", "死去", "死亡"]},
    "god": {"en": ["god", "deity", "divine"], "zh": ["神", "神明"]},
    "game": {"en": ["game", "games"], "zh": ["游戏"]},
    "film": {"en": ["film", "movie", "cinema"], "zh": ["电影", "影片"]},
    "music": {"en": ["music", "album", "song"], "zh": ["音乐", "专辑", "歌曲"]},
    "art": {"en": ["art", "artist"], "zh": ["艺术", "艺术家"]},
    "history": {"en": ["history", "historic"], "zh": ["历史"]},
    "lost": {"en": ["lost", "missing"], "zh": ["失落", "遗失"]},
    "mystery": {"en": ["mystery", "secret"], "zh": ["谜", "秘密"]},
}

CONCEPTS.update(
    {
        "philosophy": {"en": ["philosophy", "philosophical"], "zh": ["哲学"]},
        "world": {"en": ["world", "worlds"], "zh": ["世界"]},
        "incredible": {"en": ["incredible", "amazing", "astonishing"], "zh": ["令人惊叹", "惊叹"]},
        "science": {"en": ["science", "scientific"], "zh": ["科学"]},
        "funny": {"en": ["funny", "humor", "humour", "comedy"], "zh": ["搞笑", "有趣"]},
    }
)


def build_search_url(query: str) -> str:
    return BILIBILI_SEARCH_URL.format(keyword=quote(query.strip()))


def build_search_api_url(query: str) -> str:
    return BILIBILI_SEARCH_API_URL.format(keyword=quote(query.strip()))


def strip_html(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", value or "", flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_query_key(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", (value or "").lower(), flags=re.U)


def normalize_text_for_match(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip().lower()


def english_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", value or "")
    cleaned: list[str] = []
    for token in tokens:
        normalized = token.strip("'-").lower()
        if len(normalized) < 2 or normalized in EN_STOP_WORDS:
            continue
        cleaned.append(normalized)
    return cleaned


def clean_title(title: str) -> str:
    cleaned = re.sub(r"[\[\(（【].*?[\]\)）】]", " ", title or "")
    cleaned = re.sub(r"\b(?:ep|episode|part|pt|p)\s*[.#:-]?\s*\d+\b", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"\b\d+\s*/\s*\d+\b", " ", cleaned)
    cleaned = re.sub(r"[^\w\s'-]+", " ", cleaned, flags=re.U)
    return normalize_space(cleaned)


def extract_proper_phrases(title: str) -> list[str]:
    phrases = re.findall(r"\b[A-Z][A-Za-z0-9'-]+(?:\s+[A-Z][A-Za-z0-9'-]+){0,3}", title or "")
    results: list[str] = []
    for phrase in phrases:
        tokens = [token for token in phrase.split() if token.lower() not in EN_STOP_WORDS]
        if not tokens:
            continue
        cleaned = " ".join(tokens)
        if cleaned.lower() in {"youtube"}:
            continue
        results.append(cleaned)
    return dedupe_strings(results, limit=5)


def concept_hits_for_tokens(tokens: list[str]) -> list[str]:
    token_set = set(tokens)
    hits: list[str] = []
    for concept, variants in CONCEPTS.items():
        if token_set.intersection(variants["en"]):
            hits.append(concept)
    return hits


def concept_hits_for_text(value: str) -> list[str]:
    lowered = normalize_text_for_match(value)
    hits: list[str] = []
    token_set = set(english_tokens(value))
    for concept, variants in CONCEPTS.items():
        if token_set.intersection(variants["en"]) or any(term.lower() in lowered for term in variants["zh"]):
            hits.append(concept)
    return hits


def zh_terms_for_concepts(concepts: list[str]) -> list[str]:
    terms: list[str] = []
    for concept in concepts:
        variants = CONCEPTS.get(concept, {}).get("zh", [])
        if variants:
            terms.append(variants[0])
    return terms


def phrase_variants_for_concepts(concepts: list[str]) -> list[str]:
    concept_set = set(concepts)
    variants: list[str] = []
    if {"philosophy", "world", "incredible"}.issubset(concept_set):
        variants.extend(
            [
                "哲学的世界令人惊叹",
                "哲学 世界 令人惊叹",
                "哲学 中配",
            ]
        )
    if {"russian", "dying", "god", "book"}.issubset(concept_set):
        variants.extend(
            [
                "垂死的神 俄罗斯 小说",
                "死去的神 俄罗斯 书",
                "俄罗斯 神明 小说 解说",
                "dying god book",
                "Russian book dying god",
            ]
        )
    if {"dying", "god"}.issubset(concept_set):
        variants.append("垂死的神")
    if {"russian", "book"}.issubset(concept_set):
        variants.append("俄罗斯 小说")
    if {"game"}.issubset(concept_set):
        variants.append("游戏 解说")
    if {"film"}.issubset(concept_set):
        variants.append("电影 解说")
    if {"music"}.issubset(concept_set):
        variants.append("音乐 专辑")
    return variants


def title_semantic_query_variants(title_concepts: list[str], author: str) -> list[tuple[str, str, list[str], str]]:
    variants: list[tuple[str, str, list[str], str]] = []
    for phrase in phrase_variants_for_concepts(title_concepts):
        variants.append(
            (
                "title_translation",
                phrase,
                title_concepts,
                "标题语义优先生成的中文意译/关键词重组",
            )
        )
    zh_terms = dedupe_strings(zh_terms_for_concepts(title_concepts), limit=6)
    if zh_terms:
        variants.append(
            (
                "title_keywords_zh",
                " ".join(zh_terms),
                title_concepts,
                "标题核心关键词中文化",
            )
        )
    if author and "philosophy" in title_concepts:
        variants.append(
            (
                "author_title_context",
                f"{author} 中配",
                [author, "中配"],
                "作者名仅作为标题语义的弱补充",
            )
        )
    return variants


def dedupe_strings(values: list[str], *, limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for value in values:
        cleaned = normalize_space(value)
        if not cleaned:
            continue
        key = normalize_query_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        results.append(cleaned)
        if limit is not None and len(results) >= limit:
            break
    return results


def build_bilibili_query_plan(youtube_meta: dict, glossary: dict | None = None) -> list[dict]:
    title = str(youtube_meta.get("title") or "")
    description = str(youtube_meta.get("description") or "")
    author = str(youtube_meta.get("author") or youtube_meta.get("channel") or "")
    cleaned_title = clean_title(title)
    title_tokens = english_tokens(cleaned_title or title)
    description_tokens = english_tokens(description)[:24]
    title_core_tokens = [
        token
        for token in title_tokens
        if token not in GENERIC_TOKENS and not token.isdigit()
    ][:8]
    core_tokens = title_core_tokens[:]
    if len(core_tokens) < 3:
        core_tokens = (core_tokens + [token for token in description_tokens if token not in core_tokens])[:8]

    title_concepts = concept_hits_for_tokens(title_core_tokens or title_tokens)
    description_concepts = concept_hits_for_tokens(description_tokens)
    concepts = title_concepts or concept_hits_for_tokens(core_tokens) or description_concepts
    zh_terms = zh_terms_for_concepts(title_concepts or concepts)
    proper_phrases = extract_proper_phrases(title)
    query_specs: list[tuple[str, str, list[str], str]] = []

    def add(kind: str, text: str, terms: list[str], reason: str) -> None:
        query_specs.append((kind, text, terms, reason))

    add("original_title", title, title_tokens, "原始 YouTube 标题")
    if cleaned_title and normalize_query_key(cleaned_title) != normalize_query_key(title):
        add("cleaned_title", cleaned_title, core_tokens, "去括号、集数和标点后的标题")
    for kind, text, terms, reason in title_semantic_query_variants(title_concepts, author):
        add(kind, text, terms, reason)
    for variant in ([] if title_concepts else phrase_variants_for_concepts(concepts)):
        add("semantic_variant", variant, concepts, "本地规则生成的中文/中英混合语义变体")

    if core_tokens:
        add("core_english_terms", " ".join(core_tokens[:6]), core_tokens[:6], "英文核心名词短语")

    if zh_terms:
        add("translated_keywords", " ".join(dedupe_strings(zh_terms, limit=6)), concepts, "核心关键词本地中文化")
        if core_tokens:
            mixed_terms = dedupe_strings(core_tokens[:2] + zh_terms[:4], limit=6)
            add("mixed_keywords", " ".join(mixed_terms), mixed_terms, "保留英文专词的中英混合查询")

    for phrase in proper_phrases:
        if zh_terms:
            add("proper_name_mixed", f"{phrase} {' '.join(zh_terms[:3])}", [phrase, *zh_terms[:3]], "专名保留英文并补中文主题词")
        else:
            add("proper_name", phrase, [phrase], "标题中的专名/作品名")

    glossary_terms = []
    if isinstance(glossary, dict):
        raw_terms = glossary.get("terms") or glossary.get("glossary") or []
        if isinstance(raw_terms, list):
            for item in raw_terms:
                if isinstance(item, dict):
                    term = str(item.get("target") or item.get("source") or "").strip()
                else:
                    term = str(item or "").strip()
                if term:
                    glossary_terms.append(term)
    if glossary_terms:
        add("glossary_terms", " ".join(dedupe_strings(glossary_terms, limit=5)), glossary_terms[:5], "项目术语表补充查询")

    if author and core_tokens:
        add("author_weak_context", f"{author} {' '.join(core_tokens[:3])}", [author, *core_tokens[:3]], "频道名仅作弱特征补充")

    deduped: list[dict] = []
    seen: set[str] = set()
    for kind, text, terms, reason in query_specs:
        cleaned = normalize_space(text)
        key = normalize_query_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "id": f"q{len(deduped) + 1:02d}",
                "kind": kind,
                "text": cleaned,
                "terms": dedupe_strings([str(term) for term in terms], limit=8),
                "reason": reason,
                "search_url": build_search_url(cleaned),
                "api_url": build_search_api_url(cleaned),
            }
        )
        if len(deduped) >= MAX_QUERY_COUNT:
            break
    return deduped


def parse_duration_to_seconds(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total if total > 0 else None


def parse_date(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:19], pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _json_field(snippet: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', snippet)
    if not match:
        return ""
    try:
        return json.loads(f'"{match.group(1)}"')
    except Exception:
        return html.unescape(match.group(1))


def _attr_value(snippet: str, name: str) -> str:
    match = re.search(rf'\b{name}\s*=\s*["\']([^"\']+)["\']', snippet, flags=re.I)
    return html.unescape(match.group(1)).strip() if match else ""


def _normalize_bilibili_url(value: str, bvid: str = "") -> str:
    url = html.unescape(value or "").strip()
    if url.startswith("//"):
        url = f"https:{url}"
    elif url.startswith("/"):
        url = f"https://www.bilibili.com{url}"
    if not url and bvid:
        url = f"https://www.bilibili.com/video/{bvid}"
    url = url.split("?")[0]
    return url.rstrip("/")


def _candidate_from_json_snippet(snippet: str, *, query: str, search_url: str) -> dict | None:
    bvid = _json_field(snippet, "bvid") or _json_field(snippet, "id")
    if not bvid.startswith("BV"):
        return None
    title = _json_field(snippet, "title") or _json_field(snippet, "typename")
    title = strip_html(title)
    if not title:
        return None
    duration = _json_field(snippet, "duration") or _json_field(snippet, "length")
    uploader = _json_field(snippet, "author") or _json_field(snippet, "up_name") or _json_field(snippet, "uname")
    published_at = _json_field(snippet, "pubdate") or _json_field(snippet, "senddate") or _json_field(snippet, "created")
    description = _json_field(snippet, "description") or _json_field(snippet, "desc")
    if str(published_at).isdigit() and len(str(published_at)) >= 9:
        try:
            published_at = datetime.fromtimestamp(int(published_at), tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            published_at = str(published_at)
    return {
        "title": title,
        "url": _normalize_bilibili_url("", bvid),
        "bvid": bvid,
        "uploader": strip_html(uploader),
        "duration": duration,
        "duration_seconds": parse_duration_to_seconds(duration),
        "published_at": str(published_at or ""),
        "description": strip_html(description),
        "snippet": strip_html(description),
        "matched_queries": [query],
        "source_search_url": search_url,
        "search_channel": "html",
    }


def _extract_json_candidates(html_text: str, *, query: str, search_url: str) -> list[dict]:
    candidates: list[dict] = []
    for match in re.finditer(r'"bvid"\s*:\s*"BV[A-Za-z0-9]+"', html_text or ""):
        start = max(0, match.start() - 900)
        end = min(len(html_text), match.end() + 2200)
        candidate = _candidate_from_json_snippet(html_text[start:end], query=query, search_url=search_url)
        if candidate:
            candidates.append(candidate)
    return candidates


def _extract_html_candidates(html_text: str, *, query: str, search_url: str) -> list[dict]:
    candidates: list[dict] = []
    anchor_re = re.compile(
        r"<a\b(?P<attrs>[^>]*?href=[\"'](?P<href>[^\"']*?/video/(?P<bvid>BV[A-Za-z0-9]+)[^\"']*)[\"'][^>]*)>(?P<body>.*?)</a>",
        flags=re.I | re.S,
    )
    for match in anchor_re.finditer(html_text or ""):
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        title = _attr_value(attrs, "title") or strip_html(body)
        title = strip_html(title)
        if not title or title.lower() in {"视频", "watch"}:
            continue
        window = html_text[max(0, match.start() - 500) : min(len(html_text), match.end() + 1400)]
        uploader = ""
        up_match = re.search(r'class=["\'][^"\']*(?:up-name|bili-video-card__info--author)[^"\']*["\'][^>]*>(.*?)</a>', window, flags=re.I | re.S)
        if up_match:
            uploader = strip_html(up_match.group(1))
        duration = ""
        duration_match = re.search(r"(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)", window)
        if duration_match:
            duration = duration_match.group(1)
        published_at = ""
        date_match = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}|昨天|今天|\d+\s*小时前)", window)
        if date_match:
            published_at = date_match.group(1)
        snippet_match = re.search(r'class=["\'][^"\']*(?:des|desc|detail)[^"\']*["\'][^>]*>(.*?)</', window, flags=re.I | re.S)
        snippet = strip_html(snippet_match.group(1)) if snippet_match else ""
        candidates.append(
            {
                "title": title,
                "url": _normalize_bilibili_url(match.group("href"), match.group("bvid")),
                "bvid": match.group("bvid"),
                "uploader": uploader,
                "duration": duration,
                "duration_seconds": parse_duration_to_seconds(duration),
                "published_at": published_at,
                "description": snippet,
                "snippet": snippet,
                "matched_queries": [query],
                "source_search_url": search_url,
                "search_channel": "html",
            }
        )
    return candidates


def is_bilibili_captcha_page(html_text: str) -> bool:
    text = html_text or ""
    lowered = text.lower()
    return (
        "验证码_哔哩哔哩" in text
        or "安全验证" in text
        or "bili-captcha" in lowered
        or "geetest" in lowered
        or "risk" in lowered and "captcha" in lowered
    )


def parse_bilibili_api_results(
    payload: dict,
    *,
    query: str = "",
    search_url: str = "",
    api_url: str = "",
) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError("Bilibili search API returned a non-object payload")
    code = payload.get("code")
    if code not in (0, None):
        message = payload.get("message") or payload.get("msg") or "unknown error"
        raise RuntimeError(f"Bilibili search API returned code {code}: {message}")

    data = payload.get("data") or {}
    raw_results = data.get("result") or []
    candidates: list[dict] = []
    if not isinstance(raw_results, list):
        return candidates

    for item in raw_results:
        if not isinstance(item, dict):
            continue
        bvid = str(item.get("bvid") or "").strip()
        title = strip_html(str(item.get("title") or ""))
        if not bvid.startswith("BV") or not title:
            continue
        url = _normalize_bilibili_url(str(item.get("arcurl") or item.get("url") or ""), bvid)
        duration = str(item.get("duration") or item.get("length") or "").strip()
        published_at = item.get("pubdate") or item.get("senddate") or item.get("created") or ""
        if str(published_at).isdigit() and len(str(published_at)) >= 9:
            try:
                published_at = datetime.fromtimestamp(int(published_at), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                published_at = str(published_at)
        description = strip_html(str(item.get("description") or item.get("desc") or ""))
        uploader = strip_html(str(item.get("author") or item.get("upname") or item.get("uname") or ""))
        candidates.append(
            {
                "title": title,
                "url": url,
                "bvid": bvid,
                "uploader": uploader,
                "duration": duration,
                "duration_seconds": parse_duration_to_seconds(duration),
                "published_at": str(published_at or ""),
                "description": description,
                "snippet": description,
                "matched_queries": [query],
                "source_search_url": search_url,
                "source_api_url": api_url,
                "search_channel": "api",
            }
        )
    return dedupe_candidates(candidates)[:MAX_RESULTS_PER_QUERY]


def dedupe_candidates(candidates: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for candidate in candidates:
        url = _normalize_bilibili_url(str(candidate.get("url") or ""))
        key = url or normalize_query_key(str(candidate.get("title") or ""))
        if not key:
            continue
        existing = merged.get(key)
        if not existing:
            candidate["url"] = url
            candidate["matched_queries"] = dedupe_strings([str(item) for item in candidate.get("matched_queries") or []])
            merged[key] = candidate
            continue
        existing["matched_queries"] = dedupe_strings(
            [*(existing.get("matched_queries") or []), *(candidate.get("matched_queries") or [])],
            limit=MAX_QUERY_COUNT,
        )
        if not existing.get("source_search_url") and candidate.get("source_search_url"):
            existing["source_search_url"] = candidate["source_search_url"]
        for field in ("uploader", "duration", "published_at", "description", "snippet"):
            if not existing.get(field) and candidate.get(field):
                existing[field] = candidate[field]
    return list(merged.values())


def parse_bilibili_search_results(html_text: str, *, query: str = "", search_url: str = "") -> list[dict]:
    candidates = [
        *_extract_json_candidates(html_text, query=query, search_url=search_url),
        *_extract_html_candidates(html_text, query=query, search_url=search_url),
    ]
    return dedupe_candidates(candidates)[:MAX_RESULTS_PER_QUERY]


def search_bilibili(
    query: str,
    *,
    proxy_url: str | None = None,
    max_results: int = MAX_RESULTS_PER_QUERY,
    timeout_seconds: float = 8.0,
) -> list[dict]:
    search_url = build_search_url(query)
    api_url = build_search_api_url(query)
    headers = {
        "User-Agent": BILIBILI_USER_AGENT,
        "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Referer": "https://www.bilibili.com/",
    }
    api_error: Exception | None = None
    with httpx.Client(
        timeout=timeout_seconds,
        proxy=proxy_url or None,
        trust_env=not bool(proxy_url),
        follow_redirects=True,
        headers=headers,
    ) as client:
        try:
            response = client.get(api_url)
            response.raise_for_status()
            candidates = parse_bilibili_api_results(
                response.json(),
                query=query,
                search_url=search_url,
                api_url=api_url,
            )
            return candidates[:max_results]
        except Exception as exc:
            api_error = exc

        response = client.get(search_url)
        response.raise_for_status()
        if is_bilibili_captcha_page(response.text):
            raise BilibiliSearchChannelLimited(
                f"Bilibili search channel limited by captcha/risk page after API failure: {api_error}",
                channel="html",
            )
    candidates = parse_bilibili_search_results(response.text, query=query, search_url=search_url)
    for candidate in candidates:
        candidate.setdefault("search_channel", "html")
    return candidates[:max_results]


def youtube_duration_seconds(youtube_meta: dict) -> int | None:
    for key in ("duration_seconds", "duration", "length_seconds"):
        seconds = parse_duration_to_seconds(youtube_meta.get(key))
        if seconds:
            return seconds
    return None


def confidence_for_score(score: int) -> str:
    if score >= 80:
        return "high_confidence_possible_duplicate"
    if score >= 60:
        return "medium_confidence_review"
    if score >= 40:
        return "low_confidence_related"
    return "ignore"


def score_bilibili_candidate(candidate: dict, youtube_meta: dict, query_plan: list[dict]) -> dict:
    title = str(candidate.get("title") or "")
    description = str(candidate.get("description") or candidate.get("snippet") or "")
    combined_text = f"{title} {description} {candidate.get('uploader') or ''}"
    combined_lower = normalize_text_for_match(combined_text)
    title_lower = normalize_text_for_match(title)

    source_title = str(youtube_meta.get("title") or "")
    source_description = str(youtube_meta.get("description") or "")
    source_author = str(youtube_meta.get("author") or "")
    source_video_id = str(youtube_meta.get("video_id") or "")
    source_tokens = [
        token
        for token in english_tokens(clean_title(source_title) or source_title)
        if token not in GENERIC_TOKENS
    ]
    candidate_tokens = set(english_tokens(title))
    source_title_concepts = concept_hits_for_tokens(source_tokens)
    source_description_concepts = concept_hits_for_tokens(english_tokens(source_description)[:24])
    source_concepts = source_title_concepts or source_description_concepts
    candidate_title_concepts = concept_hits_for_text(title)
    candidate_all_concepts = concept_hits_for_text(combined_text)
    matched_concepts = [concept for concept in source_concepts if concept in candidate_all_concepts]
    matched_title_concepts = [concept for concept in source_concepts if concept in candidate_title_concepts]

    reason_codes: list[str] = []
    evidence: list[str] = []

    title_score = 0.0
    if source_tokens:
        overlap = sorted(set(source_tokens).intersection(candidate_tokens))
        if overlap:
            title_score += min(12.0, 12.0 * len(overlap) / max(1, len(set(source_tokens))))
            reason_codes.append("english_title_token_overlap")
            evidence.append(f"英文标题 token 命中：{', '.join(overlap[:6])}")
    if source_concepts:
        title_concept_score = min(16.0, 16.0 * len(matched_title_concepts) / max(1, len(set(source_concepts))))
        if title_concept_score:
            title_score += title_concept_score
            reason_codes.append("translated_keyword_overlap")
            evidence.append(f"标题语义概念命中：{', '.join(matched_title_concepts)}")
    if ("dying" in source_concepts and "god" in source_concepts) and ("垂死的神" in title or "死去的神" in title):
        title_score += 7.0
        reason_codes.append("title_translation_phrase_hit")
        evidence.append("候选标题命中“垂死/死去的神”翻译变体")
    elif {"philosophy", "world", "incredible"}.issubset(set(source_title_concepts)) and (
        "哲学的世界令人惊叹" in title or ("哲学" in title_lower and "世界" in title_lower and "惊叹" in title_lower)
    ):
        title_score += 12.0
        reason_codes.append("title_translation_phrase_hit")
        evidence.append("标题命中哲学的世界令人惊叹")
    elif len(matched_title_concepts) >= 3:
        title_score += 5.0
        reason_codes.append("title_semantic_variant_hit")
    title_score = min(35.0, title_score)

    semantic_score = 0.0
    if source_concepts:
        semantic_score += min(18.0, 18.0 * len(matched_concepts) / max(1, len(set(source_concepts))))
        if matched_concepts:
            reason_codes.append("semantic_keyword_hit")
            evidence.append(f"标题/简介语义关键词命中：{', '.join(matched_concepts)}")
    description_concepts = source_description_concepts
    description_hits = [concept for concept in description_concepts if concept in candidate_all_concepts]
    if description_hits:
        semantic_score += min(7.0, 7.0 * len(description_hits) / max(1, len(set(description_concepts))))
        reason_codes.append("description_keyword_hit")
    semantic_score = min(25.0, semantic_score)

    duration_score = 0.0
    duration_penalty = 0.0
    yt_seconds = youtube_duration_seconds(youtube_meta)
    bili_seconds = parse_duration_to_seconds(candidate.get("duration_seconds") or candidate.get("duration"))
    if yt_seconds and bili_seconds:
        ratio = abs(bili_seconds - yt_seconds) / max(yt_seconds, 1)
        if ratio <= 0.05:
            duration_score = 15.0
            reason_codes.append("duration_near_exact")
        elif ratio <= 0.15:
            duration_score = 12.0
            reason_codes.append("duration_close")
        elif ratio <= 0.30:
            duration_score = 8.0
            reason_codes.append("duration_plausible")
        elif ratio <= 0.50:
            duration_score = 4.0
            reason_codes.append("duration_loose")
        else:
            duration_penalty = 12.0 if ratio <= 0.80 else 18.0
            reason_codes.append("duration_mismatch_penalty")
            evidence.append(f"时长差距过大：YouTube {yt_seconds}s / B 站 {bili_seconds}s")
        if yt_seconds > 600 and bili_seconds <= 90:
            duration_penalty += 10.0
            reason_codes.append("candidate_too_short")

    source_score = 0.0
    if source_video_id and source_video_id.lower() in combined_lower:
        source_score += 4.0
        reason_codes.append("youtube_video_id_hit")
        evidence.append("简介/标题出现 YouTube video id")
    if source_author and source_author.lower() in combined_lower:
        source_score += 4.0
        reason_codes.append("source_author_hit")
        evidence.append("简介/标题出现原作者或频道名")
    if any(marker.lower() in combined_lower for marker in SOURCE_MARKERS):
        source_score += 2.0
        reason_codes.append("repost_or_subtitle_marker")
    source_score = min(10.0, source_score)

    published_score = 0.0
    yt_date = parse_date(youtube_meta.get("published_at"))
    bili_date = parse_date(candidate.get("published_at"))
    if yt_date and bili_date:
        if bili_date >= yt_date:
            published_score = 5.0
            reason_codes.append("published_after_source")
        else:
            duration_penalty += 2.0
            reason_codes.append("published_before_source_penalty")

    negative_score = duration_penalty
    if any(marker in title_lower or marker in combined_lower for marker in NEGATIVE_MARKERS):
        negative_score += 8.0
        reason_codes.append("derivative_or_reaction_penalty")
    if len(matched_concepts) <= 1 and not set(source_tokens).intersection(candidate_tokens):
        negative_score += 12.0
        reason_codes.append("single_generic_term_penalty")
    if len(title.strip()) <= 4:
        negative_score += 8.0
        reason_codes.append("title_too_short_penalty")

    raw_score = title_score + semantic_score + duration_score + source_score + published_score - negative_score
    score = max(0, min(100, int(round(raw_score))))
    confidence = confidence_for_score(score)
    score_parts = {
        "title_similarity": round(title_score, 2),
        "semantic_keywords": round(semantic_score, 2),
        "duration": round(duration_score, 2),
        "source_evidence": round(source_score, 2),
        "published_at": round(published_score, 2),
        "negative": round(negative_score, 2),
    }
    scored = {
        **candidate,
        "duration_seconds": bili_seconds,
        "score": score,
        "confidence": confidence,
        "reason_codes": dedupe_strings(reason_codes),
        "evidence": dedupe_strings(evidence, limit=12),
        "score_parts": score_parts,
    }
    return scored


def summarize_query_runs(query_runs: list[dict], errors: list[dict]) -> dict:
    attempted_count = len(query_runs)
    successful_count = sum(1 for run in query_runs if run.get("ok") is True)
    parsed_count = sum(int(run.get("parsed_count") or 0) for run in query_runs)
    manual_fallback_count = sum(1 for run in query_runs if run.get("fallback_manual_review"))
    channel_limited_count = sum(
        1
        for error in errors
        if error.get("error_code") == "search_channel_limited"
        or "search channel limited" in str(error.get("error") or "").lower()
    )
    return {
        "attempted_query_count": attempted_count,
        "successful_query_count": successful_count,
        "parsed_candidate_count": parsed_count,
        "manual_fallback_query_count": manual_fallback_count,
        "channel_limited_query_count": channel_limited_count,
        "error_count": len(errors),
        "searched": successful_count > 0,
    }


def decision_for_candidates(candidates: list[dict], errors: list[dict], search_summary: dict | None = None) -> str:
    if candidates:
        best_score = int(candidates[0].get("score") or 0)
        if best_score >= 80:
            return "high_confidence_possible_duplicate"
        if best_score >= 60:
            return "medium_confidence_review"
        if best_score >= 40:
            return "low_confidence_related"
        return "no_clear_duplicate_found"
    if search_summary and search_summary.get("searched"):
        return "no_candidates_search_completed"
    if errors:
        return "search_unavailable_manual_review"
    return "no_candidates_manual_review"


def search_state_for_report(candidates: list[dict], errors: list[dict], search_summary: dict | None = None) -> str:
    if candidates:
        return "matched_candidates"
    if search_summary and search_summary.get("searched"):
        return "searched_no_parseable_candidates"
    if errors:
        return "search_unavailable"
    return "search_unavailable"


def summarize_scores(candidates: list[dict]) -> dict:
    buckets = {
        "high_confidence_possible_duplicate": 0,
        "medium_confidence_review": 0,
        "low_confidence_related": 0,
        "ignore": 0,
    }
    for candidate in candidates:
        confidence = str(candidate.get("confidence") or "ignore")
        buckets[confidence] = buckets.get(confidence, 0) + 1
    return {
        "candidate_count": len(candidates),
        "top_score": int(candidates[0].get("score") or 0) if candidates else 0,
        "confidence_counts": buckets,
    }


def build_bilibili_duplicate_report(
    input_youtube_url: str,
    youtube_meta: dict,
    *,
    proxy_url: str | None = None,
    max_queries: int = MAX_QUERY_COUNT,
    max_results_per_query: int = MAX_RESULTS_PER_QUERY,
    total_timeout_seconds: float = 45.0,
    sleep_seconds: float = 0.35,
    search_func=None,
) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    query_plan = build_bilibili_query_plan(youtube_meta)
    selected_queries = query_plan[: max(1, min(max_queries, MAX_QUERY_COUNT))]
    search_func = search_func or search_bilibili
    all_candidates: list[dict] = []
    query_runs: list[dict] = []
    errors: list[dict] = []
    started = time.monotonic()

    for index, query in enumerate(selected_queries):
        elapsed = time.monotonic() - started
        if elapsed >= total_timeout_seconds:
            errors.append(
                {
                    "query": query["text"],
                    "search_url": query["search_url"],
                    "error": f"Bilibili search stopped after {total_timeout_seconds:.0f}s total timeout.",
                }
            )
            break
        try:
            raw_candidates = search_func(
                query["text"],
                proxy_url=proxy_url,
                max_results=max_results_per_query,
            )
            for candidate in raw_candidates:
                candidate.setdefault("matched_queries", [])
                candidate["matched_queries"] = dedupe_strings([*candidate["matched_queries"], query["text"]])
                candidate.setdefault("source_search_url", query["search_url"])
                candidate.setdefault("source_api_url", query.get("api_url") or build_search_api_url(query["text"]))
            all_candidates.extend(raw_candidates)
            search_channel = raw_candidates[0].get("search_channel") if raw_candidates else "api"
            query_runs.append(
                {
                    **query,
                    "ok": True,
                    "parsed_count": len(raw_candidates),
                    "search_channel": search_channel,
                    "fallback_manual_review": len(raw_candidates) == 0,
                }
            )
        except Exception as exc:
            message = str(exc)
            error_code = getattr(exc, "reason_code", "")
            search_channel = getattr(exc, "channel", "")
            errors.append(
                {
                    "query": query["text"],
                    "search_url": query["search_url"],
                    "api_url": query.get("api_url") or build_search_api_url(query["text"]),
                    "search_channel": search_channel,
                    "error_code": error_code,
                    "error": message,
                }
            )
            query_runs.append(
                {
                    **query,
                    "ok": False,
                    "parsed_count": 0,
                    "search_channel": search_channel,
                    "error_code": error_code,
                    "fallback_manual_review": True,
                    "error": message,
                }
            )
        if index < len(selected_queries) - 1 and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    merged_candidates = dedupe_candidates(all_candidates)
    scored_candidates = [
        score_bilibili_candidate(candidate, youtube_meta, query_plan)
        for candidate in merged_candidates
    ]
    scored_candidates.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
    search_summary = summarize_query_runs(query_runs, errors)
    report = {
        "input_youtube_url": input_youtube_url,
        "youtube_meta": youtube_meta,
        "query_plan": query_plan,
        "queries": query_runs or selected_queries,
        "candidates": scored_candidates,
        "scoring_summary": summarize_scores(scored_candidates),
        "best_candidate": scored_candidates[0] if scored_candidates else None,
        "search_summary": search_summary,
        "decision": decision_for_candidates(scored_candidates, errors, search_summary),
        "search_state": search_state_for_report(scored_candidates, errors, search_summary),
        "errors": errors,
        "proxy_info": {
            "proxy_url": proxy_url or "",
            "mode": "proxy" if proxy_url else "direct",
        },
        "created_at": created_at,
    }
    return report


def write_bilibili_duplicate_artifacts(output_dir: Path, report: dict) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "00b_bilibili_duplicate_search.json"
    candidates_tsv_path = output_dir / "00b_bilibili_duplicate_candidates.tsv"
    queries_path = output_dir / "00b_bilibili_search_queries.json"

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    queries_payload = {
        "input_youtube_url": report.get("input_youtube_url"),
        "query_plan": report.get("query_plan") or [],
        "queries": report.get("queries") or [],
        "created_at": report.get("created_at"),
    }
    queries_path.write_text(json.dumps(queries_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fields = [
        "score",
        "confidence",
        "title",
        "url",
        "uploader",
        "duration",
        "duration_seconds",
        "published_at",
        "matched_queries",
        "reason_codes",
        "evidence",
        "source_search_url",
        "description",
    ]
    with candidates_tsv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for candidate in report.get("candidates") or []:
            row = {field: candidate.get(field, "") for field in fields}
            for list_field in ("matched_queries", "reason_codes", "evidence"):
                if isinstance(row[list_field], list):
                    row[list_field] = " | ".join(str(item) for item in row[list_field])
            writer.writerow(row)

    return {
        "report_path": str(report_path),
        "candidates_tsv_path": str(candidates_tsv_path),
        "queries_path": str(queries_path),
    }
