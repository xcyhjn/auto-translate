from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import threading
import traceback
import unicodedata
import uuid
import socket
from datetime import datetime, timezone
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .downloaders import DownloadConfig, DownloadManager, ManualImportRequired, check_idm
from .bilibili_search import build_bilibili_duplicate_report, write_bilibili_duplicate_artifacts
from .feedback_dataset import (
    BILIBILI_LABELS,
    DEFAULT_DATASET_DIR,
    build_gold_sets,
    collect_span_style_project,
    collect_style_project,
    dataset_paths,
    eval_span_style,
    eval_style,
    is_unsafe_span_learning_record,
    is_unsafe_style_learning_record,
    jsonl_file_lock,
    read_jsonl,
    save_bilibili_feedback_label,
    span_record_key,
    style_record_key,
    summarize_learning,
    validate_span_record,
    validate_style_record,
    write_jsonl,
)
from .feedback_ab_eval import (
    build_ab_eval_preview,
    read_latest_ab_eval_report,
    run_translation_ab_eval,
)
from .job_store import JobStore, ACTIVE_STATUSES
from .models import BilingualSubtitleStyle
from .media import normalize_asr_audio_mode, normalize_asr_vad_mode, probe_media
from .pipeline_core import build_output_slug, build_translation_style_prompt, burn_subtitle, create_safe_ass_copy, run_pipeline, write_json
from .pipeline_runner import compute_output_dir
from .qa import qa_final_ass_file
from .qa_outputs import build_blocker_report
from .glossary import write_youtube_glossary
from .segment_io import load_segments
from .style_learning import write_style_learning_artifacts
from .subtitle_io import write_bilingual_ass
from .workflow_profiles import (
    DEFAULT_WORKFLOW_PROFILE,
    INTERNAL_ARTIFACTS_DIR_NAME,
    apply_workflow_profile,
    ensure_top_ass_alias,
    find_existing_ass_path,
    list_workflow_profiles,
    load_dataset_profile,
    load_prompt_profile,
    normalize_subtitle_mode,
    project_artifact_path,
    summarize_dataset_profile,
)
from .youtube_meta import ensure_cover, ensure_padded_cover, fetch_youtube_info, fetch_youtube_meta, safe_project_slug, save_youtube_meta
from .span_translate import compact_span_prompt_example, read_span_examples, summarize_span_examples_for_hash, _stable_hash as stable_span_hash, DEFAULT_SPAN_EXAMPLE_TOP_K


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
ATTACHMENTS_DIR = BASE_DIR / "attachments"
WEB_DIR = BASE_DIR / "web"
CONFIG_PATH = BASE_DIR / "ui_config.json"
ERROR_LOG_PATH = BASE_DIR / "ui_server_error_trace.log"
STATE_SNAPSHOT_PATH = BASE_DIR / "ui_server_state.json"
LOCAL_FEEDBACK_DATASET_DIR = DEFAULT_DATASET_DIR
SERVER_VERSION = "20260519-stability1"
SERVER_PORT = int(os.environ.get("AUTOSUB_UI_PORT", "8777"))
LEARNING_QUALITY_SNAPSHOT_NAME = "learning_quality_snapshots.jsonl"
LEARNING_QUALITY_THRESHOLDS = {
    "style_prompt_min": 100,
    "style_eval_min": 30,
    "span_prompt_min": 20,
    "span_eval_min": 10,
    "unsafe_rate_warn": 0.05,
    "pending_warn": 50,
}
DEFAULT_HTTP_PROXY = "http://127.0.0.1:7890"
JOB_STORE = JobStore()
STATE_SNAPSHOT_VERSION = 1
STATE_STALE_TIMEOUT_SECONDS = 30 * 60
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
OPENAI_BASE_URL_ALIASES = ("OPENAI_API_BASE",)
OPENAI_RUNTIME_INJECTIONS: dict[str, dict] = {}

DEFAULT_CONFIG = {
    "workflow_profile": DEFAULT_WORKFLOW_PROFILE,
    "src_lang": "en",
    "dst_lang": "zh-Hans",
    "model": "distil-large-v3",
    "device": "cuda",
    "compute_type": "float16",
    "beam_size": 5,
    "asr_audio_mode": "off",
    "asr_audio_gain_db": 6.0,
    "asr_vad_mode": "auto",
    "translation_model": "gpt-5.4",
    "prompt_profile": "en_zh_natural_subtitle",
    "dataset_profile": "en_zh/general",
    "subtitle_mode": "bilingual_source_reference",
    "source_reference_label": "en",
    "subtitle_timing_mode": "bound",
    "zh_semantic_merge": False,
    "zh_target_min_duration": 3.5,
    "zh_target_max_duration": 7.5,
    "zh_hard_max_duration": 8.5,
    "zh_min_duration": 2.2,
    "translation_prompt": (
        "Prioritize faithful meaning over literal wording. Preserve casual spoken tone, "
        "hesitation, intimacy, jokes, sarcasm, and implied meaning when present. Translate "
        "spoken English into natural Simplified Chinese subtitles, not formal written Chinese. "
        "Keep the line concise and subtitle-friendly; do not add explanations. Absorb filler "
        "openings like And I and There is into Chinese, and use Arabic numerals for true "
        "numbers while preserving natural expressions like 一个, 一遍, 一边, 一样, and 每一行."
    ),
    "translation_chunk_size": 24,
    "translation_retries": 4,
    "openai_base_url": "",
    "proxy_url": "",
    "audio_override_path": "",
    "load_existing_segments": False,
    "force_retranslate_existing_segments": False,
    "preview_seconds": None,
    "skip_burn": False,
    "repair_high_risk_spans": True,
    "span_translation_max_spans": 4,
    "span_translation_max_segments": 4,
    "span_translation_max_duration": 12.0,
    "span_translation_min_risk_score": 10,
    "span_repair_max_spans": 12,
    "semantic_zh_allocation_enabled": True,
    "semantic_zh_allocation_max_spans": 16,
    "short_complete_sentence_display_grouping": True,
    "english_residue_validation_enabled": True,
    "english_residue_preserve_threshold": 85,
    "english_residue_review_threshold": 70,
    "enable_ai_display_rewrite": False,
    "enable_local_translation_feedback": False,
    "display_rewrite_max_ai_segments": 12,
    "bootstrap_entity_decisions": "high_confidence_only",
    "download_backend": "auto",
    "idm_exe_path": "",
    "idm_output_dir": str(INPUT_DIR),
    "idm_wait_timeout_seconds": 1800,
    "idm_stable_seconds": 8,
    "download_keep_intermediate_files": False,
    "download_manual_fallback": True,
    "style": asdict(BilingualSubtitleStyle()),
}


STYLE_DEFAULTS = asdict(BilingualSubtitleStyle())

STAGE_META = {
    "idle": {"title": "等待中", "description": "等待开始新的任务。", "overall_progress": 0},
    "download_start": {"title": "下载视频", "description": "正在拉取视频资源。", "overall_progress": 4},
    "download_complete": {"title": "下载视频", "description": "视频下载完成。", "overall_progress": 8},
    "downloading": {"title": "下载视频", "description": "正在拉取视频资源。", "overall_progress": 5},
    "merge_audio_start": {"title": "视频音频合并", "description": "正在合并外部音频。", "overall_progress": 10},
    "merge_audio_progress": {"title": "视频音频合并", "description": "正在合并外部音频。", "overall_progress": 12},
    "merge_audio_complete": {"title": "视频音频合并", "description": "外部音频已合并到视频。", "overall_progress": 15},
    "probe_media": {"title": "媒体探测", "description": "正在读取媒体信息。", "overall_progress": 18},
    "extract_audio_start": {"title": "音频提取", "description": "正在抽取 16k 单声道音频。", "overall_progress": 22},
    "extract_audio_progress": {"title": "音频提取", "description": "正在抽取 16k 单声道音频。", "overall_progress": 24},
    "extract_audio_complete": {"title": "音频提取", "description": "音频提取完成。", "overall_progress": 30},
    "enhance_audio_start": {"title": "识别音频增强", "description": "正在为 ASR 单独增强低语音轨。", "overall_progress": 31},
    "enhance_audio_progress": {"title": "识别音频增强", "description": "正在为 ASR 单独增强低语音轨。", "overall_progress": 33},
    "enhance_audio_complete": {"title": "识别音频增强", "description": "识别音频增强完成。", "overall_progress": 34},
    "asr_start": {"title": "识别中", "description": "正在执行语音识别。", "overall_progress": 36},
    "asr_attempt_start": {"title": "识别中", "description": "正在尝试更省显存的识别配置。", "overall_progress": 36},
    "asr_fallback": {"title": "识别降级", "description": "显存不足，正在切换到更低内存路径。", "overall_progress": 36},
    "asr_progress": {"title": "识别中", "description": "正在执行语音识别。", "overall_progress": 46},
    "asr_complete": {"title": "识别中", "description": "语音识别已完成。", "overall_progress": 58},
    "timing_start": {"title": "时间轴优化", "description": "正在优化字幕切分和时间轴。", "overall_progress": 61},
    "timing_complete": {"title": "时间轴优化", "description": "时间轴优化完成。", "overall_progress": 68},
    "translation_start": {"title": "翻译中", "description": "正在分块翻译字幕。", "overall_progress": 72},
    "zh_reading_groups_complete": {"title": "中文阅读轴", "description": "已按语义建立中文字幕阅读轴。", "overall_progress": 73},
    "translation_chunk_start": {"title": "翻译中", "description": "正在分块翻译字幕。", "overall_progress": 76},
    "translation_chunk_complete": {"title": "翻译中", "description": "分块翻译已返回结果。", "overall_progress": 82},
    "translation_complete": {"title": "翻译中", "description": "翻译完成。", "overall_progress": 88},
    "load_existing_segments": {"title": "翻译中", "description": "已复用既有分段结果。", "overall_progress": 88},
    "difficult_spans_detected": {"title": "难句标记", "description": "正在标记长难句、对齐漂移和可疑源文。", "overall_progress": 89},
    "span_repair_start": {"title": "难句修复", "description": "正在用 AI 局部修复高风险 span。", "overall_progress": 90},
    "span_repair_complete": {"title": "难句修复", "description": "AI 局部修复已返回结果。", "overall_progress": 90},
    "difficult_spans_final": {"title": "难句复查", "description": "正在输出最终难句 span 报告。", "overall_progress": 91},
    "qa_complete": {"title": "QA 检查", "description": "正在整理风险和警告。", "overall_progress": 91},
    "qa_blocking_bypassed": {"title": "QA 检查", "description": "QA 有风险项，已记录并继续输出。", "overall_progress": 92},
    "burn_start": {"title": "烧录中", "description": "正在写入双语字幕视频。", "overall_progress": 94},
    "burn_progress": {"title": "烧录中", "description": "正在写入双语字幕视频。", "overall_progress": 96},
    "burn_complete": {"title": "完成", "description": "烧录产物已经生成。", "overall_progress": 100},
    "complete": {"title": "完成", "description": "全部阶段已完成。", "overall_progress": 100},
    "error": {"title": "错误", "description": "任务执行失败。", "overall_progress": 100},
    "recovered_state": {"title": "已恢复", "description": "检测到上次任务中断，已释放卡住的状态。", "overall_progress": 0},
    "stale_task_detected": {"title": "任务超时", "description": "长时间没有收到心跳，已释放任务锁。", "overall_progress": 0},
}


STAGE_META.update(
    {
        "download_ytdlp_start": {"title": "yt-dlp 下载", "description": "正在使用 yt-dlp 拉取视频。", "overall_progress": 5},
        "download_ytdlp_failed": {"title": "yt-dlp 下载", "description": "yt-dlp 当前尝试失败，准备切换策略。", "overall_progress": 6},
        "download_ytdlp_complete": {"title": "yt-dlp 下载", "description": "yt-dlp 下载完成。", "overall_progress": 8},
        "download_auto_fallback": {"title": "切换到 IDM", "description": "yt-dlp 下载失败，正在尝试 IDM 桥接。", "overall_progress": 6},
        "download_extract_start": {"title": "解析直链", "description": "正在用 yt-dlp 提取真实媒体地址。", "overall_progress": 6},
        "download_extract_complete": {"title": "解析直链", "description": "已解析到可交给 IDM 的媒体地址。", "overall_progress": 7},
        "download_idm_start": {"title": "IDM 下载", "description": "已把媒体地址交给 IDM。", "overall_progress": 7},
        "download_idm_wait": {"title": "等待 IDM", "description": "正在等待 IDM 完成文件写入。", "overall_progress": 7},
        "download_idm_complete": {"title": "IDM 下载", "description": "IDM 文件下载完成。", "overall_progress": 8},
        "download_merge_start": {"title": "合并音视频", "description": "正在合并 IDM 下载的视频流和音频流。", "overall_progress": 8},
        "download_merge_complete": {"title": "合并音视频", "description": "IDM 下载的音视频已合并完成。", "overall_progress": 9},
        "download_manual_required": {"title": "等待手动导入", "description": "自动下载失败，请使用 IDM 手动下载到 input 目录。", "overall_progress": 6},
        "download_backend_unknown": {"title": "下载策略", "description": "下载策略未知，已按自动模式处理。", "overall_progress": 4},
    }
)


def default_phase_status() -> dict:
    return {
        "audio_extract": {
            "status": "idle",
            "progress": 0,
            "label": "等待中",
            "duration_seconds": 0,
            "processed_seconds": 0,
            "size_bytes": 0,
            "enhancement_mode": "off",
            "gain_db": 0,
            "enhanced_audio_path": "",
        },
        "asr": {
            "status": "idle",
            "progress": 0,
            "current": 0,
            "total": 0,
            "processed_seconds": 0,
            "duration_seconds": 0,
            "segment_count": 0,
            "label": "等待中",
            "audio_mode": "off",
            "vad_mode": "auto",
            "vad_filter": False,
            "source_audio_path": "",
            "enhanced_audio_path": "",
        },
        "translation": {
            "status": "idle",
            "progress": 0,
            "current": 0,
            "total": 0,
            "segment_count": 0,
            "fallback_count": 0,
            "elapsed_seconds": 0,
            "label": "等待中",
            "chunks": [],
        },
        "burn": {
            "status": "idle",
            "progress": 0,
            "size_bytes": 0,
            "estimated_final_size": 0,
            "processed_seconds": 0,
            "duration_seconds": 0,
            "remaining_seconds": 0,
            "speed": 0,
            "encoder": "h264_nvenc",
            "quality": 25,
            "preset": "p4",
            "decoder": "default",
            "hwaccel": "",
            "label": "等待中",
        },
    }


def default_runtime_meta() -> dict:
    return {
        "stage_key": "idle",
        "title": STAGE_META["idle"]["title"],
        "description": STAGE_META["idle"]["description"],
        "overall_progress": 0,
    }


STATE = {
    "running": False,
    "current_stage": "idle",
    "runtime": default_runtime_meta(),
    "history": [],
    "last_manifest": None,
    "last_error": None,
    "queue": [],
    "phase_status": default_phase_status(),
    "task_id": "",
    "task_started_at": "",
    "task_updated_at": "",
    "last_heartbeat_at": "",
    "stale_task": False,
    "stale_reason": "",
    "recovery": None,
    "restored_from_snapshot": False,
}
STATE_LOCK = threading.RLock()
STATE_SNAPSHOT_LOCK = threading.Lock()
FLOW_CONTROL = {
    "pause_requested": False,
    "paused": False,
    "pause_reason": "",
    "pause_stage": "",
    "updated_at": "",
}
FLOW_CONTROL_CONDITION = threading.Condition()
LAST_STATE_SNAPSHOT_AT = 0.0
INITIAL_INPUT_SNAPSHOT: set[str] = set()


def utc_now_iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), tz=timezone.utc).isoformat()


