## Objective
在 `D:\autosub_zh` 增加项目级、人工可审计的 evidence sidecar 和轻量关键词检索，并建立复合工程标准文档；没有 evidence 的旧项目行为必须完全不变。

## Context
- 现有 `glossary.py` 已从 YouTube 元数据提取术语，`entity_normalization.py` 和 `source_repair.py` 负责后续纠错。
- 现有 Bilibili 检索是 advisory，不能变成阻断条件；人工 ASS 仍是最终编辑事实。
- 目标仓库使用 web evidence/检索作为 glossary 补充。本切片不复制其代码、不引入 Tavily/Chroma。

## Target State
- 新建 `evidence_sidecar.py`：定义 schema、记录校验、项目/输入指纹隔离、原子写入/读取、关键词检索。
- 在 `glossary.py` 中做最小可选接入：已有 metadata 可生成 evidence 记录；没有 sidecar 时原逻辑不变。
- 新增测试覆盖 schema round-trip、无效记录过滤、跨项目隔离、关键词检索和无 evidence 兼容。
- 新建 `docs/COMPOSITE_ENGINEERING_STANDARD.md`，固定阶段契约、artifact/fingerprint、证据等级（confirmed/advisory/unknown）、人工 gate、回滚、测试和数据安全规则。

## Scope
- 只修改：`evidence_sidecar.py`、`glossary.py`、新增 `test_evidence_sidecar.py`、新增 `docs/COMPOSITE_ENGINEERING_STANDARD.md`。
- 可读取：`youtube_meta.py`、`entity_normalization.py`、`source_repair.py`、`datasets/local_feedback/README.md`、`docs/COMPOSITE_ENGINEERING_STANDARD_TASK_OVERVIEW.md`。
- 不得修改：`ui_server.py`、`pipeline_core.py`、`translate.py`、Bilibili 搜索规则、数据库、`.env`、真实数据、视频、ASS。

## Constraints
- 仅使用 Python 标准库；不得联网、不得新增依赖。
- sidecar 必须保存来源、标题、URL、摘要、抓取时间、置信度、project_id/input_fingerprint 和 schema_version。
- 检索结果只能作为补充上下文，不能覆盖 glossary 硬规则，不能自动修改 ASS。
- 任何未知字段使用 `unknown` 或空值，禁止臆测。

## Acceptance Criteria
- [ ] sidecar 记录可序列化、可读取、可校验；非法记录被拒绝或过滤。
- [ ] 不同 project_id/input_fingerprint 之间不会互相检索污染。
- [ ] 无 sidecar 时现有 glossary 输出和行为完全兼容。
- [ ] 标准文档可被新 agent 直接执行，且 `git diff --check` 和新增测试通过。

## Stop Conditions
停止并返回阻塞信息：需要联网、需要新增依赖、需要修改 UI/数据库、需要让 evidence 覆盖 glossary、需要自动改 ASS、需要删除文件或触碰 scope 外文件。

## Progress
每完成一个主要步骤输出：✅ 完成内容 — 修改文件。结束时列出测试命令、结果、兼容性说明和所有修改文件。

This prompt is for an agentic tool with real system access. Review the scope locks, forbidden actions, and stop conditions before executing.
