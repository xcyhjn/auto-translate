from __future__ import annotations

from autosub_zh.workflow_profiles import (
    DEFAULT_WORKFLOW_PROFILE,
    apply_workflow_profile,
    list_workflow_profiles,
    summarize_dataset_profile,
    load_dataset_profile,
    load_prompt_profile,
    load_workflow_profile,
    write_dataset_profile_assets,
)


def test_load_russian_workflow_profile_defaults() -> None:
    profile = load_workflow_profile("ru_to_zh_default")

    assert profile.src_lang == "ru"
    assert profile.dst_lang == "zh-Hans"
    assert profile.model == "large-v3"
    assert profile.subtitle_mode == "target_only"
    assert profile.prompt_profile == "ru_zh_natural_subtitle"
    assert profile.dataset_profile == "ru_zh/general"


def test_apply_profile_replaces_base_defaults_but_preserves_user_override() -> None:
    defaults = {
        "workflow_profile": DEFAULT_WORKFLOW_PROFILE,
        "src_lang": "en",
        "dst_lang": "zh-Hans",
        "model": "distil-large-v3",
        "translation_chunk_size": 24,
        "translation_prompt": "",
    }

    config = apply_workflow_profile(
        {
            **defaults,
            "workflow_profile": "ru_to_zh_default",
            "translation_chunk_size": 12,
        },
        defaults,
    )

    assert config["src_lang"] == "ru"
    assert config["model"] == "large-v3"
    assert config["translation_chunk_size"] == 12
    assert "Russian-to-Simplified-Chinese" in config["translation_prompt"]


def test_prompt_and_dataset_resources_are_available() -> None:
    prompt = load_prompt_profile("ru_zh_natural_subtitle")
    dataset = load_dataset_profile("ru_zh/general")
    profiles = {item["id"] for item in list_workflow_profiles()}

    assert "Russian-specific rules" in prompt
    assert "XIU XIU" in dataset["glossary_text"]
    assert "ru_to_zh_default" in profiles


def test_dataset_profile_summary_and_asset_copy(tmp_path) -> None:
    summary = summarize_dataset_profile("ru_zh/general")
    copied = write_dataset_profile_assets("ru_zh/general", tmp_path)

    assert summary["glossary_term_count"] >= 1
    assert "glossary.json" in summary["file_names"]
    assert "asr_confusions.json" in copied
    assert (tmp_path / "00_profile_glossary.json").exists()
