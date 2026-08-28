from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = BASE_DIR / "workflow_profiles"
PROMPT_DIR = BASE_DIR / "translation_prompts"
DATASET_DIR = BASE_DIR / "datasets"

DEFAULT_WORKFLOW_PROFILE = "en_to_zh_default"
VALID_SUBTITLE_MODES = {
    "bilingual_source_reference",
    "source_review",
    "target_only",
}

TOP_ASS_PREFIX = "00_ASS"
TOP_ASS_GLOB = f"{TOP_ASS_PREFIX}_*.ass"
LEGACY_ASS_GLOBS = ("08_bilingual_*.ass", "08_subtitle_*.ass", "08_source_*.ass")
INTERNAL_ARTIFACTS_DIR_NAME = "99_internal_artifacts"


@dataclass(frozen=True, slots=True)
class WorkflowProfile:
    id: str
    label: str
    description: str
    src_lang: str
    dst_lang: str
    model: str
    prompt_profile: str
    dataset_profile: str
    subtitle_mode: str
    source_reference_label: str
    config: dict[str, Any]
    style: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SubtitleOutputPlan:
    subtitle_mode: str
    src_lang: str
    dst_lang: str
    source_srt_name: str
    translated_srt_name: str
    ass_name: str
    legacy_ass_name: str
    alignment_debug_name: str
    manifest_name: str
    output_video_name: str


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Workflow resource must be a JSON object: {path}")
    return payload


def project_artifact_path(project: Path, name: str) -> Path:
    root_path = project / name
    if root_path.exists():
        return root_path
    internal_path = project / INTERNAL_ARTIFACTS_DIR_NAME / name
    if internal_path.exists():
        return internal_path
    return root_path


def normalize_subtitle_mode(value: object) -> str:
    normalized = str(value or "bilingual_source_reference").strip().lower()
    if normalized not in VALID_SUBTITLE_MODES:
        return "bilingual_source_reference"
    return normalized


def normalize_language_label(value: str | None, fallback: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        raw = fallback
    import re

    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")
    return cleaned or fallback


def build_subtitle_output_plan(
    *,
    src_lang: str | None,
    dst_lang: str | None,
    subtitle_mode: str | None,
    preview_seconds: int | None,
) -> SubtitleOutputPlan:
    source_label = normalize_language_label(src_lang, "source")
    normalized_target = normalize_language_label(dst_lang, "target")
    target_label = "zh" if normalized_target.startswith("zh") else normalized_target
    mode = normalize_subtitle_mode(subtitle_mode)
    if mode == "target_only":
        ass_name = f"{TOP_ASS_PREFIX}_subtitle_{target_label}.ass"
        legacy_ass_name = f"08_subtitle_{target_label}.ass"
        video_kind = f"{target_label}_only"
    elif mode == "source_review":
        ass_name = f"{TOP_ASS_PREFIX}_source_{source_label}.ass"
        legacy_ass_name = f"08_source_{source_label}.ass"
        video_kind = f"source_{source_label}"
    else:
        ass_name = f"{TOP_ASS_PREFIX}_bilingual_{target_label}_{source_label}.ass"
        legacy_ass_name = f"08_bilingual_{target_label}_{source_label}.ass"
        video_kind = f"bilingual_{target_label}_{source_label}"
    output_video_name = (
        f"09_burned_{video_kind}_preview_{preview_seconds}s.mp4"
        if preview_seconds is not None
        else f"09_burned_{video_kind}_video.mp4"
    )
    return SubtitleOutputPlan(
        subtitle_mode=mode,
        src_lang=source_label,
        dst_lang=target_label,
        source_srt_name=f"04_source_{source_label}.srt",
        translated_srt_name=f"06_translated_{target_label}.srt",
        ass_name=ass_name,
        legacy_ass_name=legacy_ass_name,
        alignment_debug_name=f"08a_{mode}_alignment_debug.json",
        manifest_name=f"10_manifest_{mode}.json",
        output_video_name=output_video_name,
    )


def is_final_ass_filename(name: str) -> bool:
    lowered = str(name or "").lower()
    if not lowered.endswith(".ass"):
        return False
    if "safe" in lowered or "segmentation_preview" in lowered:
        return False
    return lowered.startswith("00_ass_") or lowered.startswith("08_bilingual_") or lowered.startswith("08_subtitle_") or lowered.startswith("08_source_")


def top_ass_name_for_final(name: str) -> str | None:
    original = str(name or "")
    lowered = original.lower()
    if not is_final_ass_filename(original):
        return None
    if lowered.startswith("00_ass_"):
        return original
    prefix_map = {
        "08_bilingual_": f"{TOP_ASS_PREFIX}_bilingual_",
        "08_subtitle_": f"{TOP_ASS_PREFIX}_subtitle_",
        "08_source_": f"{TOP_ASS_PREFIX}_source_",
    }
    for old_prefix, new_prefix in prefix_map.items():
        if lowered.startswith(old_prefix):
            return f"{new_prefix}{original[len(old_prefix):]}"
    return None


def ass_candidate_paths(project: Path, manifest_ass_name: str | None = None) -> list[Path]:
    seen: set[str] = set()
    candidates: list[Path] = []

    def add(path: Path) -> None:
        key = path.name.lower()
        if key in seen or not is_final_ass_filename(path.name):
            return
        seen.add(key)
        candidates.append(path)

    for match in sorted(project.glob(TOP_ASS_GLOB)):
        add(match)
    manifest_name = str(manifest_ass_name or "").strip()
    if manifest_name:
        add(project / manifest_name)
    for pattern in LEGACY_ASS_GLOBS:
        for match in sorted(project.glob(pattern)):
            add(match)
    return candidates


def find_existing_ass_path(project: Path, manifest_ass_name: str | None = None) -> Path | None:
    for candidate in ass_candidate_paths(project, manifest_ass_name):
        if candidate.exists():
            return candidate
    return None


def ensure_top_ass_alias(project: Path, manifest_ass_name: str | None = None) -> Path | None:
    for candidate in ass_candidate_paths(project, manifest_ass_name):
        if candidate.exists() and candidate.name.lower().startswith("00_ass_"):
            return candidate
    for candidate in ass_candidate_paths(project, manifest_ass_name):
        if not candidate.exists():
            continue
        top_name = top_ass_name_for_final(candidate.name)
        if not top_name:
            continue
        top_path = project / top_name
        if top_path == candidate:
            return candidate
        if not top_path.exists() or candidate.stat().st_mtime > top_path.stat().st_mtime + 0.001:
            shutil.copy2(candidate, top_path)
        return top_path
    return None


def profile_path(profile_id: str) -> Path:
    safe_id = str(profile_id or DEFAULT_WORKFLOW_PROFILE).strip()
    if not safe_id:
        safe_id = DEFAULT_WORKFLOW_PROFILE
    if not safe_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"Unsupported workflow profile id: {profile_id!r}")
    return PROFILE_DIR / f"{safe_id}.json"


