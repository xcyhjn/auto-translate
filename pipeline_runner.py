from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .models import BilingualSubtitleStyle
from .pipeline_core import build_output_slug, run_pipeline


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
STYLE_DEFAULTS = asdict(BilingualSubtitleStyle())
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
OPENAI_BASE_URL_ALIASES = ("OPENAI_API_BASE",)
OPENAI_RUNTIME_INJECTIONS: dict[str, dict] = {}

StageCallback = Callable[[str, dict], None]
ControlCallback = Callable[[str, dict | None], None]


def read_windows_environment_value(name: str, scope: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""

    if scope == "user_env":
        root = winreg.HKEY_CURRENT_USER
        sub_key = "Environment"
    elif scope == "machine_env":
        root = winreg.HKEY_LOCAL_MACHINE
        sub_key = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    else:
        return ""

    try:
        with winreg.OpenKey(root, sub_key) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value or "").strip()


def resolve_env_value(name: str, aliases: tuple[str, ...] = ()) -> dict:
    names = (name, *aliases)
    for env_name in names:
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            return {"available": True, "name": name, "env_name": env_name, "value": value, "source": "process_env"}
    for source in ("user_env", "machine_env"):
        for env_name in names:
            value = read_windows_environment_value(env_name, source)
            if value:
                return {"available": True, "name": name, "env_name": env_name, "value": value, "source": source}
    return {"available": False, "name": name, "env_name": name, "value": "", "source": "missing"}


def mask_openai_key(value: str) -> str:
    key = str(value or "").strip()
    if not key:
        return ""
    if len(key) <= 12:
        return f"{key[:3]}..."
    return f"{key[:6]}...{key[-4:]}"


def apply_openai_injection_origin(canonical_name: str, info: dict, injected: bool) -> tuple[dict, bool]:
    origin = OPENAI_RUNTIME_INJECTIONS.get(canonical_name)
    if not origin or info.get("source") != "process_env":
        return info, injected
    display_info = {
        **info,
        "source": origin.get("source", info.get("source")),
        "env_name": origin.get("env_name", info.get("env_name")),
    }
    return display_info, bool(origin.get("injected", injected))


def build_openai_api_key_status(info: dict, injected: bool = False) -> dict:
    value = str(info.get("value") or "").strip()
    return {
        "available": bool(info.get("available")),
        "source": str(info.get("source") or "missing"),
        "env_name": str(info.get("env_name") or OPENAI_API_KEY_ENV),
        "masked": mask_openai_key(value),
        "length": len(value),
        "injected": bool(injected),
    }


def build_openai_base_url_status(info: dict, injected: bool = False, *, config_base_url: str | None = None) -> dict:
    configured = str(config_base_url or "").strip()
    if configured:
        return {
            "available": True,
            "source": "ui_config",
            "env_name": "openai_base_url",
            "value": configured,
            "injected": False,
        }
    return {
        "available": bool(info.get("available")),
        "source": str(info.get("source") or "missing"),
        "env_name": str(info.get("env_name") or OPENAI_BASE_URL_ENV),
        "value": str(info.get("value") or "").strip(),
        "injected": bool(injected),
    }


def ensure_openai_runtime_env_loaded() -> dict:
    statuses: dict[str, dict] = {}

    key_info = resolve_env_value(OPENAI_API_KEY_ENV)
    key_injected = False
    if key_info["available"] and not str(os.environ.get(OPENAI_API_KEY_ENV) or "").strip():
        os.environ[OPENAI_API_KEY_ENV] = key_info["value"]
        key_injected = True
    if key_info["available"] and (
        key_info["source"] != "process_env" or OPENAI_API_KEY_ENV not in OPENAI_RUNTIME_INJECTIONS
    ):
        OPENAI_RUNTIME_INJECTIONS[OPENAI_API_KEY_ENV] = {
            "source": key_info["source"],
            "env_name": key_info["env_name"],
            "injected": key_injected,
        }
    key_status_info, key_status_injected = apply_openai_injection_origin(OPENAI_API_KEY_ENV, key_info, key_injected)
    statuses["api_key"] = build_openai_api_key_status(key_status_info, key_status_injected)

    base_info = resolve_env_value(OPENAI_BASE_URL_ENV, OPENAI_BASE_URL_ALIASES)
    base_injected = False
    if base_info["available"] and not str(os.environ.get(OPENAI_BASE_URL_ENV) or "").strip():
        os.environ[OPENAI_BASE_URL_ENV] = base_info["value"]
        base_injected = True
    if base_info["available"] and (
        base_info["source"] != "process_env" or OPENAI_BASE_URL_ENV not in OPENAI_RUNTIME_INJECTIONS
    ):
        OPENAI_RUNTIME_INJECTIONS[OPENAI_BASE_URL_ENV] = {
            "source": base_info["source"],
            "env_name": base_info["env_name"],
            "injected": base_injected,
        }
    base_status_info, base_status_injected = apply_openai_injection_origin(OPENAI_BASE_URL_ENV, base_info, base_injected)
    statuses["base_url"] = build_openai_base_url_status(base_status_info, base_status_injected)
    return statuses


