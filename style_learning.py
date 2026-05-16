from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .segment_io import load_segments
from .subtitle_io import normalize_inline_text


ASS_DIALOGUE_RE = re.compile(
    r"^Dialogue:\s*(?P<layer>\d+),(?P<start>[^,]+),(?P<end>[^,]+),(?P<style>[^,]*),[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,(?P<text>.*)$"
)


@dataclass(slots=True)
class AssDialogue:
    layer: int
    start: float
    end: float
    style: str
    text: str


def parse_ass_timestamp(value: str) -> float:
    hours, minutes, rest = value.strip().split(":")
    seconds, centis = rest.split(".")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(centis) / 100.0


def unescape_ass_text(text: str) -> str:
    cleaned = text.replace(r"\N", "\n").replace(r"\n", "\n")
    cleaned = cleaned.replace(r"\{", "{").replace(r"\}", "}").replace(r"\\", "\\")
    cleaned = re.sub(r"\{[^}]*\}", "", cleaned)
    return cleaned.strip()


def parse_ass_dialogues(ass_path: str | Path) -> list[AssDialogue]:
    dialogues: list[AssDialogue] = []
    for raw_line in Path(ass_path).read_text(encoding="utf-8-sig").splitlines():
        match = ASS_DIALOGUE_RE.match(raw_line.strip())
        if not match:
            continue
        dialogues.append(
            AssDialogue(
                layer=int(match.group("layer")),
                start=parse_ass_timestamp(match.group("start")),
                end=parse_ass_timestamp(match.group("end")),
                style=match.group("style").strip(),
                text=unescape_ass_text(match.group("text")),
            )
        )
    return dialogues


def normalize_ass_zh_text(text: str) -> str:
    return normalize_inline_text(text.replace("\n", " ").strip())


def collect_zh_dialogues(dialogues: list[AssDialogue]) -> list[AssDialogue]:
    zh_rows: list[AssDialogue] = []
    for item in dialogues:
        if item.layer != 0:
            continue
        if not re.search(r"[\u3400-\u9fff]", item.text):
            continue
        zh_rows.append(item)
    return zh_rows


