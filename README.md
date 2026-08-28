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

当前工程化能力：

- 阶段契约：统一 `stage/status/outputs/warnings/error/metadata` 信封。
- Artifact 指纹：按输入文件、关键配置、提示词/术语和 schema 判断缓存有效性。
- 安全发布：JSON 通过同目录临时文件和原子替换写入。
- 组合式 CLI：`pipeline`、`translate`、`qa`、`burn`、`init`，同时兼容旧式单命令调用。
- Evidence sidecar：保存项目隔离的 `confirmed/advisory/unknown` 证据，不覆盖人工 glossary 或 ASS。
- 人工 Gate：人工编辑 ASS 保持最终编辑事实；Bilibili 重复检索仍为 advisory。

完整约束见 [复合工程标准](docs/COMPOSITE_ENGINEERING_STANDARD.md)，本轮拆分和验收边界见 [任务总览](docs/COMPOSITE_ENGINEERING_STANDARD_TASK_OVERVIEW.md)。

## 工作区边界

- 源码与测试：项目根目录的 `.py`、`web/`、`tools/` 和 `test_*.py`。
- 版本化规则数据：`workflow_profiles/`、`translation_prompts/` 和 `datasets/` 中的正式 profile/registry。
- 用户媒体与项目产物：`input/`、`output/`，不得按普通缓存批量删除。
- 可再生运行状态：`runtime/`；UI 状态和错误日志统一写入这里。
- 人工反馈：`datasets/local_feedback/`，只能按审核流程整理，不能当作临时文件清理。

根目录不再保存端口试跑日志、转录日志或 UI 状态快照。若运行异常，检查 `runtime/logs/`。

## 组合式 CLI

从父目录运行：

```powershell
cd D:\
python -m autosub_zh.cli --help
python -m autosub_zh.cli pipeline "D:\media\input.mp4" --config "D:\autosub_zh\ui_config.json" --dry-run
python -m autosub_zh.cli translate "D:\output\segments.json" -o "D:\output\translated.json" --dry-run
python -m autosub_zh.cli qa "D:\output\segments.json" --dry-run
python -m autosub_zh.cli burn "D:\media\input.mp4" "D:\output\subtitle.ass" "D:\output\burned.mp4" --dry-run
python -m autosub_zh.cli init --output "D:\workspace\autosub_zh.config.example.json" --dry-run
```

`--dry-run` 只输出计划，不读取大媒体、不调用网络，也不写业务产物。去掉它才会执行相应阶段。

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
