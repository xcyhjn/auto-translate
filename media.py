from __future__ import annotations

import json
import math
import subprocess
import tempfile
import threading
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

VALID_ASR_AUDIO_MODES = {"off", "whisper", "strong_whisper"}
VALID_ASR_VAD_MODES = {"auto", "on", "off"}
DEFAULT_ASR_AUDIO_GAIN_DB = 6.0

ASR_AUDIO_PROFILES: dict[str, dict[str, float]] = {
    "whisper": {
        "highpass_hz": 70.0,
        "lowpass_hz": 9000.0,
        "noise_floor_db": -28.0,
        "threshold_db": -28.0,
        "ratio": 3.0,
        "attack_ms": 8.0,
        "release_ms": 120.0,
        "makeup_db": 8.0,
        "loudnorm_i": -18.0,
        "loudnorm_tp": -1.5,
        "loudnorm_lra": 8.0,
    },
    "strong_whisper": {
        "highpass_hz": 60.0,
        "lowpass_hz": 8500.0,
        "noise_floor_db": -32.0,
        "threshold_db": -32.0,
        "ratio": 4.0,
        "attack_ms": 6.0,
        "release_ms": 160.0,
        "makeup_db": 10.0,
        "loudnorm_i": -16.0,
        "loudnorm_tp": -1.5,
        "loudnorm_lra": 7.0,
    },
}


def normalize_asr_audio_mode(mode: str) -> str:
    normalized = (mode or "off").strip().lower().replace("-", "_")
    if normalized not in VALID_ASR_AUDIO_MODES:
        raise ValueError(
            f"Unsupported ASR audio mode: {mode!r}. Expected one of: {sorted(VALID_ASR_AUDIO_MODES)}."
        )
    return normalized


def normalize_asr_vad_mode(mode: str) -> str:
    normalized = (mode or "auto").strip().lower().replace("-", "_")
    if normalized not in VALID_ASR_VAD_MODES:
        raise ValueError(
            f"Unsupported ASR VAD mode: {mode!r}. Expected one of: {sorted(VALID_ASR_VAD_MODES)}."
        )
    return normalized


def build_asr_audio_filter(mode: str, gain_db: float = DEFAULT_ASR_AUDIO_GAIN_DB) -> str:
    normalized_mode = normalize_asr_audio_mode(mode)
    if normalized_mode == "off":
        return ""

    profile = ASR_AUDIO_PROFILES[normalized_mode]
    filters = [
        f"highpass=f={profile['highpass_hz']:g}",
        f"lowpass=f={profile['lowpass_hz']:g}",
        f"afftdn=nf={profile['noise_floor_db']:g}",
    ]
    if gain_db:
        filters.append(f"volume={gain_db:g}dB")
    filters.extend(
        [
            (
                "acompressor="
                f"threshold={profile['threshold_db']:g}dB:"
                f"ratio={profile['ratio']:g}:"
                f"attack={profile['attack_ms']:g}:"
                f"release={profile['release_ms']:g}:"
                f"makeup={profile['makeup_db']:g}dB"
            ),
            (
                "loudnorm="
                f"I={profile['loudnorm_i']:g}:"
                f"TP={profile['loudnorm_tp']:g}:"
                f"LRA={profile['loudnorm_lra']:g}"
            ),
        ]
    )
    return ",".join(filters)


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
        parsed = float(value)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


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
    stderr_lines: list[str] = []
    progress_data: dict[str, str] = {}
    assert process.stdout is not None

    def read_stderr() -> None:
        if process.stderr is None:
            return
        for raw_line in process.stderr:
            stderr_lines.append(raw_line)

    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stderr_thread.start()

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

    return_code = process.wait()
    stderr_thread.join(timeout=2)
    stderr_text = "".join(stderr_lines)
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


def command_available(args: list[str]) -> bool:
    try:
        subprocess.run(
            args,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return True
    except Exception:
        return False


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

    duration = _parse_float(str(fmt.get("duration") or ""))

    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
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
        video_width=_parse_int(str(video_stream.get("width") or "")),
        video_height=_parse_int(str(video_stream.get("height") or "")),
        text_subtitle_streams=text_subtitle_streams,
        image_subtitle_streams=image_subtitle_streams,
    )


def suggest_hwaccel_decoder(input_path: str | Path) -> tuple[str | None, str | None]:
    probe_media(input_path)
    completed = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ]
    )
    codec = completed.stdout.strip().lower()
    decoder_map = {
        "av1": "av1_cuvid",
        "h264": "h264_cuvid",
        "hevc": "hevc_cuvid",
    }
    decoder = decoder_map.get(codec)
    if not decoder:
        return (None, None)
    if not command_available(["ffmpeg", "-hide_banner", "-decoders"]):
        return (None, None)
    return ("cuda", decoder)


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


def enhance_audio_for_asr(
    input_path: str | Path,
    output_path: str | Path,
    *,
    mode: str = "whisper",
    gain_db: float = DEFAULT_ASR_AUDIO_GAIN_DB,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_mode = normalize_asr_audio_mode(mode)
    if normalized_mode == "off":
        output_path.write_bytes(input_path.read_bytes())
        return output_path

    filter_chain = build_asr_audio_filter(normalized_mode, gain_db=gain_db)
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
            "-c:a",
            "pcm_s16le",
            "-af",
            filter_chain,
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
