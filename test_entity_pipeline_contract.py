from __future__ import annotations

from pathlib import Path


def build_expected_entity_outputs(*, include_project_decisions: bool) -> list[str]:
    items = [
        "06e_entity_decisions.json",
        "06f_entity_review.tsv",
        "06g_entity_normalized_segments.json",
        "08b_ass_entity_audit.json",
    ]
    if include_project_decisions:
        items.append("00_entity_decisions.json")
    return items


def test_expected_entity_outputs_without_project_decisions() -> None:
    outputs = build_expected_entity_outputs(include_project_decisions=False)

    assert "06e_entity_decisions.json" in outputs
    assert "06f_entity_review.tsv" in outputs
    assert "06g_entity_normalized_segments.json" in outputs
    assert "08b_ass_entity_audit.json" in outputs
    assert "00_entity_decisions.json" not in outputs


def test_expected_entity_outputs_with_project_decisions() -> None:
    outputs = build_expected_entity_outputs(include_project_decisions=True)

    assert "00_entity_decisions.json" in outputs


def test_pipeline_core_manifest_contract_includes_entity_outputs() -> None:
    pipeline_core_text = Path("D:/autosub_zh/pipeline_core.py").read_text(encoding="utf-8")

    for expected_name in (
        "06e_entity_decisions.json",
        "06f_entity_review.tsv",
        "06g_entity_normalized_segments.json",
        "08b_ass_entity_audit.json",
        "00_entity_decisions.json",
    ):
        assert expected_name in pipeline_core_text
