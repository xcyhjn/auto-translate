from __future__ import annotations

import os

from autosub_zh import ui_server


def clear_openai_runtime(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    ui_server.OPENAI_RUNTIME_INJECTIONS.clear()


def test_openai_runtime_prefers_process_env(monkeypatch) -> None:
    clear_openai_runtime(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-process-1234567890")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://process.example/v1")
    monkeypatch.setattr(ui_server, "read_windows_environment_value", lambda name, scope: "")

    status = ui_server.build_openai_runtime_status()

    assert status["api_key"]["available"] is True
    assert status["api_key"]["source"] == "process_env"
    assert status["api_key"]["masked"] == "sk-pro...7890"
    assert "sk-process-1234567890" not in str(status)
    assert status["base_url"]["source"] == "process_env"
    assert status["base_url"]["value"] == "https://process.example/v1"


def test_openai_runtime_injects_user_env(monkeypatch) -> None:
    clear_openai_runtime(monkeypatch)

    def fake_registry(name: str, scope: str) -> str:
        values = {
            ("OPENAI_API_KEY", "user_env"): "sk-user-abcdef123456",
            ("OPENAI_BASE_URL", "user_env"): "https://user.example/v1",
        }
        return values.get((name, scope), "")

    monkeypatch.setattr(ui_server, "read_windows_environment_value", fake_registry)

    status = ui_server.build_openai_runtime_status()

    assert os.environ["OPENAI_API_KEY"] == "sk-user-abcdef123456"
    assert os.environ["OPENAI_BASE_URL"] == "https://user.example/v1"
    assert status["api_key"]["source"] == "user_env"
    assert status["api_key"]["injected"] is True
    assert status["base_url"]["source"] == "user_env"
    assert status["base_url"]["value"] == "https://user.example/v1"
    assert status["base_url"]["injected"] is True


def test_openai_runtime_keeps_injected_origin_on_later_poll(monkeypatch) -> None:
    clear_openai_runtime(monkeypatch)

    def fake_registry(name: str, scope: str) -> str:
        values = {
            ("OPENAI_API_KEY", "user_env"): "sk-user-abcdef123456",
            ("OPENAI_BASE_URL", "user_env"): "https://user.example/v1",
        }
        return values.get((name, scope), "")

    monkeypatch.setattr(ui_server, "read_windows_environment_value", fake_registry)

    first = ui_server.build_openai_runtime_status()
    second = ui_server.build_openai_runtime_status()

    assert first["api_key"]["source"] == "user_env"
    assert second["api_key"]["source"] == "user_env"
    assert second["api_key"]["injected"] is True
    assert second["base_url"]["source"] == "user_env"
    assert second["base_url"]["injected"] is True


def test_openai_runtime_injects_machine_env_and_api_base_alias(monkeypatch) -> None:
    clear_openai_runtime(monkeypatch)

    def fake_registry(name: str, scope: str) -> str:
        values = {
            ("OPENAI_API_KEY", "machine_env"): "sk-machine-abcdef123456",
            ("OPENAI_API_BASE", "machine_env"): "https://api-base.example/v1",
        }
        return values.get((name, scope), "")

    monkeypatch.setattr(ui_server, "read_windows_environment_value", fake_registry)

    status = ui_server.build_openai_runtime_status()

    assert os.environ["OPENAI_API_KEY"] == "sk-machine-abcdef123456"
    assert os.environ["OPENAI_BASE_URL"] == "https://api-base.example/v1"
    assert status["api_key"]["source"] == "machine_env"
    assert status["base_url"]["source"] == "machine_env"
    assert status["base_url"]["env_name"] == "OPENAI_API_BASE"


def test_openai_runtime_config_base_url_wins_without_persisting_env(monkeypatch) -> None:
    clear_openai_runtime(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setattr(ui_server, "read_windows_environment_value", lambda name, scope: "")

    status = ui_server.build_openai_runtime_status({"openai_base_url": "https://config.example/v1"})

    assert status["base_url"]["source"] == "ui_config"
    assert status["base_url"]["value"] == "https://config.example/v1"
    assert os.environ["OPENAI_BASE_URL"] == "https://env.example/v1"


def test_state_payload_uses_saved_config_base_url(monkeypatch) -> None:
    clear_openai_runtime(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setattr(ui_server, "read_windows_environment_value", lambda name, scope: "")
    monkeypatch.setattr(
        ui_server,
        "read_config",
        lambda: ui_server.normalize_config({"openai_base_url": "https://saved.example/v1"}),
    )

    payload = ui_server.build_bootstrap_payload(include_collections=False)

    assert payload["openai_runtime"]["base_url"]["source"] == "ui_config"
    assert payload["openai_runtime"]["base_url"]["value"] == "https://saved.example/v1"


def test_openai_runtime_missing(monkeypatch) -> None:
    clear_openai_runtime(monkeypatch)
    monkeypatch.setattr(ui_server, "read_windows_environment_value", lambda name, scope: "")

    status = ui_server.build_openai_runtime_status()

    assert status["api_key"]["available"] is False
    assert status["api_key"]["source"] == "missing"
    assert status["api_key"]["masked"] == ""
    assert status["base_url"]["available"] is False
    assert status["base_url"]["source"] == "missing"
    assert status["base_url"]["value"] == ""
