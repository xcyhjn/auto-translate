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
from yt_dlp import YoutubeDL

from .models import BilingualSubtitleStyle
from .media import probe_media
from .pipeline_core import build_output_slug, run_pipeline


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
ATTACHMENTS_DIR = BASE_DIR / "attachments"
WEB_DIR = BASE_DIR / "web"
CONFIG_PATH = BASE_DIR / "ui_config.json"
ERROR_LOG_PATH = BASE_DIR / "ui_server_error_trace.log"
SERVER_VERSION = "20260513-ui-state-v3"
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
    "translation_chunk_size": 40,
    "translation_retries": 2,
    "openai_base_url": "",
    "audio_override_path": "",
    "load_existing_segments": False,
    "preview_seconds": None,
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
    "qa_complete": {"title": "QA 检查", "description": "正在整理风险和警告。", "overall_progress": 91},
    "burn_start": {"title": "烧录中", "description": "正在写入双语字幕视频。", "overall_progress": 94},
    "burn_progress": {"title": "烧录中", "description": "正在写入双语字幕视频。", "overall_progress": 96},
    "burn_complete": {"title": "完成", "description": "烧录产物已经生成。", "overall_progress": 100},
    "complete": {"title": "完成", "description": "全部阶段已完成。", "overall_progress": 100},
    "error": {"title": "错误", "description": "任务执行失败。", "overall_progress": 100},
}


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
            "encoder": "libx264",
            "crf": 25,
            "preset": "medium",
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

    if "winerror 10054" in lowered:
        return (
            "下载连接被远端或代理中途断开。"
            "请检查 127.0.0.1:7890 代理是否稳定，再重试下载。"
        )

    if "operation timed out" in lowered or "timed out" in lowered:
        return "下载超时。请检查代理连通性，或稍后重试。"

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
        "fallback_count",
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
                "encoder": str(payload.get("encoder", "libx264")),
                "crf": int(payload.get("crf", 25) or 25),
                "preset": str(payload.get("preset", "medium")),
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


def run_pipeline_job(video_path: str, config: dict) -> None:
    style = BilingualSubtitleStyle(**config["style"])
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


def download_video_from_url(url: str) -> dict:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    before = {item.resolve() for item in INPUT_DIR.iterdir() if item.is_file()}
    proxy_url = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or DEFAULT_HTTP_PROXY
    )
    options = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": str(INPUT_DIR / "%(title)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "proxy": proxy_url,
        "socket_timeout": 30,
        "retries": 8,
        "fragment_retries": 8,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 1,
        "continuedl": True,
        "buffersize": 1024,
        "http_chunk_size": 10485760,
        "hls_prefer_native": True,
        "nopart": False,
    }
    fallback_options = {
        **options,
        "format": "b[ext=mp4]/best",
        "merge_output_format": None,
    }
    try:
        with YoutubeDL(options) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as primary_exc:
        cleanup_partial_downloads(before)
        try:
            with YoutubeDL(fallback_options) as ydl:
                ydl.extract_info(url, download=True)
        except Exception:
            cleanup_partial_downloads(before)
            raise primary_exc

    candidates = [
        item
        for item in INPUT_DIR.iterdir()
        if item.is_file()
        and item.resolve() not in before
        and item.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".webm"}
        and item.stat().st_size > 0
    ]
    if not candidates:
        candidates = sorted(
            [
                item
                for item in INPUT_DIR.iterdir()
                if item.is_file()
                and item.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".webm"}
                and item.stat().st_size > 0
            ],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    if not candidates:
        raise RuntimeError("yt-dlp download finished, but no video file was found in input.")

    video_path = sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    return {
        "name": video_path.name,
        "stem": video_path.stem,
        "path": str(video_path),
        "size": video_path.stat().st_size,
        "external": False,
        "managed": True,
    }


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

        video = download_video_from_url(url)
        enqueue_video(video)
        append_history("download_complete", {"path": video["path"], "name": video["name"], "size": video["size"]})

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
    allow_reuse_address = False


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