def load_workflow_profile(profile_id: str | None) -> WorkflowProfile:
    path = profile_path(profile_id or DEFAULT_WORKFLOW_PROFILE)
    if not path.exists() and profile_id:
        path = profile_path(DEFAULT_WORKFLOW_PROFILE)
    if not path.exists():
        raise FileNotFoundError(f"Workflow profile not found: {path}")

    payload = read_json(path)
    profile_id_value = str(payload.get("id") or path.stem).strip()
    return WorkflowProfile(
        id=profile_id_value,
        label=str(payload.get("label") or profile_id_value).strip(),
        description=str(payload.get("description") or "").strip(),
        src_lang=str(payload.get("src_lang") or "en").strip(),
        dst_lang=str(payload.get("dst_lang") or "zh-Hans").strip(),
        model=str(payload.get("model") or "base").strip(),
        prompt_profile=str(payload.get("prompt_profile") or "").strip(),
        dataset_profile=str(payload.get("dataset_profile") or "").strip(),
        subtitle_mode=normalize_subtitle_mode(payload.get("subtitle_mode")),
        source_reference_label=str(payload.get("source_reference_label") or payload.get("src_lang") or "source").strip(),
        config=dict(payload.get("config") or {}),
        style=dict(payload.get("style") or {}),
    )


def list_workflow_profiles() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    if not PROFILE_DIR.exists():
        return profiles
    for path in sorted(PROFILE_DIR.glob("*.json")):
        try:
            profile = load_workflow_profile(path.stem)
        except Exception:
            continue
        profiles.append(workflow_profile_summary(profile))
    return profiles


def workflow_profile_summary(profile: WorkflowProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "label": profile.label,
        "description": profile.description,
        "src_lang": profile.src_lang,
        "dst_lang": profile.dst_lang,
        "model": profile.model,
        "prompt_profile": profile.prompt_profile,
        "dataset_profile": profile.dataset_profile,
        "subtitle_mode": profile.subtitle_mode,
        "source_reference_label": profile.source_reference_label,
        "config": profile.config,
        "style": profile.style,
        "prompt_preview": load_prompt_profile(profile.prompt_profile),
        "dataset_summary": summarize_dataset_profile(profile.dataset_profile),
    }


def prompt_path(prompt_profile: str | None) -> Path | None:
    if not prompt_profile:
        return None
    safe_name = str(prompt_profile).strip()
    if not safe_name:
        return None
    if not safe_name.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"Unsupported prompt profile id: {prompt_profile!r}")
    return PROMPT_DIR / f"{safe_name}.md"


