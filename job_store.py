from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "runtime" / "autosub_jobs.sqlite"
ACTIVE_STATUSES = {"queued", "running", "paused", "cancel_requested"}
TERMINAL_STATUSES = {"succeeded", "succeeded_with_qa_issues", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_db_path() -> Path:
    return Path(os.environ.get("AUTOSUB_JOB_DB_PATH") or DEFAULT_DB_PATH)


def encode_json(payload: Any) -> str:
    return json.dumps(payload if payload is not None else {}, ensure_ascii=False, sort_keys=True)


def decode_json(value: str | None, default: Any = None) -> Any:
    if not value:
        return {} if default is None else default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {} if default is None else default


def row_to_job(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    payload["config"] = decode_json(payload.pop("config_json", None))
    payload["error"] = decode_json(payload.pop("error_json", None), None)
    return payload


def row_to_event(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    payload["payload"] = decode_json(payload.pop("payload_json", None))
    return payload


def row_to_artifact(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    payload["metadata"] = decode_json(payload.pop("metadata_json", None))
    return payload


class JobStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else default_db_path()

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL DEFAULT 'pipeline',
                    input_path TEXT NOT NULL,
                    output_dir TEXT NOT NULL DEFAULT '',
                    workflow_profile TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    current_stage TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    worker_pid INTEGER,
                    lease_until REAL NOT NULL DEFAULT 0,
                    error_json TEXT,
                    manifest_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_job_events_job_seq
                    ON job_events(job_id, seq);

                CREATE TABLE IF NOT EXISTS stage_checkpoints (
                    job_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_hash TEXT NOT NULL DEFAULT '',
                    output_path TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, stage),
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS job_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER NOT NULL DEFAULT 0,
                    mtime REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'available',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_kind
                    ON job_artifacts(job_id, kind);
                """
            )

    def create_job(
        self,
        *,
        input_path: str,
        output_dir: str,
        workflow_profile: str,
        config: dict,
        kind: str = "pipeline",
    ) -> dict:
        self.initialize()
        job_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, kind, input_path, output_dir, workflow_profile, config_json,
                    status, current_stage, progress, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 'queued', 0, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    str(input_path),
                    str(output_dir or ""),
                    str(workflow_profile or ""),
                    encode_json(config),
                    now,
                    now,
                ),
            )
        self.add_event(job_id, "queued", {"input_path": input_path, "output_dir": output_dir}, message="Job queued")
        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Failed to create job {job_id}")
        return job

    def get_job(self, job_id: str) -> dict | None:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return row_to_job(row)

    def list_jobs(self, limit: int = 50) -> list[dict]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [job for row in rows if (job := row_to_job(row))]

    def get_active_job(self) -> dict | None:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('queued', 'running', 'paused', 'cancel_requested')
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """
            ).fetchone()
        return row_to_job(row)

    def get_latest_job(self) -> dict | None:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs ORDER BY updated_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
        return row_to_job(row)

    def has_active_job(self) -> bool:
        return self.get_active_job() is not None

    def claim_next_job(self, *, worker_pid: int, lease_seconds: int = 120) -> dict | None:
        self.initialize()
        now_ts = time.time()
        lease_until = now_ts + max(30, int(lease_seconds))
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued'
                   OR (status = 'running' AND lease_until > 0 AND lease_until < ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now_ts,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            connection.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    current_stage = CASE WHEN current_stage = 'queued' THEN 'starting' ELSE current_stage END,
                    worker_pid = ?,
                    lease_until = ?,
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (int(worker_pid), lease_until, now, now, row["id"]),
            )
            connection.commit()
        self.add_event(str(row["id"]), "claimed", {"worker_pid": worker_pid}, message="Worker claimed job")
        return self.get_job(str(row["id"]))

    def update_heartbeat(self, job_id: str, *, lease_seconds: int = 120) -> None:
        lease_until = time.time() + max(30, int(lease_seconds))
        with self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET lease_until = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (lease_until, utc_now(), job_id),
            )

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        current_stage: str | None = None,
        progress: int | None = None,
        output_dir: str | None = None,
        error: dict | None = None,
        manifest_path: str | None = None,
        worker_pid: int | None = None,
    ) -> None:
        assignments = ["updated_at = ?"]
        params: list[Any] = [utc_now()]
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
            if status in TERMINAL_STATUSES:
                assignments.append("completed_at = COALESCE(completed_at, ?)")
                params.append(utc_now())
                assignments.append("lease_until = 0")
        if current_stage is not None:
            assignments.append("current_stage = ?")
            params.append(current_stage)
        if progress is not None:
            assignments.append("progress = ?")
            params.append(max(0, min(100, int(progress))))
        if output_dir is not None:
            assignments.append("output_dir = ?")
            params.append(str(output_dir))
        if error is not None:
            assignments.append("error_json = ?")
            params.append(encode_json(error))
        if manifest_path is not None:
            assignments.append("manifest_path = ?")
            params.append(str(manifest_path))
        if worker_pid is not None:
            assignments.append("worker_pid = ?")
            params.append(int(worker_pid))
        params.append(job_id)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?",
                params,
            )

    def add_event(
        self,
        job_id: str,
        stage: str,
        payload: dict | None = None,
        *,
        level: str = "info",
        message: str = "",
    ) -> dict:
        self.initialize()
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM job_events WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            seq = int(row["next_seq"] if row else 1)
            cursor = connection.execute(
                """
                INSERT INTO job_events (job_id, seq, stage, level, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, seq, stage, level, message, encode_json(payload or {}), now),
            )
            connection.commit()
            event_id = int(cursor.lastrowid)
        event = self.get_event(event_id)
        return event or {
            "id": event_id,
            "job_id": job_id,
            "seq": seq,
            "stage": stage,
            "level": level,
            "message": message,
            "payload": payload or {},
            "created_at": now,
        }

    def get_event(self, event_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM job_events WHERE id = ?", (event_id,)).fetchone()
        return row_to_event(row)

    def get_events(self, job_id: str, limit: int = 120) -> list[dict]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                    SELECT * FROM job_events
                    WHERE job_id = ?
                    ORDER BY seq DESC
                    LIMIT ?
                )
                ORDER BY seq ASC
                """,
                (job_id, int(limit)),
            ).fetchall()
        return [event for row in rows if (event := row_to_event(row))]

    def upsert_checkpoint(
        self,
        job_id: str,
        stage: str,
        *,
        status: str,
        payload: dict | None = None,
        output_path: str = "",
        input_hash: str = "",
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO stage_checkpoints (
                    job_id, stage, status, input_hash, output_path, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, stage) DO UPDATE SET
                    status = excluded.status,
                    input_hash = excluded.input_hash,
                    output_path = excluded.output_path,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (job_id, stage, status, input_hash, output_path, encode_json(payload or {}), now),
            )

    def upsert_artifact(
        self,
        job_id: str,
        kind: str,
        path: str | Path,
        *,
        status: str = "available",
        metadata: dict | None = None,
    ) -> None:
        target = Path(path)
        size = target.stat().st_size if target.exists() and target.is_file() else 0
        mtime = target.stat().st_mtime if target.exists() else 0.0
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id FROM job_artifacts WHERE job_id = ? AND kind = ? AND path = ?",
                (job_id, kind, str(target)),
            ).fetchone()
            if row:
                connection.execute(
                    """
                    UPDATE job_artifacts
                    SET size = ?, mtime = ?, status = ?, metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (size, mtime, status, encode_json(metadata or {}), now, row["id"]),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO job_artifacts (
                        job_id, kind, path, size, mtime, status, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (job_id, kind, str(target), size, mtime, status, encode_json(metadata or {}), now, now),
                )

    def get_artifacts(self, job_id: str) -> list[dict]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM job_artifacts WHERE job_id = ? ORDER BY kind, path",
                (job_id,),
            ).fetchall()
        return [artifact for row in rows if (artifact := row_to_artifact(row))]

    def pause_job(self, job_id: str) -> None:
        self.update_job(job_id, status="paused", current_stage="paused")
        self.add_event(job_id, "flow_pause_requested", {}, message="Pause requested")

    def resume_job(self, job_id: str) -> None:
        job = self.get_job(job_id) or {}
        next_status = "running" if job.get("started_at") or job.get("worker_pid") else "queued"
        self.update_job(job_id, status=next_status, current_stage="resuming")
        self.add_event(job_id, "flow_resumed", {}, message="Resume requested")

    def cancel_job(self, job_id: str) -> None:
        self.update_job(job_id, status="cancel_requested", current_stage="cancel_requested")
        self.add_event(job_id, "cancel_requested", {}, message="Cancel requested")
