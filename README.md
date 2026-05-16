# autosub_zh

本项目当前路径是：

```text
D:\autosub_zh
```

因为 `autosub_zh` 是 Python 包名，所以用 `python -m autosub_zh.xxx` 运行时，终端要先进入它的父目录：

```powershell
cd D:\
```

如果你在 `D:\autosub_zh` 里面运行 `python -m autosub_zh.doctor`，Python 会把当前目录当作搜索根，反而找不到同名包，于是报 `ModuleNotFoundError: No module named 'autosub_zh'`。

## 功能

当前流水线：

1. 用 `ffprobe` 探测媒体信息
2. 用 `ffmpeg` 抽取音频
3. 用 `faster-whisper` 本地转写并生成时间轴
4. 可选接入 OpenAI 兼容接口翻译字幕
5. 做基础 QA
6. 导出 `.srt`
7. 可选保存或读取中间字幕片段 JSON

## 安装依赖

```powershell
cd D:\
python -m pip install -r .\autosub_zh\requirements.txt
```

## 检查环境

```powershell
cd D:\
python -m autosub_zh.doctor
```

## UI 下载模式

Web UI 的下载区现在支持四种模式：

- `auto`: 先用 yt-dlp 下载；失败后用 yt-dlp 解析直链并交给 IDM；仍失败则提示手动导入。
- `ytdlp`: 只使用 yt-dlp。
- `idm`: 只使用 IDM 桥接下载。
- `manual`: 不自动下载，用户用浏览器/IDM 下载到 `input` 后点击“扫描 input”。

IDM 默认会自动寻找 `C:\Program Files (x86)\Internet Download Manager\IDMan.exe`。如果安装位置不同，在 UI 里填写 `IDMan.exe` 路径后点击“检测 IDM”。

## 配置 OpenAI 中转

临时配置，当前 PowerShell 窗口有效：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_BASE_URL="https://www.gptcodeplan.com"
```

永久配置，写入当前 Windows 用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "你的 API Key", "User")
[Environment]::SetEnvironmentVariable("OPENAI_BASE_URL", "https://www.gptcodeplan.com", "User")
```

永久配置后要重新打开 VS Code 或终端。

## 验证中转站

```powershell
cd D:\
python -m autosub_zh.cli --openai-dry-run
```

## 只转写，不翻译

```powershell
cd D:\
python -m autosub_zh.cli input.mp4 --src-lang en --model tiny --output input.en.srt
```

## 转写并翻译

```powershell
cd D:\
python -m autosub_zh.cli input.mp4 --src-lang en --dst-lang zh-Hans --model base --translate --translation-model gpt-5.4-mini --output input.zh.srt
```

## 保存和复用中间结果

```powershell
cd D:\
python -m autosub_zh.cli input.mp4 --src-lang en --save-segments output.segments.json --output output.en.srt
python -m autosub_zh.cli input.mp4 --load-segments output.segments.json --translate --output output.zh.srt
```

## GPU / CPU 示例

CUDA GPU：

```powershell
cd D:\
python -m autosub_zh.cli input.mp4 --src-lang en --model small --device cuda --compute-type float16 --output input.en.srt
```

CPU：

```powershell
cd D:\
python -m autosub_zh.cli input.mp4 --src-lang en --model small --device cpu --compute-type int8 --output input.en.srt
```

不要把真实 API Key 写进代码或文档。真实 key 只放在环境变量里。
