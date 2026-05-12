# OpenAI API 接入说明

当前项目路径：

```text
D:\桌面\autosub_zh
```

运行模块命令时，先进入父目录：

```powershell
cd D:\桌面
```

## SDK 是什么

这里的 SDK 指 Python 包 `openai`。它负责：

- 读取 `OPENAI_API_KEY`
- 把请求发到 OpenAI 或兼容 OpenAI 的中转站
- 返回模型响应对象，例如 `response.output_text`

安装：

```powershell
cd D:\桌面
python -m pip install openai
```

## 环境变量怎么写

临时配置，当前 PowerShell 窗口有效：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_BASE_URL="https://www.gptcodeplan.com"
```

永久配置，写入 Windows 当前用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "你的 API Key", "User")
[Environment]::SetEnvironmentVariable("OPENAI_BASE_URL", "https://www.gptcodeplan.com", "User")
```

永久配置后要重新打开 VS Code 或终端。

## 代码接入位置

- `translate.py`
  - `resolve_openai_base_url()`：读取命令行参数、`OPENAI_BASE_URL` 或 `OPENAI_API_BASE`
  - `translate_chunk_with_openai()`：真正调用 OpenAI 兼容接口翻译字幕
  - `dry_run_openai_translation()`：发送极小测试请求，验证 key、模型和中转站
- `cli.py`
  - `--translate`：开启翻译
  - `--openai-base-url`：临时指定中转地址
  - `--openai-dry-run`：只验证接口，不处理视频
  - `--translation-model`：指定翻译模型
- `doctor.py`
  - 检查 Python、`faster_whisper`、`openai`、环境变量、`ffmpeg` 和 `ffprobe`

## 推荐验证顺序

```powershell
cd D:\桌面
python -m autosub_zh.doctor
python -m autosub_zh.cli --openai-dry-run
python -m autosub_zh.cli input.mp4 --src-lang en --translate --output input.zh.srt
```

## 中转站 base_url

你的中转是：

```powershell
$env:OPENAI_BASE_URL="https://www.gptcodeplan.com"
```

如果中转站要求 `/v1` 这类额外路径，就把完整地址写进 `OPENAI_BASE_URL` 或传给 `--openai-base-url`。

不要把真实 API Key 写入 `.py`、`.md` 或任何会同步/提交的文件。
