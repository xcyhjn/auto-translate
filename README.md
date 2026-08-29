# autosub_zh

面向中英、俄中视频字幕制作的本地工作流。项目把下载或导入、语音识别、翻译、双语 ASS、质量检查、人工校对和重新烧录放在同一套 Web UI 与 Python 流水线里。

它的重点不是把字幕一次生成完，而是把机器处理和人工校对接起来：JSON 保存可复用的机器中间结果，ASS 保存人工确认后的显示文本。字幕改完后可以直接重新烧录，不需要重新跑 ASR 和翻译。

## 主要能力

- **本地语音识别**：使用 `faster-whisper`，保留 word 级时间，支持长音频分块和 CUDA/CPU 降级。
- **中文字幕阅读轴**：根据停顿、句界、时长和阅读速度调整显示节奏；俄中流程可使用独立中文阅读轴。
- **完整英文参考层**：英文优先按词级时间和语义边界拆分，不能安全拆分时使用显式 `\N`，不靠省略号截断原文。
- **双语 ASS 布局**：中文使用 `Default`，源语言参考使用 `EnglishSmall`；只有参考层实际多行时才抬升中文字幕。
- **术语和实体校正**：支持项目 glossary、实体注册表、ASR 混淆项、专名归一化和英文残留检查。
- **局部修复**：先标出高风险 span，再对难句、碎片句和语义错配做有限范围修复。
- **人工编辑闭环**：人工修改后的 ASS 是重新烧录和风格学习的依据，不会被机器 JSON 自动覆盖。
- **可审查的反馈学习**：机器译文与人工 ASS 修改可整理为 JSONL 样例；学习集和评测集分开维护。
- **任务状态保存**：Web UI 支持任务状态、暂停、恢复、取消、产物浏览和进程异常后的状态恢复。
- **可追溯产物**：每个视频有独立输出目录，保存配置、阶段报告、QA、manifest 和 artifact fingerprint。

## 工作流

```text
下载或导入视频
  -> 媒体探测 / 外部音频合并
  -> 16 kHz 单声道音频
  -> faster-whisper + word timing
  -> 源语言时间轴整理
  -> glossary / 实体 / 高风险 span
  -> 分块翻译
  -> 中文显示轴与双语参考层
  -> QA
  -> ASS
  -> 视频烧录
  -> 人工修改 ASS
  -> 重新烧录 / 反馈复核
```

下载、识别、时间轴和烧录在本地完成。远程模型只用于已启用的翻译、局部修复和显示文本重写。

## 开始使用

### 准备环境

当前项目以 Windows 和 PowerShell 为主要运行环境。需要：

- Python 3.11 或可兼容的 Python 3.x
- `ffmpeg` 和 `ffprobe`
- 项目 Python 依赖
- 可选：NVIDIA CUDA、Internet Download Manager、OpenAI 兼容接口

假设项目位于 `D:\autosub_zh`，在项目根目录安装：

```powershell
cd D:\autosub_zh
python -m pip install -e .
python -m autosub_zh.doctor
```

项目使用标准 `src` 布局。`pip install -e .` 只建立可编辑安装，后续修改源码不需要重复安装；安装后可以在任意目录调用 `autosub-zh`、`autosub-zh-ui` 或 `python -m autosub_zh...`。

### 启动 Web UI

从项目目录运行：

```powershell
cd D:\autosub_zh
powershell -ExecutionPolicy Bypass -File .\scripts\start_ui_server.ps1
```

脚本会寻找可用的 Python，检查端口并在前台启动服务。默认地址是：

```text
http://127.0.0.1:8777
```

如果 `8777` 被占用，脚本会尝试后续端口；以终端打印的地址为准。

需要代理时，启动前设置：

```powershell
$env:AUTOSUB_PROXY_URL="http://127.0.0.1:7890"
```

不设置时按直连处理。

## 在 Web UI 中处理视频

下载区支持四种模式：

| 模式     | 行为                                              |
| -------- | ------------------------------------------------- |
| `auto`   | 先尝试 `yt-dlp`，失败后尝试 IDM，最后提示手动导入 |
| `ytdlp`  | 只使用 `yt-dlp`                                   |
| `idm`    | 把解析后的媒体地址交给 IDM                        |
| `manual` | 不自动下载，从 `input/` 扫描本地文件              |

