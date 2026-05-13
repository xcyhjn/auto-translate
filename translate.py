from __future__ import annotations

import json
import os
import time
from typing import Any
from typing import Callable

from .models import Segment

TranslationProgressCallback = Callable[[str, dict], None]


def load_glossary(glossary: str | None) -> str:
    """如果用户提供了纯文本术语表，就把它读进来。

    这里先刻意保持简单。以后如果需要，可以再扩展 CSV/YAML 解析；
    目前纯文本已经足够承载固定人名、术语和偏好译法。
    """
    if not glossary:
        return ""
    with open(glossary, "r", encoding="utf-8") as file:
        return file.read().strip()


def chunk_segments(segments: list[Segment], chunk_size: int) -> list[list[Segment]]:
    """把字幕分块，保证模型还能看到上下文。

    一条一条翻译会丢掉代词、说话人和术语上下文。
    分块可以把相邻句子放在一起，同时在某次 API 调用失败时也更容易重试。
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero.")
    return [segments[index : index + chunk_size] for index in range(0, len(segments), chunk_size)]


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

    glossary_block = glossary_text or "No glossary provided."
    return (
        "You are a professional subtitle translator.\n"
        f"Translate subtitles from {src_lang or 'auto-detected source language'} "
        f"to {dst_lang}.\n\n"
        "Rules:\n"
        "- Translate naturally for on-screen subtitles.\n"
        "- Keep the translation concise; avoid explanatory expansion.\n"
        "- Preserve names, numbers, and domain terms according to the glossary.\n\n"
        f"Glossary:\n{glossary_block}\n\n"
        "Input JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
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
    base_url: str | None = None,
    max_retries: int = 2,
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

    client_kwargs = {}
    if base_url:
        # 如果你使用 GPTCodePlan 这类中转站，就在这里把 base_url 传给 SDK。
        client_kwargs["base_url"] = base_url

    client = OpenAI(**client_kwargs)
    prompt = build_translation_prompt(
        chunk,
        src_lang=src_lang,
        dst_lang=dst_lang,
        glossary_text=glossary_text,
    )
    translation_schema = build_translation_schema()

    raw_text = ""
    last_error: Exception | None = None
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
            if attempt >= max_retries:
                raise RuntimeError(
                    "OpenAI translation failed after retries. Last raw output:\n"
                    f"{raw_text}"
                ) from last_error
            # 简单的指数退避可以避免短暂的网络/接口波动
            # 直接把长翻译任务打断。
            time.sleep(2**attempt)

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
    returned_ids = set(translations)
    source_by_id = {segment.id: segment.source_text for segment in chunk}
    if expected_ids != returned_ids:
        missing = sorted(expected_ids - returned_ids)
        extra = sorted(returned_ids - expected_ids)
        if extra:
            raise RuntimeError(f"Translation id mismatch. missing={missing}, extra={extra}")
        for segment_id in missing:
            source_text = source_by_id.get(segment_id, "").strip()
            if source_text:
                translations[segment_id] = source_text
            else:
                raise RuntimeError(f"Translation id mismatch. missing={missing}, extra={extra}")

    empty_ids = [segment_id for segment_id, text in translations.items() if not text]
    if empty_ids:
        for segment_id in empty_ids:
            source_text = source_by_id.get(segment_id, "").strip()
            if source_text:
                translations[segment_id] = source_text
            else:
                raise RuntimeError(f"OpenAI returned empty translations for ids: {empty_ids}")

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
    client_kwargs = {}
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
    resolved_base_url = resolve_openai_base_url(openai_base_url)
    chunks = chunk_segments(segments, chunk_size)
    for chunk_index, chunk in enumerate(chunks, start=1):
        if progress_callback:
            progress_callback(
                "translation_chunk_start",
                {
                    "chunk_index": chunk_index,
                    "chunk_total": len(chunks),
                    "segment_count": len(chunk),
                },
            )
        print(f"Translating chunk {chunk_index}/{len(chunks)} with {len(chunk)} segments.")
        started_at = time.time()
        translations = translate_chunk_with_openai(
            chunk,
            src_lang=src_lang,
            dst_lang=dst_lang,
            glossary_text=glossary_text,
            model=model,
            base_url=resolved_base_url,
            max_retries=max_retries,
        )
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
                    "fallback_count": fallback_count,
                    "elapsed_seconds": round(time.time() - started_at, 2),
                },
            )

    return segments
