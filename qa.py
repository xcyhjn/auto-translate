from __future__ import annotations

from dataclasses import dataclass, field

from .models import Segment, SubtitleRules

DEFAULT_MAX_CHARS = 42
DEFAULT_MAX_CPS = 18.0


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


def qa_check(
    segments: list[Segment],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_cps: float = DEFAULT_MAX_CPS,
    rules: SubtitleRules | None = None,
) -> QaReport:
    report = QaReport()
    if rules is None:
        rules = SubtitleRules()

    if not segments:
        report.errors.append("No subtitle segments were generated.")
        return report

    previous_end = -1.0
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

    return report
