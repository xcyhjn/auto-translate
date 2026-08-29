## Objective
在 `D:\autosub_zh` 为现有字幕流水线增加可复用的阶段契约、输入指纹和 JSON 原子发布能力，提升恢复与缓存判断的可靠性，同时保持现有 pipeline 行为兼容。

## Context
- 现有主编排位于 `src/autosub_zh/pipeline_runner.py` 与 `src/autosub_zh/pipeline_core.py`。
- `src/autosub_zh/pipeline_runner.py` 已写入 `00_effective_config.json`；`src/autosub_zh/pipeline_core.py` 返回 manifest，并通过 callback/control_callback 暴露阶段。
- 现有翻译有增量 checkpoint；不要改变 ASS、Segment、Word、翻译、切分或 UI 语义。
- 工作树存在用户修改；不要回滚或格式化无关文件。

## Target State
- 新建 `src/autosub_zh/stage_contract.py`：定义最小的 stage result/event 类型和稳定的序列化字段。
- 新建 `src/autosub_zh/artifact_manifest.py`：提供文件快照、配置/文本 hash、schema version、fingerprint 比较和 JSON 原子写入。
- 只在 `src/autosub_zh/pipeline_runner.py` 做最小接入，使 effective config 或 manifest 带有可验证的 schema/fingerprint 元数据。
- 新增专门单测，覆盖 round-trip、输入/配置变化、损坏 JSON 和临时文件清理。

## Scope
- 只修改：`src/autosub_zh/stage_contract.py`、`src/autosub_zh/artifact_manifest.py`、`src/autosub_zh/pipeline_runner.py`、新增 `tests/test_stage_contract.py`、新增 `tests/test_artifact_manifest.py`。
- 可读取：`src/autosub_zh/models.py`、`src/autosub_zh/segment_io.py`、`src/autosub_zh/pipeline_core.py`、`src/autosub_zh/job_store.py`。
- 不得修改：`src/autosub_zh/ui_server.py`、`src/autosub_zh/pipeline_core.py`、`src/autosub_zh/translate.py`、`src/autosub_zh/subtitle_io.py`、数据库 schema、`requirements.txt`、`.env`、输出产物、日志。

## Constraints
- Python 标准库优先；不得新增依赖。
- 保持 ASCII 源码默认；保留现有 UTF-8 JSON 行为。
- 原子写入必须使用同目录临时文件和替换；失败时清理临时文件。
- 指纹必须至少覆盖路径、size、mtime_ns，以及调用方提供的配置/文本 hash 和 schema version。
- 只做直接请求的变更，不做相邻重构。

## Acceptance Criteria
- [ ] 旧的 `run_pipeline_from_config` 调用签名和返回结构保持兼容。
- [ ] 相同输入产生相同 fingerprint；文件或关键配置变化产生不同 fingerprint。
- [ ] 损坏或不完整 JSON 不被当成有效 manifest；临时文件不会残留。
- [ ] 新增测试通过；`git diff --check` 通过。

## Stop Conditions
停止并返回阻塞信息，不要自行决策：需要新增依赖、需要改数据库 schema、需要修改 `src/autosub_zh/pipeline_core.py`、需要删除文件、需要改变现有输出命名或需要触碰 scope 外文件。

## Progress
每完成一个主要步骤输出：✅ 完成内容 — 修改文件。结束时列出测试命令、结果和所有修改文件。

This prompt is for an agentic tool with real system access. Review the scope locks, forbidden actions, and stop conditions before executing.
