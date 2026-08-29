from __future__ import annotations

from pathlib import Path

import json

from autosub_zh.entity_normalization import audit_ass_entities, build_entity_metrics, build_entity_review_rows, normalize_entities
from autosub_zh.models import Segment
from autosub_zh.qa import qa_ass_entity_audit
from autosub_zh.qa import build_quality_metrics


def test_entity_normalization_translates_chinese_residue_and_normalizes_reference() -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="Victor Torsk wrote a paper.",
            target_text="Victor Torsk 写过一篇论文。",
        ),
        Segment(
            id=2,
            start=2.0,
            end=4.0,
            source_text="Torsk called it an influencing machine.",
            target_text="Torsk 把它叫作影响机器。",
        ),
    ]

    report = normalize_entities(segments)

    assert segments[0].source_text == "Victor Torsk wrote a paper."
    assert segments[0].reference_text == "Viktor Tausk wrote a paper."
    assert segments[0].target_text == "维克托·陶斯克 写过一篇论文。"
    assert segments[1].source_text == "Torsk called it an influencing machine."
    assert segments[1].reference_text == "Viktor Tausk called it an influencing machine."
    assert segments[1].target_text == "陶斯克 把它叫作影响机器。"
    assert report["summary"]["segments_changed"] == 2
    assert report["summary"]["reference_text_replacements"] >= 2
    assert report["summary"]["target_text_replacements"] >= 2


def test_entity_normalization_uses_full_then_short_name_strategy() -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="James Tilly Matthews drew this machine.",
            target_text="James Tilly Matthews 画出了这台机器。",
        ),
        Segment(
            id=2,
            start=2.0,
            end=4.0,
            source_text="Matthews was hospitalized in 1797.",
            target_text="Matthews 于 1797 年住院。",
        ),
    ]

    normalize_entities(segments)

    assert segments[0].target_text == "詹姆斯·蒂利·马修斯 画出了这台机器。"
    assert segments[1].target_text == "马修斯 于 1797 年住院。"
    assert segments[0].reference_text == "James Tilly Matthews drew this machine."
    assert segments[1].reference_text == "James Tilly Matthews was hospitalized in 1797."


def test_entity_normalization_fixes_known_artist_name_variants() -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="This is a piece by Paul Gosh.",
            target_text="这是 Paul Gosh 的一幅作品。",
        )
    ]

    normalize_entities(segments)

    assert segments[0].source_text == "This is a piece by Paul Gosh."
    assert segments[0].reference_text == "This is a piece by Paul Gösch."
    assert segments[0].target_text == "这是 保罗·戈施 的一幅作品。"


def test_entity_review_rows_flag_unknown_english_residue() -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="Someone mentioned Strange Name.",
            target_text="这像 Strange Name 提到的情况。",
        )
    ]

    rows = build_entity_review_rows(segments)

    assert rows
    assert rows[0]["candidate"] == "Strange Name"
    assert rows[0]["entity_type"] == "unknown"
    assert rows[0]["reason"] == "unknown_english_residue_in_chinese_target"
    assert rows[0]["reference_text"] == "Someone mentioned Strange Name."


def test_ass_entity_audit_flags_chinese_residue_and_bad_reference_names(tmp_path: Path) -> None:
    ass_path = tmp_path / "audit.ass"
    ass_path.write_text(
        "\n".join(
            [
                "[Script Info]",
                "Title: test",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                "Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,这像 Richard Sharp Shaver 提到的情况。",
                "Dialogue: 1,0:00:00.00,0:00:02.00,EnglishSmall,,0,0,0,,Richard Sharp Shaver comes to mind.",
            ]
        ),
        encoding="utf-8-sig",
    )

    audit = audit_ass_entities(ass_path)

    assert audit["summary"]["issue_count"] == 2
    assert audit["summary"]["english_residue_count"] == 1
    assert audit["summary"]["reference_name_issue_count"] == 1


def test_qa_ass_entity_audit_maps_issues_to_errors_and_warnings() -> None:
    report = qa_ass_entity_audit(
        {
            "issues": [
                {"issue_type": "english_residue_in_chinese_layer", "text": "Richard Sharp Shaver"},
                {"issue_type": "non_canonical_reference_name", "text": "Richard Sharp Shaver"},
            ]
        }
    )

    assert any("Chinese subtitle line still contains English residue" in item for item in report.errors)
    assert any("English reference line still contains non-canonical name" in item for item in report.warnings)


def test_project_entity_decisions_override_and_bootstrap(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "00_entity_decisions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "entities": [
                    {
                        "key": "custom_person",
                        "canonical_en": "Custom Person",
                        "canonical_zh": "自定义人物",
                        "surface_forms": ["Custom Person", "Person"],
                        "short_zh": "人物",
                        "mention_strategy": "full_then_short",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="Custom Person appeared here.",
            target_text="Custom Person 出现在这里。",
        )
    ]

    report = normalize_entities(segments, project_dir=project_dir)

    assert segments[0].target_text == "自定义人物 出现在这里。"
    assert report["summary"]["project_decisions_path"] == str(project_dir / "00_entity_decisions.json")


