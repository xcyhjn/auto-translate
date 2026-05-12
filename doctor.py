from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys


def command_version(command: str) -> str:
    path = shutil.which(command)
    if not path:
        return "not found on PATH"

    completed = subprocess.run(
        [command, "-version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    first_output = completed.stdout or completed.stderr
    first_line = first_output.splitlines()[0] if first_output.splitlines() else "unknown version"
    return f"{path} | {first_line}"


def module_status(module_name: str) -> str:
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return "not installed in this Python environment"
    return f"available at {spec.origin}"


def env_status(name: str) -> str:
    return "set" if os.getenv(name) else "not set"


def main() -> None:
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE")

    print(f"Current working directory: {os.getcwd()}")
    print(f"Python: {sys.version}")
    print(f"Python executable: {sys.executable}")
    print(f"faster_whisper module: {module_status('faster_whisper')}")
    print(f"openai module: {module_status('openai')}")
    print(f"OPENAI_API_KEY: {env_status('OPENAI_API_KEY')}")
    print(f"OPENAI_BASE_URL: {base_url or 'not set'}")
    print(f"ffmpeg: {command_version('ffmpeg')}")
    print(f"ffprobe: {command_version('ffprobe')}")
    print("提示：当前项目位于 D:\\桌面\\autosub_zh。")
    print("提示：运行模块命令时请先 cd D:\\桌面，然后执行 python -m autosub_zh.doctor。")
    print("提示：验证中转站可运行 python -m autosub_zh.cli --openai-dry-run。")


if __name__ == "__main__":
    main()
