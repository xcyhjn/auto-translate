from __future__ import annotations

from pathlib import Path

from autosub_zh.models import BilingualSubtitleStyle, Segment, Word
from autosub_zh.pipeline_core import build_manifest_file_list, promote_audio_artifact
from autosub_zh.qa import qa_final_ass_file
from autosub_zh.subtitle_io import (
    DisplayCue,
    apply_multiline_reference_uplift_to_ass_text,
    write_bilingual_ass,
    write_bilingual_ass_from_display_cues,
    write_source_ass,
    write_zh_ass,
)
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


def test_manifest_file_list_pins_ass_artifacts_first(tmp_path: Path) -> None:
    plan = build_subtitle_output_plan(
        src_lang="en",
        dst_lang="zh-Hans",
        subtitle_mode="bilingual_source_reference",
        preview_seconds=None,
    )

    files = build_manifest_file_list(
        tmp_path,
        plan,
        audio_override_path=None,
        output_video_name="09_burned_bilingual_zh_en_video.mp4",
    )

    assert files[:2] == ["00_ASS_bilingual_zh_en.ass", "08_bilingual_zh_en.ass"]
    assert "00_ASS_safe_for_burn.ass" not in files
    assert "08_bilingual_safe.ass" not in files


def test_promote_audio_artifact_moves_instead_of_copying(tmp_path: Path) -> None:
    extracted = tmp_path / "source-title.wav"
    canonical = tmp_path / "01_audio_16k.wav"
    extracted.write_bytes(b"audio")

    result = promote_audio_artifact(extracted, canonical)

    assert result == canonical
    assert canonical.read_bytes() == b"audio"
    assert not extracted.exists()


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


def test_bilingual_ass_only_uplifts_chinese_when_reference_has_line_break(tmp_path: Path) -> None:
    style = BilingualSubtitleStyle(
        zh_margin_v=94,
        zh_uplift_when_en_multiline=40,
        en_max_single_line_chars=24,
    )
    output_path = tmp_path / "uplift.ass"

    write_bilingual_ass_from_display_cues(
        [
            DisplayCue(
                start=0.0,
                end=2.0,
                en_text="short reference",
                zh_text="短句。",
            ),
            DisplayCue(
                start=2.0,
                end=4.0,
                en_text="this reference is long enough to exceed the configured limit but stays on one ASS line",
                zh_text="长英文但不分行。",
            ),
            DisplayCue(
                start=4.0,
                end=6.0,
                en_text=r"line one\Nline two",
                zh_text="英文真分行时中文上抬。",
            ),
        ],
        output_path,
        style=style,
    )
    text = output_path.read_text(encoding="utf-8-sig")

    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,短句。" in text
    assert "Style: Default,Maple Mono NF CN,64" in text
    assert ",0,0,100,100,-2.0,0,1," in text
    assert "Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,长英文但不分行。" in text
    assert "Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,134,,英文真分行时中文上抬。" in text


def test_manual_ass_uplift_applies_to_existing_multiline_reference() -> None:
    style = BilingualSubtitleStyle(
        zh_margin_v=94,
        zh_uplift_when_en_multiline=40,
    )
    ass_text = "\n".join(
        [
            "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,中文。",
            r"Dialogue: 1,0:00:00.00,0:00:02.00,EnglishSmall,,0,0,0,,line one\Nline two",
            "Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,另一句。",
            "Dialogue: 1,0:00:02.00,0:00:04.00,EnglishSmall,,0,0,0,,single line",
        ]
    )

    updated = apply_multiline_reference_uplift_to_ass_text(ass_text, style)

    assert "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,134,,中文。" in updated
    assert "Dialogue: 0,0:00:02.00,0:00:04.00,Default,,0,0,0,,另一句。" in updated


def test_manual_ass_uplift_updates_default_style_spacing() -> None:
    style = BilingualSubtitleStyle(zh_spacing=-2.0)
    ass_text = (
        "Style: Default,Maple Mono NF CN,64,&H001ADDFF,&H000000FF,&H47202020,&H80000000,"
        "0,0,0,0,100,100,0,0,1,1.8,0.5,2,90,90,94,1\n"
    )

    updated = apply_multiline_reference_uplift_to_ass_text(ass_text, style)

    assert (
        "Style: Default,Maple Mono NF CN,64,&H001ADDFF,&H000000FF,&H47202020,&H80000000,"
        "0,0,0,0,100,100,-2.0,0,1,1.8,0.5,2,90,90,94,1"
    ) in updated


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