def load_prompt_profile(prompt_profile: str | None) -> str:
    path = prompt_path(prompt_profile)
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def dataset_profile_dir(dataset_profile: str | None) -> Path | None:
    if not dataset_profile:
        return None
    safe_name = str(dataset_profile).strip()
    if not safe_name:
        return None
    if not safe_name.replace("_", "").replace("-", "").replace("/", "").replace("\\", "").isalnum():
        raise ValueError(f"Unsupported dataset profile id: {dataset_profile!r}")
    return DATASET_DIR / safe_name.replace("\\", "/")


def load_dataset_profile(dataset_profile: str | None) -> dict[str, Any]:
    root = dataset_profile_dir(dataset_profile)
    if not root or not root.exists():
        return {"id": dataset_profile or "", "files": {}, "glossary_text": ""}

    files: dict[str, Any] = {}
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".json":
            files[path.name] = read_json(path)
        elif path.suffix.lower() in {".jsonl", ".md", ".txt"}:
            files[path.name] = path.read_text(encoding="utf-8").strip()

    glossary_text = ""
    glossary_payload = files.get("glossary.json")
    if isinstance(glossary_payload, dict):
        lines = []
        for item in glossary_payload.get("terms") or []:
            if not isinstance(item, dict):
                continue
            canonical = str(item.get("canonical") or "").strip()
            if not canonical:
                continue
            zh = str(item.get("zh") or canonical).strip()
            policy = str(item.get("policy") or "preserve").strip()
            aliases = [str(value).strip() for value in item.get("aliases") or [] if str(value).strip()]
            line = f"- {canonical} | zh={zh} | policy={policy}"
            if aliases:
                line += f" | aliases={'; '.join(aliases)}"
            lines.append(line)
        glossary_text = "\n".join(lines)

    return {
        "id": dataset_profile or "",
        "root": str(root),
        "files": files,
        "glossary_text": glossary_text,
    }


def write_dataset_profile_assets(
    dataset_profile: str | None,
    output_dir: str | Path,
) -> dict[str, str]:
    root = dataset_profile_dir(dataset_profile)
    target_dir = Path(output_dir)
    written: dict[str, str] = {}
    if not root or not root.exists():
        return written

    target_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        target = target_dir / f"00_profile_{path.name}"
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        written[path.name] = str(target)
    return written


def apply_workflow_profile(config: dict[str, Any], defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    profile_id = str(config.get("workflow_profile") or DEFAULT_WORKFLOW_PROFILE)
    profile = load_workflow_profile(profile_id)
    defaults = defaults or {}
    merged = dict(config)
    merged["workflow_profile"] = profile.id
    profile_defaults = {
        "src_lang": profile.src_lang,
        "dst_lang": profile.dst_lang,
        "model": profile.model,
        "prompt_profile": profile.prompt_profile,
        "dataset_profile": profile.dataset_profile,
        "subtitle_mode": profile.subtitle_mode,
        "source_reference_label": profile.source_reference_label,
    }
    for key, value in profile_defaults.items():
        current = merged.get(key)
        default = defaults.get(key)
        if current in {None, ""} or (key in defaults and current == default):
            merged[key] = value
    for key, value in profile.config.items():
        current = merged.get(key)
        default = defaults.get(key)
        if key not in merged or current in {None, ""} or (key in defaults and current == default):
            merged[key] = value
    current_style = dict(merged.get("style") or {})
    default_style = dict(defaults.get("style") or {})
    style = dict(current_style)
    for key, value in profile.style.items():
        current = current_style.get(key)
        default = default_style.get(key)
        if key not in current_style or current in {None, ""} or (key in default_style and current == default):
            style[key] = value
    if style:
        merged["style"] = style
    prompt_text = load_prompt_profile(str(merged.get("prompt_profile") or profile.prompt_profile))
    current_prompt = merged.get("translation_prompt")
    default_prompt = defaults.get("translation_prompt")
    if prompt_text and (not str(current_prompt or "").strip() or current_prompt == default_prompt):
        merged["translation_prompt"] = prompt_text
    return merged


def load_dataset_glossary_terms(dataset_profile: str | None) -> list[dict[str, Any]]:
    payload = load_dataset_profile(dataset_profile)
    glossary_payload = payload.get("files", {}).get("glossary.json")
    if not isinstance(glossary_payload, dict):
        return []
    return [item for item in glossary_payload.get("terms") or [] if isinstance(item, dict)]


def summarize_dataset_profile(dataset_profile: str | None) -> dict[str, Any]:
    payload = load_dataset_profile(dataset_profile)
    files = payload.get("files", {})
    glossary_payload = files.get("glossary.json") if isinstance(files, dict) else None
    glossary_terms = glossary_payload.get("terms") if isinstance(glossary_payload, dict) else []
    return {
        "id": payload.get("id", ""),
        "root": payload.get("root", ""),
        "file_names": sorted(files.keys()) if isinstance(files, dict) else [],
        "glossary_term_count": len(glossary_terms or []),
        "glossary_preview": payload.get("glossary_text", ""),
    }