def read_state_timestamp(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 0.0
    if parsed > 0:
        return parsed
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return 0.0


def capture_state_snapshot() -> dict:
    with STATE_LOCK:
        return copy.deepcopy(STATE)


def capture_flow_control_snapshot() -> dict:
    with FLOW_CONTROL_CONDITION:
        return copy.deepcopy(FLOW_CONTROL)


def reset_flow_control() -> None:
    with FLOW_CONTROL_CONDITION:
        FLOW_CONTROL.update(
            {
                "pause_requested": False,
                "paused": False,
                "pause_reason": "",
                "pause_stage": "",
                "updated_at": utc_now_iso(),
            }
        )
        FLOW_CONTROL_CONDITION.notify_all()


def request_pause(reason: str = "user_requested") -> dict:
    with FLOW_CONTROL_CONDITION:
        FLOW_CONTROL["pause_requested"] = True
        FLOW_CONTROL["paused"] = False
        FLOW_CONTROL["pause_reason"] = reason or "user_requested"
        FLOW_CONTROL["updated_at"] = utc_now_iso()
        FLOW_CONTROL_CONDITION.notify_all()
        return copy.deepcopy(FLOW_CONTROL)


def resume_flow() -> dict:
    with FLOW_CONTROL_CONDITION:
        FLOW_CONTROL["pause_requested"] = False
        FLOW_CONTROL["paused"] = False
        FLOW_CONTROL["pause_reason"] = ""
        FLOW_CONTROL["pause_stage"] = ""
        FLOW_CONTROL["updated_at"] = utc_now_iso()
        FLOW_CONTROL_CONDITION.notify_all()
        return copy.deepcopy(FLOW_CONTROL)


def wait_if_paused(stage: str, payload: dict | None = None) -> None:
    with FLOW_CONTROL_CONDITION:
        if not FLOW_CONTROL["pause_requested"]:
            return
        FLOW_CONTROL["paused"] = True
        FLOW_CONTROL["pause_stage"] = stage
        FLOW_CONTROL["updated_at"] = utc_now_iso()
        FLOW_CONTROL_CONDITION.notify_all()
    append_history(
        "flow_paused",
        {
            "stage": stage,
            "pause_reason": capture_flow_control_snapshot().get("pause_reason", ""),
            **(payload or {}),
        },
    )
    while True:
        with FLOW_CONTROL_CONDITION:
            if not FLOW_CONTROL["pause_requested"]:
                FLOW_CONTROL["paused"] = False
                FLOW_CONTROL["pause_stage"] = ""
                FLOW_CONTROL["updated_at"] = utc_now_iso()
                break
            FLOW_CONTROL_CONDITION.wait(timeout=1.0)
        with STATE_LOCK:
            if STATE.get("running"):
                touch_task_activity_locked()
    append_history("flow_resumed", {"stage": stage})


def build_state_snapshot_payload() -> dict:
    now_ts = time.time()
    return {
        "snapshot_version": STATE_SNAPSHOT_VERSION,
        "server_version": SERVER_VERSION,
        "saved_at": utc_now_iso(now_ts),
        "saved_at_ts": now_ts,
        "state": capture_state_snapshot(),
    }


def persist_state_snapshot(*, force: bool = False) -> None:
    global LAST_STATE_SNAPSHOT_AT
    now_ts = time.time()
    with STATE_SNAPSHOT_LOCK:
        if not force and now_ts - LAST_STATE_SNAPSHOT_AT < 1.0:
            return
        payload = build_state_snapshot_payload()
        temp_path = STATE_SNAPSHOT_PATH.with_name(
            f".{STATE_SNAPSHOT_PATH.name}.{uuid.uuid4().hex}.tmp"
        )
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(STATE_SNAPSHOT_PATH)
        LAST_STATE_SNAPSHOT_AT = now_ts


def load_state_snapshot_payload() -> dict | None:
    if not STATE_SNAPSHOT_PATH.exists():
        return None
    try:
        payload = json.loads(STATE_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("snapshot_version") != STATE_SNAPSHOT_VERSION:
        return None
    state = payload.get("state")
    if not isinstance(state, dict):
        return None
    return payload


def task_activity_timestamp_locked(state: dict | None = None) -> float:
    target = state or STATE
    return max(
        read_state_timestamp(target.get("task_updated_at_ts")),
        read_state_timestamp(target.get("last_heartbeat_at_ts")),
        read_state_timestamp(target.get("task_started_at_ts")),
    )


def touch_task_activity_locked(*, now_ts: float | None = None) -> None:
    timestamp = now_ts if now_ts is not None else time.time()
    now_iso = utc_now_iso(timestamp)
    STATE["task_updated_at"] = now_iso
    STATE["task_updated_at_ts"] = timestamp
    STATE["last_heartbeat_at"] = now_iso
    STATE["last_heartbeat_at_ts"] = timestamp


def current_task_id() -> str:
    with STATE_LOCK:
        return str(STATE.get("task_id") or "")


def task_token_matches(task_id: str | None) -> bool:
    if not task_id:
        return True
    with STATE_LOCK:
        return str(STATE.get("task_id") or "") == str(task_id)


def set_recovered_state_locked(reason: str, *, source: str) -> None:
    now_ts = time.time()
    previous_stage = str(STATE.get("current_stage") or "idle")
    previous_task_id = str(STATE.get("task_id") or "")
    previous_runtime = copy.deepcopy(STATE.get("runtime") or {})

    STATE["running"] = False
    STATE["current_stage"] = "recovered_state"
    STATE["task_id"] = ""
    STATE["task_started_at"] = ""
    STATE["task_started_at_ts"] = 0.0
    touch_task_activity_locked(now_ts=now_ts)
    STATE["stale_task"] = True
    STATE["stale_reason"] = reason
    STATE["last_error"] = None
    STATE["recovery"] = {
        "message": reason,
        "source": source,
        "previous_stage": previous_stage,
        "previous_task_id": previous_task_id,
        "previous_runtime": previous_runtime,
    }
    STATE["runtime"] = {
        "stage_key": "recovered_state",
        "title": STAGE_META["recovered_state"]["title"],
        "description": reason,
        "overall_progress": 0,
        "recovery": copy.deepcopy(STATE["recovery"]),
    }
    STATE["history"].append(
        {
            "stage": "recovered_state",
            "title": STAGE_META["recovered_state"]["title"],
            "description": reason,
            "summary": {
                "source": source,
                "previous_stage": previous_stage,
            },
        }
    )
    STATE["history"] = STATE["history"][-120:]
    persist_state_snapshot(force=True)


def reconcile_runtime_state() -> bool:
    with STATE_LOCK:
        if not STATE["running"]:
            return False
        current_stage = str(STATE.get("current_stage") or "")
        if current_stage in {"idle", "complete", "error", "recovered_state"}:
            return False
        last_activity_ts = task_activity_timestamp_locked(STATE)
        if last_activity_ts <= 0:
            return False
        if time.time() - last_activity_ts < STATE_STALE_TIMEOUT_SECONDS:
            return False
        set_recovered_state_locked(
            "Previous task stopped updating and was released so the UI can continue.",
            source="stale_timeout",
        )
        persist_state_snapshot(force=True)
        return True


def restore_state_from_snapshot() -> None:
    payload = load_state_snapshot_payload()
    if not payload:
        return
    snapshot_state = payload.get("state")
    if not isinstance(snapshot_state, dict):
        return
    with STATE_LOCK:
        STATE.update(
            {
                "running": bool(snapshot_state.get("running", False)),
                "current_stage": str(snapshot_state.get("current_stage") or "idle"),
                "runtime": snapshot_state.get("runtime") if isinstance(snapshot_state.get("runtime"), dict) else default_runtime_meta(),
                "history": snapshot_state.get("history") if isinstance(snapshot_state.get("history"), list) else [],
                "last_manifest": snapshot_state.get("last_manifest"),
                "last_error": snapshot_state.get("last_error") if isinstance(snapshot_state.get("last_error"), dict) else None,
                "queue": snapshot_state.get("queue") if isinstance(snapshot_state.get("queue"), list) else [],
                "phase_status": snapshot_state.get("phase_status") if isinstance(snapshot_state.get("phase_status"), dict) else default_phase_status(),
                "task_id": str(snapshot_state.get("task_id") or ""),
                "task_started_at": str(snapshot_state.get("task_started_at") or ""),
                "task_started_at_ts": read_state_timestamp(snapshot_state.get("task_started_at_ts") or snapshot_state.get("task_started_at")),
                "task_updated_at": str(snapshot_state.get("task_updated_at") or ""),
                "task_updated_at_ts": read_state_timestamp(snapshot_state.get("task_updated_at_ts") or snapshot_state.get("task_updated_at")),
                "last_heartbeat_at": str(snapshot_state.get("last_heartbeat_at") or ""),
                "last_heartbeat_at_ts": read_state_timestamp(snapshot_state.get("last_heartbeat_at_ts") or snapshot_state.get("last_heartbeat_at")),
                "stale_task": bool(snapshot_state.get("stale_task", False)),
                "stale_reason": str(snapshot_state.get("stale_reason") or ""),
                "recovery": snapshot_state.get("recovery") if isinstance(snapshot_state.get("recovery"), dict) else None,
                "restored_from_snapshot": True,
            }
        )
        if STATE["running"]:
            set_recovered_state_locked(
                "Server restarted while a task was running. The old task was released; start a new run or reburn from the latest artifacts.",
                source="startup_snapshot",
            )
        else:
            STATE["running"] = False
        persist_state_snapshot(force=True)


def normalize_config(config: dict) -> dict:
    incoming = dict(config or {})
    base = apply_workflow_profile({**DEFAULT_CONFIG, **incoming}, DEFAULT_CONFIG)
    normalized = {**base, **incoming}
    base_style = base.get("style") if isinstance(base.get("style"), dict) else {}
    incoming_style = incoming.get("style") if isinstance(incoming.get("style"), dict) else {}
    normalized["style"] = {
        key: incoming_style.get(key, base_style.get(key, default_value))
        for key, default_value in STYLE_DEFAULTS.items()
    }
    normalized["device"] = str(normalized.get("device") or DEFAULT_CONFIG["device"]).strip().lower()
    if normalized["device"] not in {"auto", "cpu", "cuda"}:
        normalized["device"] = DEFAULT_CONFIG["device"]
    normalized["compute_type"] = str(normalized.get("compute_type") or DEFAULT_CONFIG["compute_type"]).strip().lower()
    if normalized["compute_type"] not in {"default", "float16", "int8_float16", "int8"}:
        normalized["compute_type"] = DEFAULT_CONFIG["compute_type"]
    try:
        normalized["asr_audio_mode"] = normalize_asr_audio_mode(normalized.get("asr_audio_mode"))
    except ValueError:
        normalized["asr_audio_mode"] = DEFAULT_CONFIG["asr_audio_mode"]
    try:
        normalized["asr_vad_mode"] = normalize_asr_vad_mode(normalized.get("asr_vad_mode"))
    except ValueError:
        normalized["asr_vad_mode"] = DEFAULT_CONFIG["asr_vad_mode"]
    try:
        normalized["asr_audio_gain_db"] = float(
            normalized.get("asr_audio_gain_db", DEFAULT_CONFIG["asr_audio_gain_db"])
        )
    except (TypeError, ValueError):
        normalized["asr_audio_gain_db"] = DEFAULT_CONFIG["asr_audio_gain_db"]
    normalized["force_retranslate_existing_segments"] = bool(
        normalized.get("force_retranslate_existing_segments", False)
    )
    normalized["load_existing_segments"] = bool(normalized.get("load_existing_segments", False))
    normalized["semantic_zh_allocation_enabled"] = bool(normalized.get("semantic_zh_allocation_enabled", True))
    normalized["short_complete_sentence_display_grouping"] = bool(normalized.get("short_complete_sentence_display_grouping", True))
    normalized["english_residue_validation_enabled"] = bool(normalized.get("english_residue_validation_enabled", True))
    normalized["enable_local_translation_feedback"] = bool(normalized.get("enable_local_translation_feedback", False))
    for key in (
        "span_translation_max_spans",
        "span_translation_max_segments",
        "span_translation_min_risk_score",
        "span_repair_max_spans",
        "semantic_zh_allocation_max_spans",
    ):
        try:
            normalized[key] = max(0, int(normalized.get(key, DEFAULT_CONFIG[key]) or 0))
        except (TypeError, ValueError):
            normalized[key] = DEFAULT_CONFIG[key]
    try:
        normalized["span_translation_max_duration"] = max(
            0.0,
            float(normalized.get("span_translation_max_duration", DEFAULT_CONFIG["span_translation_max_duration"]) or 0.0),
        )
    except (TypeError, ValueError):
        normalized["span_translation_max_duration"] = DEFAULT_CONFIG["span_translation_max_duration"]
    for key in ("english_residue_preserve_threshold", "english_residue_review_threshold"):
        try:
            normalized[key] = max(0, min(100, int(normalized.get(key, DEFAULT_CONFIG[key]) or DEFAULT_CONFIG[key])))
        except (TypeError, ValueError):
            normalized[key] = DEFAULT_CONFIG[key]
    normalized["subtitle_mode"] = normalize_subtitle_mode(normalized.get("subtitle_mode"))
    normalized["subtitle_timing_mode"] = str(normalized.get("subtitle_timing_mode") or "bound").strip().lower()
    if normalized["subtitle_timing_mode"] not in {"bound", "dual_axis"}:
        normalized["subtitle_timing_mode"] = "bound"
    normalized["zh_semantic_merge"] = bool(normalized.get("zh_semantic_merge", False))
    for key in ("zh_target_min_duration", "zh_target_max_duration", "zh_hard_max_duration", "zh_min_duration"):
        try:
            normalized[key] = float(normalized.get(key, DEFAULT_CONFIG[key]))
        except (TypeError, ValueError):
            normalized[key] = DEFAULT_CONFIG[key]
    bootstrap_setting = normalized.get("bootstrap_entity_decisions", DEFAULT_CONFIG["bootstrap_entity_decisions"])
    if isinstance(bootstrap_setting, bool):
        normalized["bootstrap_entity_decisions"] = "always" if bootstrap_setting else "off"
    else:
        normalized["bootstrap_entity_decisions"] = str(bootstrap_setting or DEFAULT_CONFIG["bootstrap_entity_decisions"]).strip().lower()
        if normalized["bootstrap_entity_decisions"] not in {"off", "always", "high_confidence_only"}:
            normalized["bootstrap_entity_decisions"] = DEFAULT_CONFIG["bootstrap_entity_decisions"]
    normalized["workflow_profile"] = str(normalized.get("workflow_profile") or DEFAULT_WORKFLOW_PROFILE)
    normalized["prompt_profile"] = str(normalized.get("prompt_profile") or "").strip()
    normalized["dataset_profile"] = str(normalized.get("dataset_profile") or "").strip()
    normalized["source_reference_label"] = str(
        normalized.get("source_reference_label") or normalized.get("src_lang") or "source"
    ).strip()
    env_base_url = configured_openai_base_url()
    if env_base_url:
        normalized["openai_base_url"] = env_base_url
    else:
        normalized["openai_base_url"] = str(normalized.get("openai_base_url") or "").strip()
    normalized["proxy_url"] = normalize_proxy_url(normalized.get("proxy_url"))
    return normalized


def read_config() -> dict:
    if CONFIG_PATH.exists():
        return normalize_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig")))
    return normalize_config(DEFAULT_CONFIG)


def write_config(config: dict) -> None:
    normalized = normalize_config(config)
    temp_path = CONFIG_PATH.with_name(f".{CONFIG_PATH.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(CONFIG_PATH)


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


def configured_openai_base_url() -> str:
    info = resolve_env_value(OPENAI_BASE_URL_ENV, OPENAI_BASE_URL_ALIASES)
    return str(info.get("value") or "").strip()


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


def build_openai_runtime_status(config: dict | None = None) -> dict:
    runtime = ensure_openai_runtime_env_loaded()
    base_info = resolve_env_value(OPENAI_BASE_URL_ENV, OPENAI_BASE_URL_ALIASES)
    if base_info.get("available"):
        runtime["base_url"] = build_openai_base_url_status(
            base_info,
            bool(runtime.get("base_url", {}).get("injected")),
        )
    elif config and str(config.get("openai_base_url") or "").strip():
        runtime["base_url"] = build_openai_base_url_status(
            base_info,
            bool(runtime.get("base_url", {}).get("injected")),
            config_base_url=str(config.get("openai_base_url") or "").strip(),
        )
    return runtime


def resolve_manifest_input_video(manifest: dict) -> Path:
    raw_path = str(manifest.get("input_video") or "").strip()
    if not raw_path:
        raise FileNotFoundError("Manifest input video path is empty.")
    try:
        return resolve_input_video_path(raw_path)
    except FileNotFoundError:
        fallback_name = Path(raw_path).name
        if fallback_name:
            return resolve_input_video_path(fallback_name)
        raise


def append_error_log(message: str) -> None:
    with ERROR_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message)
        handle.write("\n\n")


def is_client_disconnect_error(exc: BaseException) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror in {32, 10053, 10054}:
        return True
    errno_value = getattr(exc, "errno", None)
    return errno_value in {32, 10053, 10054}


def strip_ansi_codes(text: str) -> str:
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    cleaned = ansi_pattern.sub("", text or "")
    return cleaned.replace("\r", "").strip()


def normalize_proxy_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower() in {"none", "off", "direct", "disable", "disabled"}:
        return ""
    if "://" not in raw:
        raw = f"http://{raw}"
    return raw


def validate_proxy_url(proxy_url: str) -> str:
    if not proxy_url:
        return ""
    parsed = urlparse(proxy_url)
    if parsed.scheme not in {"http", "https", "socks5", "socks5h", "socks4"}:
        return f"Unsupported proxy scheme: {parsed.scheme or '(empty)'}"
    if not parsed.hostname:
        return f"Invalid proxy URL, missing host: {proxy_url}"
    if parsed.path and parsed.path not in {"", "/"}:
        return (
            "Proxy URL looks like a web page, not a proxy endpoint. "
            "Use a host:port address such as http://127.0.0.1:7890, not a YouTube video URL."
        )
    if parsed.query or parsed.fragment:
        return (
            "Proxy URL must not contain query strings or fragments. "
            "Use a host:port address such as http://127.0.0.1:7890."
        )
    if parsed.port is None:
        return (
            "Proxy URL is missing a port. "
            "Use a host:port address such as http://127.0.0.1:7890."
        )
    return ""


def proxy_host_port(proxy_url: str) -> tuple[str, int] | None:
    try:
        parsed = urlparse(proxy_url)
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return None
        return host, int(port)
    except Exception:
        return None


def can_connect_to_proxy(proxy_url: str, *, timeout: float = 1.5) -> bool:
    target = proxy_host_port(proxy_url)
    if not target:
        return False
    try:
        with socket.create_connection(target, timeout=timeout):
            return True
    except OSError:
        return False


def proxy_connection_error(proxy_url: str, *, timeout: float = 1.5) -> str:
    target = proxy_host_port(proxy_url)
    if not target:
        return f"Invalid proxy URL: {proxy_url}"
    try:
        with socket.create_connection(target, timeout=timeout):
            return ""
    except OSError as exc:
        return strip_ansi_codes(str(exc)) or repr(exc)


def configured_proxy_url(config: dict | None = None) -> str:
    if config is not None:
        proxy_url = normalize_proxy_url(config.get("proxy_url"))
        return "" if validate_proxy_url(proxy_url) else proxy_url
    try:
        proxy_url = normalize_proxy_url(read_config().get("proxy_url"))
        return "" if validate_proxy_url(proxy_url) else proxy_url
    except Exception:
        return ""


def build_user_facing_error_message(exc: Exception) -> str:
    raw_message = strip_ansi_codes(str(exc))
    lowered = raw_message.lower()

    if isinstance(exc, ManualImportRequired):
        return (
            f"{raw_message}\n\n"
            "操作方式：打开 input 目录，用浏览器里的 IDM 集成下载视频到这个目录；"
            "下载结束后点击“扫描 input”，再从队列启动流程。"
        )

    if "winerror 10054" in lowered:
        return (
            "下载连接被远端或代理中途断开。"
            "请检查 127.0.0.1:7890 代理是否稳定，再重试下载。"
        )

    if "operation timed out" in lowered or "timed out" in lowered:
        return "下载超时。请检查代理连通性，或稍后重试。"

    if "rate limit" in lowered or "429" in lowered:
        return "翻译接口触发了上游限流。请稍后重试，或调小 chunk size / 降低并发使用频率。"

    if "sign in to confirm" in lowered or "not a bot" in lowered or "cookies" in lowered:
        return (
            "YouTube 要求登录验证或浏览器 cookies。请先在浏览器里登录 YouTube，"
            "再确认 yt-dlp 配置里的 cookies-from-browser 可用；也可以在 UI 里填写可用代理后重试。"
        )

    if "unable to download api page" in lowered or "unable to download webpage" in lowered:
        return "无法访问视频页面。请检查代理、网络连通性或目标链接是否仍可访问。"

    if (
        ("cuda" in lowered and "out of memory" in lowered)
        or "cublas" in lowered
        or "cudnn" in lowered
    ):
        return (
            "GPU 识别后端不可用或显存不足，识别阶段已经自动降级重试。"
            "如果仍然失败，请把识别设备改成 `cpu`、计算类型改成 `int8`，"
            "或检查 CUDA 运行库后再重试。"
        )

    return raw_message or "任务执行失败。"


def build_error_payload(exc: Exception, *, proxy_url: str = "", operation: str = "") -> dict:
    user_message = build_user_facing_error_message(exc)
    raw_error = strip_ansi_codes(str(exc))
    detail_lines = [
        user_message,
        f"operation: {operation}" if operation else "",
        f"mode: {'proxy' if proxy_url else 'direct'}",
        f"proxy: {proxy_url}" if proxy_url else "",
        f"exception: {type(exc).__name__}",
        f"detail: {raw_error}" if raw_error and raw_error != user_message else "",
    ]
    return {
        "error": "\n".join(line for line in detail_lines if line),
        "error_detail": raw_error,
        "exception_type": type(exc).__name__,
        "operation": operation,
        "proxy_url": proxy_url,
        "mode": "proxy" if proxy_url else "direct",
        "traceback": traceback.format_exc(),
    }


def set_state_error(message: str, traceback_text: str) -> None:
    reset_flow_control()
    with STATE_LOCK:
        STATE["running"] = False
        STATE["current_stage"] = "error"
        STATE["task_id"] = ""
        STATE["task_started_at"] = ""
        STATE["task_started_at_ts"] = 0.0
        STATE["task_updated_at"] = utc_now_iso()
        STATE["task_updated_at_ts"] = time.time()
        STATE["last_heartbeat_at"] = STATE["task_updated_at"]
        STATE["last_heartbeat_at_ts"] = STATE["task_updated_at_ts"]
        STATE["stale_task"] = False
        STATE["stale_reason"] = ""
        STATE["recovery"] = None
        STATE["last_error"] = {
            "message": message,
            "traceback": traceback_text,
        }
        update_runtime_meta("error", {"message": message})
        STATE["history"].append(
            {
                "stage": "error",
                "title": "错误",
                "description": message,
                "summary": {"message": message},
            }
        )
        STATE["history"] = STATE["history"][-120:]
        persist_state_snapshot(force=True)


def cleanup_partial_downloads(before_paths: set[Path]) -> None:
    temp_suffixes = {".part", ".ytdl", ".temp"}
    for item in INPUT_DIR.iterdir():
        if item.resolve() in before_paths:
            continue
        try:
            if item.is_file() and (item.suffix.lower() in temp_suffixes or item.stat().st_size == 0):
                item.unlink()
        except Exception:
            continue


def ensure_proxy_environment() -> None:
    proxy_url = normalize_proxy_url(os.environ.get("AUTOSUB_PROXY_URL"))
    if not proxy_url:
        return
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if not os.environ.get(key):
            os.environ[key] = proxy_url


def normalize_lookup_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "").strip())
    collapsed = re.sub(r"\s+", " ", normalized)
    return collapsed.casefold()


def iter_input_video_files(root: Path, *, include_video_suffixes: bool = True) -> list[Path]:
    video_suffixes = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if include_video_suffixes and path.suffix.lower() not in video_suffixes:
            continue
        files.append(path)
    return sorted(files)


def list_input_videos() -> list[dict]:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    videos = []
    for path in iter_input_video_files(INPUT_DIR):
        size = path.stat().st_size
        # 0 B 的残留文件没有处理价值，也会污染输入列表。
        if size <= 0:
            continue
        videos.append(
            {
                "name": path.name,
                "stem": path.stem,
                "path": str(path),
                "size": size,
                "external": False,
                "managed": str(path.resolve()) not in INITIAL_INPUT_SNAPSHOT,
            }
        )
    return videos
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    videos = []
    for path in sorted(INPUT_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".webm"}:
            size = path.stat().st_size
            # 中断下载留下的 0 B 文件没有任何处理价值，也会污染输入列表。
            if size <= 0:
                continue
            videos.append(
                {
                    "name": path.name,
                    "stem": path.stem,
                    "path": str(path),
                    "size": size,
                    "external": False,
                    "managed": str(path.resolve()) not in INITIAL_INPUT_SNAPSHOT,
                }
            )
    return videos


