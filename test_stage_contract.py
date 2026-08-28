from __future__ import annotations

import pytest

from autosub_zh.stage_contract import StageEvent, StageResult


def test_stage_result_round_trip_has_stable_fields() -> None:
    result = StageResult(
        stage="translation",
        status="success",
        outputs={"path": "translated.json"},
        warnings=["used fallback"],
        metadata={"count": 2},
    )

    restored = StageResult.from_dict(result.to_dict())

    assert restored.to_dict() == result.to_dict()
    assert list(result.to_dict()) == [
        "schema_version",
        "stage",
        "status",
        "outputs",
        "warnings",
        "error",
        "metadata",
    ]


def test_stage_result_rejects_missing_or_unknown_status() -> None:
    with pytest.raises(ValueError):
        StageResult.from_dict({"stage": "asr"})
    with pytest.raises(ValueError):
        StageResult(stage="asr", status="done")


def test_stage_event_serializes_payload() -> None:
    event = StageEvent(stage="asr", status="running", payload={"progress": 0.5})

    payload = event.to_dict()

    assert payload["stage"] == "asr"
    assert payload["status"] == "running"
    assert payload["payload"] == {"progress": 0.5}
    assert payload["timestamp"]
    assert StageEvent.from_dict(payload).to_dict() == payload


def test_stage_event_rejects_unknown_status() -> None:
    with pytest.raises(ValueError):
        StageEvent(stage="asr", status="done")
