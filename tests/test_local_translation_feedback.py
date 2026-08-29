from __future__ import annotations

from pathlib import Path

from autosub_zh.pipeline_core import build_translation_style_prompt


def test_local_translation_feedback_style_prompt_is_opt_in(tmp_path: Path) -> None:
    project_style = tmp_path / "06d_style_rewrite_prompt.txt"
    local_style = tmp_path / "learned_style_guidelines.md"
    project_style.write_text("Project style guidance", encoding="utf-8")
    local_style.write_text("Local feedback guidance", encoding="utf-8")

    disabled = build_translation_style_prompt(
        translation_prompt="Base prompt",
        project_style_prompt_path=project_style,
        enable_local_translation_feedback=False,
        local_feedback_style_path=local_style,
    )
    enabled = build_translation_style_prompt(
        translation_prompt="Base prompt",
        project_style_prompt_path=project_style,
        enable_local_translation_feedback=True,
        local_feedback_style_path=local_style,
    )

    assert "Base prompt" in disabled
    assert "Project style guidance" in disabled
    assert "Local feedback guidance" not in disabled
    assert "Base prompt" in enabled
    assert "Project style guidance" in enabled
    assert "Local feedback guidance" in enabled