def overlap_seconds(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def align_segments_to_manual_ass(
    segments_path: str | Path,
    ass_path: str | Path,
    *,
    min_overlap_ratio: float = 0.35,
) -> list[dict]:
    segments = load_segments(segments_path)
    manual_dialogues = collect_zh_dialogues(parse_ass_dialogues(ass_path))
    pairs: list[dict] = []

    for segment in segments:
        duration = max(0.001, float(segment.end) - float(segment.start))
        best_match: AssDialogue | None = None
        best_ratio = 0.0
        for dialogue in manual_dialogues:
            overlap = overlap_seconds(segment.start, segment.end, dialogue.start, dialogue.end)
            if overlap <= 0:
                continue
            ratio = overlap / duration
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = dialogue
        if best_match is None or best_ratio < min_overlap_ratio:
            continue

        original_target = normalize_inline_text(segment.target_text or "")
        manual_target = normalize_ass_zh_text(best_match.text)
        if not original_target or not manual_target:
            continue

        changed = original_target != manual_target
        pairs.append(
            {
                "segment_id": segment.id,
                "start": segment.start,
                "end": segment.end,
                "source_text": segment.source_text,
                "machine_target_text": original_target,
                "manual_target_text": manual_target,
                "changed": changed,
                "overlap_ratio": round(best_ratio, 3),
                "manual_line_count": len(best_match.text.splitlines() or [best_match.text]),
            }
        )
    return pairs


def detect_edit_tags(pair: dict) -> list[str]:
    machine = str(pair.get("machine_target_text") or "")
    manual = str(pair.get("manual_target_text") or "")
    source = str(pair.get("source_text") or "")
    tags: list[str] = []

    if machine == manual:
        tags.append("unchanged")
    if "\n" in str(pair.get("manual_target_text") or ""):
        tags.append("manual_linebreak")
    if len(manual) < len(machine) - 4:
        tags.append("compressed")
    if len(manual) > len(machine) + 4:
        tags.append("expanded")
    if "（" in manual and "）" in manual:
        tags.append("mixed_naming")
    if re.search(r"[A-Za-z]{2,}", source) and re.search(r"[A-Za-z]{2,}", manual):
        tags.append("preserve_english")
    if re.search(r"[，。！？；、]", manual):
        tags.append("punctuation_tuned")
    if machine.endswith(("的", "和", "但", "因为", "所以")) and not manual.endswith(("的", "和", "但", "因为", "所以")):
        tags.append("fixed_open_ending")
    return tags


def normalize_loose_text(text: str) -> str:
    return re.sub(r"[\s，。！？；、,.!?;:：'\"“”‘’（）()\-—]+", "", normalize_inline_text(text))


def is_surface_only_edit(machine: str, manual: str) -> bool:
    if not machine or not manual:
        return False
    return normalize_loose_text(machine) == normalize_loose_text(manual) and machine != manual


def tokenize_style_text(text: str) -> set[str]:
    normalized = normalize_inline_text(text)
    english_tokens = {
        token.casefold()
        for token in re.findall(r"[A-Za-z]{2,}", normalized)
    }
    chinese_bigrams = {
        normalized[index : index + 2]
        for index in range(max(0, len(normalized) - 1))
        if re.search(r"[\u3400-\u9fff]", normalized[index : index + 2])
    }
    return english_tokens | chinese_bigrams


def build_style_features(pair: dict) -> dict:
    machine = str(pair.get("machine_target_text") or "")
    manual = str(pair.get("manual_target_text") or "")
    source = str(pair.get("source_text") or "")
    return {
        "source_tokens": sorted(tokenize_style_text(source)),
        "machine_tokens": sorted(tokenize_style_text(machine)),
        "manual_tokens": sorted(tokenize_style_text(manual)),
        "source_length": len(source),
        "machine_length": len(machine),
        "manual_length": len(manual),
        "char_delta": len(manual) - len(machine),
        "surface_only": is_surface_only_edit(machine, manual),
    }


def abstract_topic_text(text: str) -> str:
    normalized = normalize_inline_text(text)
    normalized = re.sub(r"[A-Z]{2,}(?:\s+[A-Z]{2,})*", "<<TERM>>", normalized)
    normalized = re.sub(r"[A-Z][A-Za-z0-9.'-]*(?:\s+[A-Z][A-Za-z0-9.'-]*){2,}", "<<TITLE>>", normalized)
    normalized = re.sub(r"[A-Z][A-Za-z0-9.'-]*(?:\s+[A-Z][A-Za-z0-9.'-]*){1,2}", "<<NAME>>", normalized)
    normalized = re.sub(r"\b[A-Za-z]{2,}\b", "<<EN>>", normalized)
    normalized = re.sub(r"\d+(?:[.,]\d+)?", "<NUM>", normalized)
    normalized = re.sub(r"<{3,}\s*EN\s*>{3,}", "<<EN>>", normalized)
    normalized = re.sub(r"<{3,}\s*NAME\s*>{3,}", "<<NAME>>", normalized)
    normalized = re.sub(r"<{3,}\s*TITLE\s*>{3,}", "<<TITLE>>", normalized)
    normalized = re.sub(r"<{3,}\s*TERM\s*>{3,}", "<<TERM>>", normalized)
    normalized = re.sub(r"<<(?:NAME|TITLE)>>\s+<<EN>>", "<<NAME>>", normalized)
    normalized = re.sub(r"<<EN>>\s+<<NAME>>", "<<NAME>>", normalized)
    normalized = re.sub(r"<<TITLE>>\s+<<EN>>", "<<TITLE>>", normalized)
    normalized = re.sub(r"(?:<<TITLE>>\s+){2,}<<TITLE>>", "<<TITLE>>", normalized)
    normalized = re.sub(r"(?:<<NAME>>\s+){2,}<<NAME>>", "<<NAME>>", normalized)
    normalized = re.sub(r"(?:<<TERM>>\s+){2,}<<TERM>>", "<<TERM>>", normalized)
    normalized = re.sub(r"(?:<<EN>>\s+){2,}<<EN>>", "<<EN>>", normalized)
    return normalized


def build_text_shape(text: str) -> str:
    abstracted = abstract_topic_text(text)
    parts = re.findall(r"<<[A-Z]+>>|<NUM>|[\u3400-\u9fff]+|[，。！？；、,.!?;:：]|.", abstracted)
    shaped: list[str] = []
    for part in parts:
        if re.fullmatch(r"[\u3400-\u9fff]+", part):
            token = "<<ZH>>"
        else:
            token = part
        if shaped and shaped[-1] == token == "<<ZH>>":
            continue
        shaped.append(token)
    return "".join(shaped)


def infer_edit_strategies(machine: str, manual: str, tags: list[str]) -> list[str]:
    strategies: list[str] = []
    normalized_machine = normalize_inline_text(machine)
    normalized_manual = normalize_inline_text(manual)
    if "compressed" in tags:
        strategies.append("compress")
    if "expanded" in tags:
        strategies.append("expand")
    if "preserve_english" in tags:
        strategies.append("preserve_term")
    if "fixed_open_ending" in tags:
        strategies.append("close_open_clause")
    if "manual_linebreak" in tags:
        strategies.append("rebalance_lines")

    if normalized_machine.startswith(normalized_manual) and len(normalized_manual) < len(normalized_machine):
        strategies.append("trim_tail")
    elif normalized_machine.endswith(normalized_manual) and len(normalized_manual) < len(normalized_machine):
        strategies.append("trim_lead")
    elif normalized_manual and normalized_manual in normalized_machine and len(normalized_manual) < len(normalized_machine):
        strategies.append("keep_core_clause")

    machine_commas = len(re.findall(r"[，,、；;：:]", normalized_machine))
    manual_commas = len(re.findall(r"[，,、；;：:]", normalized_manual))
    if manual_commas < machine_commas:
        strategies.append("reduce_clause_count")

    seen: list[str] = []
    for item in strategies:
        if item not in seen:
            seen.append(item)
    return seen


def build_edit_operation_summary(pair: dict) -> dict:
    machine = str(pair.get("machine_target_text") or "")
    manual = str(pair.get("manual_target_text") or "")
    tags = detect_edit_tags(pair)
    machine_length = len(machine)
    manual_length = len(manual)
    return {
        "operation": ", ".join(tags) or "rewrite",
        "strategies": infer_edit_strategies(machine, manual, tags),
        "machine_template": abstract_topic_text(machine),
        "manual_template": abstract_topic_text(manual),
        "machine_shape": build_text_shape(machine),
        "manual_shape": build_text_shape(manual),
        "length_delta": manual_length - machine_length,
        "drops_open_ending": machine.endswith(("的", "和", "但", "因为", "所以")) and not manual.endswith(("的", "和", "但", "因为", "所以")),
    }


def style_example_signal_score(example: dict) -> float:
    tags = set(example.get("edit_tags") or [])
    features = example.get("features") if isinstance(example.get("features"), dict) else {}
    score = 0.0
    if "fixed_open_ending" in tags:
        score += 4.0
    if "compressed" in tags:
        score += 3.0
    if "manual_linebreak" in tags:
        score += 2.5
    if "preserve_english" in tags or "mixed_naming" in tags:
        score += 2.0
    if "expanded" in tags:
        score += 1.0
    if "punctuation_tuned" in tags:
        score += 0.5
    if features.get("surface_only"):
        score -= 2.0
    score += min(3.0, abs(float(features.get("char_delta") or 0)) / 6.0)
    return score


def build_style_examples(pairs: list[dict], *, max_examples: int = 80) -> list[dict]:
    changed = [pair for pair in pairs if pair.get("changed")]
    examples: list[dict] = []
    for item in changed:
        tags = detect_edit_tags(item)
        features = build_style_features(item)
        examples.append(
            {
                **item,
                "edit_tags": tags,
                "features": features,
                "operation_summary": build_edit_operation_summary(item),
            }
        )
    ranked = sorted(
        examples,
        key=lambda item: (
            -style_example_signal_score(item),
            -float(item.get("overlap_ratio") or 0.0),
            int(item["segment_id"]),
        ),
    )
    trimmed: list[dict] = []
    for index, item in enumerate(ranked[:max_examples], start=1):
        trimmed.append(
            {
                **item,
                "example_id": f"style-{index:04d}",
                "signal_score": round(style_example_signal_score(item), 2),
            }
        )
    return trimmed


def summarize_style_profile(examples: list[dict], *, source_segments_path: str, manual_ass_path: str) -> dict:
    tag_counts: Counter[str] = Counter()
    strategy_counts: Counter[str] = Counter()
    for example in examples:
        tag_counts.update(example.get("edit_tags") or [])
        operation_summary = example.get("operation_summary") if isinstance(example.get("operation_summary"), dict) else {}
        strategy_counts.update(operation_summary.get("strategies") or [])

    changed_count = sum(1 for item in examples if item.get("changed"))
    compressed_count = sum(1 for item in examples if "compressed" in (item.get("edit_tags") or []))
    english_preserve_count = sum(1 for item in examples if "preserve_english" in (item.get("edit_tags") or []))
    manual_linebreak_count = sum(1 for item in examples if "manual_linebreak" in (item.get("edit_tags") or []))
    surface_only_count = sum(
        1 for item in examples
        if isinstance(item.get("features"), dict) and item["features"].get("surface_only")
    )
    high_signal_count = sum(1 for item in examples if float(item.get("signal_score") or 0.0) >= 2.5)
    avg_char_delta = round(
        (
            sum(abs(float(item.get("features", {}).get("char_delta") or 0.0)) for item in examples) / len(examples)
        ),
        2,
    ) if examples else 0.0

    guidelines: list[str] = []
    if compressed_count:
        guidelines.append("优先压缩冗余表达，让中文字幕更像成片字幕而不是逐词翻译。")
    if english_preserve_count:
        guidelines.append("专名、术语和标题允许保留英文，不强行全译。")
    if manual_linebreak_count:
        guidelines.append("人工会主动调整换行，让屏幕阅读节奏比机器默认更自然。")
    if tag_counts.get("fixed_open_ending"):
        guidelines.append("避免悬空尾字和半句落屏，必要时把语义收束到当前屏。")
    if high_signal_count and surface_only_count < len(examples):
        guidelines.append("优先参考高信号人工改写样例，而不是只看表面标点微调。")
    if examples and surface_only_count == len(examples):
        guidelines.append("当前样例大多只是表层标点调整，若要学到更强风格，需要导入真正手修过的 ASS。")
    if not guidelines:
        guidelines.append("优先保持自然、简洁、可独立上屏的中文字幕。")

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_segments_path": str(source_segments_path),
        "manual_ass_path": str(manual_ass_path),
        "summary": {
            "example_count": len(examples),
            "changed_example_count": changed_count,
            "high_signal_example_count": high_signal_count,
            "surface_only_example_count": surface_only_count,
            "average_char_delta": avg_char_delta,
            "tag_counts": dict(sorted(tag_counts.items())),
            "strategy_counts": dict(sorted(strategy_counts.items())),
        },
        "guidelines": guidelines,
    }