def list_audio_files() -> list[dict]:
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    audios = []
    for path in sorted(ATTACHMENTS_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".flac"}:
            audios.append(
                {
                    "name": path.name,
                    "stem": path.stem,
                    "path": str(path),
                    "size": path.stat().st_size,
                    "external": False,
                }
            )
    return audios


def get_proxy_url() -> str:
    return configured_proxy_url()


def inspect_video(path: str) -> dict:
    target = resolve_input_video_path(path)
    media_info = probe_media(target)
    return {
        "path": str(target),
        "duration_seconds": media_info.duration,
        "has_audio": media_info.has_audio,
        "text_subtitle_streams": len(media_info.text_subtitle_streams),
        "image_subtitle_streams": len(media_info.image_subtitle_streams),
    }


def resolve_input_video_path(path_or_name: str) -> Path:
    raw = str(path_or_name or "").strip()
    if not raw:
        raise FileNotFoundError("Input video path is empty.")

    raw_name = Path(raw).name
    raw_name_key = normalize_lookup_text(raw_name)
    raw_path_key = normalize_lookup_text(raw)

    direct = Path(raw)
    if direct.exists() and direct.is_file():
        return direct

    candidate = INPUT_DIR / Path(raw).name
    if candidate.exists() and candidate.is_file():
        return candidate

    for item in iter_input_video_files(INPUT_DIR):
        item_name_key = normalize_lookup_text(item.name)
        item_path_key = normalize_lookup_text(str(item))
        if item.name == raw_name:
            return item
        if item_name_key == raw_name_key or item_path_key == raw_path_key:
            return item

    for item in INPUT_DIR.iterdir():
        if item.is_file() and item.name == Path(raw).name:
            return item

    raise FileNotFoundError(f"Input video not found: {raw}")


def test_proxy_connection() -> dict:
    configured_raw_proxy_url = normalize_proxy_url(read_config().get("proxy_url"))
    proxy_validation_error = validate_proxy_url(configured_raw_proxy_url)
    proxy_url = "" if proxy_validation_error else configured_raw_proxy_url
    started_at = datetime.now(timezone.utc)
    targets = []
    if configured_raw_proxy_url:
        targets.append(("proxy", configured_raw_proxy_url))
    targets.append(("youtube", "https://www.youtube.com"))
    targets.append(("youtube_image", "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg"))
    results = []

    for name, url in targets:
        entry = {"name": name, "url": url, "ok": False}
        try:
            if name == "proxy":
                if proxy_validation_error:
                    raise ValueError(proxy_validation_error)
                proxy_error = proxy_connection_error(proxy_url)
                if proxy_error:
                    raise ConnectionError(f"Proxy is not listening: {proxy_url}; {proxy_error}")
                entry["ok"] = True
                entry["status_code"] = "listening"
                results.append(entry)
                continue
            else:
                with httpx.Client(
                    proxy=proxy_url or None,
                    trust_env=not bool(proxy_url),
                    timeout=10.0,
                    follow_redirects=True,
                    headers={"User-Agent": "autosub-zh-ui-probe"},
                ) as client:
                    response = client.get(url)
            entry["ok"] = True
            entry["status_code"] = response.status_code
            entry["final_url"] = str(response.url)
        except Exception as exc:
            raw_error = strip_ansi_codes(str(exc))
            entry["error"] = build_user_facing_error_message(exc)
            if raw_error and raw_error != entry["error"]:
                entry["error"] = f"{entry['error']} | {type(exc).__name__}: {raw_error}"
            entry["raw_error"] = raw_error
            entry["exception_type"] = type(exc).__name__
        results.append(entry)

    overall_ok = all(item.get("ok") for item in results)
    checked_at = started_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "ok": overall_ok,
        "checked_at": checked_at,
        "proxy_url": configured_raw_proxy_url,
        "active_proxy_url": proxy_url,
        "proxy_validation_error": proxy_validation_error,
        "mode": "proxy" if proxy_url else "direct",
        "results": results,
    }


def scan_input_queue() -> list[dict]:
    videos = list_input_videos()
    for video in videos:
        enqueue_video(video)
    return videos


def internal_artifacts_dir(project_dir: Path) -> Path:
    return project_dir / INTERNAL_ARTIFACTS_DIR_NAME


def project_file_path(project_dir: Path, name: str) -> Path:
    return project_artifact_path(project_dir, name)


def read_project_json_file(project_dir: Path, name: str) -> dict:
    path = project_file_path(project_dir, name)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def file_entry(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size": stat.st_size,
        "mtime_ts": stat.st_mtime,
    }


def project_file_entry(project_dir: Path, file_index: dict[str, dict], name: str) -> dict | None:
    entry = file_index.get(name)
    if entry:
        return entry
    path = internal_artifacts_dir(project_dir) / name
    if path.exists() and path.is_file():
        return file_entry(path)
    return None


def resolve_project_file_entry(project_dir: Path, file_index: dict[str, dict], path_or_name: str) -> dict | None:
    raw = str(path_or_name or "").strip()
    if not raw:
        return None
    name = Path(raw).name
    if not name:
        return None
    return project_file_entry(project_dir, file_index, name)


def find_project_burned_file(project_dir: Path, file_index: dict[str, dict], manifest_payload: dict) -> dict | None:
    burn_plan = manifest_payload.get("burn_plan") if isinstance(manifest_payload.get("burn_plan"), dict) else {}
    burned_file = resolve_project_file_entry(project_dir, file_index, str(burn_plan.get("output_path") or ""))
    if burned_file:
        return burned_file
    for name, entry in file_index.items():
        if re.match(r"^09_.*\.mp4$", name, flags=re.IGNORECASE):
            return entry
    internal = internal_artifacts_dir(project_dir)
    if internal.exists():
        for item in sorted(internal.iterdir()):
            if item.is_file() and re.match(r"^09_.*\.mp4$", item.name, flags=re.IGNORECASE):
                return file_entry(item)
    return None


def build_release_artifacts(project_dir: Path, file_index: dict[str, dict], ass_file: dict | None, burned_file: dict | None) -> list[dict]:
    specs = [
        ("description", "简介", project_file_entry(project_dir, file_index, "00_youtube_info.txt")),
        ("cover", "封面", project_file_entry(project_dir, file_index, "00_youtube_cover.jpg")),
        ("cover_1280x960", "1280x960 封面", project_file_entry(project_dir, file_index, "00_youtube_cover_1280x960.jpg")),
        ("ass", "ASS 字幕", ass_file),
        ("burned_video", "烤制视频", burned_file),
    ]
    artifacts = []
    for key, label, entry in specs:
        artifacts.append(
            {
                "key": key,
                "label": label,
                "required": True,
                "present": bool(entry),
                "name": entry.get("name") if entry else "",
                "path": entry.get("path") if entry else "",
                "size": entry.get("size") if entry else 0,
                "mtime_ts": entry.get("mtime_ts") if entry else 0,
            }
        )
    return artifacts


def read_project_qa_summary(project_dir: Path) -> dict:
    qa_payload = read_project_json_file(project_dir, "07g_final_ass_qa.json") or read_project_json_file(project_dir, "07_qa_report.json")
    metrics_payload = read_project_json_file(project_dir, "07j_segmentation_qa_metrics.json")
    summary = qa_payload.get("summary") if isinstance(qa_payload.get("summary"), dict) else qa_payload
    metrics_summary = metrics_payload.get("summary") if isinstance(metrics_payload.get("summary"), dict) else metrics_payload
    blocking = 0
    warnings = 0
    for payload in (summary, metrics_summary):
        if not isinstance(payload, dict):
            continue
        blocking += int(payload.get("blocking_count") or payload.get("blocking_issue_count") or payload.get("english_residue_blocking_count") or 0)
        warnings += int(payload.get("warning_count") or payload.get("english_residue_review_count") or 0)
    return {"blocking_count": blocking, "warning_count": warnings}


def build_project_health(project_dir: Path, release_artifacts: list[dict]) -> dict:
    present = sum(1 for item in release_artifacts if item.get("present"))
    total = len(release_artifacts)
    missing = [str(item.get("label") or item.get("key")) for item in release_artifacts if not item.get("present")]
    qa = read_project_qa_summary(project_dir)
    blocking_count = int(qa.get("blocking_count") or 0)
    warning_count = int(qa.get("warning_count") or 0)
    score = int(round((present / total) * 100)) if total else 0
    if blocking_count > 0:
        score = max(0, score - min(30, blocking_count * 10))
    internal = internal_artifacts_dir(project_dir)
    internal_file_count = 0
    if internal.exists():
        internal_file_count = sum(1 for item in internal.iterdir() if item.is_file())
    return {
        "score": score,
        "ready": not missing and blocking_count == 0,
        "missing_release_artifacts": missing,
        "release_artifact_count": present,
        "release_artifact_total": total,
        "qa_blocking_count": blocking_count,
        "qa_warning_count": warning_count,
        "internal_dir": str(internal),
        "internal_file_count": internal_file_count,
        "organized": internal.exists() and internal_file_count > 0,
    }


def project_public_release_paths(project: dict) -> set[Path]:
    paths: set[Path] = set()
    for artifact in project.get("release_artifacts") or []:
        if artifact.get("present") and artifact.get("path"):
            try:
                paths.add(Path(str(artifact["path"])).resolve())
            except OSError:
                continue
    return paths


def collision_safe_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    index = 1
    while True:
        candidate = parent / f"{stem}.{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def read_output_tree() -> list[dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    projects = []
    for folder in sorted(OUTPUT_DIR.iterdir()):
        if not folder.is_dir():
            continue
        manifest_payload = read_project_json_file(folder, "10_manifest_bilingual.json")
        subtitle_output = manifest_payload.get("subtitle_output") if isinstance(manifest_payload.get("subtitle_output"), dict) else {}
        manifest_ass_name = str(subtitle_output.get("ass_name") or "").strip()
        ensure_top_ass_alias(folder, manifest_ass_name)
        files = []
        file_index: dict[str, dict] = {}
        for item in sorted(folder.iterdir()):
            if item.is_file():
                entry = file_entry(item)
                files.append(entry)
                file_index[item.name] = entry
        internal_files = []
        internal = internal_artifacts_dir(folder)
        if internal.exists():
            for item in sorted(internal.iterdir()):
                if item.is_file():
                    internal_files.append(file_entry(item))
        manifest_file = project_file_entry(folder, file_index, "10_manifest_bilingual.json")
        manifest_ass_name = str(subtitle_output.get("ass_name") or "").strip()
        ass_path = find_existing_ass_path(folder, manifest_ass_name)
        ass_file = file_index.get(ass_path.name) if ass_path else None
        burned_file = find_project_burned_file(folder, file_index, manifest_payload)
        release_artifacts = build_release_artifacts(folder, file_index, ass_file, burned_file)
        health = build_project_health(folder, release_artifacts)
        input_video = str(manifest_payload.get("input_video") or "").strip()
        projects.append(
            {
                "name": folder.name,
                "path": str(folder),
                "files": files,
                "internal_files": internal_files,
                "ass_path": ass_file.get("path") if ass_file else "",
                "ass_mtime_ts": ass_file.get("mtime_ts") if ass_file else 0,
                "burned_video_path": burned_file.get("path") if burned_file else "",
                "burned_video_mtime_ts": burned_file.get("mtime_ts") if burned_file else 0,
                "manifest_path": manifest_file.get("path") if manifest_file else "",
                "subtitle_mode": str(manifest_payload.get("subtitle_mode") or subtitle_output.get("mode") or ""),
                "input_video": input_video,
                "input_video_name": Path(input_video).name if input_video else "",
                "release_artifacts": release_artifacts,
                "health": health,
            }
        )
    return projects


def stage_title(stage: str) -> str:
    meta = STAGE_META.get(stage) or {}
    return str(meta.get("title") or stage or "stage")


def stage_description(stage: str, payload: dict | None = None) -> str:
    meta = STAGE_META.get(stage) or {}
    payload = payload or {}
    if stage == "error":
        return str(payload.get("message") or meta.get("description") or "Task failed.")
    return str(meta.get("description") or payload.get("message") or "")


def build_jobs_payload() -> dict:
    try:
        jobs = JOB_STORE.list_jobs(limit=30)
        active_job = JOB_STORE.get_active_job() or (jobs[0] if jobs else None)
        return {"jobs": jobs, "active_job": active_job}
    except Exception as exc:
        append_error_log(f"[job_store] failed to read jobs: {exc}")
        return {"jobs": [], "active_job": None}


def build_flow_control_from_jobs() -> dict | None:
    job = JOB_STORE.get_active_job()
    if not job:
        return None
    status = str(job.get("status") or "")
    return {
        "pause_requested": status == "paused",
        "paused": status == "paused",
        "pause_reason": "user_requested" if status == "paused" else "",
        "pause_stage": str(job.get("current_stage") or ""),
        "updated_at": str(job.get("updated_at") or ""),
    }


def build_compatible_state_from_jobs() -> dict | None:
    job = JOB_STORE.get_active_job() or JOB_STORE.get_latest_job()
    if not job:
        return None
    events = JOB_STORE.get_events(str(job["id"]), limit=120)
    phase_status = default_phase_status()
    history = []
    last_error = job.get("error") if isinstance(job.get("error"), dict) else None
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        stage = str(event.get("stage") or "")
        try:
            update_phase_status_for_snapshot(phase_status, stage, payload)
        except Exception:
            pass
        history.append(
            {
                "stage": stage,
                "title": stage_title(stage),
                "description": stage_description(stage, payload),
                "summary": summarize_payload(payload),
                "created_at": event.get("created_at"),
                "job_id": job.get("id"),
            }
        )
        if stage == "error" and not last_error:
            last_error = {
                "message": str(payload.get("message") or event.get("message") or "Task failed."),
                "traceback": str(payload.get("traceback") or ""),
            }
    status = str(job.get("status") or "")
    current_stage = str(job.get("current_stage") or "idle")
    running = status in ACTIVE_STATUSES
    runtime = {
        "stage_key": current_stage,
        "title": stage_title(current_stage),
        "description": stage_description(current_stage, last_error or {}),
        "overall_progress": finite_int(job.get("progress"), 0),
        "task_id": str(job.get("id") or ""),
        "job_id": str(job.get("id") or ""),
        "job_status": status,
    }
    if status == "succeeded_with_qa_issues":
        runtime["stage_key"] = "complete"
        runtime["title"] = "完成（QA 有风险）"
        runtime["description"] = "产物已生成，但 QA 报告存在错误或警告。"
        runtime["overall_progress"] = 100
    elif status == "succeeded":
        runtime["stage_key"] = "complete"
        runtime["title"] = STAGE_META["complete"]["title"]
        runtime["description"] = STAGE_META["complete"]["description"]
        runtime["overall_progress"] = 100
    elif status == "failed":
        runtime["stage_key"] = "error"
        runtime["title"] = STAGE_META["error"]["title"]
        runtime["description"] = str((last_error or {}).get("message") or "Task failed.")
        runtime["overall_progress"] = 100
    elif status == "cancelled":
        runtime["stage_key"] = "complete"
        runtime["title"] = "已取消"
        runtime["description"] = "任务已取消。"
        runtime["overall_progress"] = 100
    manifest_path = str(job.get("manifest_path") or "")
    last_manifest = None
    if manifest_path and Path(manifest_path).exists():
        try:
            last_manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except Exception:
            last_manifest = {"manifest_path": manifest_path}
    return {
        "running": running,
        "current_stage": runtime["stage_key"],
        "runtime": runtime,
        "history": history,
        "last_manifest": last_manifest,
        "last_error": last_error,
        "queue": capture_state_snapshot().get("queue", []),
        "phase_status": phase_status,
        "task_id": str(job.get("id") or "") if running else "",
        "task_started_at": str(job.get("started_at") or ""),
        "task_updated_at": str(job.get("updated_at") or ""),
        "last_heartbeat_at": str(job.get("updated_at") or ""),
        "stale_task": False,
        "stale_reason": "",
        "recovery": None,
        "restored_from_snapshot": False,
    }


def legacy_state_should_take_precedence(snapshot: dict, latest_job: dict | None) -> bool:
    if snapshot.get("running"):
        return True
    stage = str(snapshot.get("current_stage") or "idle")
    if stage in {"idle", "recovered_state"}:
        return False
    state_ts = max(
        read_state_timestamp(snapshot.get("task_updated_at_ts")),
        read_state_timestamp(snapshot.get("task_updated_at")),
        read_state_timestamp(snapshot.get("last_heartbeat_at_ts")),
        read_state_timestamp(snapshot.get("last_heartbeat_at")),
    )
    job_ts = read_state_timestamp((latest_job or {}).get("updated_at"))
    return state_ts > job_ts


def build_state_payload(job_payload: dict) -> dict:
    snapshot = capture_state_snapshot()
    latest_job = job_payload.get("active_job") if isinstance(job_payload, dict) else None
    if isinstance(latest_job, dict) and legacy_state_should_take_precedence(snapshot, latest_job):
        return snapshot
    if latest_job is None and legacy_state_should_take_precedence(snapshot, None):
        return snapshot
    return build_compatible_state_from_jobs() or snapshot


def update_phase_status_for_snapshot(phase_status: dict, stage: str, payload: dict) -> None:
    with STATE_LOCK:
        original = STATE.get("phase_status")
        try:
            STATE["phase_status"] = phase_status
            update_phase_status(stage, payload)
        finally:
            STATE["phase_status"] = original


def create_pipeline_job(video_path: str, config: dict) -> dict:
    JOB_STORE.initialize()
    if JOB_STORE.has_active_job():
        raise RuntimeError("task already running")
    resolved_path = str(resolve_input_video_path(video_path))
    normalized_config = normalize_config(config)
    output_dir = compute_output_dir(resolved_path, OUTPUT_DIR)
    job = JOB_STORE.create_job(
        input_path=resolved_path,
        output_dir=str(output_dir),
        workflow_profile=str(normalized_config.get("workflow_profile") or ""),
        config=normalized_config,
    )
    JOB_STORE.upsert_artifact(job["id"], "effective_config", output_dir / "00_effective_config.json", status="planned")
    return job


