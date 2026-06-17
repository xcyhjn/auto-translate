from __future__ import annotations

import json
from pathlib import Path

from autosub_zh.feedback_dataset import (
    build_gold_sets,
    collect_bilibili_project,
    collect_span_style_project,
    collect_style_project,
    dataset_paths,
    eval_bilibili,
    eval_span_style,
    eval_style,
    read_jsonl,
    save_bilibili_feedback_label,
    summarize_learning,
    validate_dataset,
    write_jsonl,
)


YOUTUBE_META = {
    "video_id": "abc123XYZ09",
    "video_url": "https://www.youtube.com/watch?v=abc123XYZ09",
    "title": "The Russian book about a dying god",
    "description": "A video essay about a Russian novel where a god is dying.",
    "author": "Paper Trail",
    "published_at": "2025-01-10",
    "duration": 1200,
}


def write_project_report(project: Path) -> None:
    project.mkdir(parents=True)
    report = {
        "input_youtube_url": YOUTUBE_META["video_url"],
        "youtube_meta": YOUTUBE_META,
        "query_plan": [{"id": "q01", "kind": "original_title", "text": YOUTUBE_META["title"]}],
        "candidates": [
            {
                "title": "垂死的神：一部俄罗斯小说的奇怪神明",
                "url": "https://www.bilibili.com/video/BV1mock411c7mD",
                "bvid": "BV1mock411c7mD",
                "uploader": "搬运字幕组",
                "duration": "20:10",
                "published_at": "2025-02-01",
                "description": "转载 Paper Trail，附中文字幕。",
                "matched_queries": ["垂死的神 俄罗斯 小说"],
                "score": 74,
                "reason_codes": ["semantic_keyword_hit", "duration_near_exact"],
            }
        ],
    }
    (project / "00b_bilibili_duplicate_search.json").write_text(
        json.dumps(report, ensure_ascii=False),
        encoding="utf-8",
    )


