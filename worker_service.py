from __future__ import annotations

import argparse
import json
import os
import signal
import time
import traceback
from pathlib import Path

from .job_store import JobStore, ACTIVE_STATUSES
from .pipeline_core import write_json
from .pipeline_runner import compute_output_dir, run_pipeline_from_config


LEASE_SECONDS = 120
POLL_SECONDS = 2.0


class JobCancelled(RuntimeError):
    pass


class PipelineWorker:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.stop_requested = False
        self.current_job_id = ""

    def request_stop(self, *_args: object) -> None:
        self.stop_requested = True

    def run_forever(self, *, once: bool = False) -> None:
        self.store.initialize()
        while not self.stop_requested:
            job = self.store.claim_next_job(worker_pid=os.getpid(), lease_seconds=LEASE_SECONDS)
            if job:
                self.run_job(job)
                if once:
                    return
            elif once:
                return
            else:
                time.sleep(POLL_SECONDS)

    def run_job(self, job: dict) -> None:
        job_id = str(job["id"])
        self.current_job_id = job_id
        config = dict(job.get("config") or {})
        video_path = str(job.get("input_path") or "")
        output_dir = compute_output_dir(video_path)
        self.store.update_job(
            job_id,
            status="running",
            current_stage="starting",
            progress=1,
            output_dir=str(output_dir),
            worker_pid=os.getpid(),
        )
        self.store.upsert_artifact(job_id, "effective_config", output_dir / "00_effective_config.json", status="planned")

        def callback(stage: str, payload: dict) -> None:
            safe_payload = dict(payload or {})
            progress = self.progress_for_stage(stage, safe_payload)
            self.store.update_job(
                job_id,
                status="running",
                current_stage=stage,
                progress=progress,
                worker_pid=os.getpid(),
            )
            self.store.add_event(job_id, stage, safe_payload)
            self.store.upsert_checkpoint(
                job_id,
                stage,
                status="complete" if stage.endswith("_complete") or stage in {"complete", "load_existing_segments"} else "running",
                payload=safe_payload,
                output_path=str(safe_payload.get("path") or safe_payload.get("output_dir") or ""),
            )
            self.record_payload_artifacts(job_id, safe_payload)
            self.store.update_heartbeat(job_id, lease_seconds=LEASE_SECONDS)

        def control_callback(stage: str, payload: dict | None = None) -> None:
            self.store.update_heartbeat(job_id, lease_seconds=LEASE_SECONDS)
            current = self.store.get_job(job_id)
            status = str((current or {}).get("status") or "")
            if status == "cancel_requested" or self.stop_requested:
                raise JobCancelled("Job cancelled")
            if status == "paused":
                self.store.add_event(
                    job_id,
                    "flow_paused",
                    {"pause_stage": stage, **(payload or {})},
                    message="Job paused at checkpoint",
                )
                while not self.stop_requested:
                    time.sleep(1.0)
                    self.store.update_heartbeat(job_id, lease_seconds=LEASE_SECONDS)
                    current = self.store.get_job(job_id)
                    status = str((current or {}).get("status") or "")
                    if status == "cancel_requested":
                        raise JobCancelled("Job cancelled")
                    if status != "paused":
                        self.store.add_event(
                            job_id,
                            "flow_resumed",
                            {"resume_stage": stage},
                            message="Job resumed",
                        )
                        break

        try:
            self.store.add_event(job_id, "starting", {"input_path": video_path}, message="Pipeline started")
            manifest = run_pipeline_from_config(
                video_path=video_path,
                config=config,
                callback=callback,
                control_callback=control_callback,
            )
            manifest_path = self.write_manifest_if_needed(output_dir, manifest)
            qa = manifest.get("qa") if isinstance(manifest.get("qa"), dict) else {}
            final_status = "succeeded" if qa.get("pass", True) else "succeeded_with_qa_issues"
            self.record_manifest_artifacts(job_id, manifest)
            self.store.update_job(
                job_id,
                status=final_status,
                current_stage="complete",
                progress=100,
                manifest_path=str(manifest_path),
            )
            self.store.add_event(job_id, "complete", manifest, message="Pipeline completed")
        except JobCancelled as exc:
            self.store.update_job(
                job_id,
                status="cancelled",
                current_stage="cancelled",
                progress=self.progress_for_stage("cancelled", {}),
                error={"message": str(exc)},
            )
            self.store.add_event(job_id, "cancelled", {"message": str(exc)}, level="warning")
        except Exception as exc:
            traceback_text = traceback.format_exc()
            self.store.update_job(
                job_id,
                status="failed",
                current_stage="error",
                progress=100,
                error={"message": str(exc), "traceback": traceback_text},
            )
            self.store.add_event(
                job_id,
                "error",
                {"message": str(exc), "traceback": traceback_text},
                level="error",
                message=str(exc),
            )
        finally:
            self.current_job_id = ""

    @staticmethod
    def progress_for_stage(stage: str, payload: dict) -> int:
        if stage == "translation_chunk_complete":
            total = int(payload.get("chunk_total") or 0)
            index = int(payload.get("chunk_index") or 0)
            if total:
                return 72 + int(round(max(0.0, min(1.0, index / total)) * 16))
        if stage == "burn_progress":
            value = float(payload.get("progress") or 0)
            return min(99, 94 + int(round(value * 0.05)))
        stage_progress = {
            "queued": 0,
            "starting": 1,
            "init": 2,
            "probe_media": 18,
            "extract_audio_start": 22,
            "extract_audio_complete": 30,
            "asr_start": 36,
            "asr_complete": 58,
            "timing_start": 61,
            "timing_complete": 68,
            "translation_start": 72,
            "span_translation_done": 74,
            "translation_complete": 88,
            "display_rewrite_complete": 89,
            "entity_normalization_complete": 90,
            "qa_complete": 91,
            "qa_blocking_bypassed": 92,
            "burn_start": 94,
            "burn_complete": 100,
            "complete": 100,
            "error": 100,
            "cancelled": 100,
        }
        return int(stage_progress.get(stage, 50))

    def record_payload_artifacts(self, job_id: str, payload: dict) -> None:
        for key, value in payload.items():
            if not value or not isinstance(value, str):
                continue
            if key.endswith("path") or key in {"path", "output_dir", "segments_path", "report_path"}:
                target = Path(value)
                kind = self.kind_for_path(target)
                self.store.upsert_artifact(job_id, kind, target)

    def record_manifest_artifacts(self, job_id: str, manifest: dict) -> None:
        output_dir = Path(str(manifest.get("output_dir") or ""))
        if not output_dir:
            return
        subtitle_output = manifest.get("subtitle_output") if isinstance(manifest.get("subtitle_output"), dict) else {}
        burn_plan = manifest.get("burn_plan") if isinstance(manifest.get("burn_plan"), dict) else {}
        for kind, raw_path in {
            "ass": subtitle_output.get("ass_path"),
            "video": burn_plan.get("output_path"),
            "manifest": output_dir / str(manifest.get("manifest_name") or "10_manifest_bilingual.json"),
            "qa": output_dir / "07_qa_report.json",
            "entity_review": output_dir / "06f_entity_review.tsv",
            "entity_metrics": output_dir / "07i_entity_metrics.json",
        }.items():
            if raw_path:
                self.store.upsert_artifact(job_id, kind, Path(raw_path))

    @staticmethod
    def kind_for_path(path: Path) -> str:
        name = path.name.lower()
        if name.endswith(".mp4"):
            return "video"
        if name.endswith(".ass"):
            return "ass"
        if "qa" in name:
            return "qa"
        if "entity" in name and "metric" in name:
            return "entity_metrics"
        if "entity" in name and "review" in name:
            return "entity_review"
        if "manifest" in name:
            return "manifest"
        if "translated_segments" in name:
            return "segments"
        return "artifact"

    @staticmethod
    def write_manifest_if_needed(output_dir: Path, manifest: dict) -> Path:
        manifest_path = output_dir / "10_manifest_bilingual.json"
        if manifest_path.exists():
            return manifest_path
        output_dir.mkdir(parents=True, exist_ok=True)
        write_json(manifest_path, manifest)
        return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autosub SQLite-backed worker service.")
    parser.add_argument("--db", default="", help="Path to autosub_jobs.sqlite.")
    parser.add_argument("--once", action="store_true", help="Claim at most one queued job and exit.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    store = JobStore(args.db or None)
    worker = PipelineWorker(store)
    try:
        signal.signal(signal.SIGTERM, worker.request_stop)
        signal.signal(signal.SIGINT, worker.request_stop)
    except ValueError:
        pass
    worker.run_forever(once=bool(args.once))


if __name__ == "__main__":
    main()
