from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .models import MediaInfo


TEXT_SUBTITLE_CODECS = {
    "subrip",
    "ass",
    "ssa",
    "webvtt",
    "mov_text",
    "text",
}

IMAGE_SUBTITLE_CODECS = {
    "hdmv_pgs_subtitle",
    "dvd_subtitle",
    "dvb_subtitle",
    "xsub",
}

ProgressCallback = Callable[[dict], None]


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        tool = args[0]
        raise RuntimeError(
            f"{tool} was not found on PATH. Install FFmpeg and make sure "
            f"`{tool} -version` works in a new PowerShell window."
        ) from exc
    except subprocess.CalledProcessError as exc:
        command = " ".join(args)
        details = exc.stderr.strip() or exc.stdout.strip()
        raise RuntimeError(f"Command failed: {command}\n{details}") from exc


def _parse_float(value: str | None) -> float | None:
    if value in {None, "", "N/A"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value in {None, "", "N/A"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_speed(value: str | None) -> float | None:
    if not value:
        return None
    return _parse_float(value.removesuffix("x"))


def build_ffmpeg_progress_snapshot(progress_data: dict[str, str]) -> dict:
    snapshot: dict[str, float | int] = {}

    out_time_us = _parse_int(progress_data.get("out_time_us"))
    out_time_ms = _parse_int(progress_data.get("out_time_ms"))
    if out_time_us is not None:
        snapshot["out_time_seconds"] = out_time_us / 1_000_000
    elif out_time_ms is not None:
        snapshot["out_time_seconds"] = out_time_ms / 1_000_000

    total_size = _parse_int(progress_data.get("total_size"))
    if total_size is not None:
        snapshot["size_bytes"] = total_size

    frame = _parse_int(progress_data.get("frame"))
    if frame is not None:
        snapshot["frame"] = frame

    fps = _parse_float(progress_data.get("fps"))
    if fps is not None:
        snapshot["fps"] = fps

    speed = _parse_speed(progress_data.get("speed"))
    if speed is not None:
        snapshot["speed"] = speed

    return snapshot


def run_ffmpeg_command(
    args: list[str],
    *,
    progress_callback: ProgressCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    if progress_callback is None:
        return run_command(args)

    progress_args = list(args)
    progress_args[1:1] = ["-progress", "pipe:1", "-nostats"]

    try:
        process = subprocess.Popen(
            progress_args,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        tool = progress_args[0]
        raise RuntimeError(
            f"{tool} was not found on PATH. Install FFmpeg and make sure "
            f"`{tool} -version` works in a new PowerShell window."
        ) from exc

    stdout_lines: list[str] = []
    progress_data: dict[str, str] = {}
    assert process.stdout is not None

    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        stdout_lines.append(line)
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        if key == "progress":
            snapshot = build_ffmpeg_progress_snapshot(progress_data)
            if snapshot:
                snapshot["state"] = value
                progress_callback(snapshot)
            if value == "end":
                progress_data = {}
            else:
                progress_data = {}
            continue

        progress_data[key] = value

    stderr_text = process.stderr.read() if process.stderr is not None else ""
    return_code = process.wait()
    completed = subprocess.CompletedProcess(
        progress_args,
        return_code,
        stdout="\n".join(stdout_lines),
        stderr=stderr_text,
    )
    if return_code != 0:
        command = " ".join(progress_args)
        details = stderr_text.strip() or completed.stdout.strip()
        raise RuntimeError(f"Command failed: {command}\n{details}")
    return completed


def probe_media(input_path: str | Path) -> MediaInfo:
    path = str(input_path)
    completed = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
    )
    payload = json.loads(completed.stdout)
    streams = payload.get("streams", [])
    fmt = payload.get("format", {})

    duration = None
    if fmt.get("duration"):
        duration = float(fmt["duration"])

    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    text_subtitle_streams = []
    image_subtitle_streams = []

    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue
        codec_name = stream.get("codec_name")
        if codec_name in TEXT_SUBTITLE_CODECS:
            text_subtitle_streams.append(stream)
        elif codec_name in IMAGE_SUBTITLE_CODECS:
            image_subtitle_streams.append(stream)

    return MediaInfo(
        path=path,
        duration=duration,
        has_audio=has_audio,
        text_subtitle_streams=text_subtitle_streams,
        image_subtitle_streams=image_subtitle_streams,
    )


def extract_audio(
    input_path: str | Path,
    work_dir: str | Path | None = None,
    *,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="autosub_zh_")

    output_path = Path(work_dir) / f"{Path(input_path).stem}.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    run_ffmpeg_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ],
        progress_callback=progress_callback,
    )
    return output_path


def merge_video_with_audio(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    *,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    run_ffmpeg_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ],
        progress_callback=progress_callback,
    )
    return output_path
