from __future__ import annotations

from autosub_zh.qa_outputs import build_entity_qa_rows


def test_build_entity_qa_rows_combines_ass_audit_and_quality_metric_samples() -> None:
    ass_entity_audit = {
        "issues": [
            {
                "issue_type": "non_canonical_reference_name",
                "layer": 1,
                "style": "EnglishSmall",
                "start": 1.0,
                "end": 2.0,
                "text": "Richard Sharp Shaver",
                "canonical_en": "Richard Sharpe Shaver",
                "canonical_native": "",
                "line_text": "Richard Sharp Shaver comes to mind.",
            }
        ]
    }
    quality_metrics = {
        "translation": {
            "entity_residue_samples": [
                {
                    "segment_id": 1,
                    "leaks": ["Richard Sharp Shaver"],
                    "target_text": "比如 Richard Sharp Shaver 就是一个。",
                }
            ]
        }
    }

    rows = build_entity_qa_rows(ass_entity_audit, quality_metrics)

    assert len(rows) == 2
    assert rows[0]["issue_type"] == "non_canonical_reference_name"
    assert rows[0]["entity_type"] == ""
    assert rows[1]["segment_id"] == 1
    assert rows[1]["entity_type"] == "unknown"
    assert rows[1]["issue_type"] == "entity_residue_in_target"
