from __future__ import annotations

import json
from pathlib import Path

from autosub_zh.models import MediaInfo, Segment
from autosub_zh.pipeline_core import run_pipeline
from autosub_zh.segment_io import save_segments_payload


def test_run_pipeline_writes_entity_outputs_from_existing_segments(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "sample.mp4"
    input_path.write_bytes(b"fake")
    output_root = tmp_path / "out"
    project_dir = output_root / "sample"
    project_dir.mkdir(parents=True)

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
            source_text="Richard Sharpe Shaver comes to mind.",
            target_text="比如 Richard Sharp Shaver 就是一个。",
        ),
    ]
    save_segments_payload(segments, project_dir / "05_translated_segments.json", input_file=str(input_path))

    def fake_probe_media(path):
        return MediaInfo(
            path=str(path),
            duration=4.0,
            has_audio=True,
            video_width=1920,
            video_height=1080,
            text_subtitle_streams=[],
            image_subtitle_streams=[],
        )

    monkeypatch.setattr("autosub_zh.pipeline_core.probe_media", fake_probe_media)
    monkeypatch.setattr("autosub_zh.pipeline_core.resolve_output_dir", lambda input_path, output_root: project_dir)

    manifest = run_pipeline(
        input_path=input_path,
        output_root=output_root,
        load_existing_segments=True,
        skip_burn=True,
        bootstrap_entity_decisions=True,
    )

    assert (project_dir / "06e_entity_decisions.json").exists()
    assert (project_dir / "06f_entity_review.tsv").exists()
    assert (project_dir / "06g_entity_normalized_segments.json").exists()
    assert (project_dir / "07h_entity_qa.tsv").exists()
    assert (project_dir / "08b_ass_entity_audit.json").exists()
    assert (project_dir / "00_entity_decisions.json").exists()

    entity_report = json.loads((project_dir / "06e_entity_decisions.json").read_text(encoding="utf-8"))
    assert entity_report["summary"]["segments_changed"] >= 1

    normalized_payload = json.loads((project_dir / "06g_entity_normalized_segments.json").read_text(encoding="utf-8"))
    normalized_segments = normalized_payload["segments"]
    assert normalized_segments[0]["reference_text"] == "Viktor Tausk wrote a paper."
    assert normalized_segments[0]["target_text"] == "维克托·陶斯克 写过一篇论文。"

    review_tsv = (project_dir / "06f_entity_review.tsv").read_text(encoding="utf-8-sig")
    assert "Richard Sharp Shaver" not in review_tsv

    entity_qa_tsv = (project_dir / "07h_entity_qa.tsv").read_text(encoding="utf-8-sig")
    assert "non_canonical_reference_name" in entity_qa_tsv or "entity_residue_in_target" in entity_qa_tsv

    assert "06e_entity_decisions.json" in manifest["files"]
    assert "06f_entity_review.tsv" in manifest["files"]
    assert "06g_entity_normalized_segments.json" in manifest["files"]
    assert "07h_entity_qa.tsv" in manifest["files"]
    assert "08b_ass_entity_audit.json" in manifest["files"]
    assert "00_entity_decisions.json" in manifest["files"]
