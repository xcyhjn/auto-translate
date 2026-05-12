from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

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


def extract_audio(input_path: str | Path, work_dir: str | Path | None = None) -> Path:
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="autosub_zh_")

    output_path = Path(work_dir) / f"{Path(input_path).stem}.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    run_command(
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
        ]
    )
    return output_path


def merge_video_with_audio(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    run_command(
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
        ]
    )
    return output_path