def test_project_entity_bootstrap_is_disabled_by_default(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="Victor Torsk wrote a paper.",
            target_text="Victor Torsk 写过一篇论文。",
        )
    ]

    report = normalize_entities(segments, project_dir=project_dir)

    assert report["summary"]["project_decisions_path"] == ""
    assert not (project_dir / "00_entity_decisions.json").exists()


def test_project_entity_bootstrap_can_be_enabled(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="Victor Torsk wrote a paper.",
            target_text="Victor Torsk 写过一篇论文。",
        )
    ]

    report = normalize_entities(
        segments,
        project_dir=project_dir,
        bootstrap_project_decisions=True,
    )

    assert report["summary"]["project_decisions_path"] == str(project_dir / "00_entity_decisions.json")
    assert (project_dir / "00_entity_decisions.json").exists()


def test_project_entity_bootstrap_high_confidence_only_can_write(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="Victor Torsk wrote a paper.",
            target_text="Victor Torsk 写过一篇论文。",
        )
    ]

    report = normalize_entities(
        segments,
        project_dir=project_dir,
        bootstrap_project_decisions="high_confidence_only",
    )

    assert report["summary"]["project_decisions_path"] == str(project_dir / "00_entity_decisions.json")
    assert (project_dir / "00_entity_decisions.json").exists()


def test_entity_review_rows_skip_candidates_not_seen_in_source_or_reference() -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="This line mentions nobody by name.",
            target_text="这像 Strange Name 提到的情况。",
        )
    ]

    rows = build_entity_review_rows(segments)

    assert rows == []


def test_entity_review_rows_skip_project_preserve_terms(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "00_entity_decisions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "entities": [
                    {
                        "key": "sent_down_girl",
                        "canonical_en": "The Sent-Down Girl",
                        "canonical_zh": "下乡女",
                        "surface_forms": ["The Sent-Down Girl"],
                        "short_zh": "下乡女",
                        "mention_strategy": "full_only",
                        "policy": "preserve",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="The Sent-Down Girl is referenced here.",
            target_text="这里提到了 The Sent-Down Girl。",
        )
    ]

    rows = build_entity_review_rows(segments, project_dir=project_dir)

    assert rows == []


def test_entity_review_rows_skip_title_like_phrases_inside_quotes() -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="The title The Sent-Down Girl appears here.",
            target_text="这里提到了《The Sent-Down Girl》。",
        )
    ]

    rows = build_entity_review_rows(segments)

    assert rows == []


def test_entity_review_rows_skip_glossary_preserve_terms(tmp_path: Path) -> None:
    glossary_path = tmp_path / "glossary.json"
    glossary_path.write_text(
        json.dumps(
            {
                "version": 1,
                "terms": [
                    {
                        "canonical": "The Sent-Down Girl",
                        "policy": "preserve",
                        "aliases": [],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="The Sent-Down Girl is referenced here.",
            target_text="这里提到了 The Sent-Down Girl。",
        )
    ]

    rows = build_entity_review_rows(segments, glossary_path=glossary_path)

    assert rows == []


def test_quality_metrics_tracks_entity_residue_from_short_english_leaks() -> None:
    segments = [
        Segment(
            id=1,
            start=0.0,
            end=2.0,
            source_text="Richard Sharpe Shaver comes to mind.",
            target_text="比如 Richard Sharp Shaver 就是一个。",
        )
    ]

    metrics = build_quality_metrics(segments, [], dst_lang="zh-Hans")

    assert metrics["translation"]["entity_residue_count"] == 1
    assert metrics["translation"]["entity_residue_samples"][0]["leaks"] == ["Richard Sharp Shaver"]


def test_build_entity_metrics_summarizes_entity_outputs() -> None:
    payload = build_entity_metrics(
        {
            "summary": {"decision_count": 3, "segments_changed": 2, "reference_text_replacements": 4, "target_text_replacements": 2},
            "decisions": [
                {"entity_type": "person"},
                {"entity_type": "person"},
                {"entity_type": "paper"},
            ],
        },
        {"summary": {"issue_count": 2, "english_residue_count": 1, "reference_name_issue_count": 1}},
        {"translation": {"entity_residue_count": 1, "entity_residue_samples": [{"segment_id": 1, "leaks": ["Richard Sharp Shaver"]}]}},
    )

    assert payload["summary"]["entity_decision_count"] == 3
    assert payload["summary"]["ass_issue_count"] == 2
    assert payload["summary"]["target_entity_residue_count"] == 1
    assert payload["entity_type_counts"]["person"] == 2
    assert payload["entity_type_counts"]["paper"] == 1
