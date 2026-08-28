# 复合工程优化验收记录

## 已交付

- 阶段结果/事件契约与稳定序列化。
- 文件、配置、提示词和术语的 artifact fingerprint。
- JSON 同目录临时写入与原子替换。
- 兼容旧入口的 `pipeline/translate/qa/burn/init` CLI。
- 项目与输入隔离的 evidence sidecar、校验和关键词检索。
- glossary 的 opt-in evidence 接入；默认旧行为不生成 sidecar。
- OpenAI Base URL 的 UI 配置优先级和注入来源保留修复。
- 可推广的五层工程模型、人工 gate、证据等级、验证与回滚标准。

## 自动化证据

- 新增切片测试：18 passed。
- CLI 与工作流相关测试：11 passed。
- Evidence/实体相关测试：25 passed。
- OpenAI runtime 回归：7 passed。
- 全量 pytest：210 passed。
- Python `py_compile`：新增及接入模块通过。
- `git diff --check`：本轮提交文件通过。

所有网络、LLM、ffmpeg、下载器和媒体处理均未在单元测试中真实调用。

## 保持不变的边界

- 未修改数据库 schema。
- 未新增项目运行依赖。
- 未改变 Segment/Word、字幕切分、翻译、ASS 样式或输出命名。
- 未自动写入 evidence；只有调用方明确提供 sidecar 路径时才发布。
- 未把 advisory evidence 提升为 glossary 硬规则。
- 未提交 `.env`、密钥、视频、字幕、数据库、运行日志或本地反馈数据。

## 开放 Gate

- 尚未用真实媒体执行 ffmpeg/ASR/烧录回归。
- 尚未验证 GPU、下载器和远程翻译接口。
- 尚未做最终 ASS/视频人工视觉检查。
- 当前资源调度仍沿用既有 SQLite worker；多视频 CPU/IO/NVENC/ASR 分资源并发调度属于下一阶段，不在本轮低风险基础设施切片内。

这些 Gate 未通过前，不应把本轮结果描述为真实媒体生产链的完整运行验证。
