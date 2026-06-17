from __future__ import annotations

from pathlib import Path

from autosub_zh.models import BilingualSubtitleStyle, Segment
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
    assert plan.ass_name == "00_ASS_subtitle_zh.ass"
    assert plan.legacy_ass_name == "08_subtitle_zh.ass"
    assert plan.output_video_name == "09_burned_zh_only_preview_60s.mp4"


def test_subtitle_output_plan_names_bilingual_with_language_labels() -> None:
    plan = build_subtitle_output_plan(
        src_lang="ru",
        dst_lang="zh-Hans",
        subtitle_mode="bilingual_source_reference",
        preview_seconds=None,
    )

    assert plan.ass_name == "00_ASS_bilingual_zh_ru.ass"
    assert plan.legacy_ass_name == "08_bilingual_zh_ru.ass"
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
        Segment(id=1, start=0.0, end=2.0, source_text="movie title intro", target_text="这部电影叫"),
        Segment(id=2, start=2.0, end=4.0, source_text="The Sand Pebbles", target_text="The Sand Pebbles"),
    ]
    output_path = tmp_path / "target_only_english_tail.ass"

    write_zh_ass(segments, output_path)

    text = output_path.read_text(encoding="utf-8-sig")
    assert "这部电影叫The Sand Pebbles" in text


def test_bilingual_ass_prefers_reference_text_over_raw_source_text(tmp_path: Path) -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="Victor Torsk wrote a paper.",
            reference_text="Viktor Tausk wrote a paper.",
            target_text="维克托·陶斯克写过一篇论文。",
        )
    ]
    output_path = tmp_path / "reference_pref.ass"

    write_bilingual_ass(segments, output_path)

    text = output_path.read_text(encoding="utf-8-sig")
    assert "Viktor Tausk wrote a paper." in text
    assert "Victor Torsk wrote a paper." not in text


def test_russian_full_split_keeps_long_reference_without_ellipsis(tmp_path: Path) -> None:
    source_text = (
        "\u042d\u0442\u043e \u043e\u0447\u0435\u043d\u044c \u0434\u043b\u0438\u043d\u043d\u0430\u044f "
        "\u0440\u0443\u0441\u0441\u043a\u0430\u044f \u0440\u0435\u043f\u043b\u0438\u043a\u0430, "
        "\u043f\u043e\u0442\u043e\u043c\u0443 \u0447\u0442\u043e \u043e\u043d\u0430 "
        "\u0434\u043e\u043b\u0436\u043d\u0430 \u043e\u0441\u0442\u0430\u0442\u044c\u0441\u044f "
        "\u043f\u043e\u043b\u043d\u043e\u0439 \u0438 \u043d\u0435 \u0434\u043e\u043b\u0436\u043d\u0430 "
        "\u043f\u0440\u0435\u0432\u0440\u0430\u0449\u0430\u0442\u044c\u0441\u044f \u0432 "
        "\u043c\u043d\u043e\u0433\u043e\u0442\u043e\u0447\u0438\u0435."
    )
    style = BilingualSubtitleStyle(
        reference_mode="full_split",
        en_max_single_line_chars=42,
        en_max_split_parts=4,
        min_split_duration=0.5,
    )
    output_path = tmp_path / "ru_full_split.ass"

    debug_rows = write_bilingual_ass(
        [
            Segment(
                id=1,
                start=0.0,
                end=8.0,
                source_text=source_text,
                target_text="\u8fd9\u662f\u4e00\u53e5\u5f88\u957f\u7684\u4fc4\u6587\u53c2\u8003\u5b57\u5e55\uff0c\u9700\u8981\u5b8c\u6574\u663e\u793a\u3002",
            )
        ],
        output_path,
        style=style,
        reference_lang="ru",
    )

    text = output_path.read_text(encoding="utf-8-sig")
    assert text.count("EnglishSmall") > 1
    assert "..." not in text
    assert "\u2026" not in text
    assert debug_rows[0]["english_group_count"] > 1
    assert debug_rows[0]["rewrite_action"] == "reference_split"


def test_russian_full_split_keeps_protected_title_together(tmp_path: Path) -> None:
    style = BilingualSubtitleStyle(
        reference_mode="full_split",
        en_max_single_line_chars=12,
        en_max_split_parts=4,
    )
    output_path = tmp_path / "ru_title.ass"

    debug_rows = write_bilingual_ass(
        [
            Segment(
                id=1,
                start=0.0,
                end=3.0,
                source_text="Xiu Xiu: The Sent-Down Girl",
                target_text="\u300a\u5929\u6d74\u300b",
            )
        ],
        output_path,
        style=style,
        reference_lang="ru",
    )

    text = output_path.read_text(encoding="utf-8-sig")
    assert "Xiu Xiu: The Sent-Down Girl" in text
    assert debug_rows[0]["english_group_count"] == 1
