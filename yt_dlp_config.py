from __future__ import annotations

from pathlib import Path

from yt_dlp.__init__ import parse_options


def user_config_paths() -> list[Path]:
    home = Path.home()
    paths = [
        home / ".config" / "yt-dlp" / "config.txt",
        home / "AppData" / "Roaming" / "yt-dlp" / "config.txt",
        home / ".yt-dlp" / "config.txt",
    ]
    return [path for path in paths if path.exists() and path.is_file()]


def ytdlp_auth_options_from_user_config() -> dict:
    """Return yt-dlp library options that this app must opt into explicitly."""
    config_paths = user_config_paths()
    if not config_paths:
        return {}

    argv: list[str] = []
    for path in config_paths:
        argv.extend(["--config-locations", str(path)])

    try:
        parsed = parse_options(argv)
    except Exception:
        return {}

    options = parsed.ydl_opts
    auth_options: dict = {}
    for key in ("cookiefile", "cookiesfrombrowser", "js_runtimes"):
        value = options.get(key)
        if value:
            auth_options[key] = value
    return auth_options
