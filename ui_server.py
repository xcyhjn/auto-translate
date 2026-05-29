from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import time
import threading
import traceback
import unicodedata
import uuid
from datetime import datetime, timezone
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .downloaders import DownloadConfig, DownloadManager, ManualImportRequired, check_idm
from .models import BilingualSubtitleStyle
from .media import normalize_asr_audio_mode, normalize_asr_vad_mode, probe_media
from .pipeline_core import build_output_slug, burn_subtitle, create_safe_ass_copy, run_pipeline, write_json
from .qa import qa_final_ass_file
from .qa_outputs import build_blocker_report
from .glossary import write_youtube_glossary
from .segment_io import load_segments
from .style_learning import write_style_learning_artifacts
from .subtitle_io import write_bilingual_ass
from .youtube_meta import ensure_cover, ensure_padded_cover, fetch_youtube_info, fetch_youtube_meta, safe_project_slug, save_youtube_meta


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
ATTACHMENTS_DIR = BASE_DIR / "attachments"
WEB_DIR = BASE_DIR / "web"
CONFIG_PATH = BASE_DIR / "ui_config.json"
ERROR_LOG_PATH = BASE_DIR / "ui_server_error_trace.log"
STATE_SNAPSHOT_PATH = BASE_DIR / "ui_server_state.json"
SERVER_VERSION = "20260519-stability1"
SERVER_PORT = int(os.environ.get("AUTOSUB_UI_PORT", "8777"))
DEFAULT_HTTP_PROXY = "http://127.0.0.1:7890"
STATE_SNAPSHOT_VERSION = 1
STATE_STALE_TIMEOUT_SECONDS = 30 * 60

