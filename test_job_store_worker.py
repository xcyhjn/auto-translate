from __future__ import annotations

from pathlib import Path

from autosub_zh.job_store import JobStore
from autosub_zh import ui_server
from autosub_zh.worker_service import PipelineWorker


def test_job_store_creates_and_claims_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite")
    job = store.create_job(
        input_path="input.mp4",
        output_dir="output/project",
        workflow_profile="en_to_zh_default",
        config={"translation_chunk_size": 24},
    )

    assert job["status"] == "queued"
    assert job["config"]["translation_chunk_size"] == 24

    claimed = store.claim_next_job(worker_pid=1234)

    assert claimed is not None
    assert claimed["id"] == job["id"]
    assert claimed["status"] == "running"
    assert claimed["worker_pid"] == 1234


def test_job_store_pause_resume_cancel(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite")
    job = store.create_job(
        input_path="input.mp4",
        output_dir="output/project",
        workflow_profile="en_to_zh_default",
        config={},
    )

    store.pause_job(job["id"])
    paused = store.get_job(job["id"])
    assert paused is not None
    assert paused["status"] == "paused"

    store.resume_job(job["id"])
    resumed = store.get_job(job["id"])
    assert resumed is not None
    assert resumed["status"] == "queued"

    store.cancel_job(job["id"])
    cancelled = store.get_job(job["id"])
    assert cancelled is not None
    assert cancelled["status"] == "cancel_requested"


def test_worker_progress_for_translation_chunk() -> None:
    assert PipelineWorker.progress_for_stage(
        "translation_chunk_complete",
        {"chunk_index": 12, "chunk_total": 24},
    ) == 80


def test_job_events_are_ordered(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite")
    job = store.create_job(
        input_path="input.mp4",
        output_dir="output/project",
        workflow_profile="en_to_zh_default",
        config={},
    )
    store.add_event(job["id"], "translation_chunk_start", {"chunk_index": 1})
    store.add_event(job["id"], "translation_chunk_complete", {"chunk_index": 1})

    events = store.get_events(job["id"])

    assert [event["stage"] for event in events][-2:] == [
        "translation_chunk_start",
        "translation_chunk_complete",
    ]


def test_ui_bootstrap_maps_active_job_to_compatible_state(tmp_path: Path, monkeypatch) -> None:
    store = JobStore(tmp_path / "jobs.sqlite")
    monkeypatch.setattr(ui_server, "JOB_STORE", store)
    monkeypatch.setattr(ui_server, "resolve_input_video_path", lambda value: Path(value))

    job = ui_server.create_pipeline_job(
        "input.mp4",
        ui_server.normalize_config({"workflow_profile": "en_to_zh_default"}),
    )
    store.claim_next_job(worker_pid=1234)
    store.update_job(job["id"], status="running", current_stage="translation_chunk_complete", progress=80)
    store.add_event(job["id"], "translation_chunk_complete", {"chunk_index": 12, "chunk_total": 24})

    payload = ui_server.build_bootstrap_payload(include_collections=False)

    assert payload["active_job"]["id"] == job["id"]
    assert payload["state"]["runtime"]["job_id"] == job["id"]
    assert payload["state"]["runtime"]["stage_key"] == "translation_chunk_complete"
    assert payload["state"]["phase_status"]["translation"]["current"] == 12
