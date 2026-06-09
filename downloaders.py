from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from .media import merge_video_with_audio, probe_media
from .yt_dlp_config import ytdlp_auth_options_from_user_config


VIDEO_SUFFIXES = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
TEMP_SUFFIXES = {".part", ".ytdl", ".temp", ".tmp", ".crdownload"}
UNSUPPORTED_DIRECT_PROTOCOLS = {"m3u8", "m3u8_native", "http_dash_segments", "f4m"}

DownloadStageCallback = Callable[[str, dict], None]


def get_youtube_dl_class():
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed in this Python environment. "
            "Install it with: python -m pip install yt-dlp"
        ) from exc
    return YoutubeDL


class DownloadError(RuntimeError):
    def __init__(self, message: str, *, code: str = "DOWNLOAD_FAILED", details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ManualImportRequired(DownloadError):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message, code="MANUAL_IMPORT_REQUIRED", details=details)


@dataclass
class DownloadConfig:
    input_dir: Path
    backend: str = "auto"
    proxy_url: str | None = None
    idm_exe_path: str = ""
    idm_output_dir: Path | None = None
    idm_wait_timeout_seconds: int = 1800
    idm_stable_seconds: int = 8
    keep_intermediate_files: bool = False
    manual_fallback: bool = True

    @classmethod
    def from_ui_config(cls, config: dict, *, input_dir: Path, proxy_url: str | None) -> "DownloadConfig":
        idm_output = config.get("idm_output_dir") or str(input_dir)
        return cls(
            input_dir=input_dir,
            backend=str(config.get("download_backend") or "auto").lower(),
            proxy_url=proxy_url,
            idm_exe_path=str(config.get("idm_exe_path") or ""),
            idm_output_dir=Path(idm_output),
            idm_wait_timeout_seconds=_int_config(config.get("idm_wait_timeout_seconds"), 1800),
            idm_stable_seconds=_int_config(config.get("idm_stable_seconds"), 8),
            keep_intermediate_files=bool(config.get("download_keep_intermediate_files", False)),
            manual_fallback=bool(config.get("download_manual_fallback", True)),
        )


@dataclass
class DownloadResult:
    path: Path
    method: str
    source_url: str
    details: dict = field(default_factory=dict)

    def as_video_dict(self) -> dict:
        return {
            "name": self.path.name,
            "stem": self.path.stem,
            "path": str(self.path),
            "size": self.path.stat().st_size,
            "external": False,
            "managed": True,
            "download_method": self.method,
            "download_details": self.details,
        }


@dataclass
class DirectMedia:
    url: str
    kind: str
    ext: str
    title: str
    format_id: str
    headers: dict = field(default_factory=dict)

    @property
    def suffix(self) -> str:
        ext = self.ext.lstrip(".") or "bin"
        return f".{ext}"


