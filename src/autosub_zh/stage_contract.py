"""Stable data contracts for pipeline stage reporting.

The contracts are intentionally small so existing callback payloads can keep
their original shape while callers gain a predictable envelope when needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


STAGE_CONTRACT_SCHEMA_VERSION = 1
STAGE_STATUSES = frozenset({"pending", "running", "success", "failed", "skipped"})


def _copy_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


@dataclass(slots=True)
class StageResult:
    """Result envelope shared by stage runners and adapters."""

    stage: str
    status: str
    outputs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: int = STAGE_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.stage = str(self.stage)
        self.status = str(self.status)
        if not self.stage:
            raise ValueError("stage must not be empty")
        if self.status not in STAGE_STATUSES:
            raise ValueError(f"unsupported stage status: {self.status}")
        self.outputs = _copy_mapping(self.outputs)
        self.warnings = [str(item) for item in self.warnings]
        self.metadata = _copy_mapping(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready mapping with stable field names."""
        return {
            "schema_version": self.schema_version,
            "stage": self.stage,
            "status": self.status,
            "outputs": dict(self.outputs),
            "warnings": list(self.warnings),
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StageResult":
        if not isinstance(payload, Mapping):
            raise ValueError("stage result must be a mapping")
        if "stage" not in payload or "status" not in payload:
            raise ValueError("stage result requires stage and status")
        return cls(
            stage=str(payload["stage"]),
            status=str(payload["status"]),
            outputs=payload.get("outputs") or {},
            warnings=payload.get("warnings") or [],
            error=payload.get("error"),
            metadata=payload.get("metadata") or {},
            schema_version=int(payload.get("schema_version", STAGE_CONTRACT_SCHEMA_VERSION)),
        )


@dataclass(slots=True)
class StageEvent:
    """Callback event with the same core fields as :class:`StageResult`."""

    stage: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: Any = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = STAGE_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.stage = str(self.stage)
        self.status = str(self.status)
        if not self.stage:
            raise ValueError("stage must not be empty")
        if self.status not in STAGE_STATUSES:
            raise ValueError(f"unsupported stage status: {self.status}")
        self.payload = _copy_mapping(self.payload)
        self.warnings = [str(item) for item in self.warnings]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "stage": str(self.stage),
            "status": str(self.status),
            "payload": dict(self.payload),
            "warnings": [str(item) for item in self.warnings],
            "error": self.error,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StageEvent":
        if not isinstance(payload, Mapping):
            raise ValueError("stage event must be a mapping")
        if "stage" not in payload or "status" not in payload:
            raise ValueError("stage event requires stage and status")
        return cls(
            stage=str(payload["stage"]),
            status=str(payload["status"]),
            payload=payload.get("payload") or {},
            warnings=payload.get("warnings") or [],
            error=payload.get("error"),
            timestamp=str(payload.get("timestamp") or datetime.now(timezone.utc).isoformat()),
            schema_version=int(payload.get("schema_version", STAGE_CONTRACT_SCHEMA_VERSION)),
        )
