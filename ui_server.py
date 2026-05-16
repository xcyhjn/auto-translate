from __future__ import annotations

import json
import os
import re
import shutil
import threading
import traceback
from datetime import datetime, timezone
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .downloaders import DownloadConfig, DownloadManager, ManualImportRequired, check_idm
from .models import BilingualSubtitleStyle
from .media import probe_media
from .pipeline_core import build_output_slug, burn_subtitle, create_safe_ass_copy, run_pipeline
from .glossary import write_youtube_glossary
from .style_learning import write_style_learning_artifacts
from .youtube_meta import ensure_cover, ensure_padded_cover, fetch_youtube_info, fetch_youtube_meta, safe_project_slug, save_youtube_meta


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
ATTACHMENTS_DIR = BASE_DIR / "attachments"
WEB_DIR = BASE_DIR / "web"
CONFIG_PATH = BASE_DIR / "ui_config.json"
ERROR_LOG_PATH = BASE_DIR / "ui_server_error_trace.log"
SERVER_VERSION = "20260514-idm-download-v1"
SERVER_PORT = int(os.environ.get("AUTOSUB_UI_PORT", "8777"))
DEFAULT_HTTP_PROXY = "http://127.0.0.1:7890"

DEFAULT_CONFIG = {
    "src_lang": "en",
    "dst_lang": "zh-Hans",
    "model": "distil-large-v3",
    "device": "cuda",
    "compute_type": "float16",
    "beam_size": 5,
    "translation_model": "gpt-5.4-mini",
    "translation_chunk_size": 24,
    "translation_retries": 4,
    "openai_base_url": "",
    "audio_override_path": "",
    "load_existing_segments": False,
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
    "asr_start": {"title": "识别中", "description": "正在执行语音识别。", "overall_progress": 36},
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
    "burn_start": {"title": "烧录中", "description": "正在写入双语字幕视频。", "overall_progress": 94},
    "burn_progress": {"title": "烧录中", "description": "正在写入双语字幕视频。", "overall_progress": 96},
    "burn_complete": {"title": "完成", "description": "烧录产物已经生成。", "overall_progress": 100},
    "complete": {"title": "完成", "description": "全部阶段已完成。", "overall_progress": 100},
    "error": {"title": "错误", "description": "任务执行失败。", "overall_progress": 100},
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
}
STATE_LOCK = threading.Lock()
INITIAL_INPUT_SNAPSHOT: set[str] = set()


def read_config() -> dict:
    if CONFIG_PATH.exists():
        return {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text(encoding="utf-8"))}
    return DEFAULT_CONFIG.copy()


def write_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def append_error_log(message: str) -> None:
    with ERROR_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message)
        handle.write("\n\n")


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

    return raw_message or "任务执行失败。"


def set_state_error(message: str, traceback_text: str) -> None:
    with STATE_LOCK:
        STATE["running"] = False
        STATE["current_stage"] = "error"
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


def list_input_videos() -> list[dict]:
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
    target = Path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"Input video not found: {target}")
    media_info = probe_media(target)
    return {
        "path": str(target),
        "duration_seconds": media_info.duration,
        "has_audio": media_info.has_audio,
        "text_subtitle_streams": len(media_info.text_subtitle_streams),
        "image_subtitle_streams": len(media_info.image_subtitle_streams),
    }


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
        for item in sorted(folder.iterdir()):
            if item.is_file():
                files.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "size": item.stat().st_size,
                    }
                )
        projects.append({"name": folder.name, "path": str(folder), "files": files})
    return projects


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