def start_worker_process() -> None:
    JOB_STORE.initialize()
    existing = []
    try:
        import subprocess as _subprocess

        result = _subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
                "Where-Object { $_.CommandLine -like '*autosub_zh.worker_service*' } | "
                "Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        existing = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        existing = []
    if existing:
        return
    log_dir = BASE_DIR / "runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = open(log_dir / "worker_stdout.log", "a", encoding="utf-8")
    stderr = open(log_dir / "worker_stderr.log", "a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, "-m", "autosub_zh.worker_service"],
        cwd=str(BASE_DIR.parent),
        stdout=stdout,
        stderr=stderr,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def build_bootstrap_payload(*, include_collections: bool) -> dict:
    reconcile_runtime_state()
    config = read_config()
    job_payload = build_jobs_payload()
    state_payload = build_state_payload(job_payload)
    active_job = job_payload["active_job"]
    if state_payload.get("task_id") and state_payload.get("running") and not JOB_STORE.get_active_job():
        active_job = None
    payload = {
        "server_version": SERVER_VERSION,
        "state": state_payload,
        "flow_control": build_flow_control_from_jobs() or capture_flow_control_snapshot(),
        "jobs": job_payload["jobs"],
        "active_job": active_job,
        "openai_runtime": build_openai_runtime_status(config),
    }
    if include_collections:
        payload["videos"] = list_input_videos()
        payload["audios"] = list_audio_files()
        payload["projects"] = read_output_tree()
        payload["config"] = config
        payload["workflow_profiles"] = list_workflow_profiles()
        payload["active_prompt_profile"] = load_prompt_profile(config.get("prompt_profile"))
        payload["active_dataset_profile"] = summarize_dataset_profile(config.get("dataset_profile"))
    return payload


def safe_filename(name: str) -> str:
    cleaned = Path(name).name.strip()
    return cleaned or "upload.bin"


def unique_destination(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / safe_filename(filename)
    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{index}{suffix}"
        index += 1
    return candidate


def save_uploaded_file(target_dir: Path, filename: str, data: bytes) -> dict:
    destination = unique_destination(target_dir, filename)
    destination.write_bytes(data)
    return {
        "name": destination.name,
        "stem": destination.stem,
        "path": str(destination),
        "size": destination.stat().st_size,
        "external": False,
        "managed": True,
    }


def enqueue_video(video: dict) -> None:
    with STATE_LOCK:
        if all(item["path"] != video["path"] for item in STATE["queue"]):
            STATE["queue"].append(video)
            persist_state_snapshot()


def is_busy() -> bool:
    try:
        if JOB_STORE.has_active_job():
            return True
    except Exception:
        pass
    reconcile_runtime_state()
    with STATE_LOCK:
        return bool(STATE["running"])


def fail_if_busy() -> None:
    if is_busy():
        raise RuntimeError("A task is already running. Please wait for it to finish before starting another one.")


def try_begin_task(stage_key: str, title: str, description: str, *, overall_progress: int = 0) -> bool:
    with STATE_LOCK:
        reconcile_runtime_state()
        if STATE["running"]:
            return False
        reset_flow_control()
        now_ts = time.time()
        STATE["running"] = True
        STATE["current_stage"] = stage_key
        STATE["history"] = []
        STATE["last_error"] = None
        STATE["last_manifest"] = None
        STATE["phase_status"] = default_phase_status()
        STATE["stale_task"] = False
        STATE["stale_reason"] = ""
        STATE["recovery"] = None
        STATE["task_id"] = uuid.uuid4().hex
        STATE["task_started_at"] = utc_now_iso(now_ts)
        STATE["task_started_at_ts"] = now_ts
        touch_task_activity_locked(now_ts=now_ts)
        STATE["runtime"] = {
            "stage_key": stage_key,
            "title": title,
            "description": description,
            "overall_progress": overall_progress,
            "task_id": STATE["task_id"],
        }
        persist_state_snapshot(force=True)
        return True


def reset_runtime_state() -> None:
    reset_flow_control()
    STATE["running"] = False
    STATE["current_stage"] = "idle"
    STATE["runtime"] = default_runtime_meta()
    STATE["history"] = []
    STATE["last_manifest"] = None
    STATE["last_error"] = None
    STATE["phase_status"] = default_phase_status()
    STATE["task_id"] = ""
    STATE["task_started_at"] = ""
    STATE["task_started_at_ts"] = 0.0
    STATE["task_updated_at"] = ""
    STATE["task_updated_at_ts"] = 0.0
    STATE["last_heartbeat_at"] = ""
    STATE["last_heartbeat_at_ts"] = 0.0
    STATE["stale_task"] = False
    STATE["stale_reason"] = ""
    STATE["recovery"] = None
    STATE["restored_from_snapshot"] = False
    persist_state_snapshot(force=True)


def summarize_payload(payload: dict) -> dict:
    summary = {}
    numeric_keys = {
        "count",
        "errors",
        "warnings",
        "chunk_index",
        "chunk_total",
        "segment_count",
        "progress",
        "size_bytes",
        "estimated_final_size",
        "processed_seconds",
        "duration_seconds",
        "remaining_seconds",
        "direct_count",
        "fallback_count",
        "span_count",
        "high_count",
        "medium_count",
        "low_count",
        "needs_ai_repair_count",
        "review_count",
        "candidate_count",
        "attempted_count",
        "repaired_segment_count",
        "failed_count",
        "rejected_count",
        "eligible_span_count",
        "virtual_chunk_current",
        "virtual_chunk_total",
        "speed",
        "gain_db",
    }
    for key, value in payload.items():
        if value in (None, "", [], {}):
            continue
        if key.endswith("path") or key.endswith("dir") or key == "url":
            summary[key] = str(value)
        elif key in numeric_keys:
            summary[key] = finite_float(value)
        elif key in {"audio_mode", "enhancement_mode", "vad_mode"}:
            summary[key] = str(value)
        elif key == "vad_filter":
            summary[key] = bool(value)
    if not summary:
        for key, value in list(payload.items())[:4]:
            if value not in (None, "", [], {}):
                summary[key] = value
    return summary


def finite_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def finite_int(value: object, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed


def update_runtime_meta(stage: str, payload: dict) -> None:
    meta = STAGE_META.get(stage, {"title": stage, "description": "", "overall_progress": 0})
    if stage == "flow_pause_requested":
        meta = {"title": "等待暂停", "description": "已收到暂停请求，将在下一个安全检查点暂停。", "overall_progress": finite_int(STATE["runtime"].get("overall_progress"), 0)}
    elif stage == "flow_paused":
        meta = {"title": "暂停中", "description": "流程已在安全检查点暂停，等待继续翻译。", "overall_progress": finite_int(STATE["runtime"].get("overall_progress"), 0)}
    elif stage == "flow_resumed":
        meta = {"title": "继续翻译", "description": "流程已恢复，继续执行后续步骤。", "overall_progress": finite_int(STATE["runtime"].get("overall_progress"), 0)}
    runtime = STATE["runtime"]
    runtime["stage_key"] = stage
    runtime["title"] = meta["title"]
    runtime["description"] = meta["description"]
    runtime["overall_progress"] = int(meta["overall_progress"])

    if stage == "burn_progress":
        runtime["overall_progress"] = min(
            99,
            94 + int(round(finite_float(payload.get("progress")) * 0.05)),
        )
    elif stage == "translation_chunk_complete":
        chunk_total = int(payload.get("chunk_total", 0) or 0)
        chunk_index = int(payload.get("chunk_index", 0) or 0)
        if chunk_total > 0:
            ratio = max(0.0, min(1.0, chunk_index / chunk_total))
            runtime["overall_progress"] = 72 + int(round(ratio * 16))
    elif stage == "asr_progress":
        duration_seconds = finite_float(payload.get("duration_seconds"))
        processed_seconds = finite_float(payload.get("processed_seconds"))
        if duration_seconds > 0:
            ratio = max(0.0, min(1.0, processed_seconds / duration_seconds))
            runtime["overall_progress"] = 36 + int(round(ratio * 22))

    if stage == "error":
        runtime["title"] = "错误"
        runtime["description"] = str(payload.get("message", "任务执行失败。"))
        runtime["overall_progress"] = 100


def update_phase_status(stage: str, payload: dict) -> None:
    phase = STATE["phase_status"]
    audio_progress = finite_float(phase["audio_extract"].get("progress"))

    if stage in {"download_start", "download_complete"}:
        phase["audio_extract"]["label"] = "等待下载完成" if stage == "download_start" else "下载完成，等待处理"
        return

    if stage == "merge_audio_start":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 5),
                "label": "正在合并外部音频",
                "duration_seconds": finite_float(payload.get("duration_seconds")),
            }
        )
        return

    if stage == "merge_audio_progress":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, finite_float(payload.get("progress")) * 0.4),
                "label": "正在合并外部音频",
                "processed_seconds": finite_float(payload.get("out_time_seconds")),
                "duration_seconds": finite_float(payload.get("duration_seconds")),
            }
        )
        return

    if stage == "merge_audio_complete":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 40),
                "label": "外部音频合并完成，准备提取音频",
                "size_bytes": int(payload.get("size_bytes", 0) or 0),
            }
        )
        return

    if stage == "probe_media":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 10),
                "label": "媒体探测完成",
                "duration_seconds": finite_float(payload.get("duration_seconds")),
            }
        )
        return

    if stage == "extract_audio_start":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 45 if audio_progress >= 40 else 15),
                "label": "正在提取音频",
                "duration_seconds": finite_float(payload.get("duration_seconds")),
            }
        )
        return

    if stage == "extract_audio_progress":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 45 + finite_float(payload.get("progress")) * 0.55 if audio_progress >= 40 else finite_float(payload.get("progress"))),
                "label": "正在提取音频",
                "processed_seconds": finite_float(payload.get("out_time_seconds")),
                "duration_seconds": finite_float(payload.get("duration_seconds")),
                "size_bytes": int(payload.get("size_bytes", 0) or 0),
            }
        )
        return

    if stage == "extract_audio_complete":
        phase["audio_extract"].update(
            {
                "status": "complete",
                "progress": 100,
                "label": "音频提取完成",
                "duration_seconds": finite_float(payload.get("duration_seconds")),
                "size_bytes": int(payload.get("size_bytes", 0) or 0),
            }
        )
        return

    if stage == "enhance_audio_start":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 65),
                "label": "正在增强识别音频",
                "enhancement_mode": str(payload.get("enhancement_mode") or "off"),
                "gain_db": finite_float(payload.get("gain_db")),
                "enhanced_audio_path": str(payload.get("path") or ""),
            }
        )
        return

    if stage == "enhance_audio_progress":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 65 + finite_float(payload.get("progress")) * 0.35),
                "label": "正在增强识别音频",
                "processed_seconds": finite_float(payload.get("out_time_seconds")),
                "duration_seconds": finite_float(payload.get("duration_seconds")),
                "size_bytes": int(payload.get("size_bytes", 0) or 0),
                "enhancement_mode": str(payload.get("enhancement_mode") or "off"),
                "gain_db": finite_float(payload.get("gain_db")),
                "enhanced_audio_path": str(payload.get("path") or ""),
            }
        )
        return

    if stage == "enhance_audio_complete":
        phase["audio_extract"].update(
            {
                "status": "complete",
                "progress": 100,
                "label": "识别音频增强完成",
                "duration_seconds": finite_float(payload.get("duration_seconds")),
                "size_bytes": int(payload.get("size_bytes", 0) or 0),
                "enhancement_mode": str(payload.get("enhancement_mode") or "off"),
                "gain_db": finite_float(payload.get("gain_db")),
                "enhanced_audio_path": str(payload.get("path") or ""),
            }
        )
        return

    if stage == "asr_start":
        phase["asr"].update(
            {
                "status": "running",
                "progress": 0,
                "label": "正在识别音频",
                "duration_seconds": finite_float(payload.get("duration_seconds")),
                "current": 0,
                "total": 0,
                "audio_mode": str(payload.get("audio_mode") or "off"),
                "vad_mode": str(payload.get("vad_mode") or "auto"),
                "vad_filter": bool(payload.get("vad_filter", False)),
                "source_audio_path": str(payload.get("source_audio_path") or ""),
                "enhanced_audio_path": str(payload.get("enhanced_audio_path") or ""),
            }
        )
        return

    if stage == "asr_attempt_start":
        phase["asr"].update(
            {
                "status": "running",
                "label": f"姝ｅ湪鍠峰姞 {payload.get('device', '')}/{payload.get('compute_type', '')}",
                "current": 0,
                "total": 0,
            }
        )
        return

    if stage == "asr_fallback":
        phase["asr"].update(
            {
                "status": "running",
                "label": str(payload.get("message") or "ASR 显存不足，正在降级重试"),
            }
        )
        return

    if stage == "asr_progress":
        duration_seconds = finite_float(payload.get("duration_seconds"))
        processed_seconds = finite_float(payload.get("processed_seconds"))
        progress = finite_float(payload.get("progress"))
        if duration_seconds > 0 and progress == 0:
            progress = round(max(0.0, min(1.0, processed_seconds / duration_seconds)) * 100, 2)
        current = finite_int(payload.get("virtual_chunk_current"))
        total = finite_int(payload.get("virtual_chunk_total"))
        phase["asr"].update(
            {
                "status": "running",
                "progress": progress,
                "current": current,
                "total": total,
                "segment_count": int(payload.get("segment_count", 0) or 0),
                "processed_seconds": processed_seconds,
                "duration_seconds": duration_seconds,
                "label": f"已处理 {current}/{total} 块",
            }
        )
        return

    if stage == "asr_complete":
        phase["asr"].update(
            {
                "status": "complete",
                "progress": 100,
                "segment_count": int(payload.get("count", 0) or 0),
                "label": f"识别完成，共 {int(payload.get('count', 0) or 0)} 段",
            }
        )
        return

    if stage == "timing_start":
        phase["asr"].update(
            {
                "status": "running",
                "progress": 100,
                "label": "正在优化时间轴",
            }
        )
        return

    if stage == "timing_complete":
        count = int(payload.get("count", 0) or 0)
        source_count = int(payload.get("source_count", 0) or 0)
        phase["asr"].update(
            {
                "status": "complete",
                "progress": 100,
                "segment_count": count,
                "label": f"打轴完成 {source_count} -> {count} 段",
            }
        )
        phase["translation"]["status"] = "running"
        phase["translation"]["label"] = "准备翻译"
        return

    if stage == "translation_start":
        phase["translation"].update(
            {
                "status": "running",
                "progress": 0,
                "current": 0,
                "total": 0,
                "segment_count": int(payload.get("segment_count", 0) or 0),
                "label": "正在初始化翻译任务",
                "chunks": [],
            }
        )
        return

    if stage == "translation_chunk_start":
        chunk_index = int(payload.get("chunk_index", 0) or 0)
        chunk_total = int(payload.get("chunk_total", 0) or 0)
        chunks = phase["translation"]["chunks"]
        while len(chunks) < chunk_total:
            chunks.append({"index": len(chunks) + 1, "status": "pending"})
        if 1 <= chunk_index <= len(chunks):
            chunks[chunk_index - 1] = {
                "index": chunk_index,
                "status": "running",
                "segment_count": int(payload.get("segment_count", 0) or 0),
            }
        phase["translation"].update(
            {
                "status": "running",
                "current": chunk_index,
                "total": chunk_total,
                "progress": round((chunk_index - 1) / chunk_total * 100, 2) if chunk_total else 0,
                "label": f"正在翻译 Chunk {chunk_index}/{chunk_total}",
            }
        )
        return

    if stage == "translation_chunk_complete":
        chunk_index = int(payload.get("chunk_index", 0) or 0)
        chunk_total = int(payload.get("chunk_total", 0) or 0)
        fallback_count = int(payload.get("fallback_count", 0) or 0)
        chunks = phase["translation"]["chunks"]
        while len(chunks) < chunk_total:
            chunks.append({"index": len(chunks) + 1, "status": "pending"})
        if 1 <= chunk_index <= len(chunks):
            chunks[chunk_index - 1] = {
                "index": chunk_index,
                "status": "fallback" if fallback_count else "done",
                "segment_count": int(payload.get("segment_count", 0) or 0),
                "fallback_count": fallback_count,
                "elapsed_seconds": finite_float(payload.get("elapsed_seconds")),
            }
        phase["translation"].update(
            {
                "status": "running",
                "current": chunk_index,
                "total": chunk_total,
                "progress": round(chunk_index / chunk_total * 100, 2) if chunk_total else 0,
                "fallback_count": fallback_count,
                "elapsed_seconds": finite_float(payload.get("elapsed_seconds")),
                "label": f"Chunk {chunk_index}/{chunk_total} 已完成",
            }
        )
        return

    if stage in {"translation_complete", "load_existing_segments"}:
        count = int(payload.get("count", 0) or 0)
        label = "已复用现有翻译结果" if stage == "load_existing_segments" else f"翻译完成，共 {count} 段"
        phase["translation"].update(
            {
                "status": "complete",
                "progress": 100,
                "label": label,
                "segment_count": count,
            }
        )
        phase["burn"]["status"] = "running"
        phase["burn"]["label"] = "准备烧录"
        return

    if stage == "difficult_spans_detected":
        span_count = int(payload.get("span_count", 0) or 0)
        ai_count = int(payload.get("needs_ai_repair_count", 0) or 0)
        phase["translation"].update(
            {
                "status": "running",
                "progress": 100,
                "label": f"已标记 {span_count} 个难句 span，待 AI 修复 {ai_count} 个",
            }
        )
        phase["burn"].update(
            {
                "status": "running",
                "label": f"难句标记完成：{span_count} 个 span",
            }
        )
        return

    if stage == "span_repair_start":
        span_index = int(payload.get("span_index", 0) or 0)
        span_total = int(payload.get("span_total", 0) or 0)
        phase["translation"].update(
            {
                "status": "running",
                "progress": 100,
                "label": f"正在修复高风险 span {span_index}/{span_total}",
            }
        )
        phase["burn"].update(
            {
                "status": "running",
                "label": f"AI 修复 span {span_index}/{span_total}",
            }
        )
        return

    if stage == "span_repair_complete":
        span_index = int(payload.get("span_index", 0) or 0)
        span_total = int(payload.get("span_total", 0) or 0)
        status = str(payload.get("status") or "done")
        repaired_count = int(payload.get("repaired_count", 0) or 0)
        status_label = {
            "repaired": f"已修复 {repaired_count} 段",
            "rejected": "已拒绝本次修复",
            "failed": "修复失败",
            "skipped": "已跳过",
        }.get(status, status)
        phase["translation"].update(
            {
                "status": "running",
                "progress": 100,
                "label": f"span {span_index}/{span_total}：{status_label}",
            }
        )
        phase["burn"].update(
            {
                "status": "running",
                "label": f"AI 难句修复进度 {span_index}/{span_total}",
            }
        )
        return

    if stage == "difficult_spans_final":
        span_count = int(payload.get("span_count", 0) or 0)
        ai_count = int(payload.get("needs_ai_repair_count", 0) or 0)
        phase["translation"].update(
            {
                "status": "complete",
                "progress": 100,
                "label": f"难句复查完成：{span_count} 个 span，仍有 {ai_count} 个待人工/后续处理",
            }
        )
        phase["burn"].update(
            {
                "status": "running",
                "label": f"难句复查完成，剩余高风险 {ai_count} 个",
            }
        )
        return

    if stage == "qa_complete":
        phase["burn"].update(
            {
                "status": "running",
                "label": f"QA 完成，警告 {int(payload.get('warnings', 0) or 0)} 条",
            }
        )
        return

    if stage == "burn_start":
        phase["burn"].update(
            {
                "status": "running",
                "progress": 0,
                "label": "正在烧录双语视频",
                "duration_seconds": finite_float(payload.get("duration_seconds")),
                "encoder": str(payload.get("encoder", "h264_nvenc")),
                "quality": int(payload.get("quality", payload.get("crf", 25)) or 25),
                "preset": str(payload.get("preset", "p4")),
                "decoder": str(payload.get("decoder", "default")),
                "hwaccel": str(payload.get("hwaccel", "")),
            }
        )
        return

    if stage == "burn_progress":
        phase["burn"].update(
            {
                "status": "running",
                "progress": finite_float(payload.get("progress")),
                "processed_seconds": finite_float(payload.get("out_time_seconds")),
                "duration_seconds": finite_float(payload.get("duration_seconds")),
                "remaining_seconds": finite_float(payload.get("remaining_seconds")),
                "size_bytes": int(payload.get("size_bytes", 0) or 0),
                "estimated_final_size": int(payload.get("estimated_final_size", 0) or 0),
                "speed": finite_float(payload.get("speed")),
                "label": "正在烧录双语视频",
            }
        )
        return

    if stage == "burn_complete":
        phase["burn"].update(
            {
                "status": "complete",
                "progress": 100,
                "size_bytes": int(payload.get("size_bytes", 0) or 0),
                "duration_seconds": finite_float(payload.get("duration_seconds")),
                "label": "烧录完成",
            }
        )
        return


def append_history(stage: str, payload: dict) -> None:
    with STATE_LOCK:
        current_task = str(STATE.get("task_id") or "")
        payload_task = str(payload.get("task_id") or current_task)
        if payload_task != current_task:
            return
        STATE["current_stage"] = stage
        update_runtime_meta(stage, payload)
        touch_task_activity_locked()
        if current_task:
            STATE["runtime"]["task_id"] = current_task
        STATE["history"].append(
            {
                "stage": stage,
                "title": STATE["runtime"]["title"],
                "description": STATE["runtime"]["description"],
                "summary": summarize_payload(payload),
            }
        )
        STATE["history"] = STATE["history"][-120:]
        update_phase_status(stage, payload)
        if stage == "complete":
            reset_flow_control()
            STATE["current_stage"] = "complete"
            STATE["running"] = False
            STATE["task_id"] = ""
            STATE["task_started_at"] = ""
            STATE["task_started_at_ts"] = 0.0
            STATE["stale_task"] = False
            STATE["stale_reason"] = ""
            STATE["recovery"] = None
        persist_state_snapshot()


def remove_output_for_video(video_path: Path) -> None:
    target_dir = OUTPUT_DIR / build_output_slug(video_path)
    if target_dir.exists() and target_dir.is_dir():
        shutil.rmtree(target_dir, ignore_errors=True)


def clear_queue() -> None:
    managed_videos = [item for item in list_input_videos() if item.get("managed")]
    for item in managed_videos:
        path = Path(item["path"])
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass
        remove_output_for_video(path)

    with STATE_LOCK:
        STATE["queue"] = []
        reset_runtime_state()


