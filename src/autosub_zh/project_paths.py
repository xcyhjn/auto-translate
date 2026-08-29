from __future__ import annotations

import os
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent


def discover_project_root() -> Path:
    configured = str(os.environ.get("AUTOSUB_PROJECT_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    candidates = [Path.cwd().resolve(), *PACKAGE_DIR.parents]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "pyproject.toml").is_file() and (candidate / "web").is_dir():
            return candidate

    return Path.cwd().resolve()


PROJECT_ROOT = discover_project_root()
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
ATTACHMENTS_DIR = PROJECT_ROOT / "attachments"
LOCAL_DATASETS_DIR = PROJECT_ROOT / "datasets"
WEB_DIR = PACKAGE_DIR / "web"
DATASETS_DIR = PACKAGE_DIR / "datasets"
WORKFLOW_PROFILES_DIR = PACKAGE_DIR / "workflow_profiles"
TRANSLATION_PROMPTS_DIR = PACKAGE_DIR / "translation_prompts"