def test_default_reference_mode_keeps_long_english_without_ellipsis(tmp_path: Path) -> None:
    output_path = tmp_path / "default_reference_mode.ass"

    debug_rows = write_bilingual_ass(
        [
            Segment(
                id=1,
                start=0.0,
                end=5.0,
                source_text="I cannot just show this out of context because it would make no sense at all.",
                target_text="\u8fd9\u53e5\u82f1\u6587\u53c2\u8003\u5c42\u5fc5\u987b\u5b8c\u6574\u4fdd\u7559\u3002",
            )
        ],
        output_path,
        style=BilingualSubtitleStyle(en_max_single_line_chars=36, en_max_split_parts=3),
    )

    text = output_path.read_text(encoding="utf-8-sig")
    assert "..." not in text
    assert "\u2026" not in text
    assert r"\N" in text or text.count("EnglishSmall") > 2
    assert debug_rows[0]["reference_mode"] == "full_split"


def test_compact_long_english_reference_uses_multiline_not_ellipsis(tmp_path: Path) -> None:
    style = BilingualSubtitleStyle(
        reference_mode="compact",
        en_max_single_line_chars=34,
        en_max_split_parts=3,
    )
    output_path = tmp_path / "long_en_multiline.ass"

    debug_rows = write_bilingual_ass(
        [
            Segment(
                id=1,
                start=0.0,
                end=5.0,
                source_text="This reference line is far too long for one line but it still needs to stay complete.",
                target_text="\u8fd9\u6761\u82f1\u6587\u53c2\u8003\u592a\u957f\uff0c\u4f46\u5185\u5bb9\u5fc5\u987b\u4fdd\u7559\u5b8c\u6574\u3002",
            )
        ],
        output_path,
        style=style,
    )

    text = output_path.read_text(encoding="utf-8-sig")
    assert "..." not in text
    assert "\u2026" not in text
    assert r"\N" in text
    assert debug_rows[0]["rewrite_action"] == "reference_multiline"
    assert debug_rows[0]["english_group_count"] == 1
    assert qa_final_ass_file(output_path, dst_lang="zh-Hans").errors == []


def test_high_confidence_long_english_reference_splits_on_word_timing(tmp_path: Path) -> None:
    style = BilingualSubtitleStyle(
        reference_mode="compact",
        en_max_single_line_chars=60,
        en_max_split_parts=2,
        min_split_duration=0.5,
    )
    words = [
        Word("I", 0.00, 0.10, 0.95),
        Word("took", 0.12, 0.30, 0.95),
        Word("an", 0.32, 0.42, 0.95),
        Word("After", 0.44, 0.70, 0.95),
        Word("Effects", 0.72, 1.05, 0.95),
        Word("class", 1.07, 1.35, 0.95),
        Word("in", 1.37, 1.48, 0.95),
        Word("college", 1.50, 1.85, 0.95),
        Word("a", 1.87, 1.95, 0.95),
        Word("few", 1.97, 2.13, 0.95),
        Word("years", 2.15, 2.38, 0.95),
        Word("ago,", 2.40, 2.62, 0.95),
        Word("and", 3.25, 3.39, 0.95),
        Word("there", 3.41, 3.62, 0.95),
        Word("are", 3.64, 3.78, 0.95),
        Word("some", 3.80, 4.00, 0.95),
        Word("3D", 4.02, 4.18, 0.95),
        Word("things", 4.20, 4.48, 0.95),
        Word("you", 4.50, 4.65, 0.95),
        Word("can", 4.67, 4.82, 0.95),
        Word("do", 4.84, 5.00, 0.95),
        Word("there.", 5.02, 5.35, 0.95),
    ]
    output_path = tmp_path / "word_timed_split.ass"

    debug_rows = write_bilingual_ass(
        [
            Segment(
                id=1,
                start=0.0,
                end=5.5,
                source_text=" ".join(word.word for word in words),
                target_text="\u6211\u51e0\u5e74\u524d\u5728\u5927\u5b66\u4e0a\u8fc7 After Effects \u8bfe\uff0c\u90a3\u91cc\u4e5f\u80fd\u505a\u4e00\u4e9b 3D \u76f8\u5173\u7684\u4e1c\u897f\u3002",
                words=words,
            )
        ],
        output_path,
        style=style,
    )

    row = debug_rows[0]
    actions = row["rewrite_action"] if isinstance(row["rewrite_action"], list) else [row["rewrite_action"]]
    assert "reference_split" in actions
    assert row["english_group_count"] == 2
    assert row["cues"][0]["end"] == 2.62
    assert row["cues"][1]["start"] == 3.25
    assert "..." not in output_path.read_text(encoding="utf-8-sig")
    assert "\u2026" not in output_path.read_text(encoding="utf-8-sig")