def open_output_in_explorer(project_path: str | None) -> str:
    if project_path:
        folder = Path(project_path)
    else:
        manifest = STATE.get("last_manifest") or {}
        folder = Path(manifest.get("output_dir", "")) if manifest.get("output_dir") else OUTPUT_DIR

    if not folder.exists():
        raise FileNotFoundError(f"Output folder not found: {folder}")

    candidate_names = [
        "09_burned_bilingual_video.mp4",
        "09_burned_bilingual_preview_60s.mp4",
        "08_burned_zh_video.mp4",
    ]
    selected_path = None
    for name in candidate_names:
        candidate = folder / name
        if candidate.exists():
            selected_path = candidate
            break

    if selected_path is None:
        mp4_files = sorted(folder.glob("*.mp4"))
        if mp4_files:
            selected_path = mp4_files[-1]

    import subprocess

    if selected_path is not None:
        subprocess.run(["explorer.exe", "/select,", str(selected_path)], check=False)
        return str(selected_path)

    subprocess.run(["explorer.exe", str(folder)], check=False)
    return str(folder)


def open_input_in_explorer() -> str:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    import subprocess

    subprocess.run(["explorer.exe", str(INPUT_DIR)], check=False)
    return str(INPUT_DIR)


def resolve_youtube_output_dir(meta_title: str) -> Path:
    project_name = safe_project_slug(meta_title, fallback="youtube-video")
    output_dir = OUTPUT_DIR / project_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def migrate_legacy_youtube_assets(video_id: str, target_dir: Path) -> None:
    legacy_prefix = f"youtube-{video_id}-"
    for folder in OUTPUT_DIR.iterdir():
        if not folder.is_dir() or not folder.name.startswith(legacy_prefix):
            continue
        if folder.resolve() == target_dir.resolve():
            continue
        for name in ("00_youtube_meta.json", "00_youtube_info.txt", "00_youtube_cover.jpg", "10_youtube_manifest.json"):
            source = folder / name
            destination = target_dir / name
            if source.exists() and not destination.exists():
                shutil.move(str(source), str(destination))
        try:
            if not any(folder.iterdir()):
                folder.rmdir()
        except Exception:
            pass


