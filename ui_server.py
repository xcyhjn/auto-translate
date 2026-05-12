from __future__ import annotations

import json
import subprocess
import threading
import traceback
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .models import BilingualSubtitleStyle
from .pipeline_core import run_pipeline


BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
WEB_DIR = BASE_DIR / "web"
CONFIG_PATH = BASE_DIR / "ui_config.json"
ERROR_LOG_PATH = BASE_DIR / "ui_server_error_trace.log"

DEFAULT_CONFIG = {
    "src_lang": "en",
    "dst_lang": "zh-Hans",
    "model": "tiny",
    "device": "cpu",
    "compute_type": "int8",
    "beam_size": 5,
    "translation_model": "gpt-5.4-mini",
    "translation_chunk_size": 40,
    "translation_retries": 2,
    "openai_base_url": "",
    "audio_override_path": "",
    "load_existing_segments": True,
    "preview_seconds": 60,
    "style": asdict(BilingualSubtitleStyle()),
}

STATE = {
    "running": False,
    "current_stage": "idle",
    "history": [],
    "last_manifest": None,
    "last_error": None,
    "imported_videos": [],
    "imported_audios": [],
}
STATE_LOCK = threading.Lock()


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


def list_input_videos() -> list[dict]:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    videos = []
    for path in sorted(INPUT_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".webm"}:
            videos.append(
                {
                    "name": path.name,
                    "stem": path.stem,
                    "path": str(path),
                    "size": path.stat().st_size,
                }
            )
    return videos


def collect_videos() -> list[dict]:
    builtin = list_input_videos()
    imported = STATE.get("imported_videos", [])
    seen = {video["path"] for video in builtin}
    merged = builtin[:]
    for video in imported:
        if video["path"] not in seen:
            merged.append(video)
    return merged


def collect_audios() -> list[dict]:
    return STATE.get("imported_audios", [])


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


def pick_input_video() -> dict | None:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.OpenFileDialog; "
            "$dialog.Filter = 'Video Files|*.mp4;*.mkv;*.mov;*.avi;*.webm|All Files|*.*'; "
            "$dialog.Multiselect = $false; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "Write-Output $dialog.FileName }"
        ),
    ]
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    chosen = (completed.stdout or "").strip()
    if not chosen:
        return None
    path = Path(chosen)
    return {
        "name": path.name,
        "stem": path.stem,
        "path": str(path),
        "size": path.stat().st_size,
        "external": True,
    }


def pick_audio_file() -> dict | None:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.OpenFileDialog; "
            "$dialog.Filter = 'Audio Files|*.mp3;*.wav;*.m4a;*.aac;*.flac|All Files|*.*'; "
            "$dialog.Multiselect = $false; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "Write-Output $dialog.FileName }"
        ),
    ]
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    chosen = (completed.stdout or "").strip()
    if not chosen:
        return None
    path = Path(chosen)
    return {
        "name": path.name,
        "stem": path.stem,
        "path": str(path),
        "size": path.stat().st_size,
        "external": True,
    }


def register_imported_video(video: dict) -> None:
    with STATE_LOCK:
        imported = STATE["imported_videos"]
        if all(item["path"] != video["path"] for item in imported):
            imported.append(video)


def register_imported_audio(audio: dict) -> None:
    with STATE_LOCK:
        imported = STATE["imported_audios"]
        if all(item["path"] != audio["path"] for item in imported):
            imported.append(audio)


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

    if selected_path is not None:
        subprocess.run(["explorer.exe", "/select,", str(selected_path)], check=False)
        return str(selected_path)

    subprocess.run(["explorer.exe", str(folder)], check=False)
    return str(folder)


def append_history(stage: str, payload: dict) -> None:
    with STATE_LOCK:
        STATE["current_stage"] = stage
        STATE["history"].append({"stage": stage, "payload": payload})
        STATE["history"] = STATE["history"][-200:]


def run_pipeline_job(video_path: str, config: dict) -> None:
    input_path = Path(video_path)
    style = BilingualSubtitleStyle(**config["style"])
    try:
        with STATE_LOCK:
            STATE["running"] = True
            STATE["current_stage"] = "starting"
            STATE["history"] = []
            STATE["last_error"] = None

        manifest = run_pipeline(
            input_path=input_path,
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
    except Exception as exc:
        with STATE_LOCK:
            STATE["running"] = False
            STATE["current_stage"] = "error"
            STATE["last_error"] = {
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }


class UIServerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def _json_response(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error_response(self, exc: Exception) -> None:
        append_error_log(traceback.format_exc())
        self._json_response(
            {
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
            status=500,
        )

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/bootstrap":
                self._json_response(
                    {
                        "videos": collect_videos(),
                        "audios": collect_audios(),
                        "projects": read_output_tree(),
                        "config": read_config(),
                        "state": STATE,
                    }
                )
                return

            if parsed.path == "/api/state":
                self._json_response(
                    {
                        "state": STATE,
                        "projects": read_output_tree(),
                        "videos": collect_videos(),
                        "audios": collect_audios(),
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
                self._json_response(
                    {
                        "path": str(target),
                        "content": target.read_text(encoding="utf-8", errors="replace"),
                    }
                )
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
            payload = json.loads(raw.decode("utf-8"))

            if parsed.path == "/api/save-config":
                config = {**read_config(), **payload}
                write_config(config)
                self._json_response({"ok": True, "config": config})
                return

            if parsed.path == "/api/pick-input":
                video = pick_input_video()
                if video is None:
                    self._json_response({"ok": False, "cancelled": True})
                    return
                register_imported_video(video)
                self._json_response({"ok": True, "video": video, "videos": collect_videos()})
                return

            if parsed.path == "/api/pick-audio":
                audio = pick_audio_file()
                if audio is None:
                    self._json_response({"ok": False, "cancelled": True})
                    return
                register_imported_audio(audio)
                self._json_response({"ok": True, "audio": audio, "audios": collect_audios()})
                return

            if parsed.path == "/api/open-output":
                opened = open_output_in_explorer(payload.get("project_path"))
                self._json_response({"ok": True, "opened": opened})
                return

            if parsed.path == "/api/run":
                config = {**read_config(), **payload.get("config", {})}
                video_path = payload["video_path"]
                thread = threading.Thread(target=run_pipeline_job, args=(video_path, config), daemon=True)
                thread.start()
                self._json_response({"ok": True})
                return

            self._json_response({"error": "not found"}, status=404)
        except Exception as exc:
            self._error_response(exc)


def main() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 8765), UIServerHandler)
    print("UI server running at http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()