典型操作顺序：

1. 下载视频，或把本地视频放入 `input/`。
2. 选择工作流，例如 English to Chinese 或 Russian to Chinese。
3. 检查模型、设备、翻译接口和字幕样式。
4. 启动任务，观察 ASR、翻译、QA 和烧录阶段。
5. 在项目输出区打开最终 ASS，完成人工校对。
6. 回到 Web UI 重新烧录。
7. 需要积累样例时，再手动收集并审核反馈。

Bilibili 重复视频检查只提供参考。无结果或检查失败不会阻止下载、翻译、烧录和反馈整理。

## 使用命令行

项目保留旧式单文件命令，同时提供 `pipeline`、`translate`、`qa`、`burn` 和 `init` 子命令。

查看帮助：

```powershell
autosub-zh --help
```

### 只做转写

```powershell
autosub-zh .\input\video.mp4 `
  --src-lang en `
  --model distil-large-v3 `
  --device cuda `
  --compute-type float16 `
  --output .\output\video.en.srt
```

### 转写并翻译

```powershell
autosub-zh .\input\video.mp4 `
  --src-lang en `
  --dst-lang zh-Hans `
  --translate `
  --translation-model gpt-5.4 `
  --output .\output\video.zh.srt
```

### 复用中间结果

```powershell
autosub-zh .\input\video.mp4 `
  --src-lang en `
  --save-segments .\output\video.segments.json `
  --output .\output\video.en.srt

autosub-zh .\input\video.mp4 `
  --load-segments .\output\video.segments.json `
  --translate `
  --output .\output\video.zh.srt
```

### 先检查子命令计划

`--dry-run` 只输出参数计划，不读取大媒体、不联网，也不写业务产物：

```powershell
autosub-zh pipeline .\input\video.mp4 `
  --config .\ui_config.json `
  --dry-run

autosub-zh qa .\output\video\05_translated_segments.json `
  --dry-run
```

## 配置翻译接口

项目读取 `OPENAI_API_KEY`，并从 `OPENAI_BASE_URL` 或 `OPENAI_API_BASE` 读取兼容接口地址。

当前 PowerShell 会话：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_BASE_URL="https://example.com/v1"
```

写入当前 Windows 用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "你的 API Key", "User")
[Environment]::SetEnvironmentVariable("OPENAI_BASE_URL", "https://example.com/v1", "User")
```

重新打开终端后检查：

```powershell
autosub-zh --openai-dry-run
```

Base URL 应填写服务实际要求的完整地址。不要把真实 key 写进代码、Markdown、`ui_config.json` 或提交记录。

## 识别失败时如何降级

默认英文流程使用 `distil-large-v3`，俄语流程使用 `large-v3`。CUDA 路径出现显存、DLL 或计算类型问题时，识别器会按可用条件尝试：

1. 当前配置。
2. 更低的 beam size。
3. `int8_float16` 或 CUDA `int8`。
4. CPU `int8`。

这套降级是为了让长任务继续完成，不代表低资源路径与原配置质量完全一致。最终文本仍需要人工检查。

## 输出目录

每个输入视频在 `output/` 下使用独立目录。一个完整的中英双语项目通常包含：

```text
output/<project>/
  00_effective_config.json
  00_media_probe.json
  01_audio_16k.wav
  02_asr_raw_segments.json
  02_terms_from_asr.json
  03_timed_source_segments.json
  03_glossary_resolved.json
  04_source_en.srt
  04a_source_spans.json
  05_translated_segments.json
  05a_span_translation_report.json
  06_translated_zh.srt
  06c_display_rewrite_report.json
  06e_entity_decisions.json
  07_qa_report.json
  07a_quality_metrics.json
  07b_difficult_spans.json
  07g_final_ass_qa.json
  07k_english_residue_report.json
  00_ASS_bilingual_zh_en.ass
  08a_bilingual_source_reference_alignment_debug.json
  08b_ass_entity_audit.json
  09_burned_bilingual_zh_en_video.mp4
  10_manifest_bilingual_source_reference.json
  99_internal_artifacts/