def test_word_timed_split_is_not_stretched_by_minimum_duration(tmp_path: Path) -> None:
    style = BilingualSubtitleStyle(
        reference_mode="full_split",
        en_max_single_line_chars=74,
        en_max_split_parts=2,
        min_split_duration=2.0,
    )
    words = [
        Word("So", 372.32, 372.82, 0.95),
        Word("I", 372.82, 373.08, 0.95),
        Word("am", 373.08, 373.26, 0.95),
        Word("going", 373.26, 373.48, 0.95),
        Word("to", 373.48, 373.80, 0.95),
        Word("recap", 373.80, 374.44, 0.95),
        Word("it", 374.44, 374.84, 0.95),
        Word("real", 374.84, 374.96, 0.95),
        Word("quick,", 374.96, 375.34, 0.95),
        Word("mostly", 375.70, 375.70, 0.95),
        Word("for", 375.70, 375.86, 0.95),
        Word("my", 375.86, 375.98, 0.95),
        Word("own", 375.98, 376.14, 0.95),
        Word("amusement,", 376.14, 376.52, 0.95),
        Word("and", 376.98, 376.98, 0.95),
        Word("also", 376.98, 377.30, 0.95),
        Word("so", 377.30, 377.50, 0.95),
        Word("that", 377.50, 377.64, 0.95),
        Word("y", 377.64, 377.80, 0.95),
        Word("'all", 377.80, 377.84, 0.95),
        Word("know,", 377.84, 378.16, 0.95),
    ]
    output_path = tmp_path / "word_timed_not_stretched.ass"

    debug_rows = write_bilingual_ass(
        [
            Segment(
                id=77,
                start=372.32,
                end=378.16,
                source_text=" ".join(word.word for word in words),
                target_text="\u6240\u4ee5\u6211\u8fd8\u662f\u5feb\u901f\u7ed9\u4f60\u4eec\u634b\u4e00\u904d\uff0c\u4e3b\u8981\u662f\u56fe\u6211\u81ea\u5df1\u4e50\uff0c\u4e5f\u987a\u4fbf\u8ba9\u4f60\u4eec\u77e5\u9053\uff0c",
                words=words,
            )
        ],
        output_path,
        style=style,
    )

    cues = debug_rows[0]["cues"]
    assert cues[0]["end"] == 376.52
    assert cues[1]["start"] == 376.98
    assert cues[1]["end"] == 378.16


def test_long_english_falls_back_to_multiline_when_chinese_split_is_unstable(tmp_path: Path) -> None:
    style = BilingualSubtitleStyle(
        reference_mode="compact",
        en_max_single_line_chars=30,
        en_max_split_parts=3,
    )
    output_path = tmp_path / "fallback_multiline.ass"

    debug_rows = write_bilingual_ass(
        [
            Segment(
                id=1,
                start=0.0,
                end=5.0,
                source_text="This long reference has enough words to split but the Chinese side is too short to divide safely.",
                target_text="\u597d\u3002",
            )
        ],
        output_path,
        style=style,
    )

    text = output_path.read_text(encoding="utf-8-sig")
    assert debug_rows[0]["rewrite_action"] == "reference_multiline"
    assert debug_rows[0]["english_group_count"] == 1
    assert text.count("\u597d\u3002") == 1
    assert r"\N" in text
    assert "..." not in text
    assert "\u2026" not in text


def test_final_ass_blocks_ellipsized_english_reference(tmp_path: Path) -> None:
    ass_path = tmp_path / "ellipsized.ass"
    ass_path.write_text(
        "\n".join(
            [
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                "Dialogue: 1,0:00:00.00,0:00:02.00,EnglishSmall,,0,0,0,,This reference was cut...",
                "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,\u8fd9\u662f\u4e2d\u6587\u3002",
            ]
        )
        + "\n",
        encoding="utf-8-sig",
    )

    report = qa_final_ass_file(ass_path, dst_lang="zh-Hans")

    assert any("ellipsized" in error for error in report.errors)
