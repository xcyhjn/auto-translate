from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from autosub_zh import ui_server


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