def reset_runtime_state() -> None:
    STATE["running"] = False
    STATE["current_stage"] = "idle"
    STATE["runtime"] = default_runtime_meta()
    STATE["history"] = []
    STATE["last_manifest"] = None
    STATE["last_error"] = None
    STATE["phase_status"] = default_phase_status()


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
    }
    for key, value in payload.items():
        if value in (None, "", [], {}):
            continue
        if key.endswith("path") or key.endswith("dir") or key == "url":
            summary[key] = str(value)
        elif key in numeric_keys:
            summary[key] = value
    if not summary:
        for key, value in list(payload.items())[:4]:
            if value not in (None, "", [], {}):
                summary[key] = value
    return summary


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
            94 + int(round(float(payload.get("progress", 0)) * 0.05)),
        )
    elif stage == "translation_chunk_complete":
        chunk_total = int(payload.get("chunk_total", 0) or 0)
        chunk_index = int(payload.get("chunk_index", 0) or 0)
        if chunk_total > 0:
            ratio = max(0.0, min(1.0, chunk_index / chunk_total))
            runtime["overall_progress"] = 72 + int(round(ratio * 16))
    elif stage == "asr_progress":
        duration_seconds = float(payload.get("duration_seconds", 0) or 0)
        processed_seconds = float(payload.get("processed_seconds", 0) or 0)
        if duration_seconds > 0:
            ratio = max(0.0, min(1.0, processed_seconds / duration_seconds))
            runtime["overall_progress"] = 36 + int(round(ratio * 22))

    if stage == "error":
        runtime["title"] = "错误"
        runtime["description"] = str(payload.get("message", "任务执行失败。"))
        runtime["overall_progress"] = 100


def update_phase_status(stage: str, payload: dict) -> None:
    phase = STATE["phase_status"]
    audio_progress = float(phase["audio_extract"].get("progress", 0) or 0)

    if stage in {"download_start", "download_complete"}:
        phase["audio_extract"]["label"] = "等待下载完成" if stage == "download_start" else "下载完成，等待处理"
        return

    if stage == "merge_audio_start":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 5),
                "label": "正在合并外部音频",
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
            }
        )
        return

    if stage == "merge_audio_progress":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, float(payload.get("progress", 0) or 0) * 0.4),
                "label": "正在合并外部音频",
                "processed_seconds": float(payload.get("out_time_seconds", 0) or 0),
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
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
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
            }
        )
        return

    if stage == "extract_audio_start":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 45 if audio_progress >= 40 else 15),
                "label": "正在提取音频",
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
            }
        )
        return

    if stage == "extract_audio_progress":
        phase["audio_extract"].update(
            {
                "status": "running",
                "progress": max(audio_progress, 45 + float(payload.get("progress", 0) or 0) * 0.55 if audio_progress >= 40 else float(payload.get("progress", 0) or 0)),
                "label": "正在提取音频",
                "processed_seconds": float(payload.get("out_time_seconds", 0) or 0),
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
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
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
                "size_bytes": int(payload.get("size_bytes", 0) or 0),
            }
        )
        return

    if stage == "asr_start":
        phase["asr"].update(
            {
                "status": "running",
                "progress": 0,
                "label": "正在识别音频",
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
                "current": 0,
                "total": 0,
            }
        )
        return

    if stage == "asr_progress":
        duration_seconds = float(payload.get("duration_seconds", 0) or 0)
        processed_seconds = float(payload.get("processed_seconds", 0) or 0)
        progress = float(payload.get("progress", 0) or 0)
        if duration_seconds > 0 and progress == 0:
            progress = round(max(0.0, min(1.0, processed_seconds / duration_seconds)) * 100, 2)
        current = int(payload.get("virtual_chunk_current", 0) or 0)
        total = int(payload.get("virtual_chunk_total", 0) or 0)
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
                "elapsed_seconds": float(payload.get("elapsed_seconds", 0) or 0),
            }
        phase["translation"].update(
            {
                "status": "running",
                "current": chunk_index,
                "total": chunk_total,
                "progress": round(chunk_index / chunk_total * 100, 2) if chunk_total else 0,
                "fallback_count": fallback_count,
                "elapsed_seconds": float(payload.get("elapsed_seconds", 0) or 0),
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
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
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
                "progress": float(payload.get("progress", 0) or 0),
                "processed_seconds": float(payload.get("out_time_seconds", 0) or 0),
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
                "remaining_seconds": float(payload.get("remaining_seconds", 0) or 0),
                "size_bytes": int(payload.get("size_bytes", 0) or 0),
                "estimated_final_size": int(payload.get("estimated_final_size", 0) or 0),
                "speed": float(payload.get("speed", 0) or 0),
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
                "duration_seconds": float(payload.get("duration_seconds", 0) or 0),
                "label": "烧录完成",
            }
        )
        return


def append_history(stage: str, payload: dict) -> None:
    with STATE_LOCK:
        STATE["current_stage"] = stage
        update_runtime_meta(stage, payload)
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


