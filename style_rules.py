from __future__ import annotations

from pathlib import Path


DEFAULT_STYLE_GUIDANCE = """House subtitle style:
- Write natural Simplified Chinese for finished video subtitles, not literal word-by-word Chinese.
- Keep the tone polished but alive: documentary/explainer narration can be vivid, lightly casual, and humorous when the source is.
- Prefer concise clauses, but do not crush the line into awkward shorthand. A readable line around 29-33 visible Chinese characters is acceptable when timing is comfortable.
- Translate well-known places, products, people, and infrastructure names to their established Chinese names when unambiguous.
- Keep channel names, sponsor names, product names, UI names, and terms marked preserve by the glossary in English.
- Use glossary and context to repair obvious ASR name/place mistakes before translating.
- Every subtitle ID should read as a useful on-screen sentence or phrase. Avoid dangling connectors, lone particles, or half-clauses.
- Preserve numbers, units, comparisons, and negation accurately.
- English reference text is auxiliary. Standalone first-person English I must always be uppercase.
- Do not add manual line breaks, markdown, bullets, or explanations inside subtitle text."""


def load_style_prompt_text(style_prompt_path: str | Path | None, *, max_chars: int = 8000) -> str:
    if not style_prompt_path:
        return ""
    path = Path(style_prompt_path)
    if not path.exists() or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return ""
    max_chars = max(1000, int(max_chars or 8000))
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[style prompt truncated]"


def build_style_guidance(style_prompt_text: str | None = None) -> str:
    learned = (style_prompt_text or "").strip()
    if not learned:
        return DEFAULT_STYLE_GUIDANCE
    return f"{DEFAULT_STYLE_GUIDANCE}\n\nEditor-learned style profile:\n{learned}"