def build_style_prompt(profile: dict, examples: list[dict], *, max_examples: int = 12) -> str:
    lines = [
        "You are rewriting Chinese subtitle text to match the editor's established style.",
        "Use the profile and examples below as house style guidance.",
        "",
        "Style profile:",
    ]
    for guideline in profile.get("guidelines") or []:
        lines.append(f"- {guideline}")
    if examples:
        lines.append("")
        lines.append("Abstract Edit Patterns:")
        for item in examples[:max_examples]:
            operation_summary = item.get("operation_summary") if isinstance(item.get("operation_summary"), dict) else {}
            lines.extend(
                [
                    f"- Example ID: {item.get('example_id', '')}",
                    f"  Operation: {operation_summary.get('operation', 'rewrite')}",
                    f"  Strategies: {', '.join(operation_summary.get('strategies') or []) or 'rewrite'}",
                    f"  Machine shape: {operation_summary.get('machine_shape', '')}",
                    f"  Manual shape: {operation_summary.get('manual_shape', '')}",
                    f"  Length delta: {operation_summary.get('length_delta', 0)}",
                    f"  Tags: {', '.join(item.get('edit_tags') or []) or 'none'}",
                    f"  Signal: {item.get('signal_score', 0)}",
                ]
            )
    return "\n".join(lines).strip() + "\n"


def write_style_learning_artifacts(
    *,
    segments_path: str | Path,
    manual_ass_path: str | Path,
    output_dir: str | Path,
) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs = align_segments_to_manual_ass(segments_path, manual_ass_path)
    examples = build_style_examples(pairs)
    profile = summarize_style_profile(
        examples,
        source_segments_path=str(segments_path),
        manual_ass_path=str(manual_ass_path),
    )
    prompt_text = build_style_prompt(profile, examples)

    profile_path = output_dir / "00_style_profile.json"
    examples_path = output_dir / "00_style_examples.jsonl"
    prompt_path = output_dir / "06d_style_rewrite_prompt.txt"

    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    with examples_path.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example, ensure_ascii=False) + "\n")
    prompt_path.write_text(prompt_text, encoding="utf-8")

    return {
        "profile_path": str(profile_path),
        "examples_path": str(examples_path),
        "prompt_path": str(prompt_path),
        "summary": profile["summary"],
        "message": (
            "No edited subtitle examples were detected. Use a manually revised ASS file to learn style."
            if not examples
            else "Style examples extracted successfully."
        ),
    }
