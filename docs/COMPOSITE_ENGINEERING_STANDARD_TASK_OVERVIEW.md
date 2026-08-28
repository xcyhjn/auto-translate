# 复合工程标准优化任务总览

## 目标

在不破坏人工编辑 ASS 源文件、现有双语布局、反馈学习和 Bilibili advisory 边界的前提下，把 `autosub_zh` 提升为可复用的复合工程标准样板：

`明确阶段契约 -> 可验证缓存/产物 -> 可组合 CLI -> 可追溯证据 -> 人工可审计交付`

本轮只做低风险、可回滚的基础设施切片，不重写字幕业务规则，不引入远程服务，不安装新依赖。

## 当前基线

- Python 项目根：`D:\autosub_zh`。
- 现有主链：媒体探测、音频抽取、faster-whisper、时间轴优化、翻译、难句/span 修复、实体归一化、双语 ASS、QA、硬压。
- 现有任务层：`job_store.py` + `worker_service.py`，支持队列、暂停、恢复、取消、心跳、checkpoint 和 artifact。
- 现有人工闭环：ASS 人工修订是最终编辑事实；本地反馈 JSONL、风格学习、A/B eval 和 Bilibili 检索保持人工确认。
- 工作树已有用户修改；所有 agent 必须只改声明范围，不能清理或回滚既有修改。

## 垂直切片

### S1: 阶段契约与产物指纹

Owner: `stage_contract.py`、`artifact_manifest.py`、`pipeline_runner.py`、对应测试。

交付：

- 定义统一的 stage result/event 数据结构，至少包含 `stage/status/outputs/warnings/error`。
- 增加可复用的输入指纹工具：文件路径、size、mtime_ns、配置/提示词/术语内容 hash、schema version。
- 增加 JSON 原子写入工具，避免半写入产物被当成有效缓存。
- 在不改变现有输出文件名的情况下，让 `00_effective_config.json` 或 manifest 能记录 fingerprint/schema 信息。

验收：

- 旧调用路径仍可运行；现有 pipeline 返回结构不破坏。
- 指纹对输入或关键配置变化可识别；损坏 JSON 被视为无效。
- 至少覆盖 round-trip、输入变化、原子替换失败清理的单测。

禁止：修改字幕切分、翻译策略、ASS 样式或数据库 schema。

### S2: 组合式 CLI 入口

Owner: `cli.py`、新建的 CLI dispatch/adapter 文件、对应测试；不得修改 `pipeline_core.py`。

交付：

- 保留当前旧式单命令调用兼容性。
- 增加明确的子命令入口：`pipeline`、`translate`、`qa`、`burn`、`init`；缺少实现的命令必须返回清晰的非零错误，不得假装成功。
- 统一退出码、`--dry-run` 和 `--help` 行为。
- 子命令只做参数解析和调用转发，业务逻辑留在现有模块。

验收：

- parser 单测覆盖命令枚举、未知命令、兼容旧参数和退出码。
- 不启动真实媒体、不调用网络、不添加依赖。
- CLI 变更不影响 UI 通过现有 Python API 调用 pipeline。

禁止：重写 `ui_server.py`、改变现有 API key 读取、修改输出命名。

### S3: 可追溯证据 sidecar 与标准文档

Owner: 新建 `evidence_sidecar.py`、`glossary.py` 中最小接入点、对应测试和本任务文档；不得修改 UI。

交付：

- 定义项目级 evidence sidecar schema，保存来源、标题、URL、摘要、抓取时间、置信度和关联项目/输入指纹。
- 提供原子写入、读取校验和基于关键词的轻量检索接口；不引入 Chroma/Tavily 依赖。
- sidecar 只能作为 glossary/entity 修复的补充上下文，不能替代人工确认的 glossary 硬规则。
- 在文档中固定来源权威、未知状态、人工审核和回滚边界。

验收：

- schema round-trip、跨项目隔离、无效记录过滤和关键词检索有单测。
- 现有没有 evidence 的项目行为完全不变。
- 文档明确哪些是 confirmed、advisory、unknown，禁止自动提交或自动改 ASS。

禁止：联网抓取、写入真实用户数据、修改 Bilibili advisory 为阻断条件。

## 集成验收门

1. 静态：`git diff --check`；只出现声明范围文件。
2. 单测：运行仓库现有测试发现命令；新增测试必须通过。
3. 契约：旧 CLI、UI pipeline API、ASS 人工 reburn 路径保持可用。
4. 数据安全：不提交 `.env`、密钥、视频、字幕成品、运行日志或数据库文件。
5. 标准化：补充 `docs/COMPOSITE_ENGINEERING_STANDARD.md`，包含阶段契约、证据等级、人工 gate、回滚和测试门槛。

## 总体停止条件

- 任何 agent 需要新增依赖、修改数据库 schema、删除文件、改变 ASS/segment 事实来源或触碰声明范围外文件时，必须停止并返回阻塞信息。
- 真实 API、真实视频、GPU、下载器和浏览器验证不属于本轮自动验收；只能报告为 open gate。
