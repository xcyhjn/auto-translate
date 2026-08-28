## Objective
在 `D:\autosub_zh` 增加兼容旧调用的组合式 CLI 入口，让 `pipeline`、`translate`、`qa`、`burn`、`init` 成为明确子命令，同时不把业务逻辑搬进 CLI。

## Context
- 当前 `cli.py` 是单体参数入口，真正的流水线逻辑在 `pipeline_runner.py`/`pipeline_core.py`，UI 直接调用 Python API。
- 现有参数和默认值必须保持；用户已有脚本不能因 parser 重构失效。
- `qa.py`、`pipeline_core.py` 已有可调用函数；先检查真实签名，不要猜测。

## Target State
- 保留旧式 `python -m autosub_zh.cli <input> ...` 调用。
- 增加子命令 dispatch：`pipeline` 调用现有 pipeline runner；`translate` 调用现有翻译路径；`qa` 和 `burn` 仅在已有可靠函数时接入，否则输出明确非零“未实现/需要项目参数”的错误。
- 增加 `init`（只创建缺失的示例配置或输出帮助，不覆盖用户文件）和统一 `--dry-run`/`--help`/退出码行为。
- 新增 parser/dispatch 单测，外部媒体、网络和真实 API 全部 mock。

## Scope
- 只修改：`cli.py`、可新建 `cli_commands.py`、新增 `test_cli_commands.py`。
- 可读取：`pipeline_runner.py`、`pipeline_core.py`、`translate.py`、`qa.py`、`subtitle_io.py`、`workflow_profiles.py`。
- 不得修改：`ui_server.py`、`pipeline_core.py`、`job_store.py`、`worker_service.py`、`requirements.txt`、数据库和生成产物。

## Constraints
- 不新增依赖，不启动服务，不下载视频，不调用远程接口。
- CLI 只解析参数、转发调用、规范化退出码；不得复制 stage 业务逻辑。
- 旧命令的默认输出、API key 读取和中文错误信息保持兼容。
- 对不存在或参数不足的子命令必须 fail-closed，不能返回成功假象。

## Acceptance Criteria
- [ ] 旧式单命令 parser 测试继续通过。
- [ ] 子命令枚举、未知命令、help、dry-run、成功/失败退出码均有测试。
- [ ] UI 使用的现有 Python API 不受影响。
- [ ] `git diff --check` 和新增 CLI 测试通过。

## Stop Conditions
停止并返回阻塞信息：需要改变 `pipeline_core.py` 签名、需要新增依赖、需要修改 UI/API、需要改输出命名、需要删除旧参数或 scope 外文件。

## Progress
每完成一个主要步骤输出：✅ 完成内容 — 修改文件。结束时列出测试命令、结果、兼容性说明和所有修改文件。

This prompt is for an agentic tool with real system access. Review the scope locks, forbidden actions, and stop conditions before executing.