```

不同工作流和字幕模式会省略部分文件，语言后缀也会变化。`00_ASS_*.ass` 是项目区优先展示的最终字幕文件；`99_internal_artifacts/` 保存预览和内部检查产物。

## 人工校对规则

- 人工字幕修改写入最终 ASS，不直接改机器 segment JSON。
- 中文字幕样式是 `Default`，源语言参考样式是 `EnglishSmall`。
- 同一条双语字幕应保持相同起止时间，除非两层明确一起重分段。
- 英文单行时，中文字幕不额外抬升。
- 英文包含显式 `\N` 时，烧录安全副本会按当前样式抬升中文字幕。
- 不用 `...` 或 `…` 解决过长英文；应重新分段或使用明确换行。
- 重新烧录前保留当前 ASS 文本，只应用确定性的布局安全处理。

## 反馈与评测

`datasets/local_feedback/` 保存人工可检查的本地样例：

- `translation_edit_examples.jsonl`：机器翻译与人工 ASS 修改的对应关系。
- `span_translation_examples.jsonl`：跨 segment 的语义分配样例。
- `term_entity_decisions.jsonl`：术语与实体决策。
- `eval_sets/`：从已审核反馈中冻结的评测集。

反馈默认只是候选记录。只有人工接受的样例才能进入提示词或评测；同一条样例不能同时用于学习和评测。

常用检查：

```powershell
cd D:\autosub_zh
python -m autosub_zh.feedback_dataset validate
python -m autosub_zh.feedback_dataset summarize
python -m autosub_zh.feedback_dataset eval-style
```

## 项目结构

```text
src/autosub_zh/               Python 包源码与只读资源
  asr.py / media.py           识别、音频处理与 CUDA 降级
  pipeline_core.py            完整流水线编排
  timing.py / zh_reading_axis.py
                              源语言时间轴与中文阅读轴
  translate.py / span_*.py    翻译、span 识别和局部修复
  glossary.py / terminology.py
                              术语、实体和专名策略
  subtitle_io.py / qa.py      SRT/ASS 输出与质量检查
  job_store.py / worker_service.py
                              SQLite 任务状态和后台 worker
  ui_server.py / web/         本地 Web 服务与静态文件
  workflow_profiles/          英中、俄中等工作流配置
  translation_prompts/        翻译提示词
  datasets/                   正式规则数据与实体表
datasets/local_feedback/       人工反馈与评测数据
tools/                        增量工具与 VS Code ASS 高亮器
tools/fixes/                 一次性修复与迁移脚本
tests/                        自动化测试
input/ / output/              用户媒体与项目产物
runtime/                      数据库、状态和运行日志
docs/                         设计、交接、审计和变更记录
```

## 测试

安装开发依赖后，从项目根目录运行：

```powershell
cd D:\autosub_zh
python -m pip install -e ".[dev]"
python -m pytest -q
```

测试会 mock 或隔离网络、LLM、`yt-dlp`、`ffmpeg` 和 Whisper。通过自动化测试不等于真实媒体、CUDA、远程 API 和最终画面已经验证。

## 当前边界

- 项目目前是 Windows 优先的本地工作流，不是通用云服务。
- Web UI 只允许一个活动任务；尚未实现按 CPU/IO、NVENC 和 ASR 分类的多视频资源调度。
- `stage_contract.py` 已定义阶段信封，但现有全部编排还没有统一迁移到该契约。
- Evidence sidecar 是可选的补充证据，不会替代人工 glossary，也不会自动改 ASS。
- 最终字幕质量仍依赖人工检查，尤其是专名、笑点、碎片句、长英文和双语布局。

## 文档

- [输出文件约定](docs/OUTPUT_STRUCTURE.md)
- [OpenAI 兼容接口说明](docs/OPENAI_API_INTEGRATION.md)
- [本地反馈数据说明](datasets/local_feedback/README.md)
- [复合工程标准](docs/COMPOSITE_ENGINEERING_STANDARD.md)
- [复合工程验收记录](docs/COMPOSITE_ENGINEERING_VALIDATION.md)
- [变更日志](docs/CHANGELOG.md)
- [VS Code ASS 高亮器](tools/vscode-ass-bilingual-highlighter/README.md)
