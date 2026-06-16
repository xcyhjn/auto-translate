from __future__ import annotations

from autosub_zh.models import Segment
from autosub_zh.terminology import apply_terminology_short_circuit


def test_auto_preserve_person_name_is_not_locked(tmp_path) -> None:
    glossary_path = tmp_path / "glossary.json"
    glossary_path.write_text(
        """
{
  "terms": [
    {
      "canonical": "Juan Kokom",
      "zh": "Juan Kokom",
      "policy": "preserve",
      "sources": ["asr_count:3"]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    segments = [Segment(id=1, start=0, end=1, source_text="Juan Kokom.")]

    locked_ids, report = apply_terminology_short_circuit(segments, glossary_path)

    assert locked_ids == set()
    assert report["summary"]["locked_segment_count"] == 0
    assert not segments[0].target_text


def test_code_like_preserve_term_can_be_locked(tmp_path) -> None:
    glossary_path = tmp_path / "glossary.json"
    glossary_path.write_text(
        """
{
  "terms": [
    {
      "canonical": "Node.js",
      "zh": "Node.js",
      "policy": "preserve",
      "priority": "hard",
      "sources": ["project_decision"]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )
    segments = [Segment(id=1, start=0, end=1, source_text="Node.js.")]

    locked_ids, report = apply_terminology_short_circuit(segments, glossary_path)

    assert locked_ids == {1}
    assert report["summary"]["locked_segment_count"] == 1
    assert segments[0].target_text == "Node.js"
