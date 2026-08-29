from __future__ import annotations

import threading
import time

from autosub_zh import ui_server
from autosub_zh.ui_server import (
    build_bootstrap_payload,
    capture_flow_control_snapshot,
    normalize_config,
    request_pause,
    resume_flow,
)


def test_normalize_config_preserves_bootstrap_entity_decision_modes() -> None:
    for mode in ("off", "always", "high_confidence_only"):
        config = normalize_config({"bootstrap_entity_decisions": mode})

        assert config["bootstrap_entity_decisions"] == mode


def test_normalize_config_maps_legacy_bootstrap_booleans() -> None:
    assert normalize_config({"bootstrap_entity_decisions": True})["bootstrap_entity_decisions"] == "always"
    assert normalize_config({"bootstrap_entity_decisions": False})["bootstrap_entity_decisions"] == "off"


def test_normalize_config_uses_russian_reference_defaults() -> None:
    config = normalize_config({"workflow_profile": "ru_to_zh_default"})

    assert config["src_lang"] == "ru"
    assert config["model"] == "large-v3"
    assert config["prompt_profile"] == "ru_zh_natural_subtitle"
    assert config["dataset_profile"] == "ru_zh/general"
    assert config["style"]["en_font_name"] == "Huiwen-HKHei"
    assert config["style"]["en_font_size"] == 32
    assert config["style"]["en_max_single_line_chars"] == 80
    assert config["style"]["reference_mode"] == "full_split"


def test_normalize_config_preserves_russian_profile_style_with_partial_style() -> None:
    config = normalize_config({"workflow_profile": "ru_to_zh_default", "style": {}})

    assert config["style"]["en_font_name"] == "Huiwen-HKHei"
    assert config["style"]["en_font_size"] == 32
    assert config["style"]["en_max_single_line_chars"] == 80
    assert config["style"]["en_max_split_parts"] == 4
    assert config["style"]["min_split_duration"] == 1.2
    assert config["style"]["reference_mode"] == "full_split"


def test_flow_control_pause_resume_state_is_exposed() -> None:
    try:
        paused = request_pause("test_pause")

        assert paused["pause_requested"] is True
        assert paused["pause_reason"] == "test_pause"
        assert capture_flow_control_snapshot()["pause_requested"] is True
        assert build_bootstrap_payload(include_collections=False)["flow_control"]["pause_requested"] is True

        resumed = resume_flow()

        assert resumed["pause_requested"] is False
        assert build_bootstrap_payload(include_collections=False)["flow_control"]["pause_requested"] is False
    finally:
        resume_flow()


def test_wait_if_paused_blocks_until_resume(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(ui_server, "append_history", lambda stage, payload: events.append((stage, payload)))
    resume_flow()

    try:
        request_pause("unit_test")
        worker = threading.Thread(
            target=ui_server.wait_if_paused,
            args=("translation_chunk_start", {"chunk_index": 1}),
            daemon=True,
        )
        worker.start()

        deadline = time.time() + 2.0
        while time.time() < deadline and not capture_flow_control_snapshot()["paused"]:
            time.sleep(0.01)

        paused = capture_flow_control_snapshot()
        assert paused["paused"] is True
        assert paused["pause_stage"] == "translation_chunk_start"
        assert worker.is_alive()

        resume_flow()
        worker.join(timeout=2.0)

        assert not worker.is_alive()
        assert [event[0] for event in events] == ["flow_paused", "flow_resumed"]
    finally:
        resume_flow()
