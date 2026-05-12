from __future__ import annotations

from .models import Segment, SubtitleRules
from .utils import normalize_text


def refine_timing(
    segments: list[Segment],
    *,
    rules: SubtitleRules | None = None,
) -> list[Segment]:
    if rules is None:
        rules = SubtitleRules()

    cleaned: list[Segment] = []
    previous_end = 0.0

    for segment in segments:
        text = normalize_text(segment.source_text)
        if not text:
            continue

        # 这里故意做保守的时间轴修正。
        # 我们尽量保留 faster-whisper 给出的边界，只补足字幕文件必须满足的约束：
        # 非空文本、正时长、以及与上一条不重叠。
        start = max(segment.start, previous_end + rules.min_gap if cleaned else 0.0)
        end = max(segment.end, start + rules.min_duration)
        if end - start > rules.max_duration:
            end = start + rules.max_duration

        segment.start = start
        segment.end = end
        segment.source_text = text
        cleaned.append(segment)
        previous_end = end

    for idx, segment in enumerate(cleaned, start=1):
        segment.id = idx

    return cleaned