def build_openai_runtime_status(config: dict | None = None) -> dict:
    runtime = ensure_openai_runtime_env_loaded()
    if config and str(config.get("openai_base_url") or "").strip():
        base_info = resolve_env_value(OPENAI_BASE_URL_ENV, OPENAI_BASE_URL_ALIASES)
        runtime["base_url"] = build_openai_base_url_status(
            base_info,
            bool(runtime.get("base_url", {}).get("injected")),
            config_base_url=str(config.get("openai_base_url") or "").strip(),
        )
    return runtime


def normalize_style_config(config: dict) -> BilingualSubtitleStyle:
    style_config = dict(config.get("style") or {})
    if "en_max_words_per_line" in style_config and "en_max_single_line_chars" not in style_config:
        style_config["en_max_single_line_chars"] = max(50, int(style_config.pop("en_max_words_per_line") or 12) * 6)
    style_config.pop("en_max_words_per_line", None)
    normalized = {
        key: style_config.get(key, default_value)
        for key, default_value in STYLE_DEFAULTS.items()
    }
    return BilingualSubtitleStyle(**normalized)


def compute_output_dir(input_path: str | Path, output_root: str | Path = OUTPUT_DIR) -> Path:
    return Path(output_root) / build_output_slug(Path(input_path))


def write_effective_config(output_dir: str | Path, config: dict) -> Path:
    target = Path(output_dir) / "00_effective_config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(target)
    return target


def run_pipeline_from_config(
    *,
    video_path: str | Path,
    config: dict,
    output_root: str | Path = OUTPUT_DIR,
    callback: StageCallback | None = None,
    control_callback: ControlCallback | None = None,
) -> dict:
    ensure_openai_runtime_env_loaded()
    output_dir = compute_output_dir(video_path, output_root)
    write_effective_config(output_dir, config)
    style = normalize_style_config(config)
    return run_pipeline(
        input_path=Path(video_path),
        output_root=Path(output_root),
        src_lang=config["src_lang"],
        dst_lang=config["dst_lang"],
        model=config["model"],
        device=config["device"],
        compute_type=config["compute_type"],
        beam_size=int(config["beam_size"]),
        asr_audio_mode=config.get("asr_audio_mode", "off"),
        asr_audio_gain_db=float(config.get("asr_audio_gain_db", 6.0) or 6.0),
        asr_vad_mode=config.get("asr_vad_mode", "auto"),
        translation_model=config["translation_model"],
        translation_prompt=config.get("translation_prompt", ""),
        translation_chunk_size=int(config["translation_chunk_size"]),
        translation_retries=int(config["translation_retries"]),
        openai_base_url=config["openai_base_url"] or None,
        audio_override_path=config.get("audio_override_path") or None,
        load_existing_segments=bool(config["load_existing_segments"]),
        force_retranslate_existing_segments=bool(config.get("force_retranslate_existing_segments", False)),
        preview_seconds=int(config["preview_seconds"]) if config["preview_seconds"] else None,
        skip_burn=bool(config.get("skip_burn", False)),
        repair_high_risk_spans=bool(config.get("repair_high_risk_spans", True)),
        span_translation_max_spans=int(config.get("span_translation_max_spans", 16) or 0),
        span_repair_max_spans=int(config.get("span_repair_max_spans", 12) or 12),
        semantic_zh_allocation_enabled=bool(config.get("semantic_zh_allocation_enabled", True)),
        semantic_zh_allocation_max_spans=int(config.get("semantic_zh_allocation_max_spans", 16) or 0),
        short_complete_sentence_display_grouping=bool(config.get("short_complete_sentence_display_grouping", True)),
        enable_ai_display_rewrite=bool(config.get("enable_ai_display_rewrite", False)),
        display_rewrite_max_ai_segments=int(config.get("display_rewrite_max_ai_segments", 12) or 12),
        bootstrap_entity_decisions=config.get("bootstrap_entity_decisions", "high_confidence_only"),
        subtitle_mode=config.get("subtitle_mode", "bilingual_source_reference"),
        source_reference_label=config.get("source_reference_label", ""),
        dataset_profile=config.get("dataset_profile", ""),
        bilingual_style=style,
        subtitle_timing_mode=config.get("subtitle_timing_mode", "bound"),
        zh_semantic_merge=bool(config.get("zh_semantic_merge", False)),
        zh_target_min_duration=float(config.get("zh_target_min_duration", 3.5) or 3.5),
        zh_target_max_duration=float(config.get("zh_target_max_duration", 7.5) or 7.5),
        zh_hard_max_duration=float(config.get("zh_hard_max_duration", 8.5) or 8.5),
        zh_min_duration=float(config.get("zh_min_duration", 2.2) or 2.2),
        callback=callback,
        control_callback=control_callback,
    )
