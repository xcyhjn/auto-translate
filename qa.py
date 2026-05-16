from __future__ import annotations

import re
from dataclasses import dataclass, field
import json
from pathlib import Path

from .models import Segment, SubtitleRules
from .subtitle_io import DisplayCue, wrap_chinese_text
from .text_quality import find_text_pollution, format_pollution_issues

DEFAULT_MAX_CHARS = 42
DEFAULT_MAX_CPS = 18.0
DEFAULT_ZH_MAX_LINE_CHARS = 28
DEFAULT_EN_MAX_LINE_CHARS = 78
DEFAULT_ZH_MAX_CPS = 18.0
DEFAULT_EN_MAX_CPS = 24.0
TRANSLATABLE_FUNCTION_WORDS = {
    "am",
    "are",
    "been",
    "being",
    "can",
    "could",
    "did",
    "does",
    "had",
    "has",
    "have",
    "is",
    "might",
    "must",
    "should",
    "that",
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
DIFFICULT_SPAN_BLOCKING_REASON_CODES = {
    "number_mismatch",
    "source_suspicious_asr_word",
    "target_text_pollution",
    "target_too_short",
}


@dataclass(slots=True)
class QaReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.errors)


def max_internal_gap(segment: Segment) -> float:
    if not segment.words or len(segment.words) < 2:
        return 0.0
    return max(
        max(0.0, current.start - previous.end)
        for previous, current in zip(segment.words, segment.words[1:])
    )