def youtube_assets_job(url: str, *, download_cover_only: bool = False, proxy_url: str | None = None) -> dict:
    meta = fetch_youtube_meta(url, proxy_url=normalize_proxy_url(proxy_url))
    output_dir = resolve_youtube_output_dir(meta.title)
    migrate_legacy_youtube_assets(meta.video_id, output_dir)
    save_youtube_meta(output_dir, meta)
    glossary_path = write_youtube_glossary(output_dir, meta)
    cover_path = None
    padded_cover_path = ""
    if download_cover_only:
        cover_path = ensure_cover(meta, output_dir, proxy_url=normalize_proxy_url(proxy_url))
        padded_cover_path = str(ensure_padded_cover(output_dir))
    manifest = {
        "input_url": url,
        "output_dir": str(output_dir),
        "output_path": str(output_dir),
        "meta": meta.to_dict(),
        "cover_path": str(cover_path) if cover_path else "",
        "cover_1280x960_path": padded_cover_path,
        "info_path": str(output_dir / "00_youtube_info.txt"),
        "glossary_path": str(glossary_path),
    }
    (output_dir / "10_youtube_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def youtube_info_job(url: str, *, proxy_url: str | None = None) -> dict:
    meta = fetch_youtube_info(url, proxy_url=normalize_proxy_url(proxy_url))
    output_dir = resolve_youtube_output_dir(meta.title)
    migrate_legacy_youtube_assets(meta.video_id, output_dir)
    save_youtube_meta(output_dir, meta)
    glossary_path = write_youtube_glossary(output_dir, meta)
    manifest = {
        "input_url": url,
        "output_dir": str(output_dir),
        "output_path": str(output_dir),
        "meta": meta.to_dict(),
        "info_text": meta.display_text(),
        "info_path": str(output_dir / "00_youtube_info.txt"),
        "glossary_path": str(glossary_path),
        "cover_path": "",
        "cover_1280x960_path": "",
    }
    (output_dir / "10_youtube_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def bilibili_duplicate_workflow_policy() -> dict:
    return {
        "workflow_decoupled": True,
        "blocks_translation": False,
        "blocks_download": False,
        "manual_review_only": True,
        "message": "Bilibili duplicate search is advisory. Search failures or no parsed candidates do not block download, translation, burn, or feedback learning.",
    }


def bilibili_duplicate_search_job(url: str, config: dict, youtube_meta: dict | None = None) -> dict:
    normalized_config = normalize_config({**read_config(), **config})
    configured_raw_proxy_url = normalize_proxy_url(normalized_config.get("proxy_url"))
    proxy_validation_error = validate_proxy_url(configured_raw_proxy_url)
    if proxy_validation_error:
        raise ValueError(proxy_validation_error)
    proxy_url = configured_proxy_url(normalized_config)

    meta = youtube_meta if isinstance(youtube_meta, dict) else None
    if not meta:
        meta_result = youtube_info_job(url, proxy_url=proxy_url)
        meta = meta_result.get("meta") if isinstance(meta_result.get("meta"), dict) else {}
    if not isinstance(meta, dict):
        raise RuntimeError("YouTube metadata is required to build Bilibili queries.")

    output_dir = resolve_youtube_output_dir(str(meta.get("title") or "youtube-video"))
    report = build_bilibili_duplicate_report(
        url,
        meta,
        proxy_url=proxy_url,
    )
    artifacts = write_bilibili_duplicate_artifacts(output_dir, report)
    return {
        "input_youtube_url": url,
        "output_dir": str(output_dir),
        "workflow_policy": bilibili_duplicate_workflow_policy(),
        **artifacts,
        "report": report,
    }


def bilibili_duplicate_feedback_job(payload: dict) -> dict:
    label = str(payload.get("label") or "").strip()
    if label not in BILIBILI_LABELS:
        raise ValueError(f"Unsupported label: {label}")
    report = payload.get("report")
    candidate = payload.get("candidate")
    if not isinstance(report, dict):
        raise ValueError("report required")
    if not isinstance(candidate, dict):
        raise ValueError("candidate required")
    return save_bilibili_feedback_label(
        report=report,
        candidate=candidate,
        label=label,
        human_note=str(payload.get("human_note") or ""),
        source={
            "kind": "manual_ui_feedback",
            "output_dir": str(payload.get("output_dir") or ""),
            "report_path": str(payload.get("report_path") or ""),
        },
    )


def organize_project_artifacts_job(project_path: str, preview_only: bool = False) -> dict:
    if is_busy():
        raise RuntimeError("Cannot organize project artifacts while a pipeline task is running.")
    project_dir = Path(project_path)
    if not project_dir.exists() or not project_dir.is_dir():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")

    project_snapshot = next((project for project in read_output_tree() if Path(project["path"]).resolve() == project_dir.resolve()), None)
    if not project_snapshot:
        raise FileNotFoundError(f"Project is not under output directory: {project_dir}")
    keep_paths = project_public_release_paths(project_snapshot)
    internal_dir = internal_artifacts_dir(project_dir)

    moved = []
    kept = []
    planned = []
    for item in sorted(project_dir.iterdir()):
        if item.name == INTERNAL_ARTIFACTS_DIR_NAME:
            continue
        if not item.is_file():
            continue
        try:
            resolved = item.resolve()
        except OSError:
            continue
        if resolved in keep_paths:
            kept.append(str(item))
            continue
        destination = collision_safe_destination(internal_dir / item.name)
        planned_item = {"from": str(item), "to": str(destination)}
        planned.append(planned_item)
        if not preview_only:
            internal_dir.mkdir(exist_ok=True)
            shutil.move(str(item), str(destination))
            moved.append(planned_item)

    refreshed = project_snapshot if preview_only else next((project for project in read_output_tree() if Path(project["path"]).resolve() == project_dir.resolve()), None)
    return {
        "preview_only": bool(preview_only),
        "project_path": str(project_dir),
        "internal_dir": str(internal_dir),
        "move_count": len(planned),
        "moved_count": len(moved),
        "planned": planned,
        "moved": moved,
        "kept": kept,
        "project": refreshed or project_snapshot,
        "projects": read_output_tree() if not preview_only else [],
    }


def rebuild_padded_cover_job(project_path: str) -> dict:
    output_dir = Path(project_path)
    padded_path = ensure_padded_cover(output_dir)
    manifest_path = project_file_path(output_dir, "10_youtube_manifest.json")
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_dir"] = str(output_dir)
    manifest["output_path"] = str(output_dir)
    manifest["cover_path"] = str(output_dir / "00_youtube_cover.jpg")
    manifest["cover_1280x960_path"] = str(padded_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "output_dir": str(output_dir),
        "output_path": str(output_dir),
        "cover_path": str(output_dir / "00_youtube_cover.jpg"),
        "cover_1280x960_path": str(padded_path),
    }


def learn_style_job(project_path: str) -> dict:
    project_dir = Path(project_path)
    segments_path = project_file_path(project_dir, "05_translated_segments.json")
    ass_path = find_existing_ass_path(project_dir)
    if not project_dir.exists():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")
    if not segments_path.exists():
        raise FileNotFoundError(f"Segments file not found: {segments_path}")
    if not ass_path or not ass_path.exists():
        raise FileNotFoundError(f"ASS file not found: {ass_path}")
    result = write_style_learning_artifacts(
        segments_path=segments_path,
        manual_ass_path=ass_path,
        output_dir=project_dir,
    )
    return {
        "project_path": str(project_dir),
        **result,
    }


def collect_style_feedback_job(project_path: str) -> dict:
    project_dir = Path(project_path)
    if not project_dir.exists():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")
    result = collect_style_project(project_dir)
    result["learning_source"] = "manual_ass"
    result["baseline_role"] = "05_translated_segments.json is used only as the machine baseline for ASS diff alignment."
    return result


def collect_span_feedback_job(project_path: str) -> dict:
    project_dir = Path(project_path)
    if not project_dir.exists():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")
    result = collect_span_style_project(project_dir)
    result["learning_source"] = "manual_ass"
    result["baseline_role"] = "05a/05 translated segments are used only as the machine baseline for span diff alignment."
    return result


def build_local_feedback_summary(dataset_dir: Path | None = None) -> dict:
    dataset_dir = Path(dataset_dir or LOCAL_FEEDBACK_DATASET_DIR)
    translation_edits_path = dataset_dir / "translation_edit_examples.jsonl"
    span_examples_path = dataset_dir / "span_translation_examples.jsonl"
    style_gold_path = dataset_dir / "eval_sets" / "translation_style_gold.jsonl"
    span_gold_path = dataset_dir / "eval_sets" / "span_translation_gold.jsonl"
    eval_report_path = dataset_dir / "eval_reports" / "latest_style_eval.json"
    span_eval_report_path = dataset_dir / "eval_reports" / "latest_span_translation_eval.json"
    guidelines_path = dataset_dir / "learned_style_guidelines.md"
    span_guidelines_path = dataset_dir / "learned_span_guidelines.md"
    summary_path = dataset_dir / "learning_summary.md"

    translation_records = read_jsonl(translation_edits_path)
    span_records = read_jsonl(span_examples_path)
    style_gold_records = read_jsonl(style_gold_path)
    span_gold_records = read_jsonl(span_gold_path)
    style_learning_count = sum(
        1
        for record in translation_records
        if record.get("accepted") is True
        and record.get("use_for_style_prompt") is True
        and record.get("use_for_eval") is not True
    )
    span_learning_count = sum(
        1
        for record in span_records
        if record.get("accepted") is True
        and record.get("use_for_span_prompt") is True
        and record.get("use_for_eval") is not True
    )
    eval_report: dict = {}
    if eval_report_path.exists():
        try:
            payload = json.loads(eval_report_path.read_text(encoding="utf-8"))
            eval_report = payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            eval_report = {}
    span_eval_report: dict = {}
    if span_eval_report_path.exists():
        try:
            payload = json.loads(span_eval_report_path.read_text(encoding="utf-8"))
            span_eval_report = payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            span_eval_report = {}
    guidelines_text = guidelines_path.read_text(encoding="utf-8", errors="replace") if guidelines_path.exists() else ""
    guideline_lines = [
        line.strip("- ").strip()
        for line in guidelines_text.splitlines()
        if line.strip().startswith("- ")
    ][:8]
    span_guidelines_text = span_guidelines_path.read_text(encoding="utf-8", errors="replace") if span_guidelines_path.exists() else ""
    span_guideline_lines = [
        line.strip("- ").strip()
        for line in span_guidelines_text.splitlines()
        if line.strip().startswith("- ")
    ][:8]
    return {
        "ok": True,
        "dataset_dir": str(dataset_dir),
        "paths": {
            "learning_summary": str(summary_path),
            "latest_style_eval": str(eval_report_path),
            "latest_span_eval": str(span_eval_report_path),
            "learned_style_guidelines": str(guidelines_path),
            "learned_span_guidelines": str(span_guidelines_path),
        },
        "counts": {
            "translation_edit_count": len(translation_records),
            "style_learning_count": style_learning_count,
            "style_gold_count": len(style_gold_records),
            "span_translation_example_count": len(span_records),
            "span_style_learning_count": span_learning_count,
            "span_eval_count": len(span_gold_records),
        },
        "eval": {
            "sample_count": eval_report.get("sample_count", 0),
            "sample_insufficient": bool(eval_report.get("sample_insufficient", True)),
            "metrics": eval_report.get("metrics") if isinstance(eval_report.get("metrics"), dict) else {},
            "created_at": str(eval_report.get("created_at") or ""),
        },
        "span_eval": {
            "sample_count": span_eval_report.get("sample_count", 0),
            "sample_insufficient": bool(span_eval_report.get("sample_insufficient", True)),
            "metrics": span_eval_report.get("metrics") if isinstance(span_eval_report.get("metrics"), dict) else {},
            "created_at": str(span_eval_report.get("created_at") or ""),
        },
        "guidelines": guideline_lines,
        "span_guidelines": span_guideline_lines,
        "available": {
            "learning_summary": summary_path.exists(),
            "latest_style_eval": eval_report_path.exists(),
            "latest_span_eval": span_eval_report_path.exists(),
            "learned_style_guidelines": guidelines_path.exists(),
            "learned_span_guidelines": span_guidelines_path.exists(),
        },
    }


def feedback_kind_spec(kind: str, dataset_dir: Path | None = None) -> dict:
    paths = dataset_paths(Path(dataset_dir or LOCAL_FEEDBACK_DATASET_DIR))
    normalized = str(kind or "style").strip().lower()
    if normalized in {"style", "ass", "translation"}:
        return {
            "kind": "style",
            "path": paths["translation_edits"],
            "key_func": style_record_key,
            "validator": validate_style_record,
            "prompt_flag": "use_for_style_prompt",
            "source_label": "ASS 翻译样本",
        }
    if normalized in {"span", "span_translation"}:
        return {
            "kind": "span",
            "path": paths["span_translation_examples"],
            "key_func": span_record_key,
            "validator": validate_span_record,
            "prompt_flag": "use_for_span_prompt",
            "source_label": "Span 预翻译样本",
        }
    raise ValueError(f"Unsupported feedback kind: {kind}")


def feedback_record_preview(kind: str, record: dict) -> dict:
    if kind == "span":
        manual_by_id = record.get("manual_target_by_id") if isinstance(record.get("manual_target_by_id"), dict) else {}
        machine_by_id = record.get("machine_target_by_id") if isinstance(record.get("machine_target_by_id"), dict) else {}
        return {
            "project_id": str(record.get("project_id") or ""),
            "record_id": "",
            "span_id": str(record.get("span_id") or ""),
            "segment_ids": record.get("segment_ids") if isinstance(record.get("segment_ids"), list) else [],
            "source": str(record.get("source_joined") or ""),
            "machine": " / ".join(str(machine_by_id[key]) for key in sorted(machine_by_id)),
            "manual": " / ".join(str(manual_by_id[key]) for key in sorted(manual_by_id)),
            "edit_tags": record.get("edit_tags") if isinstance(record.get("edit_tags"), list) else [],
            "learning_risk": str(record.get("learning_risk") or ""),
            "learning_recommendation": str(record.get("learning_recommendation") or ""),
            "accepted": bool(record.get("accepted")),
            "use_for_prompt": bool(record.get("use_for_span_prompt")),
            "use_for_eval": bool(record.get("use_for_eval")),
            "created_at": str(record.get("created_at") or ""),
        }
    return {
        "project_id": str(record.get("project_id") or ""),
        "record_id": "",
        "segment_id": record.get("segment_id"),
        "source": str(record.get("source_text") or ""),
        "machine": str(record.get("machine_target_text") or ""),
        "manual": str(record.get("manual_target_text") or ""),
        "edit_tags": record.get("edit_tags") if isinstance(record.get("edit_tags"), list) else [],
        "feedback_types": record.get("feedback_types") if isinstance(record.get("feedback_types"), list) else [],
        "learning_risk": str(record.get("learning_risk") or ""),
        "learning_recommendation": str(record.get("learning_recommendation") or ""),
        "accepted": bool(record.get("accepted")),
        "use_for_prompt": bool(record.get("use_for_style_prompt")),
        "use_for_eval": bool(record.get("use_for_eval")),
        "created_at": str(record.get("created_at") or ""),
    }


SPAN_PROMPT_SIGNAL_TAGS = {"semantic_reallocation", "close_open_clause", "fragment_completion", "preserve_term"}


def feedback_record_tags(record: dict) -> set[str]:
    tags: set[str] = set()
    for field in ("edit_tags", "feedback_types"):
        values = record.get(field)
        if isinstance(values, list):
            tags.update(str(item) for item in values if item)
    return tags


def is_unsafe_feedback_record(kind: str, record: dict) -> bool:
    if kind == "span":
        return is_unsafe_span_learning_record(record)
    return is_unsafe_style_learning_record(record)


def feedback_review_suggestion(kind: str, record: dict) -> dict:
    tags = feedback_record_tags(record)
    risk = str(record.get("learning_risk") or "low")
    recommendation = str(record.get("learning_recommendation") or "")
    if is_unsafe_feedback_record(kind, record):
        return {
            "suggested_action": "review_only",
            "suggestion_reason": "高风险或坏样本需要人工复核，不会批量进入 Prompt/Eval。",
            "suggestion_confidence": "high",
        }
    if recommendation == "eval_candidate":
        return {
            "suggested_action": "use_for_eval",
            "suggestion_reason": "低风险且已标记为 Eval 候选，适合保留做离线评估。",
            "suggestion_confidence": "high" if risk == "low" else "medium",
        }
    if kind == "span":
        matched_tags = sorted(tags & SPAN_PROMPT_SIGNAL_TAGS)
        if recommendation == "span_prompt_candidate" and matched_tags:
            return {
                "suggested_action": "use_for_prompt",
                "suggestion_reason": f"低风险，包含 {', '.join(matched_tags)}，可作为 Span Prompt 示例。",
                "suggestion_confidence": "high" if risk == "low" else "medium",
            }
        if recommendation == "span_prompt_candidate":
            return {
                "suggested_action": "accept_only",
                "suggestion_reason": "安全但 Span 信号较弱，建议先接受，暂不注入 Prompt/Eval。",
                "suggestion_confidence": "medium",
            }
    else:
        if recommendation == "style_prompt_candidate":
            return {
                "suggested_action": "use_for_prompt",
                "suggestion_reason": "低风险 ASS 风格样本，可作为 Prompt 示例。",
                "suggestion_confidence": "high" if risk == "low" else "medium",
            }
    if risk == "low":
        return {
            "suggested_action": "accept_only",
            "suggestion_reason": "低风险但学习信号不强，适合先接受为 review-only。",
            "suggestion_confidence": "low",
        }
    return {
        "suggested_action": "review_only",
        "suggestion_reason": "中风险或信号不明确，建议人工复核后再决定用途。",
        "suggestion_confidence": "medium",
    }


def attach_feedback_review_metadata(kind: str, record: dict, index: int, spec: dict) -> dict:
    row = feedback_record_preview(kind, record)
    row["record_id"] = spec["key_func"](record)
    row["index"] = index
    row["kind"] = spec["kind"]
    row.update(feedback_review_suggestion(kind, record))
    return row


def list_local_feedback_records(kind: str = "style", status_filter: str = "pending", limit: int = 80, dataset_dir: Path | None = None) -> dict:
    spec = feedback_kind_spec(kind, dataset_dir)
    records = read_jsonl(spec["path"])
    prompt_flag = str(spec["prompt_flag"])
    normalized_filter = str(status_filter or "pending").strip().lower()
    rows = []
    for index, record in enumerate(records):
        accepted = bool(record.get("accepted"))
        use_for_prompt = bool(record.get(prompt_flag))
        use_for_eval = bool(record.get("use_for_eval"))
        if normalized_filter == "pending" and accepted:
            continue
        if normalized_filter == "accepted" and not accepted:
            continue
        if normalized_filter == "prompt" and not use_for_prompt:
            continue
        if normalized_filter == "eval" and not use_for_eval:
            continue
        if normalized_filter == "risk" and str(record.get("learning_risk") or "") not in {"high", "medium"}:
            continue
        rows.append(attach_feedback_review_metadata(str(spec["kind"]), record, index, spec))
    rows.sort(key=lambda item: (item.get("accepted") is True, str(item.get("created_at") or "")), reverse=False)
    safe_limit = max(1, min(500, int(limit or 80)))
    return {
        "ok": True,
        "kind": spec["kind"],
        "source_label": spec["source_label"],
        "path": str(spec["path"]),
        "total": len(records),
        "filtered_count": len(rows),
        "records": rows[:safe_limit],
    }


def update_local_feedback_record(payload: dict, dataset_dir: Path | None = None) -> dict:
    kind = str(payload.get("kind") or "style")
    record_id = str(payload.get("record_id") or "").strip()
    if not record_id:
        raise ValueError("record_id required")
    spec = feedback_kind_spec(kind, dataset_dir)
    prompt_flag = str(spec["prompt_flag"])
    updates = payload.get("updates") if isinstance(payload.get("updates"), dict) else {}
    allowed_bool_fields = {"accepted", "use_for_eval", prompt_flag}
    allowed_text_fields = {"review_note"}
    with jsonl_file_lock(spec["path"]):
        records = read_jsonl(spec["path"])
        target_index = -1
        for index, record in enumerate(records):
            if spec["key_func"](record) == record_id:
                target_index = index
                break
        if target_index < 0:
            raise FileNotFoundError(f"Feedback record not found: {record_id}")
        next_record = dict(records[target_index])
        for field in allowed_bool_fields:
            if field in updates:
                next_record[field] = bool(updates[field])
        for field in allowed_text_fields:
            if field in updates:
                next_record[field] = str(updates[field] or "").strip()
        if next_record.get("use_for_eval") or next_record.get(prompt_flag):
            next_record["accepted"] = True
        if next_record.get("use_for_eval") and next_record.get(prompt_flag):
            if prompt_flag in updates and updates.get(prompt_flag):
                next_record["use_for_eval"] = False
            else:
                next_record[prompt_flag] = False
        validation_errors: list[str] = []
        spec["validator"](next_record, f"{spec['path']}:{target_index + 1}", validation_errors)
        if validation_errors:
            raise ValueError("; ".join(validation_errors[:3]))
        records[target_index] = next_record
        write_jsonl(spec["path"], records)
    return {
        "ok": True,
        "kind": spec["kind"],
        "record": {
            **feedback_record_preview(str(spec["kind"]), next_record),
            "record_id": spec["key_func"](next_record),
            "index": target_index,
            "kind": spec["kind"],
        },
        "summary": build_local_feedback_summary(dataset_dir),
    }


def get_local_feedback_record_detail(kind: str = "style", record_id: str = "", dataset_dir: Path | None = None) -> dict:
    record_id = str(record_id or "").strip()
    if not record_id:
        raise ValueError("record_id required")
    spec = feedback_kind_spec(kind, dataset_dir)
    records = read_jsonl(spec["path"])
    for index, record in enumerate(records):
        if spec["key_func"](record) == record_id:
            normalized_kind = str(spec["kind"])
            preview = attach_feedback_review_metadata(normalized_kind, record, index, spec)
            return {
                "ok": True,
                "kind": normalized_kind,
                "path": str(spec["path"]),
                "record_id": record_id,
                "index": index,
                "preview": preview,
                "record": record,
                "detail": build_feedback_record_detail(normalized_kind, record),
            }
    raise FileNotFoundError(f"Feedback record not found: {record_id}")


def build_feedback_record_detail(kind: str, record: dict) -> dict:
    tags = sorted(feedback_record_tags(record))
    common = {
        "project_id": str(record.get("project_id") or ""),
        "created_at": str(record.get("created_at") or ""),
        "learning_risk": str(record.get("learning_risk") or ""),
        "learning_recommendation": str(record.get("learning_recommendation") or ""),
        "classification_reasons": record.get("classification_reasons") if isinstance(record.get("classification_reasons"), list) else [],
        "tags": tags,
        "suggestion": feedback_review_suggestion(kind, record),
    }
    if kind == "span":
        return {
            **common,
            "span_id": str(record.get("span_id") or ""),
            "segment_ids": record.get("segment_ids") if isinstance(record.get("segment_ids"), list) else [],
            "source_joined": str(record.get("source_joined") or ""),
            "translation_strategy": str(record.get("translation_strategy") or ""),
            "risk_reasons": record.get("risk_reasons") if isinstance(record.get("risk_reasons"), dict) else {},
            "context_before": record.get("context_before") if isinstance(record.get("context_before"), list) else [],
            "context_after": record.get("context_after") if isinstance(record.get("context_after"), list) else [],
            "machine_target_by_id": record.get("machine_target_by_id") if isinstance(record.get("machine_target_by_id"), dict) else {},
            "manual_target_by_id": record.get("manual_target_by_id") if isinstance(record.get("manual_target_by_id"), dict) else {},
            "prompt_example_preview": compact_span_prompt_example(record),
        }
    return {
        **common,
        "segment_id": record.get("segment_id"),
        "start": record.get("start"),
        "end": record.get("end"),
        "source_text": str(record.get("source_text") or ""),
        "machine_target_text": str(record.get("machine_target_text") or ""),
        "manual_target_text": str(record.get("manual_target_text") or ""),
        "operation_summary": record.get("operation_summary") if isinstance(record.get("operation_summary"), dict) else {},
        "quality_flags": record.get("quality_flags") if isinstance(record.get("quality_flags"), list) else [],
        "features": record.get("features") if isinstance(record.get("features"), dict) else {},
    }


def feedback_bulk_filter_match(record: dict, filters: dict, prompt_flag: str) -> bool:
    if not filters:
        return True
    status = str(filters.get("status") or "").strip().lower()
    accepted = bool(record.get("accepted"))
    use_for_prompt = bool(record.get(prompt_flag))
    use_for_eval = bool(record.get("use_for_eval"))
    if status == "pending" and accepted:
        return False
    if status == "accepted" and not accepted:
        return False
    if status == "prompt" and not use_for_prompt:
        return False
    if status == "eval" and not use_for_eval:
        return False
    risks = filters.get("learning_risk")
    if isinstance(risks, list) and risks and str(record.get("learning_risk") or "") not in {str(item) for item in risks}:
        return False
    recommendations = filters.get("recommendations")
    if isinstance(recommendations, list) and recommendations and str(record.get("learning_recommendation") or "") not in {str(item) for item in recommendations}:
        return False
    exclude_tags = set(str(item) for item in filters.get("exclude_tags") or [] if item)
    if exclude_tags and feedback_record_tags(record) & exclude_tags:
        return False
    suggested_actions = filters.get("suggested_actions")
    if isinstance(suggested_actions, list) and suggested_actions:
        suggestion = feedback_review_suggestion("span" if prompt_flag == "use_for_span_prompt" else "style", record)
        if suggestion["suggested_action"] not in {str(item) for item in suggested_actions}:
            return False
    return True


def feedback_updates_for_bulk_action(action: str, prompt_flag: str) -> dict:
    if action == "accept":
        return {"accepted": True}
    if action == "use_for_prompt":
        return {"accepted": True, prompt_flag: True, "use_for_eval": False}
    if action == "use_for_eval":
        return {"accepted": True, prompt_flag: False, "use_for_eval": True}
    if action == "clear_usage":
        return {prompt_flag: False, "use_for_eval": False}
    if action == "return_pending":
        return {"accepted": False, prompt_flag: False, "use_for_eval": False}
    raise ValueError(f"Unsupported local feedback bulk action: {action}")


def bulk_update_local_feedback_records(payload: dict, dataset_dir: Path | None = None) -> dict:
    kind = str(payload.get("kind") or "style")
    action = str(payload.get("action") or "").strip().lower().replace("-", "_")
    spec = feedback_kind_spec(kind, dataset_dir)
    prompt_flag = str(spec["prompt_flag"])
    filters = payload.get("filter") if isinstance(payload.get("filter"), dict) else {}
    record_ids = [str(item) for item in payload.get("record_ids") or [] if str(item).strip()]
    record_id_set = set(record_ids)
    limit = max(1, min(500, int(payload.get("limit") or 50)))
    updates = feedback_updates_for_bulk_action(action, prompt_flag)
    updated_rows: list[dict] = []
    skipped: list[dict] = []
    updated_count = 0

    with jsonl_file_lock(spec["path"]):
        records = read_jsonl(spec["path"])
        next_records = list(records)
        for index, record in enumerate(records):
            record_id = spec["key_func"](record)
            if record_id_set:
                if record_id not in record_id_set:
                    continue
            elif not feedback_bulk_filter_match(record, filters, prompt_flag):
                continue
            if updated_count >= limit:
                break
            if action in {"use_for_prompt", "use_for_eval"} and is_unsafe_feedback_record(str(spec["kind"]), record):
                skipped.append(
                    {
                        "record_id": record_id,
                        "reason": "高风险、bad-example 或 bad_alignment 样本不能批量进入 Prompt/Eval。",
                    }
                )
                continue
            next_record = dict(record)
            next_record.update(updates)
            validation_errors: list[str] = []
            spec["validator"](next_record, f"{spec['path']}:{index + 1}", validation_errors)
            if validation_errors:
                skipped.append({"record_id": record_id, "reason": "; ".join(validation_errors[:2])})
                continue
            next_records[index] = next_record
            updated_count += 1
            updated_rows.append(attach_feedback_review_metadata(str(spec["kind"]), next_record, index, spec))
        if updated_count:
            write_jsonl(spec["path"], next_records)

    return {
        "ok": True,
        "kind": spec["kind"],
        "action": action,
        "updated_count": updated_count,
        "skipped_count": len(skipped),
        "skipped_reasons": skipped[:20],
        "records": updated_rows,
        "review": list_local_feedback_records(
            kind=str(spec["kind"]),
            status_filter=str(filters.get("status") or payload.get("status") or "pending"),
            limit=100,
            dataset_dir=dataset_dir,
        ),
        "summary": build_learning_quality_summary(dataset_dir),
    }


def local_feedback_snapshot_path(dataset_dir: Path) -> Path:
    return dataset_dir / "eval_reports" / LEARNING_QUALITY_SNAPSHOT_NAME


def safe_number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def count_by_field(records: list[dict], field: str) -> list[dict]:
    counts: dict[str, int] = {}
    for record in records:
        key = str(record.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return [{"value": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)]


def normalize_feedback_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def compact_record_ref(kind: str, record: dict, index: int) -> dict:
    if kind == "span":
        return {
            "index": index,
            "kind": "span",
            "record_id": span_record_key(record),
            "project_id": str(record.get("project_id") or ""),
            "span_id": str(record.get("span_id") or ""),
            "segment_ids": record.get("segment_ids") if isinstance(record.get("segment_ids"), list) else [],
            "accepted": bool(record.get("accepted")),
            "use_for_prompt": bool(record.get("use_for_span_prompt")),
            "use_for_eval": bool(record.get("use_for_eval")),
            "learning_risk": str(record.get("learning_risk") or ""),
            "edit_tags": record.get("edit_tags") if isinstance(record.get("edit_tags"), list) else [],
        }
    return {
        "index": index,
        "kind": "style",
        "record_id": style_record_key(record),
        "project_id": str(record.get("project_id") or ""),
        "segment_id": record.get("segment_id"),
        "accepted": bool(record.get("accepted")),
        "use_for_prompt": bool(record.get("use_for_style_prompt")),
        "use_for_eval": bool(record.get("use_for_eval")),
        "learning_risk": str(record.get("learning_risk") or ""),
        "edit_tags": record.get("edit_tags") if isinstance(record.get("edit_tags"), list) else [],
        "feedback_types": record.get("feedback_types") if isinstance(record.get("feedback_types"), list) else [],
    }


def feedback_diagnostic_texts(kind: str, record: dict) -> tuple[str, str, str]:
    if kind == "span":
        machine_by_id = record.get("machine_target_by_id") if isinstance(record.get("machine_target_by_id"), dict) else {}
        manual_by_id = record.get("manual_target_by_id") if isinstance(record.get("manual_target_by_id"), dict) else {}
        machine_text = " ".join(str(machine_by_id[key]) for key in sorted(machine_by_id))
        manual_text = " ".join(str(manual_by_id[key]) for key in sorted(manual_by_id))
        return (
            normalize_feedback_text(record.get("source_joined")),
            normalize_feedback_text(machine_text),
            normalize_feedback_text(manual_text),
        )
    return (
        normalize_feedback_text(record.get("source_text")),
        normalize_feedback_text(record.get("machine_target_text")),
        normalize_feedback_text(record.get("manual_target_text")),
    )


def grouped_feedback_diagnostics(kind: str, records: list[dict], *, limit: int = 8) -> dict:
    duplicate_groups: dict[tuple[str, str, str], list[tuple[int, dict]]] = {}
    machine_conflicts: dict[tuple[str, str], list[tuple[int, dict, str]]] = {}
    manual_merge_groups: dict[tuple[str, str], list[tuple[int, dict, str]]] = {}
    for index, record in enumerate(records):
        source_text, machine_text, manual_text = feedback_diagnostic_texts(kind, record)
        if not source_text and not machine_text and not manual_text:
            continue
        duplicate_groups.setdefault((source_text, machine_text, manual_text), []).append((index, record))
        machine_conflicts.setdefault((source_text, machine_text), []).append((index, record, manual_text))
        manual_merge_groups.setdefault((source_text, manual_text), []).append((index, record, machine_text))

    duplicates = [
        {
            "source": key[0][:220],
            "machine": key[1][:220],
            "manual": key[2][:220],
            "count": len(items),
            "records": [compact_record_ref(kind, record, index) for index, record in items[:5]],
        }
        for key, items in duplicate_groups.items()
        if len(items) > 1
    ]
    conflicts = [
        {
            "source": key[0][:220],
            "machine": key[1][:220],
            "manual_variant_count": len({manual for _, _, manual in items}),
            "count": len(items),
            "records": [compact_record_ref(kind, record, index) for index, record, _ in items[:6]],
        }
        for key, items in machine_conflicts.items()
        if len({manual for _, _, manual in items}) > 1
    ]
    merge_candidates = [
        {
            "source": key[0][:220],
            "manual": key[1][:220],
            "machine_variant_count": len({machine for _, _, machine in items}),
            "count": len(items),
            "records": [compact_record_ref(kind, record, index) for index, record, _ in items[:6]],
        }
        for key, items in manual_merge_groups.items()
        if len({machine for _, _, machine in items}) > 1
    ]
    duplicates.sort(key=lambda item: item["count"], reverse=True)
    conflicts.sort(key=lambda item: (item["manual_variant_count"], item["count"]), reverse=True)
    merge_candidates.sort(key=lambda item: (item["machine_variant_count"], item["count"]), reverse=True)
    return {
        "duplicate_group_count": len(duplicates),
        "duplicate_record_count": sum(item["count"] for item in duplicates),
        "conflict_group_count": len(conflicts),
        "conflict_record_count": sum(item["count"] for item in conflicts),
        "merge_candidate_group_count": len(merge_candidates),
        "merge_candidate_record_count": sum(item["count"] for item in merge_candidates),
        "duplicate_groups": duplicates[:limit],
        "conflict_groups": conflicts[:limit],
        "merge_candidate_groups": merge_candidates[:limit],
    }


def build_learning_dataset_diagnostics(style_records: list[dict], span_records: list[dict]) -> dict:
    return {
        "style": grouped_feedback_diagnostics("style", style_records),
        "span": grouped_feedback_diagnostics("span", span_records),
    }


def read_learning_quality_snapshots(dataset_dir: Path, limit: int = 10) -> list[dict]:
    path = local_feedback_snapshot_path(dataset_dir)
    try:
        rows = read_jsonl(path)
    except Exception:
        return []
    return rows[-max(1, limit) :][::-1]


def append_learning_quality_snapshot(payload: dict, dataset_dir: Path) -> dict:
    path = local_feedback_snapshot_path(dataset_dir)
    quality = payload.get("quality") or {}
    counts = payload.get("counts") or {}
    eval_info = payload.get("eval") or {}
    span_eval_info = payload.get("span_eval") or {}
    metrics = eval_info.get("metrics") if isinstance(eval_info.get("metrics"), dict) else {}
    span_metrics = span_eval_info.get("metrics") if isinstance(span_eval_info.get("metrics"), dict) else {}
    record = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "score": int(quality.get("score") or 0),
        "overall_status": str(quality.get("overall_status") or "unknown"),
        "style_prompt_count": int(counts.get("style_learning_count") or 0),
        "style_eval_count": int(counts.get("style_gold_count") or 0),
        "span_prompt_count": int(counts.get("span_style_learning_count") or 0),
        "span_eval_count": int(counts.get("span_eval_count") or 0),
        "style_unsafe_rate": safe_number(metrics.get("unsafe_sample_rate"), 0.0),
        "style_signal_rate": safe_number(metrics.get("semantic_or_style_signal_rate"), 0.0),
        "span_unsafe_rate": safe_number(span_metrics.get("unsafe_sample_rate"), 0.0),
        "span_signal_rate": max(
            safe_number(span_metrics.get("semantic_reallocation_rate"), 0.0),
            safe_number(span_metrics.get("fragment_completion_rate"), 0.0),
        ),
    }
    with jsonl_file_lock(path):
        rows = read_jsonl(path)
        rows.append(record)
        write_jsonl(path, rows[-200:])
    return record


def build_learning_quality_details(
    *,
    summary: dict,
    style_records: list[dict],
    span_records: list[dict],
    dataset_dir: Path,
) -> dict:
    counts = summary.get("counts", {}) if isinstance(summary.get("counts"), dict) else {}
    eval_info = summary.get("eval", {}) if isinstance(summary.get("eval"), dict) else {}
    span_eval_info = summary.get("span_eval", {}) if isinstance(summary.get("span_eval"), dict) else {}
    eval_metrics = eval_info.get("metrics") if isinstance(eval_info.get("metrics"), dict) else {}
    span_metrics = span_eval_info.get("metrics") if isinstance(span_eval_info.get("metrics"), dict) else {}

    style_total = int(counts.get("translation_edit_count") or len(style_records))
    span_total = int(counts.get("span_translation_example_count") or len(span_records))
    style_prompt = int(counts.get("style_learning_count") or 0)
    style_eval = int(counts.get("style_gold_count") or 0)
    span_prompt = int(counts.get("span_style_learning_count") or 0)
    span_eval = int(counts.get("span_eval_count") or 0)
    pending_style = sum(1 for record in style_records if record.get("accepted") is not True)
    pending_span = sum(1 for record in span_records if record.get("accepted") is not True)

    style_high = sum(1 for record in style_records if record.get("learning_risk") == "high")
    style_medium = sum(1 for record in style_records if record.get("learning_risk") == "medium")
    span_high = sum(1 for record in span_records if record.get("learning_risk") == "high")
    span_medium = sum(1 for record in span_records if record.get("learning_risk") == "medium")
    bad_example = sum(1 for record in style_records if "bad_example" in (record.get("edit_tags") or record.get("feedback_types") or []))
    bad_alignment = sum(1 for record in span_records if "bad_alignment" in (record.get("edit_tags") or []))
    dataset_diagnostics = build_learning_dataset_diagnostics(style_records, span_records)
    conflict_total = (
        dataset_diagnostics["style"]["conflict_group_count"]
        + dataset_diagnostics["span"]["conflict_group_count"]
    )
    duplicate_total = (
        dataset_diagnostics["style"]["duplicate_group_count"]
        + dataset_diagnostics["span"]["duplicate_group_count"]
    )

    style_unsafe = safe_number(eval_metrics.get("unsafe_sample_rate"), 0.0)
    span_unsafe = safe_number(span_metrics.get("unsafe_sample_rate"), 0.0)
    unsafe_rate = max(style_unsafe, span_unsafe)
    thresholds = dict(LEARNING_QUALITY_THRESHOLDS)

    score = 0
    reasons: list[str] = []
    recommendations = {"style": [], "span": []}

    if style_prompt >= thresholds["style_prompt_min"]:
        score += 20
        recommendations["style"].append(f"ASS 学习数据较充足：已有 {style_prompt} 条 Prompt 样本，可继续关注质量而非盲目增加数量。")
    else:
        reasons.append(f"ASS Prompt 样本不足：当前 {style_prompt}/{thresholds['style_prompt_min']}。")
        recommendations["style"].append("建议优先审核高质量 ASS 样本，并将低风险样本用于 Prompt。")

    if style_eval >= thresholds["style_eval_min"]:
        score += 20
    else:
        reasons.append(f"ASS Eval 样本不足：当前 {style_eval}/{thresholds['style_eval_min']}。")
        recommendations["style"].append("建议运行 build-gold，并把一部分稳定样本保留为 Eval。")

    if span_prompt >= thresholds["span_prompt_min"]:
        score += 15
    else:
        reasons.append(f"Span 学习样本不足：当前 {span_prompt}/{thresholds['span_prompt_min']}。")
        recommendations["span"].append("Span 学习样本不足：当前还没有足够可注入 Prompt 的 Span 样本。建议先审核待审 Span。")

    if span_eval >= thresholds["span_eval_min"]:
        score += 15
    else:
        reasons.append(f"Span Eval 样本不足：当前 {span_eval}/{thresholds['span_eval_min']}。")
        recommendations["span"].append("Eval 样本不足：当前 Span Eval 不足，无法判断 Span 学习是否真的改善。")

    if unsafe_rate <= thresholds["unsafe_rate_warn"]:
        score += 15
    else:
        reasons.append(f"不安全样本率偏高：当前最高 {unsafe_rate:.1%}。")
        recommendations["style"].append("先复核中高风险样本，不要把 bad-example 或 high-risk 样本放入 Prompt/Eval。")

    pending_total = pending_style + pending_span
    if pending_total <= thresholds["pending_warn"]:
        score += 10
    else:
        reasons.append(f"待审样本过多：当前 {pending_total} 条。")
    if conflict_total:
        reasons.append(f"学习样本存在翻译冲突：当前 {conflict_total} 组同源/同机器基线对应不同人工译法。")
        recommendations["style"].append("先复核样本冲突，避免把互相矛盾的译法同时注入 Prompt 或 Eval。")
    if duplicate_total:
        recommendations["style"].append(f"发现 {duplicate_total} 组重复学习样本，可先去重或仅保留质量最高的一条。")

    latest_times = [
        str(item.get("created_at") or "")
        for item in (eval_info, span_eval_info)
        if isinstance(item, dict) and item.get("created_at")
    ]
    latest_eval_at = max(latest_times) if latest_times else ""
    if latest_eval_at or summary.get("available", {}).get("learning_summary"):
        score += 5
    else:
        reasons.append("还没有学习摘要或 Eval 报告。")

    if unsafe_rate > thresholds["unsafe_rate_warn"] or style_high or span_high or bad_example or bad_alignment:
        status = "unsafe"
    elif eval_info.get("sample_insufficient") or span_eval_info.get("sample_insufficient") or style_eval < thresholds["style_eval_min"]:
        status = "eval_insufficient"
    elif span_prompt < thresholds["span_prompt_min"] or span_eval < thresholds["span_eval_min"]:
        status = "span_insufficient"
    elif pending_total > thresholds["pending_warn"]:
        status = "review_needed"
    else:
        status = "healthy"

    if not reasons:
        reasons.append("学习数据覆盖和 Eval 状态良好，可以维持当前节奏。")

    return {
        "quality": {
            "overall_status": status,
            "score": min(100, max(0, score)),
            "reasons": reasons,
            "latest_eval_at": latest_eval_at,
            "thresholds": thresholds,
        },
        "coverage": {
            "style_prompt_ratio": safe_ratio(style_prompt, style_total),
            "style_eval_ratio": safe_ratio(style_eval, style_total),
            "span_prompt_ratio": safe_ratio(span_prompt, span_total),
            "span_eval_ratio": safe_ratio(span_eval, span_total),
            "style_pending_ratio": safe_ratio(pending_style, style_total),
            "span_pending_ratio": safe_ratio(pending_span, span_total),
        },
        "risk": {
            "style_high_risk_count": style_high,
            "style_medium_risk_count": style_medium,
            "span_high_risk_count": span_high,
            "span_medium_risk_count": span_medium,
            "bad_example_count": bad_example,
            "bad_alignment_count": bad_alignment,
        },
        "distributions": {
            "style_risk": count_by_field(style_records, "learning_risk"),
            "span_risk": count_by_field(span_records, "learning_risk"),
            "style_recommendation": count_by_field(style_records, "learning_recommendation"),
            "span_recommendation": count_by_field(span_records, "learning_recommendation"),
        },
        "dataset_diagnostics": dataset_diagnostics,
        "recommendations": recommendations,
        "history": read_learning_quality_snapshots(dataset_dir),
    }


def build_learning_quality_summary(dataset_dir: Path | None = None) -> dict:
    summary = build_local_feedback_summary(dataset_dir)
    dataset_dir = Path(dataset_dir or LOCAL_FEEDBACK_DATASET_DIR)
    paths = dataset_paths(dataset_dir)
    style_records = read_jsonl(paths["translation_edits"])
    span_records = read_jsonl(paths["span_translation_examples"])

    def count_pending(records: list[dict]) -> int:
        return sum(1 for record in records if record.get("accepted") is not True)

    def project_counts(records: list[dict]) -> list[dict]:
        counts: dict[str, int] = {}
        for record in records:
            project_id = str(record.get("project_id") or "unknown")
            counts[project_id] = counts.get(project_id, 0) + 1
        return [{"project_id": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]]

    def tag_counts(records: list[dict]) -> list[dict]:
        counts: dict[str, int] = {}
        for record in records:
            tags = record.get("edit_tags") or record.get("feedback_types") or []
            for tag in tags if isinstance(tags, list) else []:
                key = str(tag)
                counts[key] = counts.get(key, 0) + 1
        return [{"tag": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:12]]

    result = {
        "ok": True,
        "dataset_dir": str(dataset_dir),
        "counts": summary.get("counts", {}),
        "eval": summary.get("eval", {}),
        "span_eval": summary.get("span_eval", {}),
        "pending": {
            "style": count_pending(style_records),
            "span": count_pending(span_records),
        },
        "projects": {
            "style": project_counts(style_records),
            "span": project_counts(span_records),
        },
        "tags": {
            "style": tag_counts(style_records),
            "span": tag_counts(span_records),
        },
        "guidelines": summary.get("guidelines", []),
        "span_guidelines": summary.get("span_guidelines", []),
    }
    result.update(
        build_learning_quality_details(
            summary=summary,
            style_records=style_records,
            span_records=span_records,
            dataset_dir=dataset_dir,
        )
    )
    return result


def build_local_feedback_impact_preview(dataset_dir: Path | None = None) -> dict:
    dataset_dir = Path(dataset_dir or LOCAL_FEEDBACK_DATASET_DIR)
    paths = dataset_paths(dataset_dir)
    config = normalize_config(read_config())
    style_records = read_jsonl(paths["translation_edits"])
    span_records = read_jsonl(paths["span_translation_examples"])
    span_prompt_examples = read_span_examples(paths["span_translation_examples"])
    span_hash = stable_span_hash(summarize_span_examples_for_hash(span_prompt_examples))
    style_prompt_text = build_translation_style_prompt(
        translation_prompt=str(config.get("translation_prompt") or ""),
        project_style_prompt_path=None,
        enable_local_translation_feedback=bool(config.get("enable_local_translation_feedback")),
        local_feedback_style_path=paths["learned_style_guidelines"],
    )
    style_guidelines_text = (
        paths["learned_style_guidelines"].read_text(encoding="utf-8", errors="replace").strip()
        if paths["learned_style_guidelines"].exists()
        else ""
    )
    span_guidelines_text = (
        paths["learned_span_guidelines"].read_text(encoding="utf-8", errors="replace").strip()
        if paths["learned_span_guidelines"].exists()
        else ""
    )
    compact_span_examples = [compact_span_prompt_example(example) for example in span_prompt_examples[:DEFAULT_SPAN_EXAMPLE_TOP_K]]
    preview_payload = {
        "style_prompt_preview": style_prompt_text[:2500],
        "style_prompt_char_count": len(style_prompt_text),
        "style_prompt_estimated_tokens": max(1, math.ceil(len(style_prompt_text) / 3.2)) if style_prompt_text else 0,
        "style_guidelines_preview": [
            line.strip("- ").strip()
            for line in style_guidelines_text.splitlines()
            if line.strip().startswith("- ")
        ][:10],
        "span_guidelines_preview": [
            line.strip("- ").strip()
            for line in span_guidelines_text.splitlines()
            if line.strip().startswith("- ")
        ][:10],
        "span_examples_preview": compact_span_examples,
        "span_examples_char_count": len(json.dumps(compact_span_examples, ensure_ascii=False)),
        "span_examples_estimated_tokens": max(1, math.ceil(len(json.dumps(compact_span_examples, ensure_ascii=False)) / 3.2)) if compact_span_examples else 0,
    }
    style_prompt_count = sum(
        1
        for record in style_records
        if record.get("accepted") is True
        and record.get("use_for_style_prompt") is True
        and record.get("use_for_eval") is not True
    )
    style_eval_count = sum(
        1
        for record in style_records
        if record.get("accepted") is True
        and record.get("use_for_eval") is True
        and record.get("use_for_style_prompt") is not True
    )
    span_eval_count = sum(
        1
        for record in span_records
        if record.get("accepted") is True
        and record.get("use_for_eval") is True
        and record.get("use_for_span_prompt") is not True
    )
    notes: list[str] = []
    local_feedback_enabled = bool(config.get("enable_local_translation_feedback"))
    if not local_feedback_enabled:
        notes.append("本地翻译反馈当前关闭；Prompt 与 Span 示例不会注入下一次翻译。")
    if not span_prompt_examples:
        notes.append("当前没有可注入 Prompt 的 Span 示例。")
    else:
        notes.append("Span 示例库变化后，下一次 Span 预翻译会刷新相关 05a 缓存。")
    return {
        "ok": True,
        "dataset_dir": str(dataset_dir),
        "enable_local_translation_feedback": local_feedback_enabled,
        "style_prompt_count": style_prompt_count,
        "span_prompt_count": len(span_prompt_examples),
        "style_eval_count": style_eval_count,
        "span_eval_count": span_eval_count,
        "style_guidelines_available": paths["learned_style_guidelines"].exists(),
        "span_guidelines_available": paths["learned_span_guidelines"].exists(),
        "span_examples_hash": span_hash,
        "would_inject_span_examples": local_feedback_enabled and bool(span_prompt_examples),
        "max_span_examples_per_request": DEFAULT_SPAN_EXAMPLE_TOP_K,
        "would_refresh_span_cache": bool(span_prompt_examples),
        "prompt_injection_preview": preview_payload,
        "notes": notes,
    }


def build_local_feedback_ab_eval_preview(payload: dict | None = None, dataset_dir: Path | None = None) -> dict:
    dataset_dir = Path(dataset_dir or LOCAL_FEEDBACK_DATASET_DIR)
    config = normalize_config({**read_config(), **((payload or {}).get("config", {}) if isinstance((payload or {}).get("config"), dict) else {})})
    sample_count = (payload or {}).get("sample_count", 5)
    sample_kind = (payload or {}).get("sample_kind", "mixed")
    variants = (payload or {}).get("variants")
    preview = build_ab_eval_preview(
        dataset_dir,
        sample_count=sample_count,
        sample_kind=sample_kind,
        variants=variants if isinstance(variants, list) else None,
        translation_prompt=str(config.get("translation_prompt") or ""),
    )
    latest_report = read_latest_ab_eval_report(dataset_dir)
    preview["latest_report"] = {
        "available": bool(latest_report.get("available")),
        "created_at": latest_report.get("created_at", ""),
        "summary": latest_report.get("summary") if isinstance(latest_report.get("summary"), dict) else {},
    }
    preview["cost_note"] = "此操作会调用翻译模型，但不会启动完整字幕流程，也不会修改学习 JSONL。"
    return preview


def run_local_feedback_ab_eval(payload: dict, dataset_dir: Path | None = None) -> dict:
    dataset_dir = Path(dataset_dir or LOCAL_FEEDBACK_DATASET_DIR)
    ensure_openai_runtime_env_loaded()
    config_payload = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    config = normalize_config({**read_config(), **config_payload})
    report = run_translation_ab_eval(
        dataset_dir,
        sample_kind=str(payload.get("sample_kind") or "mixed"),
        sample_count=payload.get("sample_count", 5),
        variants=payload.get("variants") if isinstance(payload.get("variants"), list) else None,
        model=str(payload.get("model") or config.get("translation_model") or ""),
        translation_prompt=str(config.get("translation_prompt") or ""),
        src_lang=str(config.get("src_lang") or "en"),
        dst_lang=str(config.get("dst_lang") or "zh-Hans"),
        glossary_text="",
        base_url=str(config.get("openai_base_url") or "") or None,
    )
    return {
        "ok": True,
        "report": report,
        "summary": build_learning_quality_summary(dataset_dir),
        "preview": build_local_feedback_ab_eval_preview(payload, dataset_dir),
    }


def run_local_feedback_action(payload: dict, dataset_dir: Path | None = None) -> dict:
    dataset_dir = Path(dataset_dir or LOCAL_FEEDBACK_DATASET_DIR)
    action = str(payload.get("action") or "").strip().lower().replace("-", "_")
    action_map = {
        "summarize": summarize_learning,
        "build_gold": build_gold_sets,
        "eval_style": eval_style,
        "eval_span_style": eval_span_style,
    }
    if action not in action_map:
        raise ValueError(f"Unsupported local feedback action: {action}")
    result = action_map[action](dataset_dir)
    summary = build_learning_quality_summary(dataset_dir)
    snapshot = append_learning_quality_snapshot(summary, dataset_dir)
    summary["history"] = read_learning_quality_snapshots(dataset_dir)
    return {
        "ok": True,
        "action": action,
        "result": result,
        "snapshot": snapshot,
        "summary": summary,
    }


def execute_pipeline_job(video_path: str, config: dict, task_id: str | None = None) -> None:
    task_id = task_id or current_task_id()
    ensure_openai_runtime_env_loaded()
    style_config = dict(config.get("style") or {})
    if "en_max_words_per_line" in style_config and "en_max_single_line_chars" not in style_config:
        style_config["en_max_single_line_chars"] = max(50, int(style_config.pop("en_max_words_per_line") or 12) * 6)
    style_config.pop("en_max_words_per_line", None)
    style_config = {
        key: style_config.get(key, default_value)
        for key, default_value in STYLE_DEFAULTS.items()
    }
    style = BilingualSubtitleStyle(**style_config)
    try:
        append_error_log(
            f"[run_pipeline_job:start] video_path={video_path}\n"
            f"config_summary={{src_lang={config.get('src_lang')}, dst_lang={config.get('dst_lang')}, "
            f"model={config.get('model')}, device={config.get('device')}, compute_type={config.get('compute_type')}}}"
        )
        manifest = run_pipeline(
            input_path=video_path,
            output_root=OUTPUT_DIR,
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
            span_translation_max_spans=int(config.get("span_translation_max_spans", 4) or 0),
            span_translation_max_segments=int(config.get("span_translation_max_segments", 4) or 4),
            span_translation_max_duration=float(config.get("span_translation_max_duration", 12.0) or 12.0),
            span_translation_min_risk_score=int(config.get("span_translation_min_risk_score", 10) or 10),
            span_repair_max_spans=int(config.get("span_repair_max_spans", 12) or 12),
            semantic_zh_allocation_enabled=bool(config.get("semantic_zh_allocation_enabled", True)),
            semantic_zh_allocation_max_spans=int(config.get("semantic_zh_allocation_max_spans", 16) or 0),
            short_complete_sentence_display_grouping=bool(config.get("short_complete_sentence_display_grouping", True)),
            english_residue_validation_enabled=bool(config.get("english_residue_validation_enabled", True)),
            english_residue_preserve_threshold=int(config.get("english_residue_preserve_threshold", 85) or 85),
            english_residue_review_threshold=int(config.get("english_residue_review_threshold", 70) or 70),
            enable_ai_display_rewrite=bool(config.get("enable_ai_display_rewrite", False)),
            enable_local_translation_feedback=bool(config.get("enable_local_translation_feedback", False)),
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
            callback=lambda stage, payload: append_history(stage, {**payload, "task_id": task_id}),
            control_callback=lambda stage, payload=None: wait_if_paused(stage, {**(payload or {}), "task_id": task_id}),
        )
        append_error_log(
            f"[run_pipeline_job:complete] video_path={video_path}\n"
            f"output_dir={manifest.get('output_dir')}\n"
            f"files={len(manifest.get('files') or [])}"
        )

        with STATE_LOCK:
            if task_id and STATE.get("task_id") and STATE["task_id"] != task_id:
                return
            STATE["running"] = False
            STATE["current_stage"] = "complete"
            STATE["last_manifest"] = manifest
            STATE["task_id"] = ""
            STATE["task_started_at"] = ""
            STATE["task_started_at_ts"] = 0.0
            touch_task_activity_locked()
            STATE["stale_task"] = False
            STATE["stale_reason"] = ""
            STATE["recovery"] = None
            STATE["runtime"] = {
                "stage_key": "complete",
                "title": "完成",
                "description": "全部阶段已完成。",
                "overall_progress": 100,
            }
            persist_state_snapshot(force=True)
    except Exception as exc:
        traceback_text = traceback.format_exc()
        user_message = build_user_facing_error_message(exc)
        if task_token_matches(task_id):
            set_state_error(user_message, traceback_text)
        append_error_log(traceback_text)


def run_pipeline_job(video_path: str, config: dict) -> None:
    if not try_begin_task("starting", "准备中", "正在初始化任务。", overall_progress=1):
        append_error_log("[run_pipeline_job] task already running; skipping duplicate start request")
        return
    execute_pipeline_job(video_path, config, current_task_id())


def reburn_from_ass_job(project_path: str, task_id: str | None = None) -> dict:
    task_id = task_id or current_task_id()
    project_dir = Path(project_path)
    manifest_path = project_file_path(project_dir, "10_manifest_bilingual.json")
    translated_segments_path = project_file_path(project_dir, "05_translated_segments.json")
    if not project_dir.exists():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    subtitle_output = manifest.get("subtitle_output") if isinstance(manifest.get("subtitle_output"), dict) else {}
    ass_name = str(subtitle_output.get("ass_name") or "").strip()
    ass_path = find_existing_ass_path(project_dir, ass_name)
    burn_plan = manifest.get("burn_plan") if isinstance(manifest.get("burn_plan"), dict) else {}
    output_name = Path(str(burn_plan.get("output_path") or "09_burned_bilingual_video.mp4")).name
    output_path = project_dir / output_name

    if not ass_path or not ass_path.exists():
        raise FileNotFoundError(f"ASS file not found: {ass_path}")
    if not translated_segments_path.exists():
        raise FileNotFoundError(f"Translated segments not found: {translated_segments_path}")

    input_video = resolve_manifest_input_video(manifest)
    manifest["input_video"] = str(input_video)
    manifest["output_dir"] = str(project_dir)
    manifest["output_root"] = str(OUTPUT_DIR)
    translated_segments = load_segments(translated_segments_path)

    write_json(
        project_dir / "07g_final_ass_qa.json",
        {
            "skipped": True,
            "reason": "manual_ass_reburn_prefers_editor_translation",
            "message": "Manual ASS reburn skipped final ASS QA and burned directly from the editor-approved subtitle file.",
        },
    )
    manifest["final_ass_qa"] = {
        "path": str(project_dir / "07g_final_ass_qa.json"),
        "skipped": True,
        "reason": "manual_ass_reburn_prefers_editor_translation",
    }
    if "07g_final_ass_qa.json" not in (manifest.get("files") or []):
        manifest["files"] = [*(manifest.get("files") or []), "07g_final_ass_qa.json"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    probe = probe_media(input_video)
    burn_duration = finite_float(probe.duration)
    append_history(
        "burn_start",
        {
            "path": str(output_path),
            "duration_seconds": burn_duration,
            "encoder": "h264_nvenc",
            "quality": 25,
            "preset": "p4",
            "task_id": task_id,
        },
    )
    wait_if_paused("burn_start", {"project_path": str(project_dir), "task_id": task_id})
    safe_ass_path = create_safe_ass_copy(ass_path)
    burn_subtitle(
        input_video,
        safe_ass_path,
        output_path,
        progress_callback=lambda stage, payload: append_history(stage, {**payload, "task_id": task_id}),
        total_duration=burn_duration,
    )
    style_learning_result = write_style_learning_artifacts(
        segments_path=translated_segments_path,
        manual_ass_path=ass_path,
        output_dir=project_dir,
    )
    manifest["style_learning"] = style_learning_result
    append_history(
        "burn_complete",
        {
            "path": str(output_path),
            "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
            "duration_seconds": burn_duration,
            "style_learning_examples": int(style_learning_result.get("example_count") or 0),
            "task_id": task_id,
        },
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with STATE_LOCK:
        if task_id and STATE.get("task_id") and STATE["task_id"] != task_id:
            return {
                "project_path": str(project_dir),
                "ass_path": str(ass_path),
                "output_path": str(output_path),
                "input_video": str(input_video),
            }
        STATE["running"] = False
        STATE["current_stage"] = "complete"
        STATE["last_manifest"] = manifest
        STATE["task_id"] = ""
        STATE["task_started_at"] = ""
        STATE["task_started_at_ts"] = 0.0
        touch_task_activity_locked()
        STATE["stale_task"] = False
        STATE["stale_reason"] = ""
        STATE["recovery"] = None
        STATE["runtime"] = {
            "stage_key": "complete",
            "title": "完成",
            "description": "按当前 ASS 重新烧录完成。",
            "overall_progress": 100,
        }
        persist_state_snapshot(force=True)
    return {
        "project_path": str(project_dir),
        "ass_path": str(ass_path),
        "output_path": str(output_path),
        "input_video": str(input_video),
    }


def safe_reburn_from_ass_job(project_path: str) -> None:
    task_id = current_task_id()
    try:
        reburn_from_ass_job(project_path, task_id)
    except Exception as exc:
        traceback_text = traceback.format_exc()
        user_message = build_user_facing_error_message(exc)
        if task_token_matches(task_id):
            set_state_error(user_message, traceback_text)
        append_error_log(traceback_text)


def build_download_config(config: dict) -> DownloadConfig:
    return DownloadConfig.from_ui_config(
        config,
        input_dir=INPUT_DIR,
        proxy_url=configured_proxy_url(config),
    )


def download_video_from_url(url: str, config: dict, task_id: str | None = None) -> dict:
    download_config = build_download_config(config)
    manager = DownloadManager(
        download_config,
        callback=lambda stage, payload: append_history(stage, {**payload, "task_id": task_id}),
    )
    result = manager.download(url)
    return result.as_video_dict()


def download_and_optionally_run_job(url: str, config: dict, run_after_download: bool) -> None:
    task_id = current_task_id()
    try:
        append_history("download_start", {"url": url, "task_id": task_id})
        wait_if_paused("download_start", {"url": url, "task_id": task_id})

        video = download_video_from_url(url, config, task_id)
        enqueue_video(video)
        append_history(
            "download_complete",
            {
                "path": video["path"],
                "name": video["name"],
                "size": video["size"],
                "method": video.get("download_method", ""),
                "task_id": task_id,
            },
        )

        if run_after_download:
            execute_pipeline_job(video["path"], config, task_id)
        else:
            with STATE_LOCK:
                if task_id and STATE.get("task_id") and STATE["task_id"] != task_id:
                    return
                STATE["running"] = False
                STATE["current_stage"] = "idle"
                STATE["task_id"] = ""
                STATE["task_started_at"] = ""
                STATE["task_started_at_ts"] = 0.0
                touch_task_activity_locked()
                STATE["stale_task"] = False
                STATE["stale_reason"] = ""
                STATE["recovery"] = None
                STATE["runtime"] = {
                    "stage_key": "idle",
                    "title": "等待中",
                    "description": "下载已完成，等待后续操作。",
                    "overall_progress": 0,
                }
                persist_state_snapshot(force=True)
    except Exception as exc:
        traceback_text = traceback.format_exc()
        user_message = build_user_facing_error_message(exc)
        if task_token_matches(task_id):
            set_state_error(user_message, traceback_text)
        append_error_log(traceback_text)


class UIServerHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        return

    def _json_response(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError as exc:
            if is_client_disconnect_error(exc):
                return
            raise

    def _error_response(self, exc: Exception) -> None:
        if is_client_disconnect_error(exc):
            return
        append_error_log(traceback.format_exc())
        try:
            self._json_response({"error": str(exc), "traceback": traceback.format_exc()}, status=500)
        except OSError as response_exc:
            if is_client_disconnect_error(response_exc):
                return
            raise

    def do_GET(self) -> None:
        try:
            reconcile_runtime_state()
            parsed = urlparse(self.path)
            if parsed.path == "/api/bootstrap":
                self._json_response(build_bootstrap_payload(include_collections=True))
                return

            if parsed.path == "/api/state":
                self._json_response(build_bootstrap_payload(include_collections=False))
                return

            if parsed.path == "/api/proxy/status":
                self._json_response(
                    {
                        "server_version": SERVER_VERSION,
                        "proxy": test_proxy_connection(),
                    }
                )
                return

            if parsed.path == "/api/local-feedback-summary":
                self._json_response(build_local_feedback_summary())
                return

            if parsed.path == "/api/local-feedback-records":
                qs = parse_qs(parsed.query)
                kind = qs.get("kind", ["style"])[0]
                status_filter = qs.get("status", ["pending"])[0]
                limit = int(qs.get("limit", ["80"])[0] or 80)
                self._json_response(list_local_feedback_records(kind=kind, status_filter=status_filter, limit=limit))
                return

            if parsed.path == "/api/local-feedback-record-detail":
                qs = parse_qs(parsed.query)
                kind = qs.get("kind", ["style"])[0]
                record_id = qs.get("record_id", [""])[0]
                self._json_response(get_local_feedback_record_detail(kind=kind, record_id=record_id))
                return

            if parsed.path == "/api/learning-quality-summary":
                self._json_response(build_learning_quality_summary())
                return

            if parsed.path == "/api/local-feedback-impact-preview":
                self._json_response(build_local_feedback_impact_preview())
                return

            if parsed.path == "/api/local-feedback-ab-eval-preview":
                self._json_response(build_local_feedback_ab_eval_preview())
                return

            if parsed.path == "/api/local-feedback-ab-eval-report":
                self._json_response(read_latest_ab_eval_report(LOCAL_FEEDBACK_DATASET_DIR))
                return

            if parsed.path == "/api/file":
                qs = parse_qs(parsed.query)
                path = qs.get("path", [""])[0]
                target = Path(path)
                if not target.exists() or not target.is_file():
                    self._json_response({"error": "file not found"}, status=404)
                    return
                self._json_response({"path": str(target), "content": target.read_text(encoding="utf-8", errors="replace")})
                return

            if parsed.path.startswith("/output/"):
                relative = parsed.path[len("/output/") :]
                target = OUTPUT_DIR / relative
                if not target.exists() or not target.is_file():
                    self._json_response({"error": "file not found"}, status=404)
                    return
                self.send_response(200)
                if target.suffix.lower() == ".mp4":
                    self.send_header("Content-Type", "video/mp4")
                elif target.suffix.lower() == ".wav":
                    self.send_header("Content-Type", "audio/wav")
                else:
                    self.send_header("Content-Type", "application/octet-stream")
                data = target.read_bytes()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            return super().do_GET()
        except OSError as exc:
            if is_client_disconnect_error(exc):
                return
            self._error_response(exc)
        except Exception as exc:
            self._error_response(exc)

    def do_POST(self) -> None:
        try:
            reconcile_runtime_state()
            parsed = urlparse(self.path)
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length else b"{}"

            if parsed.path in {"/api/upload-video", "/api/pick-input"}:
                filename = unquote(self.headers.get("X-Filename", "upload.mp4"))
                video = save_uploaded_file(INPUT_DIR, filename, raw)
                enqueue_video(video)
                self._json_response({"ok": True, "video": video, "videos": list_input_videos(), "state": STATE})
                return

            if parsed.path in {"/api/upload-audio", "/api/pick-audio"}:
                filename = unquote(self.headers.get("X-Filename", "upload.mp3"))
                audio = save_uploaded_file(ATTACHMENTS_DIR, filename, raw)
                self._json_response({"ok": True, "audio": audio, "audios": list_audio_files(), "state": STATE})
                return

            payload = json.loads(raw.decode("utf-8")) if raw else {}

            if parsed.path == "/api/save-config":
                config = normalize_config({**read_config(), **payload})
                write_config(config)
                self._json_response({"ok": True, "config": config})
                return

            if parsed.path == "/api/open-output":
                opened = open_output_in_explorer(payload.get("project_path"))
                self._json_response({"ok": True, "opened": opened})
                return

            if parsed.path == "/api/open-input":
                opened = open_input_in_explorer()
                self._json_response({"ok": True, "opened": opened})
                return

            if parsed.path == "/api/scan-input":
                videos = scan_input_queue()
                self._json_response(
                    {
                        "ok": True,
                        "videos": videos,
                        "state": STATE,
                        "projects": read_output_tree(),
                    }
                )
                return

            if parsed.path == "/api/check-idm":
                config = {**read_config(), **payload.get("config", {})}
                self._json_response({"ok": True, "idm": check_idm(build_download_config(config))})
                return

            if parsed.path == "/api/youtube-meta":
                url = str(payload.get("url") or "").strip()
                if not url:
                    self._json_response({"ok": False, "error": "url required"}, status=400)
                    return
                config = normalize_config({**read_config(), **payload.get("config", {})})
                configured_raw_proxy_url = normalize_proxy_url(config.get("proxy_url"))
                proxy_validation_error = validate_proxy_url(configured_raw_proxy_url)
                if proxy_validation_error:
                    exc = ValueError(proxy_validation_error)
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                proxy_url=configured_raw_proxy_url,
                                operation="youtube_meta_proxy_validation",
                            ),
                        },
                        status=400,
                    )
                    return
                proxy_url = configured_proxy_url(config)
                try:
                    manifest = youtube_info_job(url, proxy_url=proxy_url)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {"ok": False, **build_error_payload(exc, proxy_url=proxy_url, operation="youtube_meta")},
                        status=502,
                    )
                    return
                self._json_response({"ok": True, **manifest})
                return

            if parsed.path == "/api/youtube-cover":
                url = str(payload.get("url") or "").strip()
                if not url:
                    self._json_response({"ok": False, "error": "url required"}, status=400)
                    return
                config = normalize_config({**read_config(), **payload.get("config", {})})
                configured_raw_proxy_url = normalize_proxy_url(config.get("proxy_url"))
                proxy_validation_error = validate_proxy_url(configured_raw_proxy_url)
                if proxy_validation_error:
                    exc = ValueError(proxy_validation_error)
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                proxy_url=configured_raw_proxy_url,
                                operation="youtube_cover_proxy_validation",
                            ),
                        },
                        status=400,
                    )
                    return
                proxy_url = configured_proxy_url(config)
                try:
                    manifest = youtube_assets_job(url, download_cover_only=True, proxy_url=proxy_url)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {"ok": False, **build_error_payload(exc, proxy_url=proxy_url, operation="youtube_cover")},
                        status=502,
                    )
                    return
                self._json_response({"ok": True, **manifest})
                return

            if parsed.path == "/api/bilibili-duplicate-search":
                url = str(payload.get("url") or "").strip()
                if not url:
                    self._json_response({"ok": False, "error": "url required"}, status=400)
                    return
                config = normalize_config({**read_config(), **payload.get("config", {})})
                configured_raw_proxy_url = normalize_proxy_url(config.get("proxy_url"))
                proxy_validation_error = validate_proxy_url(configured_raw_proxy_url)
                if proxy_validation_error:
                    exc = ValueError(proxy_validation_error)
                    self._json_response(
                        {
                            "ok": False,
                            "workflow_policy": bilibili_duplicate_workflow_policy(),
                            **build_error_payload(
                                exc,
                                proxy_url=configured_raw_proxy_url,
                                operation="bilibili_duplicate_search_proxy_validation",
                            ),
                        },
                        status=400,
                    )
                    return
                proxy_url = configured_proxy_url(config)
                youtube_meta = payload.get("youtube_meta")
                try:
                    manifest = bilibili_duplicate_search_job(url, config, youtube_meta if isinstance(youtube_meta, dict) else None)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {
                            "ok": False,
                            "workflow_policy": bilibili_duplicate_workflow_policy(),
                            **build_error_payload(
                                exc,
                                proxy_url=proxy_url,
                                operation="bilibili_duplicate_search",
                            ),
                        },
                        status=502,
                    )
                    return
                manifest.setdefault("workflow_policy", bilibili_duplicate_workflow_policy())
                self._json_response({"ok": True, **manifest})
                return

            if parsed.path == "/api/bilibili-duplicate-feedback":
                try:
                    result = bilibili_duplicate_feedback_job(payload)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                operation="bilibili_duplicate_feedback",
                            ),
                        },
                        status=400,
                    )
                    return
                self._json_response({"ok": True, **result})
                return

            if parsed.path == "/api/local-feedback-record-update":
                try:
                    result = update_local_feedback_record(payload)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                operation="local_feedback_record_update",
                            ),
                        },
                        status=400,
                    )
                    return
                self._json_response(result)
                return

            if parsed.path == "/api/local-feedback-bulk-update":
                try:
                    result = bulk_update_local_feedback_records(payload)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                operation="local_feedback_bulk_update",
                            ),
                        },
                        status=400,
                    )
                    return
                self._json_response(result)
                return

            if parsed.path == "/api/local-feedback-action":
                try:
                    result = run_local_feedback_action(payload)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                operation="local_feedback_action",
                            ),
                        },
                        status=400,
                    )
                    return
                self._json_response(result)
                return

            if parsed.path == "/api/local-feedback-ab-eval":
                try:
                    result = run_local_feedback_ab_eval(payload)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                operation="local_feedback_ab_eval",
                            ),
                        },
                        status=400,
                    )
                    return
                self._json_response(result)
                return

            if parsed.path == "/api/rebuild-youtube-cover-1280x960":
                project_path = str(payload.get("project_path") or "").strip()
                if not project_path:
                    self._json_response({"ok": False, "error": "project_path required"}, status=400)
                    return
                manifest = rebuild_padded_cover_job(project_path)
                self._json_response({"ok": True, **manifest})
                return

            if parsed.path == "/api/organize-project-artifacts":
                project_path = str(payload.get("project_path") or "").strip()
                if not project_path:
                    self._json_response({"ok": False, "error": "project_path required"}, status=400)
                    return
                try:
                    result = organize_project_artifacts_job(project_path, preview_only=bool(payload.get("preview_only")))
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                operation="organize_project_artifacts",
                            ),
                        },
                        status=400,
                    )
                    return
                self._json_response({"ok": True, **result})
                return

            if parsed.path == "/api/queue/clear":
                clear_queue()
                self._json_response(
                    {
                        "ok": True,
                        "state": STATE,
                        "videos": list_input_videos(),
                        "projects": read_output_tree(),
                    }
                )
                return

            if parsed.path == "/api/pause":
                active_job = JOB_STORE.get_active_job()
                if active_job:
                    JOB_STORE.pause_job(str(active_job["id"]))
                    response = build_bootstrap_payload(include_collections=False)
                    response["ok"] = True
                    self._json_response(response)
                    return
                if not is_busy():
                    self._json_response({"ok": False, "error": "no running task", "flow_control": capture_flow_control_snapshot()}, status=409)
                    return
                flow_control = request_pause(str(payload.get("reason") or "user_requested"))
                append_history(
                    "flow_pause_requested",
                    {
                        "pause_reason": flow_control.get("pause_reason", ""),
                        "task_id": current_task_id(),
                    },
                )
                self._json_response({"ok": True, "flow_control": flow_control, "state": capture_state_snapshot()})
                return

            if parsed.path == "/api/resume":
                active_job = JOB_STORE.get_active_job()
                if active_job:
                    JOB_STORE.resume_job(str(active_job["id"]))
                    start_worker_process()
                    response = build_bootstrap_payload(include_collections=False)
                    response["ok"] = True
                    self._json_response(response)
                    return
                flow_control = resume_flow()
                self._json_response({"ok": True, "flow_control": flow_control, "state": capture_state_snapshot()})
                return

            if parsed.path == "/api/cancel":
                active_job = JOB_STORE.get_active_job()
                if not active_job:
                    self._json_response({"ok": False, "error": "no running task"}, status=409)
                    return
                JOB_STORE.cancel_job(str(active_job["id"]))
                response = build_bootstrap_payload(include_collections=False)
                response["ok"] = True
                self._json_response(response)
                return

            if parsed.path == "/api/download-video":
                config = {**read_config(), **payload.get("config", {})}
                url = payload["url"]
                run_after_download = bool(payload.get("run_after_download"))
                if run_after_download:
                    ensure_openai_runtime_env_loaded()
                if not try_begin_task("downloading", "下载视频", "正在拉取视频资源。", overall_progress=4):
                    self._json_response({"ok": False, "error": "task already running"}, status=409)
                    return
                thread = threading.Thread(
                    target=download_and_optionally_run_job,
                    args=(url, config, run_after_download),
                    daemon=True,
                )
                thread.start()
                self._json_response({"ok": True})
                return

            if parsed.path == "/api/run":
                config = {**read_config(), **payload.get("config", {})}
                resolved_video_path = str(resolve_input_video_path(payload["video_path"]))
                ensure_openai_runtime_env_loaded()
                try:
                    job = create_pipeline_job(resolved_video_path, config)
                except RuntimeError as exc:
                    self._json_response({"ok": False, "error": str(exc)}, status=409)
                    return
                start_worker_process()
                response = build_bootstrap_payload(include_collections=False)
                response["ok"] = True
                response["job_id"] = job["id"]
                response["job"] = job
                self._json_response(response)
                return

            if parsed.path == "/api/reburn-from-ass":
                project_path = str(payload.get("project_path") or "").strip()
                if not project_path:
                    self._json_response({"ok": False, "error": "project_path required"}, status=400)
                    return
                if not try_begin_task("burn_start", "烧录中", "正在按当前 ASS 重新烧录。", overall_progress=94):
                    self._json_response({"ok": False, "error": "task already running"}, status=409)
                    return
                thread = threading.Thread(target=safe_reburn_from_ass_job, args=(project_path,), daemon=True)
                thread.start()
                self._json_response({"ok": True})
                return

            if parsed.path == "/api/learn-style":
                project_path = str(payload.get("project_path") or "").strip()
                if not project_path:
                    self._json_response({"ok": False, "error": "project_path required"}, status=400)
                    return
                manifest = learn_style_job(project_path)
                self._json_response({"ok": True, **manifest})
                return

            if parsed.path == "/api/collect-style-feedback":
                project_path = str(payload.get("project_path") or "").strip()
                if not project_path:
                    self._json_response({"ok": False, "error": "project_path required"}, status=400)
                    return
                try:
                    result = collect_style_feedback_job(project_path)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                operation="collect_style_feedback",
                            ),
                        },
                        status=400,
                    )
                    return
                self._json_response({"ok": True, **result})
                return

            if parsed.path == "/api/collect-span-feedback":
                project_path = str(payload.get("project_path") or "").strip()
                if not project_path:
                    self._json_response({"ok": False, "error": "project_path required"}, status=400)
                    return
                try:
                    result = collect_span_feedback_job(project_path)
                except Exception as exc:
                    append_error_log(traceback.format_exc())
                    self._json_response(
                        {
                            "ok": False,
                            **build_error_payload(
                                exc,
                                operation="collect_span_feedback",
                            ),
                        },
                        status=400,
                    )
                    return
                self._json_response({"ok": True, **result})
                return

            if parsed.path == "/api/video-inspect":
                resolved_video_path = str(resolve_input_video_path(payload["video_path"]))
                self._json_response(
                    {
                        "ok": True,
                        "media": inspect_video(resolved_video_path),
                    }
                )
                return

            self._json_response({"error": "not found"}, status=404)
        except OSError as exc:
            if is_client_disconnect_error(exc):
                return
            self._error_response(exc)
        except Exception as exc:
            self._error_response(exc)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    global INITIAL_INPUT_SNAPSHOT
    INITIAL_INPUT_SNAPSHOT = {str(item.resolve()) for item in iter_input_video_files(INPUT_DIR)}
    restore_state_from_snapshot()
    ensure_proxy_environment()
    try:
        if JOB_STORE.has_active_job():
            start_worker_process()
    except Exception as exc:
        append_error_log(f"[worker] failed to start worker for active job: {exc}")
    server = ReusableThreadingHTTPServer(("127.0.0.1", SERVER_PORT), UIServerHandler)
    print(f"UI server running at http://127.0.0.1:{SERVER_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
