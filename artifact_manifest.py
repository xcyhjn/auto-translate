"""Artifact fingerprints and safe JSON publication helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


ARTIFACT_MANIFEST_SCHEMA_VERSION = 1
SCHEMA_VERSION = ARTIFACT_MANIFEST_SCHEMA_VERSION


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_text(_canonical_json(value))


def file_snapshot(path: str | Path) -> dict[str, Any]:
    """Capture the identity fields used to decide whether an input changed."""
    target = Path(path).expanduser().resolve(strict=False)
    try:
        stat = target.stat()
    except OSError:
        return {"path": str(target), "exists": False, "size": None, "mtime_ns": None}
    return {"path": str(target), "exists": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def compute_fingerprint(
    input_path: str | Path | None = None,
    *,
    config: Any = None,
    prompt: str = "",
    glossary: str = "",
    schema_version: int = ARTIFACT_MANIFEST_SCHEMA_VERSION,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Return a deterministic digest for inputs and caller-provided settings."""
    payload: dict[str, Any] = {
        "schema_version": int(schema_version),
        "input": file_snapshot(input_path) if input_path is not None else None,
        "config_hash": sha256_value(config) if config is not None else None,
        "prompt_hash": sha256_text(prompt) if prompt else None,
        "glossary_hash": sha256_text(glossary) if glossary else None,
        "extra": dict(extra or {}),
    }
    return sha256_value(payload)


def fingerprint_matches(expected: str, actual: str) -> bool:
    return bool(expected) and str(expected) == str(actual)


def build_artifact_manifest(
    input_path: str | Path | None = None,
    *,
    config: Any = None,
    prompt: str = "",
    glossary: str = "",
    outputs: Mapping[str, Any] | None = None,
    schema_version: int = ARTIFACT_MANIFEST_SCHEMA_VERSION,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": int(schema_version),
        "fingerprint": compute_fingerprint(
            input_path,
            config=config,
            prompt=prompt,
            glossary=glossary,
            schema_version=schema_version,
            extra=extra,
        ),
        "input": file_snapshot(input_path) if input_path is not None else None,
        "config_hash": sha256_value(config) if config is not None else None,
        "prompt_hash": sha256_text(prompt) if prompt else None,
        "glossary_hash": sha256_text(glossary) if glossary else None,
        "outputs": dict(outputs or {}),
        "extra": dict(extra or {}),
    }


def atomic_write_json(path: str | Path, payload: Any) -> Path:
    """Write JSON through a same-directory temporary file and replace."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return target


def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def load_artifact_manifest(path: str | Path) -> dict[str, Any] | None:
    payload = read_json(path)
    if not isinstance(payload, dict):
        return None
    if not payload.get("fingerprint") or "schema_version" not in payload:
        return None
    try:
        payload["schema_version"] = int(payload["schema_version"])
    except (TypeError, ValueError):
        return None
    if payload["schema_version"] != ARTIFACT_MANIFEST_SCHEMA_VERSION:
        return None
    fingerprint = str(payload.get("fingerprint") or "")
    if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint.lower()):
        return None
    return payload


write_json_atomic = atomic_write_json
get_file_snapshot = file_snapshot
build_fingerprint = compute_fingerprint
