from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from .yt_dlp_config import ytdlp_auth_options_from_user_config


YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def get_youtube_dl_class():
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed in this Python environment. "
            "Install it with: python -m pip install yt-dlp"
        ) from exc
    return YoutubeDL


@dataclass(slots=True)
class YouTubeMeta:
    video_id: str
    video_url: str
    author: str
    published_at: str
    title: str
    description: str
    cover_url: str
    cover_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "video_url": self.video_url,
            "author": self.author,
            "published_at": self.published_at,
            "title": self.title,
            "description": self.description,
            "cover_url": self.cover_url,
            "cover_path": self.cover_path,
        }

    def display_text(self) -> str:
        return (
            f"原视频链接：{self.video_url}\n"
            f"原作者：{self.author}\n"
            f"原发布时间：{self.published_at}\n"
            f"原视频标题：{self.title}\n"
            f"原视频简介：{self.description}\n"
        )


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in YOUTUBE_DOMAINS)


def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if host.endswith("youtu.be"):
        candidate = parsed.path.strip("/").split("/")[0]
        if YOUTUBE_ID_RE.match(candidate or ""):
            return candidate

    query = parse_qs(parsed.query)
    candidate = (query.get("v") or [""])[0]
    if YOUTUBE_ID_RE.match(candidate or ""):
        return candidate

    YoutubeDL = get_youtube_dl_class()
    with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    if isinstance(info, dict):
        candidate = str(info.get("id") or "").strip()
        if YOUTUBE_ID_RE.match(candidate):
            return candidate
    raise ValueError("Could not extract a YouTube video id from the URL.")


def fetch_youtube_meta(url: str, *, proxy_url: str | None = None) -> YouTubeMeta:
    options = {
        **ytdlp_auth_options_from_user_config(),
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    if proxy_url:
        options["proxy"] = proxy_url
    YoutubeDL = get_youtube_dl_class()
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("Could not read YouTube metadata.")

    video_id = str(info.get("id") or extract_video_id(url))
    author = str(info.get("channel") or info.get("uploader") or info.get("channel_title") or info.get("uploader_id") or "").strip()
    published_at = format_published_at(info)
    title = str(info.get("title") or "").strip()
    description = str(info.get("description") or "").strip()
    thumbnails = info.get("thumbnails") or []
    cover_url = _pick_thumbnail_url(thumbnails) or _pick_cover_from_info(info) or build_fallback_cover_url(video_id)

    return YouTubeMeta(
        video_id=video_id,
        video_url=url,
        author=author or "Unknown",
        published_at=published_at or "Unknown",
        title=title or "Unknown",
        description=description or "No description",
        cover_url=cover_url,
    )


def fetch_youtube_info(url: str, *, proxy_url: str | None = None) -> YouTubeMeta:
    meta = fetch_youtube_meta(url, proxy_url=proxy_url)
    meta.cover_url = ""
    meta.cover_path = None
    return meta


def _pick_thumbnail_url(thumbnails: list[dict]) -> str:
    order = {"maxres": 5, "standard": 4, "high": 3, "medium": 2, "default": 1}
    ranked: list[tuple[int, int, str]] = []
    for index, item in enumerate(thumbnails):
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        name = str(item.get("id") or "").lower()
        preference = order.get(name, 0)
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        area = max(width * height, 0)
        ranked.append((preference, area or width, url))
    if not ranked:
        return ""
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def _pick_cover_from_info(info: dict) -> str:
    for key in ("thumbnail", "thumbnails"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build_fallback_cover_url(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"


def format_published_at(info: dict) -> str:
    timestamp = info.get("timestamp") or info.get("release_timestamp")
    if timestamp:
        try:
            dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).astimezone()
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    upload_date = str(info.get("upload_date") or info.get("release_date") or "").strip()
    if len(upload_date) == 8 and upload_date.isdigit():
        return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    return upload_date or "Unknown"


def build_output_dir(output_root: Path, meta: YouTubeMeta) -> Path:
    slug = safe_project_slug(meta.title, fallback=meta.video_id)
    return output_root / f"youtube-{meta.video_id}-{slug}"


def safe_slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-._")
    return cleaned[:80]


def safe_project_slug(text: str, fallback: str = "video") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "").strip()).strip("-._")
    return cleaned[:160] or fallback


def download_cover(url: str, output_path: Path, *, proxy_url: str | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60.0, proxy=proxy_url, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        output_path.write_bytes(response.content)
    return output_path


def build_padded_cover(source_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vf",
        "scale=1280:960:force_original_aspect_ratio=decrease,pad=1280:960:(ow-iw)/2:(oh-ih)/2:black",
        "-frames:v",
        "1",
        str(output_path),
    ]
    try:
        subprocess.run(
            command,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg was not found on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() or exc.stdout.strip()
        raise RuntimeError(f"Could not generate 1280x960 padded cover: {details}") from exc
    return output_path


def save_youtube_meta(output_dir: Path, meta: YouTubeMeta) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "00_youtube_meta.json"
    path.write_text(json.dumps(meta.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "00_youtube_info.txt").write_text(meta.display_text(), encoding="utf-8")
    return path


def ensure_cover(meta: YouTubeMeta, output_dir: Path, *, proxy_url: str | None = None) -> Path:
    cover_path = output_dir / "00_youtube_cover.jpg"
    if not meta.cover_url:
        raise RuntimeError("No YouTube cover URL could be resolved.")
    try:
        download_cover(meta.cover_url, cover_path, proxy_url=proxy_url)
    except Exception:
        fallback_url = build_fallback_cover_url(meta.video_id)
        download_cover(fallback_url, cover_path, proxy_url=proxy_url)
    meta.cover_path = str(cover_path)
    return cover_path


def ensure_padded_cover(output_dir: Path) -> Path:
    cover_path = output_dir / "00_youtube_cover.jpg"
    if not cover_path.exists():
        raise FileNotFoundError(f"Original cover not found: {cover_path}")
    padded_path = output_dir / "00_youtube_cover_1280x960.jpg"
    return build_padded_cover(cover_path, padded_path)
