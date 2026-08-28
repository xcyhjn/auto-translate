from __future__ import annotations

import json
from pathlib import Path

import pytest

from autosub_zh.artifact_manifest import (
    atomic_write_json,
    build_artifact_manifest,
    compute_fingerprint,
    file_snapshot,
    fingerprint_matches,
    load_artifact_manifest,
)
from autosub_zh.pipeline_runner import write_effective_config


def test_manifest_round_trip_and_effective_config_metadata(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    manifest = build_artifact_manifest(source, config={"model": "small"}, prompt="translate")
    target = tmp_path / "manifest.json"

    atomic_write_json(target, manifest)

    loaded = load_artifact_manifest(target)
    assert loaded is not None
    assert loaded["fingerprint"] == manifest["fingerprint"]
    assert loaded["input"]["size"] == 4

    effective = write_effective_config(tmp_path / "output", {"model": "small"}, input_path=source)
    effective_payload = json.loads(effective.read_text(encoding="utf-8"))
    assert effective_payload["model"] == "small"
    assert effective_payload["_artifact_manifest"]["fingerprint"]


def test_fingerprint_changes_for_file_and_configuration_changes(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"one")
    first = compute_fingerprint(source, config={"beam_size": 5}, prompt="A")
    assert fingerprint_matches(first, compute_fingerprint(source, config={"beam_size": 5}, prompt="A"))

    source.write_bytes(b"two-two")
    changed_file = compute_fingerprint(source, config={"beam_size": 5}, prompt="A")
    changed_config = compute_fingerprint(source, config={"beam_size": 6}, prompt="A")
    assert changed_file != first
    assert changed_config != changed_file
    assert file_snapshot(source)["mtime_ns"] is not None


def test_corrupt_or_incomplete_manifest_is_invalid(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    target.write_text("{broken", encoding="utf-8")
    assert load_artifact_manifest(target) is None

    target.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    assert load_artifact_manifest(target) is None

    target.write_text(json.dumps({"schema_version": 2, "fingerprint": "a" * 64}), encoding="utf-8")
    assert load_artifact_manifest(target) is None


def test_atomic_write_cleans_temp_file_on_replace_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "manifest.json"

    def fail_replace(source: str | Path, destination: str | Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("autosub_zh.artifact_manifest.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        atomic_write_json(target, {"ok": True})

    assert not target.exists()
    assert list(tmp_path.glob(".manifest.json.*.tmp")) == []