def run_pipeline_job(video_path: str, config: dict) -> None:
    style_config = dict(config.get("style") or {})
    if "en_max_words_per_line" in style_config and "en_max_single_line_chars" not in style_config:
        style_config["en_max_single_line_chars"] = max(50, int(style_config.pop("en_max_words_per_line") or 12) * 6)
    style_config.pop("en_max_words_per_line", None)
    style = BilingualSubtitleStyle(**style_config)
    try:
        with STATE_LOCK:
            STATE["running"] = True
            STATE["current_stage"] = "starting"
            STATE["history"] = []
            STATE["last_error"] = None
            STATE["phase_status"] = default_phase_status()
            STATE["runtime"] = {
                "stage_key": "starting",
                "title": "准备中",
                "description": "正在初始化任务。",
                "overall_progress": 1,
            }

        manifest = run_pipeline(
            input_path=video_path,
            output_root=OUTPUT_DIR,
            src_lang=config["src_lang"],
            dst_lang=config["dst_lang"],
            model=config["model"],
            device=config["device"],
            compute_type=config["compute_type"],
            beam_size=int(config["beam_size"]),
            translation_model=config["translation_model"],
            translation_chunk_size=int(config["translation_chunk_size"]),
            translation_retries=int(config["translation_retries"]),
            openai_base_url=config["openai_base_url"] or None,
            audio_override_path=config.get("audio_override_path") or None,
            load_existing_segments=bool(config["load_existing_segments"]),
            preview_seconds=int(config["preview_seconds"]) if config["preview_seconds"] else None,
            skip_burn=bool(config.get("skip_burn", False)),
            repair_high_risk_spans=bool(config.get("repair_high_risk_spans", True)),
            span_repair_max_spans=int(config.get("span_repair_max_spans", 12) or 12),
            enable_ai_display_rewrite=bool(config.get("enable_ai_display_rewrite", False)),
            display_rewrite_max_ai_segments=int(config.get("display_rewrite_max_ai_segments", 12) or 12),
            bilingual_style=style,
            callback=append_history,
        )

        with STATE_LOCK:
            STATE["running"] = False
            STATE["current_stage"] = "complete"
            STATE["last_manifest"] = manifest
            STATE["runtime"] = {
                "stage_key": "complete",
                "title": "完成",
                "description": "全部阶段已完成。",
                "overall_progress": 100,
            }
    except Exception as exc:
        traceback_text = traceback.format_exc()
        user_message = build_user_facing_error_message(exc)
        set_state_error(user_message, traceback_text)
        append_error_log(traceback_text)


