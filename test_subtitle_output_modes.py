from __future__ import annotations

from pathlib import Path

from autosub_zh.models import Segment
from autosub_zh.subtitle_io import write_bilingual_ass, write_source_ass, write_zh_ass
from autosub_zh.workflow_profiles import build_subtitle_output_plan


def test_subtitle_output_plan_names_russian_target_only() -> None:
    plan = build_subtitle_output_plan(
        src_lang="ru",
        dst_lang="zh-Hans",
        subtitle_mode="target_only",
        preview_seconds=60,
    )

    assert plan.source_srt_name == "04_source_ru.srt"
    assert plan.translated_srt_name == "06_translated_zh.srt"
    assert plan.ass_name == "08_subtitle_zh.ass"
    assert plan.output_video_name == "09_burned_zh_only_preview_60s.mp4"


def test_subtitle_output_plan_names_bilingual_with_language_labels() -> None:
    plan = build_subtitle_output_plan(
        src_lang="ru",
        dst_lang="zh-Hans",
        subtitle_mode="bilingual_source_reference",
        preview_seconds=None,
    )

    assert plan.ass_name == "08_bilingual_zh_ru.ass"
    assert plan.output_video_name == "09_burned_bilingual_zh_ru_video.mp4"


def test_target_only_ass_omits_source_reference_lines(tmp_path: Path) -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="eto samyy tragichnyy albom.",
            target_text="zhe shi zui bei shang de zhuan ji.",
        )
    ]
    target_only_path = tmp_path / "target_only.ass"
    bilingual_path = tmp_path / "bilingual.ass"

    write_zh_ass(segments, target_only_path)
    write_bilingual_ass(segments, bilingual_path)

    target_only_text = target_only_path.read_text(encoding="utf-8-sig")
    bilingual_text = bilingual_path.read_text(encoding="utf-8-sig")
    assert "EnglishSmall" not in target_only_text
    assert "eto samyy tragichnyy albom." not in target_only_text
    assert "EnglishSmall" in bilingual_text
    assert "eto samyy tragichnyy albom." in bilingual_text


def test_source_review_ass_contains_source_only_lines(tmp_path: Path) -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="eto samyy tragichnyy albom.",
            target_text="zhe shi zui bei shang de zhuan ji.",
        )
    ]
    output_path = tmp_path / "source_review.ass"

    write_source_ass(segments, output_path)

    text = output_path.read_text(encoding="utf-8-sig")
    assert "Style: SourceOnly" in text
    assert "eto samyy tragichnyy albom." in text
    assert "zhe shi zui bei shang de zhuan ji." not in text


def test_target_only_ass_skips_pure_english_target_lines(tmp_path: Path) -> None:
    segments = [
        Segment(id=1, start=0.0, end=2.0, source_text="movie title", target_text="zhe bu dianying jiao"),
        Segment(id=2, start=2.0, end=4.0, source_text="The Sand Pebbles", target_text="The Sand Pebbles"),
    ]
    output_path = tmp_path / "target_only_english_gap.ass"

    write_zh_ass(segments, output_path)

    text = output_path.read_text(encoding="utf-8-sig")
    assert "zhe bu dianying jiao" not in text
    assert "The Sand Pebbles" not in text


def test_target_only_ass_merges_english_tail_into_previous_chinese_line(tmp_path: Path) -> None:
    segments = [
        Segment(id=1, start=0.0, end=2.0, source_text="movie title intro", target_text="zhe bu dianying jiao"),
        Segment(id=2, start=2.0, end=4.0, source_text="The Sand Pebbles", target_text="The Sand Pebbles"),
    ]
    output_path = tmp_path / "target_only_english_tail.ass"

    write_zh_ass(segments, output_path)

    text = output_path.read_text(encoding="utf-8-sig")
    assert "zhe bu dianying jiaoThe Sand Pebbles" in text