def _int_config(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def emit(callback: DownloadStageCallback | None, stage: str, payload: dict) -> None:
    if callback:
        callback(stage, payload)


def safe_filename(name: str, fallback: str = "download") -> str:
    cleaned = unquote(str(name or "")).strip()
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-")
    if not cleaned:
        cleaned = fallback
    return cleaned[:160]


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / safe_filename(filename)
    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{index}{suffix}"
        index += 1
    return candidate


def snapshot_files(directory: Path) -> set[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    return {item.resolve() for item in directory.iterdir() if item.is_file()}


def cleanup_partial_files(directory: Path, before_paths: set[Path]) -> None:
    for item in directory.iterdir():
        try:
            if item.resolve() in before_paths or not item.is_file():
                continue
            if item.suffix.lower() in TEMP_SUFFIXES or item.stat().st_size == 0:
                item.unlink()
        except Exception:
            continue


def newest_video_candidate(directory: Path, before_paths: set[Path]) -> Path | None:
    candidates = [
        item
        for item in directory.iterdir()
        if item.is_file()
        and item.resolve() not in before_paths
        and item.suffix.lower() in VIDEO_SUFFIXES
        and item.stat().st_size > 0
    ]
    if not candidates:
        candidates = [
            item
            for item in directory.iterdir()
            if item.is_file() and item.suffix.lower() in VIDEO_SUFFIXES and item.stat().st_size > 0
        ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def default_idm_paths() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(Path(root) / "Internet Download Manager" / "IDMan.exe")
    candidates.extend(
        [
            Path("C:/Program Files (x86)/Internet Download Manager/IDMan.exe"),
            Path("C:/Program Files/Internet Download Manager/IDMan.exe"),
        ]
    )
    return candidates


def resolve_idm_exe(configured_path: str | None = None) -> Path | None:
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.exists() and candidate.is_file():
            return candidate
    for candidate in default_idm_paths():
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def check_idm(config: DownloadConfig) -> dict:
    resolved = resolve_idm_exe(config.idm_exe_path)
    output_dir = config.idm_output_dir or config.input_dir
    return {
        "ok": bool(resolved),
        "configured_path": config.idm_exe_path,
        "resolved_path": str(resolved) if resolved else "",
        "output_dir": str(output_dir),
        "output_dir_exists": output_dir.exists(),
        "output_dir_writable": _directory_writable(output_dir),
    }


def _directory_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".autosub_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


class YtdlpDownloader:
    def __init__(self, config: DownloadConfig, callback: DownloadStageCallback | None = None) -> None:
        self.config = config
        self.callback = callback

    def base_options(self) -> dict:
        options = {
            **ytdlp_auth_options_from_user_config(),
            "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]/best",
            "merge_output_format": "mp4",
            "outtmpl": str(self.config.input_dir / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
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
        if self.config.proxy_url:
            options["proxy"] = self.config.proxy_url
        return options

    def native_download(self, url: str) -> DownloadResult:
        self.config.input_dir.mkdir(parents=True, exist_ok=True)
        before = snapshot_files(self.config.input_dir)
        attempts = [
            ("primary", self.base_options()),
            (
                "fallback",
                {
                    **self.base_options(),
                    "format": "b[ext=mp4]/best",
                    "merge_output_format": None,
                },
            ),
        ]
        errors: list[str] = []

        for attempt_name, options in attempts:
            emit(self.callback, "download_ytdlp_start", {"url": url, "attempt": attempt_name})
            try:
                YoutubeDL = get_youtube_dl_class()
                with YoutubeDL(options) as ydl:
                    ydl.extract_info(url, download=True)
            except Exception as exc:
                cleanup_partial_files(self.config.input_dir, before)
                message = str(exc)
                errors.append(f"{attempt_name}: {message}")
                emit(
                    self.callback,
                    "download_ytdlp_failed",
                    {"attempt": attempt_name, "error": message},
                )
                continue

            candidate = newest_video_candidate(self.config.input_dir, before)
            if candidate:
                emit(
                    self.callback,
                    "download_ytdlp_complete",
                    {"path": str(candidate), "size_bytes": candidate.stat().st_size, "attempt": attempt_name},
                )
                return DownloadResult(
                    path=candidate,
                    method=f"yt-dlp:{attempt_name}",
                    source_url=url,
                    details={"attempt": attempt_name},
                )
            errors.append(f"{attempt_name}: no media file was created")

        raise DownloadError(
            "yt-dlp download failed; " + " | ".join(errors[-2:]),
            code="YTDLP_NATIVE_FAILED",
            details={"errors": errors},
        )

    def extract_direct_media(self, url: str) -> list[DirectMedia]:
        emit(self.callback, "download_extract_start", {"url": url})
        options = {
            **self.base_options(),
            "skip_download": True,
        }
        try:
            YoutubeDL = get_youtube_dl_class()
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            raise DownloadError(
                f"yt-dlp could not extract direct media URLs: {exc}",
                code="YTDLP_EXTRACT_FAILED",
            ) from exc

        if not isinstance(info, dict):
            raise DownloadError("yt-dlp returned an empty media description", code="YTDLP_EXTRACT_FAILED")

        if info.get("_type") == "playlist" and info.get("entries"):
            first_entry = next((entry for entry in info["entries"] if entry), None)
            if isinstance(first_entry, dict):
                info = first_entry

        title = safe_filename(info.get("title") or info.get("id") or "download")
        direct_items = self._direct_items_from_info(info)
        media = [self._direct_media_from_item(item, title, info) for item in direct_items]
        media = [item for item in media if item is not None]
        if not media:
            raise DownloadError(
                "yt-dlp did not expose direct HTTP media URLs suitable for IDM",
                code="YTDLP_EXTRACT_NO_DIRECT_URL",
            )

        emit(
            self.callback,
            "download_extract_complete",
            {
                "url": url,
                "title": title,
                "count": len(media),
                "kinds": ",".join(item.kind for item in media),
            },
        )
        return media

    def _direct_items_from_info(self, info: dict) -> list[dict]:
        if isinstance(info.get("requested_downloads"), list) and info["requested_downloads"]:
            return [item for item in info["requested_downloads"] if isinstance(item, dict)]
        if isinstance(info.get("requested_formats"), list) and info["requested_formats"]:
            return [item for item in info["requested_formats"] if isinstance(item, dict)]
        if info.get("url"):
            return [info]
        return []

    def _direct_media_from_item(self, item: dict, title: str, parent_info: dict) -> DirectMedia | None:
        url = str(item.get("url") or "")
        if not url.startswith(("http://", "https://")):
            return None

        protocol = str(item.get("protocol") or parent_info.get("protocol") or "").lower()
        if protocol in UNSUPPORTED_DIRECT_PROTOCOLS:
            return None

        ext = str(item.get("ext") or _ext_from_url(url) or "mp4").lstrip(".")
        vcodec = str(item.get("vcodec") or "")
        acodec = str(item.get("acodec") or "")
        has_video = bool(vcodec and vcodec != "none")
        has_audio = bool(acodec and acodec != "none")
        if has_video and has_audio:
            kind = "media"
        elif has_video:
            kind = "video"
        elif has_audio:
            kind = "audio"
        else:
            kind = "media"

        headers = {}
        if isinstance(parent_info.get("http_headers"), dict):
            headers.update(parent_info["http_headers"])
        if isinstance(item.get("http_headers"), dict):
            headers.update(item["http_headers"])

        return DirectMedia(
            url=url,
            kind=kind,
            ext=ext,
            title=title,
            format_id=str(item.get("format_id") or ""),
            headers=headers,
        )


class IdmDownloader:
    def __init__(self, config: DownloadConfig, callback: DownloadStageCallback | None = None) -> None:
        self.config = config
        self.callback = callback

    def download_url(self, media: DirectMedia, *, directory: Path, filename: str) -> Path:
        idm_exe = resolve_idm_exe(self.config.idm_exe_path)
        if not idm_exe:
            raise DownloadError(
                "IDMan.exe was not found. Set the IDM path in download settings.",
                code="IDM_EXE_NOT_FOUND",
            )

        directory.mkdir(parents=True, exist_ok=True)
        target_path = unique_path(directory, filename)
        before = snapshot_files(directory)
        emit(
            self.callback,
            "download_idm_start",
            {
                "path": str(target_path),
                "kind": media.kind,
                "format_id": media.format_id,
                "has_headers": bool(media.headers),
            },
        )

        command = [
            str(idm_exe),
            "/d",
            media.url,
            "/p",
            str(target_path.parent),
            "/f",
            target_path.name,
            "/n",
        ]
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            raise DownloadError(f"Could not start IDM: {exc}", code="IDM_START_FAILED") from exc

        completed = self.wait_for_file(target_path, before)
        emit(
            self.callback,
            "download_idm_complete",
            {"path": str(completed), "size_bytes": completed.stat().st_size, "kind": media.kind},
        )
        return completed

    def wait_for_file(self, target_path: Path, before_paths: set[Path]) -> Path:
        deadline = time.monotonic() + self.config.idm_wait_timeout_seconds
        stable_seconds = max(2, self.config.idm_stable_seconds)
        last_sizes: dict[Path, int] = {}
        stable_since: dict[Path, float] = {}
        last_emit = 0.0

        while time.monotonic() < deadline:
            candidates = self._candidate_files(target_path, before_paths)
            now = time.monotonic()
            for candidate in candidates:
                try:
                    size = candidate.stat().st_size
                except OSError:
                    continue
                if size <= 0:
                    continue
                if last_sizes.get(candidate) == size:
                    stable_since.setdefault(candidate, now)
                    if now - stable_since[candidate] >= stable_seconds:
                        return candidate
                else:
                    last_sizes[candidate] = size
                    stable_since[candidate] = now

                if now - last_emit >= 2:
                    emit(
                        self.callback,
                        "download_idm_wait",
                        {
                            "path": str(candidate),
                            "size_bytes": size,
                            "remaining_seconds": max(0, int(deadline - now)),
                        },
                    )
                    last_emit = now
            time.sleep(1)

        raise DownloadError(
            f"Timed out waiting for IDM to finish: {target_path}",
            code="IDM_TIMEOUT",
            details={"path": str(target_path)},
        )

    def _candidate_files(self, target_path: Path, before_paths: set[Path]) -> list[Path]:
        candidates: list[Path] = []
        if target_path.exists() and target_path.is_file():
            candidates.append(target_path)
        for item in target_path.parent.iterdir():
            if not item.is_file() or item.suffix.lower() in TEMP_SUFFIXES:
                continue
            try:
                is_new = item.resolve() not in before_paths
            except OSError:
                is_new = False
            if item.name == target_path.name or (is_new and item.stem.startswith(target_path.stem)):
                candidates.append(item)
        return sorted(set(candidates), key=lambda path: path.stat().st_mtime, reverse=True)


class DownloadManager:
    def __init__(self, config: DownloadConfig, callback: DownloadStageCallback | None = None) -> None:
        self.config = config
        self.callback = callback
        self.ytdlp = YtdlpDownloader(config, callback)
        self.idm = IdmDownloader(config, callback)

    def download(self, url: str) -> DownloadResult:
        backend = (self.config.backend or "auto").lower()
        if backend == "ytdlp":
            return self.ytdlp.native_download(url)
        if backend == "idm":
            return self.idm_bridge_download(url)
        if backend == "manual":
            return self.require_manual_import(url)
        if backend != "auto":
            emit(self.callback, "download_backend_unknown", {"backend": backend})

        try:
            return self.ytdlp.native_download(url)
        except DownloadError as native_error:
            emit(
                self.callback,
                "download_auto_fallback",
                {"from": "yt-dlp", "to": "idm", "error": str(native_error)},
            )
            try:
                return self.idm_bridge_download(url)
            except DownloadError as idm_error:
                if self.config.manual_fallback:
                    return self.require_manual_import(
                        url,
                        details={"yt_dlp_error": str(native_error), "idm_error": str(idm_error)},
                    )
                raise idm_error

    def idm_bridge_download(self, url: str) -> DownloadResult:
        media_items = self.ytdlp.extract_direct_media(url)
        media_only = [item for item in media_items if item.kind == "media"]
        video_only = [item for item in media_items if item.kind == "video"]
        audio_only = [item for item in media_items if item.kind == "audio"]

        if media_only:
            item = media_only[0]
            output_dir = self.config.idm_output_dir or self.config.input_dir
            filename = f"{item.title}{item.suffix}"
            downloaded = self.idm.download_url(item, directory=output_dir, filename=filename)
            final_path = self._ensure_in_input(downloaded)
            self._validate_video(final_path, require_audio=True)
            return DownloadResult(
                path=final_path,
                method="idm:single",
                source_url=url,
                details={"direct_count": len(media_items), "format_id": item.format_id},
            )

        if video_only and audio_only:
            video_item = video_only[0]
            audio_item = audio_only[0]
            parts_dir = self.config.input_dir / "_idm_parts"
            video_path = self.idm.download_url(
                video_item,
                directory=parts_dir,
                filename=f"{video_item.title}.video{video_item.suffix}",
            )
            audio_path = self.idm.download_url(
                audio_item,
                directory=parts_dir,
                filename=f"{audio_item.title}.audio{audio_item.suffix}",
            )
            final_path = unique_path(self.config.input_dir, f"{video_item.title}.mp4")
            emit(
                self.callback,
                "download_merge_start",
                {"video_path": str(video_path), "audio_path": str(audio_path), "merged_path": str(final_path)},
            )
            merge_video_with_audio(video_path, audio_path, final_path)
            emit(
                self.callback,
                "download_merge_complete",
                {"path": str(final_path), "size_bytes": final_path.stat().st_size},
            )
            self._validate_video(final_path, require_audio=True)
            self._cleanup_parts([video_path, audio_path])
            return DownloadResult(
                path=final_path,
                method="idm:merged",
                source_url=url,
                details={
                    "direct_count": len(media_items),
                    "video_format_id": video_item.format_id,
                    "audio_format_id": audio_item.format_id,
                },
            )

        raise DownloadError(
            "IDM bridge needs either a single media URL or separate video/audio URLs.",
            code="IDM_UNSUPPORTED_MEDIA_SET",
            details={"kinds": [item.kind for item in media_items]},
        )

    def require_manual_import(self, url: str, details: dict | None = None) -> DownloadResult:
        message = (
            "Automatic download failed. Use the browser IDM integration to download the video into "
            f"{self.config.input_dir}, then click scan input in the UI."
        )
        emit(self.callback, "download_manual_required", {"url": url, "input_dir": str(self.config.input_dir)})
        raise ManualImportRequired(message, details=details)

    def _ensure_in_input(self, path: Path) -> Path:
        input_dir = self.config.input_dir.resolve()
        try:
            if path.parent.resolve() == input_dir:
                return path
        except OSError:
            pass
        destination = unique_path(self.config.input_dir, path.name)
        shutil.copy2(path, destination)
        return destination

    def _validate_video(self, path: Path, *, require_audio: bool) -> None:
        try:
            media = probe_media(path)
        except Exception as exc:
            raise DownloadError(f"Downloaded file is not readable by ffprobe: {exc}", code="MEDIA_PROBE_FAILED") from exc
        if require_audio and not media.has_audio:
            raise DownloadError(
                "Downloaded video has no audio track. Try manual IDM import or attach an external audio file.",
                code="DOWNLOADED_VIDEO_HAS_NO_AUDIO",
            )

    def _cleanup_parts(self, paths: list[Path]) -> None:
        if self.config.keep_intermediate_files:
            return
        parts_dir = (self.config.input_dir / "_idm_parts").resolve()
        for path in paths:
            try:
                if path.resolve().parent == parts_dir and path.exists():
                    path.unlink()
            except Exception:
                continue


def _ext_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix:
        return suffix
    return ""