DEFAULT_CONFIG = {
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
    "translation_prompt": (
        "Prioritize faithful meaning over literal wording. Preserve casual spoken tone, "
        "hesitation, intimacy, jokes, sarcasm, and implied meaning when present. Translate "
        "spoken English into natural Simplified Chinese subtitles, not formal written Chinese. "
        "Keep the line concise and subtitle-friendly; do not add explanations."
    ),
    "translation_chunk_size": 24,
    "translation_retries": 4,
    "openai_base_url": "",
    "audio_override_path": "",
    "load_existing_segments": False,
    "force_retranslate_existing_segments": False,
    "preview_seconds": None,
    "skip_burn": False,
    "repair_high_risk_spans": True,
    "span_repair_max_spans": 12,
    "enable_ai_display_rewrite": False,
    "display_rewrite_max_ai_segments": 12,
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
    normalized = {**DEFAULT_CONFIG, **(config or {})}
    style = normalized.get("style") if isinstance(normalized.get("style"), dict) else {}
    normalized["style"] = {
        key: style.get(key, default_value)
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
    return normalized


def read_config() -> dict:
    if CONFIG_PATH.exists():
        return normalize_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return normalize_config(DEFAULT_CONFIG)


def write_config(config: dict) -> None:
    normalized = normalize_config(config)
    temp_path = CONFIG_PATH.with_name(f".{CONFIG_PATH.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(CONFIG_PATH)


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


def set_state_error(message: str, traceback_text: str) -> None:
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
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if not os.environ.get(key):
            os.environ[key] = DEFAULT_HTTP_PROXY


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
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or DEFAULT_HTTP_PROXY
    )


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
    proxy_url = get_proxy_url()
    started_at = datetime.now(timezone.utc)
    targets = [
        ("proxy", "http://127.0.0.1:7890"),
        ("youtube", "https://www.youtube.com"),
    ]
    results = []

    for name, url in targets:
        entry = {"name": name, "url": url, "ok": False}
        try:
            if name == "proxy":
                response = httpx.get(url, timeout=5.0)
            else:
                transport = httpx.HTTPTransport(proxy=proxy_url)
                with httpx.Client(
                    transport=transport,
                    timeout=10.0,
                    follow_redirects=True,
                    headers={"User-Agent": "autosub-zh-ui-probe"},
                ) as client:
                    response = client.get(url)
            entry["ok"] = True
            entry["status_code"] = response.status_code
        except Exception as exc:
            entry["error"] = build_user_facing_error_message(exc)
            entry["raw_error"] = strip_ansi_codes(str(exc))
        results.append(entry)

    overall_ok = all(item.get("ok") for item in results)
    checked_at = started_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "ok": overall_ok,
        "checked_at": checked_at,
        "proxy_url": proxy_url,
        "results": results,
    }


def scan_input_queue() -> list[dict]:
    videos = list_input_videos()
    for video in videos:
        enqueue_video(video)
    return videos


def read_output_tree() -> list[dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    projects = []
    for folder in sorted(OUTPUT_DIR.iterdir()):
        if not folder.is_dir():
            continue
        files = []
        file_index: dict[str, dict] = {}
        manifest_payload: dict = {}
        for item in sorted(folder.iterdir()):
            if item.is_file():
                stat = item.stat()
                entry = {
                    "name": item.name,
                    "path": str(item),
                    "size": stat.st_size,
                    "mtime_ts": stat.st_mtime,
                }
                files.append(entry)
                file_index[item.name] = entry
        manifest_file = file_index.get("10_manifest_bilingual.json")
        if manifest_file:
            try:
                manifest_payload = json.loads(Path(manifest_file["path"]).read_text(encoding="utf-8"))
            except Exception:
                manifest_payload = {}
        ass_file = file_index.get("08_bilingual_zh_en.ass")
        burned_file = file_index.get("09_burned_bilingual_video.mp4")
        input_video = str(manifest_payload.get("input_video") or "").strip()
        projects.append(
            {
                "name": folder.name,
                "path": str(folder),
                "files": files,
                "ass_path": ass_file.get("path") if ass_file else "",
                "ass_mtime_ts": ass_file.get("mtime_ts") if ass_file else 0,
                "burned_video_path": burned_file.get("path") if burned_file else "",
                "burned_video_mtime_ts": burned_file.get("mtime_ts") if burned_file else 0,
                "manifest_path": manifest_file.get("path") if manifest_file else "",
                "input_video": input_video,
                "input_video_name": Path(input_video).name if input_video else "",
            }
        )
    return projects


def build_bootstrap_payload(*, include_collections: bool) -> dict:
    reconcile_runtime_state()
    payload = {
        "server_version": SERVER_VERSION,
        "state": capture_state_snapshot(),
    }
    if include_collections:
        payload["videos"] = list_input_videos()
        payload["audios"] = list_audio_files()
        payload["projects"] = read_output_tree()
        payload["config"] = read_config()
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


def youtube_assets_job(url: str, *, download_cover_only: bool = False) -> dict:
    meta = fetch_youtube_meta(url, proxy_url=get_proxy_url())
    output_dir = resolve_youtube_output_dir(meta.title)
    migrate_legacy_youtube_assets(meta.video_id, output_dir)
    save_youtube_meta(output_dir, meta)
    glossary_path = write_youtube_glossary(output_dir, meta)
    cover_path = None
    padded_cover_path = ""
    if download_cover_only:
        cover_path = ensure_cover(meta, output_dir, proxy_url=get_proxy_url())
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


def youtube_info_job(url: str) -> dict:
    meta = fetch_youtube_info(url, proxy_url=get_proxy_url())
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


def rebuild_padded_cover_job(project_path: str) -> dict:
    output_dir = Path(project_path)
    padded_path = ensure_padded_cover(output_dir)
    manifest_path = output_dir / "10_youtube_manifest.json"
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
    segments_path = project_dir / "05_translated_segments.json"
    ass_path = project_dir / "08_bilingual_zh_en.ass"
    if not project_dir.exists():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")
    if not segments_path.exists():
        raise FileNotFoundError(f"Segments file not found: {segments_path}")
    if not ass_path.exists():
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


def execute_pipeline_job(video_path: str, config: dict, task_id: str | None = None) -> None:
    task_id = task_id or current_task_id()
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
            span_repair_max_spans=int(config.get("span_repair_max_spans", 12) or 12),
            enable_ai_display_rewrite=bool(config.get("enable_ai_display_rewrite", False)),
            display_rewrite_max_ai_segments=int(config.get("display_rewrite_max_ai_segments", 12) or 12),
            bilingual_style=style,
            callback=lambda stage, payload: append_history(stage, {**payload, "task_id": task_id}),
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
    manifest_path = project_dir / "10_manifest_bilingual.json"
    ass_path = project_dir / "08_bilingual_zh_en.ass"
    translated_segments_path = project_dir / "05_translated_segments.json"
    output_path = project_dir / "09_burned_bilingual_video.mp4"
    if not project_dir.exists():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    if not ass_path.exists():
        raise FileNotFoundError(f"ASS file not found: {ass_path}")
    if not translated_segments_path.exists():
        raise FileNotFoundError(f"Translated segments not found: {translated_segments_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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
        proxy_url=get_proxy_url(),
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
                config = {**read_config(), **payload}
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
                manifest = youtube_info_job(url)
                self._json_response({"ok": True, **manifest})
                return

            if parsed.path == "/api/youtube-cover":
                url = str(payload.get("url") or "").strip()
                if not url:
                    self._json_response({"ok": False, "error": "url required"}, status=400)
                    return
                manifest = youtube_assets_job(url, download_cover_only=True)
                self._json_response({"ok": True, **manifest})
                return

            if parsed.path == "/api/rebuild-youtube-cover-1280x960":
                project_path = str(payload.get("project_path") or "").strip()
                if not project_path:
                    self._json_response({"ok": False, "error": "project_path required"}, status=400)
                    return
                manifest = rebuild_padded_cover_job(project_path)
                self._json_response({"ok": True, **manifest})
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

            if parsed.path == "/api/download-video":
                config = {**read_config(), **payload.get("config", {})}
                url = payload["url"]
                run_after_download = bool(payload.get("run_after_download"))
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
                if not try_begin_task("starting", "准备中", "正在初始化任务。", overall_progress=1):
                    self._json_response({"ok": False, "error": "task already running"}, status=409)
                    return
                thread = threading.Thread(
                    target=execute_pipeline_job,
                    args=(resolved_video_path, config, current_task_id()),
                    daemon=True,
                )
                thread.start()
                self._json_response({"ok": True})
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
    server = ReusableThreadingHTTPServer(("127.0.0.1", SERVER_PORT), UIServerHandler)
    print(f"UI server running at http://127.0.0.1:{SERVER_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
