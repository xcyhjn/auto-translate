from __future__ import annotations

import tomllib
from pathlib import Path

from autosub_zh.project_paths import DATASETS_DIR, LOCAL_DATASETS_DIR, PROJECT_ROOT, WEB_DIR


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_package_uses_src_layout() -> None:
    assert (REPOSITORY_ROOT / "src" / "autosub_zh" / "__init__.py").is_file()
    assert not list(REPOSITORY_ROOT.glob("*.py"))


def test_project_resources_stay_at_repository_root() -> None:
    assert PROJECT_ROOT == REPOSITORY_ROOT
    package_root = REPOSITORY_ROOT / "src" / "autosub_zh"
    assert WEB_DIR == package_root / "web"
    assert DATASETS_DIR == package_root / "datasets"
    assert LOCAL_DATASETS_DIR == REPOSITORY_ROOT / "datasets"


def test_pyproject_exposes_console_commands() -> None:
    payload = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = payload["project"]["scripts"]

    assert scripts["autosub-zh"] == "autosub_zh.cli:main"
    assert scripts["autosub-zh-ui"] == "autosub_zh.ui_server:main"