def normalize_for_equality(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def is_chinese_target_language(dst_lang: str | None) -> bool:
    normalized = (dst_lang or "").strip().lower()
    return normalized.startswith("zh") or "chinese" in normalized


def has_translatable_alpha_text(text: str) -> bool:
    words = [word.casefold() for word in re.findall(r"[A-Za-z]{2,}", text or "")]
    if len(words) < 2:
        return False
    if re.search(r"[.!?]", text or "") and len(words) >= 3:
        return True
    if any(word in TRANSLATABLE_FUNCTION_WORDS for word in words):
        return True
    return len(words) >= 7


def contains_term(text: str, term: str) -> bool:
    if not text or not term:
        return False
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
    return bool(pattern.search(text))


def load_glossary_terms(glossary_path: str | Path | None) -> list[dict]:
    if not glossary_path:
        return []
    path = Path(glossary_path)
    if not path.exists() or path.suffix.lower() != ".json":
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    terms = payload.get("terms") if isinstance(payload, dict) else None
    return [item for item in terms or [] if isinstance(item, dict)]


def qa_glossary_consistency(segments: list[Segment], glossary_path: str | Path | None) -> QaReport:
    report = QaReport()
    terms = load_glossary_terms(glossary_path)
    if not terms:
        return report

    for segment in segments:
        source_text = segment.source_text or ""
        target_text = segment.target_text or ""
        for item in terms:
            canonical = str(item.get("canonical") or "").strip()
            if len(canonical) < 3:
                continue
            term_sources = [str(value) for value in item.get("sources") or []]
            if not any(source.startswith(("youtube_", "user", "asr_fuzzy_alias")) for source in term_sources):
                continue
            policy = str(item.get("policy") or "preserve").strip()
            priority = str(item.get("priority") or "").strip().lower()
            bad_aliases = [str(value).strip() for value in item.get("bad_aliases") or [] if str(value).strip()]
            for bad_alias in bad_aliases:
                if contains_term(source_text, bad_alias):
                    report.warnings.append(
                        f"Segment {segment.id} source may contain bad alias '{bad_alias}' for '{canonical}'."
                    )
                if contains_term(target_text, bad_alias):
                    report.errors.append(
                        f"Segment {segment.id} target contains bad alias '{bad_alias}' for '{canonical}'."
                    )
            if policy == "preserve" and contains_term(source_text, canonical) and target_text:
                if not contains_term(target_text, canonical):
                    message = f"Segment {segment.id} may not preserve glossary term '{canonical}' in target text."
                    if priority == "hard":
                        report.errors.append(
                            f"Segment {segment.id} hard glossary missing '{canonical}' in target text."
                        )
                    else:
                        report.warnings.append(message)
    return report


def is_blocking_difficult_span(span: dict) -> bool:
    severity = str(span.get("severity") or "low")
    if severity != "high":
        return False

    reason_counts = span.get("reason_counts") if isinstance(span.get("reason_counts"), dict) else {}
    reason_codes = {str(key) for key in reason_counts}
    if reason_codes & {"target_text_pollution", "source_suspicious_asr_word"}:
        return True

    open_target_count = int(reason_counts.get("target_open_ending") or 0)
    continuation_count = int(reason_counts.get("source_starts_with_continuation") or 0)
    open_word_count = int(reason_counts.get("source_ends_with_open_word") or 0)
    open_clause_count = int(reason_counts.get("source_open_clause") or 0)
    if "target_too_short" in reason_codes and (open_target_count >= 1 or continuation_count + open_word_count >= 1):
        return True
    if "number_mismatch" in reason_codes and open_target_count >= 3 and open_clause_count >= 5:
        return True
    return False


def qa_difficult_spans(difficult_spans: dict | None) -> QaReport:
    report = QaReport()
    if not isinstance(difficult_spans, dict):
        return report

    for span in difficult_spans.get("spans") or []:
        if not isinstance(span, dict):
            continue
        reason_counts = span.get("reason_counts") if isinstance(span.get("reason_counts"), dict) else {}
        reason_summary = ", ".join(
            f"{code} x{int(count)}"
            for code, count in sorted(reason_counts.items())
            if int(count or 0) > 0
        )
        if not reason_summary:
            reason_summary = "unspecified difficult span risk"
        span_label = (
            f"{span.get('span_id', 'span')} "
            f"({int(span.get('start_segment_id') or 0)}-{int(span.get('end_segment_id') or 0)})"
        )
        message = f"Difficult span {span_label} indicates semantic alignment risk: {reason_summary}."
        if is_blocking_difficult_span(span):
            report.errors.append(message)
        elif str(span.get("severity") or "low") in {"high", "medium"}:
            report.warnings.append(message)
    return report


def build_quality_metrics(
    segments: list[Segment],
    cues: list[DisplayCue],
    *,
    dst_lang: str | None = None,
    glossary_path: str | Path | None = None,
    zh_max_line_chars: int = DEFAULT_ZH_MAX_LINE_CHARS,
    en_max_line_chars: int = DEFAULT_EN_MAX_LINE_CHARS,
    zh_max_cps: float = DEFAULT_ZH_MAX_CPS,
    en_max_cps: float = DEFAULT_EN_MAX_CPS,
    zh_wrap_trigger_chars: int = 32,
    zh_max_lines: int = 2,
    sample_limit: int = 20,
) -> dict:
    require_chinese = is_chinese_target_language(dst_lang)
    metrics = {
        "segment_count": len(segments),
        "display_cue_count": len(cues),
        "translation": {
            "source_echo_count": 0,
            "empty_target_count": 0,
            "target_without_chinese_count": 0,
            "text_pollution_count": 0,
            "source_echo_ids": [],
            "empty_target_ids": [],
            "target_without_chinese_ids": [],
            "text_pollution_samples": [],
        },
        "display": {
            "empty_chinese_cue_count": 0,
            "chinese_line_too_long_count": 0,
            "english_line_too_long_count": 0,
            "chinese_cps_too_high_count": 0,
            "english_cps_too_high_count": 0,
            "empty_chinese_cue_indexes": [],
            "chinese_line_too_long_samples": [],
            "english_line_too_long_samples": [],
            "chinese_cps_too_high_samples": [],
            "english_cps_too_high_samples": [],
        },
        "glossary": {
            "bad_alias_in_target_count": 0,
            "bad_alias_in_source_count": 0,
            "preserve_missing_count": 0,
            "hard_preserve_missing_count": 0,
            "bad_alias_in_target_samples": [],
            "bad_alias_in_source_samples": [],
            "preserve_missing_samples": [],
            "hard_preserve_missing_samples": [],
        },
    }

    def append_sample(values: list, value: object) -> None:
        if len(values) < sample_limit:
            values.append(value)

    for segment in segments:
        source_text = segment.source_text or ""
        target_text = segment.target_text or ""
        if not target_text.strip():
            metrics["translation"]["empty_target_count"] += 1
            append_sample(metrics["translation"]["empty_target_ids"], segment.id)
        if (
            require_chinese
            and target_text
            and normalize_for_equality(target_text) == normalize_for_equality(source_text)
            and has_translatable_alpha_text(source_text)
        ):
            metrics["translation"]["source_echo_count"] += 1
            append_sample(metrics["translation"]["source_echo_ids"], segment.id)
        if require_chinese and target_text and not contains_chinese(target_text) and has_translatable_alpha_text(source_text):
            metrics["translation"]["target_without_chinese_count"] += 1
            append_sample(metrics["translation"]["target_without_chinese_ids"], segment.id)
        pollution_issues = find_text_pollution(target_text, dst_lang=dst_lang)
        if pollution_issues:
            metrics["translation"]["text_pollution_count"] += 1
            append_sample(
                metrics["translation"]["text_pollution_samples"],
                {
                    "segment_id": segment.id,
                    "issues": pollution_issues,
                    "text": target_text,
                },
            )

    for cue_index, cue in enumerate(cues, start=1):
        zh_text = (cue.zh_text or "").strip()
        en_text = cue.en_text.strip()
        duration = max(cue.end - cue.start, 0.001)
        if require_chinese and en_text and not zh_text:
            metrics["display"]["empty_chinese_cue_count"] += 1
            append_sample(metrics["display"]["empty_chinese_cue_indexes"], cue_index)

        if zh_text:
            rendered_zh = wrap_chinese_text(
                zh_text,
                trigger_chars=zh_wrap_trigger_chars,
                max_chars=zh_max_line_chars,
                max_lines=zh_max_lines,
            )
            for line_number, line in enumerate(rendered_zh.splitlines() or [rendered_zh], start=1):
                line_length = len(re.sub(r"\s+", "", line))
                if line_length > zh_max_line_chars:
                    metrics["display"]["chinese_line_too_long_count"] += 1
                    append_sample(
                        metrics["display"]["chinese_line_too_long_samples"],
                        {"cue_index": cue_index, "line": line_number, "length": line_length, "text": line},
                    )
            zh_cps_value = len(re.sub(r"\s+", "", zh_text)) / duration
            if zh_cps_value > zh_max_cps:
                metrics["display"]["chinese_cps_too_high_count"] += 1
                append_sample(
                    metrics["display"]["chinese_cps_too_high_samples"],
                    {"cue_index": cue_index, "cps": round(zh_cps_value, 2), "text": zh_text},
                )

        if en_text:
            if len(en_text) > en_max_line_chars:
                metrics["display"]["english_line_too_long_count"] += 1
                append_sample(
                    metrics["display"]["english_line_too_long_samples"],
                    {"cue_index": cue_index, "length": len(en_text), "text": en_text},
                )
            en_cps_value = len(en_text) / duration
            if en_cps_value > en_max_cps:
                metrics["display"]["english_cps_too_high_count"] += 1
                append_sample(
                    metrics["display"]["english_cps_too_high_samples"],
                    {"cue_index": cue_index, "cps": round(en_cps_value, 2), "text": en_text},
                )

    glossary_terms = load_glossary_terms(glossary_path)
    for segment in segments:
        source_text = segment.source_text or ""
        target_text = segment.target_text or ""
        for item in glossary_terms:
            canonical = str(item.get("canonical") or "").strip()
            if len(canonical) < 3:
                continue
            term_sources = [str(value) for value in item.get("sources") or []]
            if not any(source.startswith(("youtube_", "user", "asr_fuzzy_alias")) for source in term_sources):
                continue
            policy = str(item.get("policy") or "preserve").strip()
            priority = str(item.get("priority") or "").strip().lower()
            bad_aliases = [str(value).strip() for value in item.get("bad_aliases") or [] if str(value).strip()]
            for bad_alias in bad_aliases:
                if contains_term(target_text, bad_alias):
                    metrics["glossary"]["bad_alias_in_target_count"] += 1
                    append_sample(
                        metrics["glossary"]["bad_alias_in_target_samples"],
                        {"segment_id": segment.id, "canonical": canonical, "bad_alias": bad_alias},
                    )
                if contains_term(source_text, bad_alias):
                    metrics["glossary"]["bad_alias_in_source_count"] += 1
                    append_sample(
                        metrics["glossary"]["bad_alias_in_source_samples"],
                        {"segment_id": segment.id, "canonical": canonical, "bad_alias": bad_alias},
                    )
            if policy == "preserve" and contains_term(source_text, canonical) and target_text and not contains_term(target_text, canonical):
                metrics["glossary"]["preserve_missing_count"] += 1
                append_sample(
                    metrics["glossary"]["preserve_missing_samples"],
                    {"segment_id": segment.id, "canonical": canonical},
                )
                if priority == "hard":
                    metrics["glossary"]["hard_preserve_missing_count"] += 1
                    append_sample(
                        metrics["glossary"]["hard_preserve_missing_samples"],
                        {"segment_id": segment.id, "canonical": canonical},
                    )

    blocking_count = (
        metrics["translation"]["source_echo_count"]
        + metrics["translation"]["empty_target_count"]
        + metrics["translation"]["target_without_chinese_count"]
        + metrics["translation"]["text_pollution_count"]
        + metrics["display"]["empty_chinese_cue_count"]
        + metrics["display"]["chinese_line_too_long_count"]
        + metrics["display"]["chinese_cps_too_high_count"]
        + metrics["glossary"]["bad_alias_in_target_count"]
        + metrics["glossary"]["hard_preserve_missing_count"]
    )
    metrics["summary"] = {
        "blocking_issue_count": blocking_count,
        "warning_issue_count": (
            metrics["glossary"]["bad_alias_in_source_count"]
            + metrics["glossary"]["preserve_missing_count"]
            + metrics["display"]["english_line_too_long_count"]
            + metrics["display"]["english_cps_too_high_count"]
        ),
        "pass": blocking_count == 0,
    }
    return metrics


def qa_check(
    segments: list[Segment],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_cps: float = DEFAULT_MAX_CPS,
    rules: SubtitleRules | None = None,
    dst_lang: str | None = None,
) -> QaReport:
    report = QaReport()
    if rules is None:
        rules = SubtitleRules()

    if not segments:
        report.errors.append("No subtitle segments were generated.")
        return report

    previous_end = -1.0
    previous_text = ""
    for expected_id, segment in enumerate(segments, start=1):
        if segment.id != expected_id:
            report.warnings.append(f"Segment id {segment.id} should be {expected_id}.")
        if segment.start >= segment.end:
            report.errors.append(f"Segment {segment.id} has invalid timing.")
        if segment.start < previous_end:
            report.errors.append(f"Segment {segment.id} overlaps the previous segment.")

        text = (segment.target_text or segment.source_text).strip()
        if not text:
            report.errors.append(f"Segment {segment.id} has empty text.")

        if (
            is_chinese_target_language(dst_lang)
            and segment.target_text is not None
            and normalize_for_equality(segment.target_text) == normalize_for_equality(segment.source_text)
            and has_translatable_alpha_text(segment.source_text)
        ):
            report.errors.append(f"Segment {segment.id} target text echoes source text.")

        if (
            is_chinese_target_language(dst_lang)
            and segment.target_text
            and not contains_chinese(segment.target_text)
            and has_translatable_alpha_text(segment.source_text)
        ):
            report.errors.append(f"Segment {segment.id} target text contains no Chinese characters.")

        pollution_issues = find_text_pollution(segment.target_text or "", dst_lang=dst_lang)
        if pollution_issues:
            report.errors.append(
                f"Segment {segment.id} target text contains suspicious polluted text: "
                f"{format_pollution_issues(pollution_issues)}."
            )

        if previous_text and text == previous_text:
            report.warnings.append(
                f"Segment {segment.id} repeats the previous subtitle text exactly."
            )

        if len(text) > max_chars:
            report.warnings.append(
                f"Segment {segment.id} is long: {len(text)} chars > {max_chars}."
            )

        duration = max(segment.end - segment.start, 0.001)
        cps = len(text) / duration
        if cps > max_cps:
            report.warnings.append(
                f"Segment {segment.id} is fast: {cps:.1f} chars/sec > {max_cps:.1f}."
            )

        internal_gap = max_internal_gap(segment)
        if internal_gap >= rules.max_internal_silence:
            report.warnings.append(
                f"Segment {segment.id} may be over-merged: internal silence {internal_gap:.2f}s."
            )

        previous_end = segment.end
        previous_text = text

    return report


def qa_display_cues(
    cues: list[DisplayCue],
    *,
    dst_lang: str | None = None,
    zh_max_line_chars: int = DEFAULT_ZH_MAX_LINE_CHARS,
    en_max_line_chars: int = DEFAULT_EN_MAX_LINE_CHARS,
    zh_max_cps: float = DEFAULT_ZH_MAX_CPS,
    en_max_cps: float = DEFAULT_EN_MAX_CPS,
    zh_wrap_trigger_chars: int = 32,
    zh_max_lines: int = 2,
) -> QaReport:
    report = QaReport()
    previous_zh = ""
    previous_source_segment_id = None
    source_zh_runs: dict[int | None, list[str]] = {}
    require_chinese = is_chinese_target_language(dst_lang)

    for index, cue in enumerate(cues, start=1):
        zh_text = (cue.zh_text or "").strip()
        en_text = cue.en_text.strip()
        source_zh_runs.setdefault(cue.source_segment_id, []).append(zh_text)

        duration = max(cue.end - cue.start, 0.001)
        if require_chinese and en_text and not zh_text:
            report.errors.append(f"Display cue {index} has English text but empty Chinese text.")
        if require_chinese and zh_text and not contains_chinese(zh_text) and has_translatable_alpha_text(en_text):
            report.errors.append(f"Display cue {index} Chinese text contains no Chinese characters.")
        pollution_issues = find_text_pollution(zh_text, dst_lang=dst_lang)
        if pollution_issues:
            report.errors.append(
                f"Display cue {index} Chinese text contains suspicious polluted text: "
                f"{format_pollution_issues(pollution_issues)}."
            )

        if zh_text:
            rendered_zh = wrap_chinese_text(
                zh_text,
                trigger_chars=zh_wrap_trigger_chars,
                max_chars=zh_max_line_chars,
                max_lines=zh_max_lines,
            )
            zh_lines = rendered_zh.splitlines() or [rendered_zh]
            for line_number, line in enumerate(zh_lines, start=1):
                line_length = len(re.sub(r"\s+", "", line))
                if line_length > zh_max_line_chars:
                    report.errors.append(
                        f"Display cue {index} Chinese line {line_number} is too long: {line_length} chars > {zh_max_line_chars}."
                    )
            if len(zh_lines) > zh_max_lines:
                report.errors.append(
                    f"Display cue {index} has too many Chinese lines: {len(zh_lines)} > {zh_max_lines}."
                )
            zh_cps = len(re.sub(r"\s+", "", zh_text)) / duration
            if zh_cps > zh_max_cps:
                report.errors.append(
                    f"Display cue {index} Chinese text is too fast: {zh_cps:.1f} chars/sec > {zh_max_cps:.1f}."
                )

        if en_text:
            en_line_length = len(en_text)
            if en_line_length > en_max_line_chars:
                report.warnings.append(
                    f"Display cue {index} English line is too long: {en_line_length} chars > {en_max_line_chars}."
                )
            en_cps = en_line_length / duration
            if en_cps > en_max_cps:
                report.warnings.append(
                    f"Display cue {index} English text is too fast: {en_cps:.1f} chars/sec > {en_max_cps:.1f}."
                )

        if previous_zh and zh_text and zh_text == previous_zh and en_text:
            report.warnings.append(
                f"Display cue {index} repeats the previous Chinese subtitle exactly."
            )

        if (
            cue.source_segment_id is not None
            and cue.source_segment_id == previous_source_segment_id
            and zh_text
            and previous_zh
            and zh_text == previous_zh
            and cue.group_total > 1
        ):
            report.warnings.append(
                f"Display cue {index} may have alignment drift: repeated Chinese text within the same split segment."
            )

        previous_zh = zh_text or previous_zh
        previous_source_segment_id = cue.source_segment_id

    for segment_id, zh_texts in source_zh_runs.items():
        repeated = sum(1 for prev, curr in zip(zh_texts, zh_texts[1:]) if prev and curr and prev == curr)
        if repeated >= 1:
            report.warnings.append(
                f"Source segment {segment_id} contains repeated Chinese cue text {repeated} time(s)."
            )
        if len(zh_texts) >= 3:
            unique_texts = {text for text in zh_texts if text}
            if len(unique_texts) == 1:
                report.warnings.append(
                    f"Source segment {segment_id} maps to the same Chinese cue text across multiple display cues."
                )

    return report
