from __future__ import annotations

from pathlib import Path

from autosub_zh.evidence_sidecar import (
    build_evidence_record,
    read_evidence_sidecar,
    search_evidence,
    write_evidence_sidecar,
)
from autosub_zh.glossary import write_youtube_glossary
from autosub_zh.youtube_meta import YouTubeMeta


def evidence_record(**overrides):
    payload = {
        "source": "youtube_metadata",
        "title": "A video about Pixar",
        "url": "https://example.test/watch",
        "summary": "Pixar animation production notes",
        "fetched_at": "2026-08-28T00:00:00Z",
        "confidence": 0.7,
        "project_id": "project-a",
        "input_fingerprint": "fingerprint-a",
        "evidence_level": "advisory",
    }
    payload.update(overrides)
    return build_evidence_record(**payload)


def test_sidecar_round_trip_and_keyword_search(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    write_evidence_sidecar(
        path,
        [evidence_record()],
        project_id="project-a",
        input_fingerprint="fingerprint-a",
    )
    payload = read_evidence_sidecar(
        path,
        project_id="project-a",
        input_fingerprint="fingerprint-a",
    )
    assert payload is not None
    assert payload["records"][0]["evidence_level"] == "advisory"
    assert search_evidence(payload, ["pixar", "animation"])[0]["source"] == "youtube_metadata"


def test_cross_project_record_is_filtered(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    write_evidence_sidecar(
        path,
        [evidence_record(project_id="project-b")],
        project_id="project-a",
        input_fingerprint="fingerprint-a",
    )
    payload = read_evidence_sidecar(path, project_id="project-a", input_fingerprint="fingerprint-a")
    assert payload is not None
    assert payload["records"] == []


def test_invalid_record_and_scope_mismatch_are_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_text('{"schema_version":1,"project_id":"project-a","input_fingerprint":"fingerprint-a","records":[{"url":"not-a-url"}]}', encoding="utf-8")
    payload = read_evidence_sidecar(path, project_id="project-a", input_fingerprint="fingerprint-a")
    assert payload is not None
    assert payload["records"] == []
    assert read_evidence_sidecar(path, project_id="project-b") is None


def test_empty_query_returns_no_results() -> None:
    assert search_evidence([evidence_record()], "") == []


def test_glossary_keeps_evidence_sidecar_opt_in(tmp_path: Path) -> None:
    meta = YouTubeMeta(
        video_id="video-1",
        video_url="https://example.test/watch",
        author="Creator",
        published_at="2026-08-28",
        title="Pixar production notes",
        description="An animation production discussion.",
        cover_url="",
        cover_path=None,
    )
    write_youtube_glossary(tmp_path, meta)
    assert not (tmp_path / "evidence.json").exists()

    write_youtube_glossary(
        tmp_path,
        meta,
        evidence_sidecar_path=tmp_path / "evidence.json",
        project_id="project-a",
        input_fingerprint="fingerprint-a",
        evidence_fetched_at="2026-08-28T00:00:00Z",
    )
    payload = read_evidence_sidecar(
        tmp_path / "evidence.json",
        project_id="project-a",
        input_fingerprint="fingerprint-a",
    )
    assert payload is not None
    assert payload["records"][0]["source"] == "youtube_metadata"