def reburn_from_ass_job(project_path: str) -> dict:
    project_dir = Path(project_path)
    manifest_path = project_dir / "10_manifest_bilingual.json"
    ass_path = project_dir / "08_bilingual_zh_en.ass"
    output_path = project_dir / "09_burned_bilingual_video.mp4"
    if not project_dir.exists():
        raise FileNotFoundError(f"Project folder not found: {project_dir}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    if not ass_path.exists():
        raise FileNotFoundError(f"ASS file not found: {ass_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    input_video = Path(str(manifest.get("input_video") or ""))
    if not input_video.exists():
        raise FileNotFoundError(f"Input video not found: {input_video}")

    probe = probe_media(input_video)
    with STATE_LOCK:
        STATE["running"] = True
        STATE["current_stage"] = "burn_start"
        STATE["last_error"] = None
        STATE["runtime"] = {
            "stage_key": "burn_start",
            "title": "烧录中",
            "description": "正在按当前 ASS 重新烧录。",
            "overall_progress": 94,
        }

    append_history(
        "burn_start",
        {
            "path": str(output_path),
            "duration_seconds": probe.duration or 0,
            "encoder": "h264_nvenc",
            "quality": 25,
            "preset": "p4",
        },
    )
    safe_ass_path = create_safe_ass_copy(ass_path)
    burn_subtitle(
        input_video,
        safe_ass_path,
        output_path,
        progress_callback=append_history,
        total_duration=probe.duration or 0,
    )
    append_history(
        "burn_complete",
        {
            "path": str(output_path),
            "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
            "duration_seconds": probe.duration or 0,
        },
    )
    with STATE_LOCK:
        STATE["running"] = False
        STATE["current_stage"] = "complete"
        STATE["last_manifest"] = manifest
        STATE["runtime"] = {
            "stage_key": "complete",
            "title": "完成",
            "description": "按当前 ASS 重新烧录完成。",
            "overall_progress": 100,
        }
    return {
        "project_path": str(project_dir),
        "ass_path": str(ass_path),
        "output_path": str(output_path),
        "input_video": str(input_video),
    }


def build_download_config(config: dict) -> DownloadConfig:
    return DownloadConfig.from_ui_config(
        config,
        input_dir=INPUT_DIR,
        proxy_url=get_proxy_url(),
    )


def download_video_from_url(url: str, config: dict) -> dict:
    download_config = build_download_config(config)
    manager = DownloadManager(download_config, callback=append_history)
    result = manager.download(url)
    return result.as_video_dict()


def download_and_optionally_run_job(url: str, config: dict, run_after_download: bool) -> None:
    try:
        with STATE_LOCK:
            STATE["running"] = True
            STATE["current_stage"] = "downloading"
            STATE["last_error"] = None
            STATE["history"] = []
            STATE["phase_status"] = default_phase_status()
            update_runtime_meta("downloading", {})
        append_history("download_start", {"url": url})

        video = download_video_from_url(url, config)
        enqueue_video(video)
        append_history(
            "download_complete",
            {
                "path": video["path"],
                "name": video["name"],
                "size": video["size"],
                "method": video.get("download_method", ""),
            },
        )

        with STATE_LOCK:
            STATE["running"] = False
            STATE["current_stage"] = "idle"
            STATE["runtime"] = {
                "stage_key": "idle",
                "title": "等待中",
                "description": "下载已完成，等待后续操作。",
                "overall_progress": 0,
            }

        if run_after_download:
            run_pipeline_job(video["path"], config)
    except Exception as exc:
        traceback_text = traceback.format_exc()
        user_message = build_user_facing_error_message(exc)
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
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error_response(self, exc: Exception) -> None:
        append_error_log(traceback.format_exc())
        self._json_response({"error": str(exc), "traceback": traceback.format_exc()}, status=500)

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/bootstrap":
                self._json_response(
                    {
                        "server_version": SERVER_VERSION,
                        "videos": list_input_videos(),
                        "audios": list_audio_files(),
                        "projects": read_output_tree(),
                        "config": read_config(),
                        "state": STATE,
                    }
                )
                return

            if parsed.path == "/api/state":
                self._json_response(
                    {
                        "server_version": SERVER_VERSION,
                        "videos": list_input_videos(),
                        "audios": list_audio_files(),
                        "projects": read_output_tree(),
                        "state": STATE,
                    }
                )
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
        except Exception as exc:
            self._error_response(exc)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length) if content_length else b"{}"

            if parsed.path == "/api/upload-video":
                filename = unquote(self.headers.get("X-Filename", "upload.mp4"))
                video = save_uploaded_file(INPUT_DIR, filename, raw)
                enqueue_video(video)
                self._json_response({"ok": True, "video": video, "videos": list_input_videos(), "state": STATE})
                return

            if parsed.path == "/api/upload-audio":
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
                thread = threading.Thread(target=run_pipeline_job, args=(payload["video_path"], config), daemon=True)
                thread.start()
                self._json_response({"ok": True})
                return

            if parsed.path == "/api/reburn-from-ass":
                project_path = str(payload.get("project_path") or "").strip()
                if not project_path:
                    self._json_response({"ok": False, "error": "project_path required"}, status=400)
                    return
                thread = threading.Thread(target=reburn_from_ass_job, args=(project_path,), daemon=True)
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
                self._json_response(
                    {
                        "ok": True,
                        "media": inspect_video(payload["video_path"]),
                    }
                )
                return

            self._json_response({"error": "not found"}, status=404)
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
    INITIAL_INPUT_SNAPSHOT = {str(item.resolve()) for item in INPUT_DIR.iterdir() if item.is_file()}
    ensure_proxy_environment()
    server = ReusableThreadingHTTPServer(("127.0.0.1", SERVER_PORT), UIServerHandler)
    print(f"UI server running at http://127.0.0.1:{SERVER_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