def test_collect_bilibili_preserves_labels_and_replay_eval_runs(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    project = tmp_path / "project"
    write_project_report(project)

    first = collect_bilibili_project(project, dataset_dir)
    assert first["added"] == 1

    paths = dataset_paths(dataset_dir)
    records = read_jsonl(paths["bilibili_labels"])
    records[0]["label"] = "duplicate"
    records[0]["use_for_eval"] = True
    records[0]["human_note"] = "confirmed repost"
    write_jsonl(paths["bilibili_labels"], records)

    second = collect_bilibili_project(project, dataset_dir)
    assert second["added"] == 0
    preserved = read_jsonl(paths["bilibili_labels"])[0]
    assert preserved["label"] == "duplicate"
    assert preserved["human_note"] == "confirmed repost"

    gold = build_gold_sets(dataset_dir)
    assert gold["bilibili_gold_count"] == 1

    report = eval_bilibili(dataset_dir)
    assert report["sample_count"] == 1
    assert report["metrics"]["recall@1"] == 1.0
    assert report["sample_insufficient"] is True
    assert paths["latest_bilibili_eval"].exists()


def test_collect_style_defaults_to_review_only_samples(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    project = tmp_path / "style_project"
    project.mkdir()
    segments = {
        "segments": [
            {
                "id": 1,
                "start": 1.0,
                "end": 3.0,
                "source_text": "This is a long literal sentence.",
                "target_text": "这是一句很长很直译的话语",
                "reference_text": "",
                "confidence": None,
                "source": "asr",
                "words": [],
            }
        ]
    }
    (project / "05_translated_segments.json").write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    (project / "08_bilingual_zh_en.ass").write_text(
        "\n".join(
            [
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,这句更自然",
            ]
        ),
        encoding="utf-8-sig",
    )

    result = collect_style_project(project, dataset_dir)
    assert result["added"] == 1

    paths = dataset_paths(dataset_dir)
    record = read_jsonl(paths["translation_edits"])[0]
    assert record["accepted"] is False
    assert record["use_for_style_prompt"] is False
    assert record["use_for_eval"] is False
    assert "needs_human_acceptance" in record["quality_flags"]
    assert isinstance(record["features"], dict)
    assert record["feedback_types"]
    assert record["learning_risk"] in {"low", "medium", "high"}
    assert record["learning_recommendation"] in {"review_only", "style_prompt_candidate", "eval_candidate"}
    assert isinstance(record["classification_reasons"], list)

    summary = summarize_learning(dataset_dir)
    assert summary["style_learning_count"] == 0


def test_collect_style_skips_empty_preferred_ass_and_uses_recovered_file(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    project = tmp_path / "style_project"
    project.mkdir()
    segments = {
        "segments": [
            {
                "id": 1,
                "start": 1.0,
                "end": 3.0,
                "source_text": "This is a long literal sentence.",
                "target_text": "这是一句很长很直译的话语。",
                "reference_text": "",
                "confidence": None,
                "source": "asr",
                "words": [],
            }
        ]
    }
    (project / "05_translated_segments.json").write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    (project / "08_bilingual_zh_en.ass").write_text("\n", encoding="utf-8-sig")
    recovered = project / "08_bilingual_zh_en.recovered_from_vscode.ass"
    recovered.write_text(
        "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,这句更自然。",
            ]
        ),
        encoding="utf-8-sig",
    )

    result = collect_style_project(project, dataset_dir)

    assert result["added"] == 1
    assert result["ass_path"] == str(recovered.resolve())


def test_style_gold_eval_reports_feedback_health(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    project = tmp_path / "style_project"
    project.mkdir()
    segments = {
        "segments": [
            {
                "id": 1,
                "start": 1.0,
                "end": 3.0,
                "source_text": "This sentence needs a compact subtitle.",
                "target_text": "杩欎釜鍙ュ瓙闇€瑕佷竴涓畝鐭殑瀛楀箷缈昏瘧",
                "reference_text": "",
                "confidence": None,
                "source": "asr",
                "words": [],
            }
        ]
    }
    (project / "05_translated_segments.json").write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    (project / "08_bilingual_zh_en.ass").write_text(
        "\n".join(
            [
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,绠€鐭€佽嚜鐒剁殑瀛楀箷",
            ]
        ),
        encoding="utf-8-sig",
    )

    collect_style_project(project, dataset_dir)
    paths = dataset_paths(dataset_dir)
    records = read_jsonl(paths["translation_edits"])
    records[0]["accepted"] = True
    records[0]["use_for_eval"] = True
    records[0]["use_for_style_prompt"] = False
    write_jsonl(paths["translation_edits"], records)

    gold = build_gold_sets(dataset_dir)
    assert gold["style_gold_count"] == 1

    report = eval_style(dataset_dir)
    assert report["sample_count"] == 1
    assert report["sample_insufficient"] is True
    assert report["metrics"]["semantic_or_style_signal_rate"] > 0
    assert paths["latest_style_eval"].exists()


def test_collect_span_style_defaults_to_review_only_samples(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    project = tmp_path / "span_project"
    project.mkdir()
    segments = {
        "segments": [
            {
                "id": 1,
                "start": 1.0,
                "end": 2.0,
                "source_text": "He told me just before leaving, and",
                "target_text": "他离开前告诉我，而且",
                "reference_text": "",
                "confidence": None,
                "source": "asr",
                "words": [],
            },
            {
                "id": 2,
                "start": 2.1,
                "end": 3.0,
                "source_text": "and the next day the police",
                "target_text": "第二天警方",
                "reference_text": "",
                "confidence": None,
                "source": "asr",
                "words": [],
            },
        ]
    }
    (project / "05_translated_segments.json").write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    (project / "04a_source_spans.json").write_text(
        json.dumps(
            {
                "spans": [
                    {
                        "span_id": "srcspan-0001",
                        "segment_ids": [1, 2],
                        "start": 1.0,
                        "end": 3.0,
                        "duration": 2.0,
                        "risk_score": 32,
                        "risk_reasons": {"ends_with_function_word": 1, "starts_with_continuation": 1},
                        "translation_strategy": "span_first",
                        "source_joined": "He told me just before leaving, and and the next day the police",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (project / "08_bilingual_zh_en.ass").write_text(
        "\n".join(
            [
                "[Events]",
                "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
                "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,他离开前告诉我",
                "Dialogue: 0,0:00:02.10,0:00:03.00,Default,,0,0,0,,第二天警方就来了",
            ]
        ),
        encoding="utf-8-sig",
    )

    result = collect_span_style_project(project, dataset_dir)

    assert result["added"] == 1
    paths = dataset_paths(dataset_dir)
    record = read_jsonl(paths["span_translation_examples"])[0]
    assert record["accepted"] is False
    assert record["use_for_span_prompt"] is False
    assert record["use_for_eval"] is False
    assert record["learning_recommendation"] == "span_prompt_candidate"
    assert "close_open_clause" in record["edit_tags"]


def test_span_gold_eval_and_validation_reject_overlap(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    paths = dataset_paths(dataset_dir)
    paths["root"].mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "project_id": "span_project",
        "span_id": "srcspan-0001",
        "segment_ids": [1, 2],
        "source_joined": "He told me just before leaving, and and the next day the police",
        "risk_reasons": {"ends_with_function_word": 1},
        "translation_strategy": "span_first",
        "context_before": [],
        "context_after": [],
        "machine_target_by_id": {"1": "他离开前告诉我，而且", "2": "第二天警方"},
        "manual_target_by_id": {"1": "他离开前告诉我", "2": "第二天警方就来了"},
        "edit_tags": ["semantic_reallocation", "fragment_completion"],
        "learning_risk": "low",
        "learning_recommendation": "span_prompt_candidate",
        "classification_reasons": ["manual edit changes multiple IDs"],
        "accepted": True,
        "use_for_span_prompt": False,
        "use_for_eval": True,
    }
    write_jsonl(paths["span_translation_examples"], [record])

    gold = build_gold_sets(dataset_dir)
    assert gold["span_gold_count"] == 1
    report = eval_span_style(dataset_dir)
    assert report["sample_count"] == 1
    assert report["metrics"]["fragment_completion_rate"] == 1.0

    record["use_for_span_prompt"] = True
    write_jsonl(paths["span_translation_examples"], [record])
    result = validate_dataset(dataset_dir)
    assert result["ok"] is False
    assert any("use_for_eval and use_for_span_prompt" in error for error in result["errors"])


def test_validate_rejects_eval_learning_overlap(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    project = tmp_path / "project"
    write_project_report(project)
    collect_bilibili_project(project, dataset_dir)

    paths = dataset_paths(dataset_dir)
    records = read_jsonl(paths["bilibili_labels"])
    records[0]["label"] = "duplicate"
    records[0]["use_for_eval"] = True
    records[0]["use_for_learning"] = True
    write_jsonl(paths["bilibili_labels"], records)

    result = validate_dataset(dataset_dir)
    assert result["ok"] is False
    assert any("must stay separate" in error for error in result["errors"])


def test_save_bilibili_feedback_label_upserts_existing_candidate(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    project = tmp_path / "project"
    write_project_report(project)
    collect_bilibili_project(project, dataset_dir)

    report = json.loads((project / "00b_bilibili_duplicate_search.json").read_text(encoding="utf-8"))
    candidate = report["candidates"][0]
    first = save_bilibili_feedback_label(
        report=report,
        candidate=candidate,
        label="same_topic",
        human_note="related but not repost",
        dataset_dir=dataset_dir,
    )
    second = save_bilibili_feedback_label(
        report=report,
        candidate=candidate,
        label="not_duplicate",
        human_note="confirmed different video",
        dataset_dir=dataset_dir,
    )

    paths = dataset_paths(dataset_dir)
    records = read_jsonl(paths["bilibili_labels"])
    assert first["updated"] is True
    assert second["updated"] is True
    assert len(records) == 1
    assert records[0]["label"] == "not_duplicate"
    assert records[0]["human_note"] == "confirmed different video"
