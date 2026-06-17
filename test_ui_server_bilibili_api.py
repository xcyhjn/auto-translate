from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from autosub_zh import ui_server
from autosub_zh.workflow_profiles import project_artifact_path


def _get_json(server: ThreadingHTTPServer, path: str) -> tuple[int, dict]:
    conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        data = response.read()
        return response.status, json.loads(data.decode("utf-8"))
    finally:
        conn.close()


def _post_json(server: ThreadingHTTPServer, path: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    try:
        conn.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        response = conn.getresponse()
        data = response.read()
        return response.status, json.loads(data.decode("utf-8"))
    finally:
        conn.close()


def _serve_once(monkeypatch):
    monkeypatch.setattr(ui_server, "reconcile_runtime_state", lambda: None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.UIServerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_bilibili_duplicate_api_returns_stable_schema(monkeypatch) -> None:
    def fake_job(url: str, config: dict, youtube_meta: dict | None = None) -> dict:
        return {
            "input_youtube_url": url,
            "output_dir": "D:/autosub_zh/output/sample",
            "report_path": "D:/autosub_zh/output/sample/00b_bilibili_duplicate_search.json",
            "candidates_tsv_path": "D:/autosub_zh/output/sample/00b_bilibili_duplicate_candidates.tsv",
            "queries_path": "D:/autosub_zh/output/sample/00b_bilibili_search_queries.json",
            "report": {
                "input_youtube_url": url,
                "youtube_meta": youtube_meta or {},
                "query_plan": [],
                "queries": [],
                "candidates": [],
                "scoring_summary": {"candidate_count": 0, "top_score": 0},
                "best_candidate": None,
                "decision": "no_candidates_manual_review",
                "errors": [],
                "proxy_info": {"proxy_url": "", "mode": "direct"},
                "created_at": "2026-06-17T00:00:00+00:00",
            },
        }

    monkeypatch.setattr(ui_server, "bilibili_duplicate_search_job", fake_job)
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _post_json(
            server,
            "/api/bilibili-duplicate-search",
            {
                "url": "https://www.youtube.com/watch?v=abc123XYZ09",
                "config": {"proxy_url": ""},
                "youtube_meta": {"title": "The Russian book about a dying god"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert payload["ok"] is True
    assert payload["workflow_policy"]["blocks_translation"] is False
    assert payload["workflow_policy"]["workflow_decoupled"] is True
    assert payload["report"]["decision"] == "no_candidates_manual_review"
    assert payload["report_path"].endswith("00b_bilibili_duplicate_search.json")
    assert payload["candidates_tsv_path"].endswith("00b_bilibili_duplicate_candidates.tsv")


def test_bilibili_duplicate_api_rejects_invalid_proxy(monkeypatch) -> None:
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _post_json(
            server,
            "/api/bilibili-duplicate-search",
            {
                "url": "https://www.youtube.com/watch?v=abc123XYZ09",
                "config": {"proxy_url": "https://www.youtube.com/watch?v=VWPkTdC488o"},
                "youtube_meta": {"title": "The Russian book about a dying god"},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 400
    assert payload["ok"] is False
    assert payload["workflow_policy"]["blocks_translation"] is False
    assert payload["operation"] == "bilibili_duplicate_search_proxy_validation"
    assert payload["mode"] == "proxy"
    assert "not a proxy endpoint" in payload["error"]


def test_bilibili_duplicate_feedback_api_saves_label(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_feedback_job(payload: dict) -> dict:
        calls.append(payload)
        return {
            "path": "D:/autosub_zh/datasets/local_feedback/bilibili_duplicate_labels.jsonl",
            "updated": False,
            "added": True,
            "label": payload["label"],
        }

    monkeypatch.setattr(ui_server, "bilibili_duplicate_feedback_job", fake_feedback_job)
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _post_json(
            server,
            "/api/bilibili-duplicate-feedback",
            {
                "report": {"youtube_meta": {"title": "The Russian book about a dying god"}, "query_plan": []},
                "candidate": {"title": "垂死的神", "url": "https://www.bilibili.com/video/BV1mock411c7mD"},
                "label": "duplicate",
                "human_note": "confirmed",
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert payload["ok"] is True
    assert payload["label"] == "duplicate"
    assert calls[0]["human_note"] == "confirmed"


def test_collect_style_feedback_api_returns_summary(monkeypatch) -> None:
    def fake_collect(project_path: str) -> dict:
        return {
            "project": project_path,
            "added": 2,
            "skipped_existing": 1,
            "path": "D:/autosub_zh/datasets/local_feedback/translation_edit_examples.jsonl",
            "learning_source": "manual_ass",
            "baseline_role": "05_translated_segments.json is used only as the machine baseline for ASS diff alignment.",
        }

    monkeypatch.setattr(ui_server, "collect_style_feedback_job", fake_collect)
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _post_json(
            server,
            "/api/collect-style-feedback",
            {"project_path": "D:/autosub_zh/output/sample"},
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert payload["ok"] is True
    assert payload["added"] == 2
    assert payload["path"].endswith("translation_edit_examples.jsonl")
    assert payload["learning_source"] == "manual_ass"
    assert "baseline" in payload["baseline_role"]


def test_collect_span_feedback_api_returns_summary(monkeypatch) -> None:
    def fake_collect(project_path: str) -> dict:
        return {
            "project": project_path,
            "added": 3,
            "skipped_existing": 1,
            "added_span_record_count": 4,
            "path": "D:/autosub_zh/datasets/local_feedback/span_translation_examples.jsonl",
            "learning_source": "manual_ass",
            "baseline_role": "05a/05 translated segments are used only as the machine baseline for span diff alignment.",
        }

    monkeypatch.setattr(ui_server, "collect_span_feedback_job", fake_collect)
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _post_json(
            server,
            "/api/collect-span-feedback",
            {"project_path": "D:/autosub_zh/output/sample"},
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert payload["ok"] is True
    assert payload["added"] == 3
    assert payload["added_span_record_count"] == 4
    assert payload["path"].endswith("span_translation_examples.jsonl")
    assert payload["learning_source"] == "manual_ass"
    assert "baseline" in payload["baseline_role"]


def test_read_output_tree_prefers_top_ass_artifact(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    project = output_root / "sample"
    project.mkdir(parents=True)
    legacy = project / "08_bilingual_zh_en.ass"
    top = project / "00_ASS_bilingual_zh_en.ass"
    legacy.write_text("legacy", encoding="utf-8")
    top.write_text("top", encoding="utf-8")
    (project / "10_manifest_bilingual.json").write_text(
        json.dumps({"subtitle_output": {"ass_name": legacy.name}, "input_video": "D:/videos/sample.mp4"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "OUTPUT_DIR", output_root)

    projects = ui_server.read_output_tree()

    assert projects[0]["ass_path"].endswith("00_ASS_bilingual_zh_en.ass")


def test_read_output_tree_creates_top_ass_alias_for_legacy_project(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    project = output_root / "sample"
    project.mkdir(parents=True)
    legacy = project / "08_bilingual_zh_en.ass"
    legacy.write_text("legacy", encoding="utf-8")
    (project / "10_manifest_bilingual.json").write_text(
        json.dumps({"subtitle_output": {"ass_name": legacy.name}, "input_video": "D:/videos/sample.mp4"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "OUTPUT_DIR", output_root)

    projects = ui_server.read_output_tree()

    top = project / "00_ASS_bilingual_zh_en.ass"
    assert top.exists()
    assert top.read_text(encoding="utf-8") == "legacy"
    assert projects[0]["ass_path"].endswith(top.name)


def test_read_output_tree_returns_release_artifacts_and_health(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    project = output_root / "sample"
    project.mkdir(parents=True)
    (project / "00_youtube_info.txt").write_text("description", encoding="utf-8")
    (project / "00_youtube_cover.jpg").write_bytes(b"cover")
    (project / "00_youtube_cover_1280x960.jpg").write_bytes(b"cover-large")
    (project / "00_ASS_bilingual_zh_en.ass").write_text("[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Hi", encoding="utf-8")
    (project / "09_burned_bilingual_video.mp4").write_bytes(b"video")
    (project / "10_manifest_bilingual.json").write_text(
        json.dumps(
            {
                "subtitle_output": {"ass_name": "00_ASS_bilingual_zh_en.ass"},
                "burn_plan": {"output_path": str(project / "09_burned_bilingual_video.mp4")},
                "input_video": "D:/videos/sample.mp4",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "OUTPUT_DIR", output_root)

    projects = ui_server.read_output_tree()

    release = {item["key"]: item for item in projects[0]["release_artifacts"]}
    assert all(item["present"] for item in release.values())
    assert release["description"]["name"] == "00_youtube_info.txt"
    assert release["cover"]["name"] == "00_youtube_cover.jpg"
    assert release["cover_1280x960"]["name"] == "00_youtube_cover_1280x960.jpg"
    assert release["ass"]["name"] == "00_ASS_bilingual_zh_en.ass"
    assert release["burned_video"]["name"] == "09_burned_bilingual_video.mp4"
    assert projects[0]["health"]["score"] == 100
    assert projects[0]["health"]["ready"] is True


def test_organize_project_artifacts_moves_non_release_files(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    project = output_root / "sample"
    project.mkdir(parents=True)
    essentials = [
        "00_youtube_info.txt",
        "00_youtube_cover.jpg",
        "00_youtube_cover_1280x960.jpg",
        "00_ASS_bilingual_zh_en.ass",
        "09_burned_bilingual_video.mp4",
    ]
    for name in essentials:
        (project / name).write_text("essential", encoding="utf-8")
    (project / "05_translated_segments.json").write_text("[]", encoding="utf-8")
    (project / "00_style_examples.jsonl").write_text("{}\n", encoding="utf-8")
    (project / "10_manifest_bilingual.json").write_text(
        json.dumps(
            {
                "subtitle_output": {"ass_name": "00_ASS_bilingual_zh_en.ass"},
                "burn_plan": {"output_path": str(project / "09_burned_bilingual_video.mp4")},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "OUTPUT_DIR", output_root)

    result = ui_server.organize_project_artifacts_job(str(project))

    internal = project / ui_server.INTERNAL_ARTIFACTS_DIR_NAME
    assert result["moved_count"] == 3
    assert (internal / "05_translated_segments.json").exists()
    assert (internal / "00_style_examples.jsonl").exists()
    assert (internal / "10_manifest_bilingual.json").exists()
    for name in essentials:
        assert (project / name).exists()
    refreshed = result["project"]
    assert refreshed["manifest_path"].endswith("10_manifest_bilingual.json")
    assert refreshed["health"]["internal_file_count"] == 3
    assert any(file["name"] == "05_translated_segments.json" for file in refreshed["internal_files"])
    assert any(file["name"] == "00_style_examples.jsonl" for file in refreshed["internal_files"])


def test_organize_project_artifacts_preview_does_not_move_files(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    project = output_root / "sample"
    project.mkdir(parents=True)
    for name in [
        "00_youtube_info.txt",
        "00_youtube_cover.jpg",
        "00_youtube_cover_1280x960.jpg",
        "00_ASS_bilingual_zh_en.ass",
        "09_burned_bilingual_video.mp4",
    ]:
        (project / name).write_text("essential", encoding="utf-8")
    internal_candidate = project / "05_translated_segments.json"
    internal_candidate.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(ui_server, "OUTPUT_DIR", output_root)

    result = ui_server.organize_project_artifacts_job(str(project), preview_only=True)

    assert result["preview_only"] is True
    assert result["move_count"] == 1
    assert result["moved_count"] == 0
    assert internal_candidate.exists()
    assert not (project / ui_server.INTERNAL_ARTIFACTS_DIR_NAME).exists()
    assert result["planned"][0]["from"].endswith("05_translated_segments.json")


def test_organize_project_artifacts_rejects_running_pipeline(monkeypatch, tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    project = output_root / "sample"
    project.mkdir(parents=True)
    monkeypatch.setattr(ui_server, "OUTPUT_DIR", output_root)
    monkeypatch.setattr(ui_server, "is_busy", lambda: True)

    try:
        ui_server.organize_project_artifacts_job(str(project))
    except RuntimeError as exc:
        assert "pipeline task is running" in str(exc)
    else:
        raise AssertionError("organize_project_artifacts_job should reject a running pipeline")


def test_project_artifact_path_prefers_root_and_falls_back_to_internal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    internal = project / ui_server.INTERNAL_ARTIFACTS_DIR_NAME
    internal.mkdir(parents=True)
    internal_file = internal / "05_translated_segments.json"
    internal_file.write_text("internal", encoding="utf-8")

    assert project_artifact_path(project, "05_translated_segments.json") == internal_file

    root_file = project / "05_translated_segments.json"
    root_file.write_text("root", encoding="utf-8")

    assert project_artifact_path(project, "05_translated_segments.json") == root_file


def test_local_feedback_summary_api_reads_counts_and_eval(monkeypatch, tmp_path: Path) -> None:
    dataset = tmp_path / "local_feedback"
    (dataset / "eval_sets").mkdir(parents=True)
    (dataset / "eval_reports").mkdir(parents=True)
    (dataset / "translation_edit_examples.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"accepted": True, "use_for_style_prompt": True, "use_for_eval": False}),
                json.dumps({"accepted": True, "use_for_style_prompt": False, "use_for_eval": True}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (dataset / "eval_sets" / "translation_style_gold.jsonl").write_text(
        json.dumps({"accepted": True, "use_for_eval": True}) + "\n",
        encoding="utf-8",
    )
    (dataset / "span_translation_examples.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"accepted": True, "use_for_span_prompt": True, "use_for_eval": False}),
                json.dumps({"accepted": True, "use_for_span_prompt": False, "use_for_eval": True}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (dataset / "eval_sets" / "span_translation_gold.jsonl").write_text(
        json.dumps({"accepted": True, "use_for_eval": True}) + "\n",
        encoding="utf-8",
    )
    (dataset / "eval_reports" / "latest_style_eval.json").write_text(
        json.dumps(
            {
                "sample_count": 1,
                "sample_insufficient": False,
                "metrics": {"unsafe_sample_rate": 0.0, "semantic_or_style_signal_rate": 1.0},
                "created_at": "2026-06-17T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (dataset / "eval_reports" / "latest_span_translation_eval.json").write_text(
        json.dumps(
            {
                "sample_count": 1,
                "sample_insufficient": False,
                "metrics": {
                    "unsafe_sample_rate": 0.0,
                    "semantic_reallocation_rate": 1.0,
                    "fragment_completion_rate": 1.0,
                },
                "created_at": "2026-06-17T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (dataset / "learned_style_guidelines.md").write_text(
        "# Learned\n\n- Keep names in English.\n- Prefer natural subtitle wording.\n",
        encoding="utf-8",
    )
    (dataset / "learned_span_guidelines.md").write_text(
        "# Learned Span\n\n- Redistribute the full idea across IDs.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "LOCAL_FEEDBACK_DATASET_DIR", dataset)
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _get_json(server, "/api/local-feedback-summary")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert payload["ok"] is True
    assert payload["counts"]["translation_edit_count"] == 2
    assert payload["counts"]["style_learning_count"] == 1
    assert payload["counts"]["style_gold_count"] == 1
    assert payload["counts"]["span_translation_example_count"] == 2
    assert payload["counts"]["span_style_learning_count"] == 1
    assert payload["counts"]["span_eval_count"] == 1
    assert payload["eval"]["sample_count"] == 1
    assert payload["eval"]["metrics"]["semantic_or_style_signal_rate"] == 1.0
    assert payload["span_eval"]["metrics"]["fragment_completion_rate"] == 1.0
    assert payload["guidelines"] == ["Keep names in English.", "Prefer natural subtitle wording."]
    assert payload["span_guidelines"] == ["Redistribute the full idea across IDs."]


def test_local_feedback_summary_api_handles_missing_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ui_server, "LOCAL_FEEDBACK_DATASET_DIR", tmp_path / "missing_feedback")
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _get_json(server, "/api/local-feedback-summary")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert payload["ok"] is True
    assert payload["counts"]["translation_edit_count"] == 0
    assert payload["counts"]["style_learning_count"] == 0
    assert payload["counts"]["style_gold_count"] == 0
    assert payload["counts"]["span_translation_example_count"] == 0
    assert payload["counts"]["span_style_learning_count"] == 0
    assert payload["counts"]["span_eval_count"] == 0
    assert payload["available"]["latest_style_eval"] is False
    assert payload["available"]["latest_span_eval"] is False


def test_feedback_review_api_lists_and_updates_style_record(monkeypatch, tmp_path: Path) -> None:
    dataset = tmp_path / "local_feedback"
    dataset.mkdir(parents=True)
    record = {
        "schema_version": 1,
        "created_at": "2026-06-17T00:00:00+00:00",
        "project_id": "sample-project",
        "segment_id": 7,
        "start": 1.0,
        "end": 3.0,
        "source_text": "This is a literal line.",
        "machine_target_text": "这是一句直译的台词。",
        "manual_target_text": "这句更像人话。",
        "edit_tags": ["style_edit"],
        "features": {},
        "operation_summary": {},
        "quality_flags": ["needs_human_acceptance"],
        "feedback_types": ["style_edit"],
        "learning_risk": "low",
        "learning_recommendation": "style_prompt_candidate",
        "classification_reasons": ["manual edit improves subtitle style"],
        "accepted": False,
        "use_for_style_prompt": False,
        "use_for_eval": False,
    }
    (dataset / "translation_edit_examples.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "LOCAL_FEEDBACK_DATASET_DIR", dataset)
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _get_json(server, "/api/local-feedback-records?kind=style&status=pending")
        assert status == 200
        assert payload["ok"] is True
        assert payload["filtered_count"] == 1
        record_id = payload["records"][0]["record_id"]

        update_status, update_payload = _post_json(
            server,
            "/api/local-feedback-record-update",
            {
                "kind": "style",
                "record_id": record_id,
                "updates": {"use_for_style_prompt": True, "use_for_eval": True},
            },
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert update_status == 200
    assert update_payload["ok"] is True
    updated = update_payload["record"]
    assert updated["accepted"] is True
    assert updated["use_for_prompt"] is True
    assert updated["use_for_eval"] is False
    saved = json.loads((dataset / "translation_edit_examples.jsonl").read_text(encoding="utf-8"))
    assert saved["accepted"] is True
    assert saved["use_for_style_prompt"] is True
    assert saved["use_for_eval"] is False


def test_local_feedback_summary_api_tolerates_invalid_eval_report(monkeypatch, tmp_path: Path) -> None:
    dataset = tmp_path / "local_feedback"
    (dataset / "eval_reports").mkdir(parents=True)
    (dataset / "eval_reports" / "latest_style_eval.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(ui_server, "LOCAL_FEEDBACK_DATASET_DIR", dataset)
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _get_json(server, "/api/local-feedback-summary")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert payload["ok"] is True
    assert payload["eval"]["sample_count"] == 0
    assert payload["eval"]["metrics"] == {}


def _style_feedback_record(index: int, *, accepted: bool = True, prompt: bool = True, eval_sample: bool = False, risk: str = "low") -> dict:
    return {
        "schema_version": 1,
        "created_at": "2026-06-17T00:00:00+00:00",
        "project_id": "quality-project",
        "segment_id": index,
        "start": float(index),
        "end": float(index + 1),
        "source_text": f"Source {index}",
        "machine_target_text": f"机器译文 {index}",
        "manual_target_text": f"人工译文 {index}",
        "edit_tags": ["style_edit"],
        "features": {},
        "operation_summary": {"strategies": ["naturalize"]},
        "quality_flags": [],
        "feedback_types": ["style_edit"],
        "learning_risk": risk,
        "learning_recommendation": "style_prompt_candidate",
        "classification_reasons": ["style signal"],
        "accepted": accepted,
        "use_for_style_prompt": prompt,
        "use_for_eval": eval_sample,
    }


def _span_feedback_record(index: int, *, accepted: bool = True, prompt: bool = True, eval_sample: bool = False, risk: str = "low") -> dict:
    return {
        "schema_version": 1,
        "created_at": "2026-06-17T00:00:00+00:00",
        "project_id": "quality-project",
        "span_id": f"span-{index}",
        "segment_ids": [index, index + 1],
        "source_joined": f"Span source {index}",
        "risk_reasons": {"open_clause": 1},
        "translation_strategy": "span_first",
        "context_before": [],
        "context_after": [],
        "machine_target_by_id": {str(index): "机器"},
        "manual_target_by_id": {str(index): "人工"},
        "edit_tags": ["semantic_reallocation"],
        "learning_risk": risk,
        "learning_recommendation": "span_prompt_candidate",
        "classification_reasons": ["span signal"],
        "accepted": accepted,
        "use_for_span_prompt": prompt,
        "use_for_eval": eval_sample,
    }


def test_learning_quality_summary_returns_diagnostics_and_history(monkeypatch, tmp_path: Path) -> None:
    dataset = tmp_path / "local_feedback"
    (dataset / "eval_sets").mkdir(parents=True)
    (dataset / "eval_reports").mkdir(parents=True)
    style_records = [_style_feedback_record(index) for index in range(100)]
    style_records.extend(_style_feedback_record(100 + index, prompt=False, eval_sample=True) for index in range(30))
    span_records = [_span_feedback_record(index, accepted=False, prompt=False) for index in range(2)]
    (dataset / "translation_edit_examples.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in style_records) + "\n",
        encoding="utf-8",
    )
    (dataset / "span_translation_examples.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in span_records) + "\n",
        encoding="utf-8",
    )
    (dataset / "eval_sets" / "translation_style_gold.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in style_records[-30:]) + "\n",
        encoding="utf-8",
    )
    (dataset / "eval_reports" / "latest_style_eval.json").write_text(
        json.dumps(
            {
                "sample_count": 30,
                "sample_insufficient": False,
                "metrics": {"unsafe_sample_rate": 0.0, "semantic_or_style_signal_rate": 1.0},
                "created_at": "2026-06-17T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (dataset / "eval_reports" / "latest_span_translation_eval.json").write_text(
        json.dumps(
            {
                "sample_count": 0,
                "sample_insufficient": True,
                "metrics": {"unsafe_sample_rate": 0.0, "semantic_reallocation_rate": 0.0, "fragment_completion_rate": 0.0},
                "created_at": "2026-06-17T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (dataset / "eval_reports" / "learning_quality_snapshots.jsonl").write_text(
        json.dumps({"created_at": "2026-06-17T00:00:00+00:00", "score": 55, "style_prompt_count": 100}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "LOCAL_FEEDBACK_DATASET_DIR", dataset)
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _get_json(server, "/api/learning-quality-summary")
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert payload["ok"] is True
    assert payload["quality"]["overall_status"] == "eval_insufficient"
    assert payload["quality"]["score"] >= 55
    assert payload["coverage"]["style_prompt_ratio"] > 0
    assert payload["coverage"]["span_prompt_ratio"] == 0
    assert payload["risk"]["style_high_risk_count"] == 0
    assert payload["distributions"]["style_recommendation"]
    assert payload["recommendations"]["span"]
    assert payload["history"][0]["score"] == 55


def test_learning_quality_summary_prioritizes_unsafe(monkeypatch, tmp_path: Path) -> None:
    dataset = tmp_path / "local_feedback"
    (dataset / "eval_reports").mkdir(parents=True)
    record = _style_feedback_record(1, risk="high")
    record["edit_tags"] = ["bad_example"]
    (dataset / "translation_edit_examples.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    (dataset / "eval_reports" / "latest_style_eval.json").write_text(
        json.dumps({"sample_count": 1, "sample_insufficient": True, "metrics": {"unsafe_sample_rate": 0.2}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ui_server, "LOCAL_FEEDBACK_DATASET_DIR", dataset)

    payload = ui_server.build_learning_quality_summary()

    assert payload["quality"]["overall_status"] == "unsafe"
    assert payload["risk"]["bad_example_count"] == 1
    assert payload["risk"]["style_high_risk_count"] == 1


def test_local_feedback_action_runs_and_writes_snapshot(monkeypatch, tmp_path: Path) -> None:
    dataset = tmp_path / "local_feedback"
    (dataset / "eval_sets").mkdir(parents=True)
    style_record = _style_feedback_record(1, prompt=False, eval_sample=True)
    (dataset / "translation_edit_examples.jsonl").write_text(json.dumps(style_record, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(ui_server, "LOCAL_FEEDBACK_DATASET_DIR", dataset)
    server, thread = _serve_once(monkeypatch)
    try:
        status, payload = _post_json(server, "/api/local-feedback-action", {"action": "build_gold"})
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert status == 200
    assert payload["ok"] is True
    assert payload["action"] == "build_gold"
    assert payload["summary"]["history"]
    snapshot_path = dataset / "eval_reports" / "learning_quality_snapshots.jsonl"
    assert snapshot_path.exists()
