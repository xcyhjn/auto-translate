"""Project-scoped, human-auditable evidence sidecars.

The sidecar is deliberately advisory.  It can provide context to glossary or
entity review, but it never changes a glossary rule or an ASS file by itself.
Only the Python standard library is used so the artifact remains portable.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


EVIDENCE_SIDECAR_SCHEMA_VERSION = 1
SCHEMA_VERSION = EVIDENCE_SIDECAR_SCHEMA_VERSION
EVIDENCE_LEVELS = frozenset({"confirmed", "advisory", "unknown"})


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


@dataclass(slots=True)
class EvidenceRecord:
    """One source observation linked to exactly one project input."""

    source: str = "unknown"
    title: str = ""
    url: str = ""
    summary: str = ""
    fetched_at: str = "unknown"
    confidence: float | str = "unknown"
    project_id: str = "unknown"
    input_fingerprint: str = "unknown"
    evidence_level: str = "advisory"
    schema_version: int = EVIDENCE_SIDECAR_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source = _text(self.source, "unknown") or "unknown"
        self.title = _text(self.title)
        self.url = _text(self.url)
        self.summary = _text(self.summary)
        self.fetched_at = _text(self.fetched_at, "unknown") or "unknown"
        self.project_id = _text(self.project_id, "unknown") or "unknown"
        self.input_fingerprint = _text(self.input_fingerprint, "unknown") or "unknown"
        self.evidence_level = _text(self.evidence_level, "unknown") or "unknown"
        self.metadata = dict(self.metadata or {})
        try:
            self.schema_version = int(self.schema_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("schema_version must be an integer") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidenceRecord":
        if not isinstance(payload, Mapping):
            raise ValueError("evidence record must be a mapping")
        return cls(**{key: payload[key] for key in cls.__dataclass_fields__ if key in payload})


def validate_evidence_record(
    record: EvidenceRecord | Mapping[str, Any],
    *,
    project_id: str | None = None,
    input_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Return a canonical record, or ``None`` when the record is unusable."""

    try:
        item = record if isinstance(record, EvidenceRecord) else EvidenceRecord.from_dict(record)
    except (TypeError, ValueError):
        return None
    if item.schema_version != EVIDENCE_SIDECAR_SCHEMA_VERSION:
        return None
    if item.evidence_level not in EVIDENCE_LEVELS:
        return None
    if not any((item.title, item.url, item.summary)):
        return None
    if isinstance(item.confidence, bool):
        return None
    if isinstance(item.confidence, (int, float)):
        item.confidence = float(item.confidence)
        if not 0.0 <= item.confidence <= 1.0:
            return None
    elif _text(item.confidence, "unknown") not in {"", "unknown"}:
        return None
    expected_project = _text(project_id) if project_id is not None else ""
    expected_fingerprint = _text(input_fingerprint) if input_fingerprint is not None else ""
    if expected_project and expected_project != "unknown":
        if item.project_id not in {"unknown", expected_project}:
            return None
        item.project_id = expected_project
    if expected_fingerprint and expected_fingerprint != "unknown":
        if item.input_fingerprint not in {"unknown", expected_fingerprint}:
            return None
        item.input_fingerprint = expected_fingerprint
    # A URL is metadata, not a fetch instruction.  Reject malformed explicit
    # URLs while allowing ``unknown``/empty values for offline evidence.
    if item.url and item.url != "unknown":
        parsed = urlparse(item.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
    return item.to_dict()


def build_evidence_record(**kwargs: Any) -> dict[str, Any]:
    """Build and validate one record for callers that prefer mappings."""

    record = validate_evidence_record(EvidenceRecord(**kwargs))
    if record is None:
        raise ValueError("invalid evidence record")
    return record


def build_evidence_sidecar(
    records: Iterable[EvidenceRecord | Mapping[str, Any]],
    *,
    project_id: str = "unknown",
    input_fingerprint: str = "unknown",
) -> dict[str, Any]:
    """Build a sidecar payload, filtering malformed records."""

    project = _text(project_id, "unknown") or "unknown"
    fingerprint = _text(input_fingerprint, "unknown") or "unknown"
    clean_records: list[dict[str, Any]] = []
    for record in records:
        clean = validate_evidence_record(record, project_id=project, input_fingerprint=fingerprint)
        if clean is not None:
            clean_records.append(clean)
    return {
        "schema_version": EVIDENCE_SIDECAR_SCHEMA_VERSION,
        "project_id": project,
        "input_fingerprint": fingerprint,
        "records": clean_records,
    }


def atomic_write_json(path: str | Path, payload: Any) -> Path:
    """Publish JSON atomically in the destination directory."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
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


def write_evidence_sidecar(
    path: str | Path,
    records: Iterable[EvidenceRecord | Mapping[str, Any]],
    *,
    project_id: str = "unknown",
    input_fingerprint: str = "unknown",
) -> Path:
    return atomic_write_json(path, build_evidence_sidecar(
        records, project_id=project_id, input_fingerprint=input_fingerprint,
    ))


def validate_evidence_sidecar(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    try:
        version = int(payload.get("schema_version"))
    except (TypeError, ValueError):
        return None
    if version != EVIDENCE_SIDECAR_SCHEMA_VERSION:
        return None
    project = _text(payload.get("project_id"), "unknown") or "unknown"
    fingerprint = _text(payload.get("input_fingerprint"), "unknown") or "unknown"
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return None
    clean_records = []
    for record in raw_records:
        clean = validate_evidence_record(record, project_id=project, input_fingerprint=fingerprint)
        if clean is not None:
            clean_records.append(clean)
    return {
        "schema_version": version,
        "project_id": project,
        "input_fingerprint": fingerprint,
        "records": clean_records,
    }


def read_evidence_sidecar(
    path: str | Path,
    *,
    project_id: str | None = None,
    input_fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Read and validate a sidecar; malformed JSON is treated as unavailable."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    clean = validate_evidence_sidecar(payload)
    if clean is None:
        return None
    if project_id is not None and clean["project_id"] != _text(project_id):
        return None
    if input_fingerprint is not None and clean["input_fingerprint"] != _text(input_fingerprint):
        return None
    return clean


load_evidence_sidecar = read_evidence_sidecar


def search_evidence(
    source: str | Path | Mapping[str, Any] | Iterable[Mapping[str, Any]],
    keywords: str | Iterable[str],
    *,
    project_id: str | None = None,
    input_fingerprint: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Search advisory evidence by case-insensitive keyword substring."""

    if isinstance(source, (str, Path)):
        payload = read_evidence_sidecar(source, project_id=project_id, input_fingerprint=input_fingerprint)
        records = payload["records"] if payload else []
    elif isinstance(source, Mapping):
        payload = validate_evidence_sidecar(source)
        records = payload["records"] if payload else []
    else:
        records = [item for item in source if isinstance(item, Mapping)]
    terms = [str(key).strip().casefold() for key in ([keywords] if isinstance(keywords, str) else keywords) if str(key).strip()]
    if not terms or int(limit) <= 0:
        return []
    project = _text(project_id) if project_id is not None else None
    fingerprint = _text(input_fingerprint) if input_fingerprint is not None else None
    matches: list[dict[str, Any]] = []
    for record in records:
        if project is not None and record.get("project_id") != project:
            continue
        if fingerprint is not None and record.get("input_fingerprint") != fingerprint:
            continue
        haystack = " ".join(str(record.get(field) or "") for field in ("source", "title", "url", "summary")).casefold()
        if all(term in haystack for term in terms):
            matches.append(dict(record))
            if len(matches) >= max(int(limit), 0):
                break
    return matches


search_evidence_sidecar = search_evidence
