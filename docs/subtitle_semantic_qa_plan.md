# 字幕语义重分配与 QA 可视化二期方案

## 当前判断

英文切片已经明显改善，但中文层还在沿用“按时间/旧 cue 跟随”的思路，容易出现：

- 一个中文片段承载两句英文意思
- 前后半句重复翻译
- 断在不自然的位置
- 短完整句为了对齐而被拆碎

这轮不再把“句子完整”当死规则，而是保持 ASR 时间轴优先，中文和显示层分别处理。

## 策略

### 1) 中文语义重分配

先做 source span 级翻译，再按 refined cues 分配中文。

- 仍复用现有 `04a_source_spans.json` 和 `span_translate.py`
- 不再把旧中文按时间重叠机械搬过去
- 对低置信度 cue 打 `semantic_allocation_review`
- 对重复、空中文、双句混载、邻接重复进行 QA 标记

### 2) 短完整句显示层合屏

底层 ASR 时间不变，只在显示层合并相邻短完整句。

- 只合并真正完整、短时长、停顿近的 cue
- 不合并开放残句、function-word 边界、明显 QA 风险 cue
- 合并结果只影响 ASS 显示，不回写底层时间轴

### 3) ASR 源文本修复

把句中断裂/错断前移到 raw ASR 阶段先处理，再保留现有 glossary/builtin alias 修复。

- 识别 `pinching his skin...`、`it. Uri...` 这类候选
- 只重组文本和 segment 边界，不改 word timestamps
- 无法确定时输出 review 标记，不靠 timing 猜

### 4) 前端 QA 可视化

把分割指标同步到前端项目产物区。

- 短残片数
- 混句数
- function-word 边界数
- 过短 / 过长条数
- semantic allocation / source repair / display grouping 统计
- 预览 ASS / JSON 下载入口

## 计划改动

- `source_repair.py`
- `zh_reading_axis.py`
- `subtitle_io.py`
- `pipeline_core.py`
- `pipeline_runner.py`
- `ui_server.py`
- `web/index.html`
- `web/app.js`
- `web/styles.css`
- 新增 `semantic_allocation.py`
- 新增 `segmentation_qa.py`
- 新增测试文件

## 产物

- `02b_asr_source_repair_candidates.json`
- `05a_semantic_allocated_segments.json`
- `05a_semantic_allocation_report.json`
- `07j_segmentation_qa_metrics.json`
- `docs/subtitle_segmentation_ops_log.md`

## 验证标准

- 英文短残片和混句明显下降
- 中文不再被时间重叠硬搬
- 短完整句可在显示层合屏，但底层时间不变
- `pinching his skin...` / `it. Uri...` 这类 raw ASR 断裂有独立 repair 记录
- 前端能直接看到 QA 指标和产物入口

## 已知边界

- “一条字幕对应一个完整句子”只是偏好，不是死规则
- 超长句仍允许必要分段
- 中文不会机械复刻英文错误切法
- 旧项目需要重新跑流程，才能得到新产物

## 本轮实现结果

### Backend

- 新增 `semantic_allocation.py`：为每个 refined cue 写入 `source_span_id`、`allocation_confidence`、`qa_flags`、`allocation_note`，输出 `05a_semantic_allocated_segments.json` 和 `05a_semantic_allocation_report.json`。
- 新增 `segmentation_qa.py`：稳定生成 `07j_segmentation_qa_metrics.json`，覆盖短残片、混句、function-word 边界、过短/过长、source repair、semantic allocation、display grouping。
- 更新 `source_repair.py`：在 raw ASR / timed source repair 链路中输出 `02b_asr_source_repair_candidates.json`，检测 `pinching his skin...`、`it. Uri...`、小写续接、异常句中断裂等候选；不改 word timestamp。
- 更新 `zh_reading_axis.py` / `subtitle_io.py`：加入 display-only short complete sentence grouping，底层 segment 时间不变，ASS 可使用 grouped display cues。
- 更新 `pipeline_core.py` / `pipeline_runner.py` / `ui_server.py`：接入新配置、新产物、manifest 和 `07a_quality_metrics.json` 汇总。

### Frontend

- `web/index.html` 增加二期配置入口：`semantic_zh_allocation_enabled`、`semantic_zh_allocation_max_spans`、`short_complete_sentence_display_grouping`。
- `web/app.js` 在“项目产物”中增加“字幕 QA”面板，读取 `07j_segmentation_qa_metrics.json`、`05a_semantic_allocation_report.json`、`03b_source_repair_report.json`，展示指标卡、问题样例和 ASS/JSON 入口。
- `web/styles.css` 增加 QA 产物链接样式；同时修复 `escapeHtml(0)` 导致 0 指标不显示的问题。

## 验证结果

相关测试：

- `python -m py_compile semantic_allocation.py segmentation_qa.py source_repair.py zh_reading_axis.py subtitle_io.py pipeline_core.py ui_server.py pipeline_runner.py`
- `node --check web\app.js`
- `pytest -q tests/test_semantic_qa_phase2.py tests/test_zh_reading_axis.py tests/test_asr_repair_flow.py`
- 结果：`17 passed in 0.28s`

Russian sample 重新生成关键二期产物：

- `02b_asr_source_repair_candidates.json`
- `05a_semantic_allocated_segments.json`
- `05a_semantic_allocation_report.json`
- `07j_segmentation_qa_metrics.json`
- `08_bilingual_zh_en.segmentation_preview.ass`

最终样本指标：

- segment_count: 833
- short_fragment_count: 27
- mixed_sentence_count: 89
- function_edge_count: 116
- too_short_count: 0
- too_long_count: 0
- semantic_review_count: 13
- source_repair_candidate_count: 170
- source_repair_review_count: 87
- display_group_count: 0
- blocking_issue_count: 232

前端验证：

- `http://127.0.0.1:8777` 已打开并检查“项目产物 -> 字幕 QA”。
- Russian sample 能显示真实 07j 指标和入口：`07j_segmentation_qa_metrics.json`、`05a_semantic_allocation_report.json`、`03b_source_repair_report.json`、`08_bilingual_zh_en.ass`、`08_bilingual_zh_en.segmentation_preview.ass`。
- 375px / 768px / 1280px / 1920px 无横向滚动；body 字体 16px；抽样按钮最小高度 46px。

## 二期自我修正记录

第一轮结果暴露两个过宽指标：

- `function_edge_count` 把正常 `The/I/He...` 句首也计入 function-word 边界，样本从而报到 339。
- `source_repair` 把普通 `it` / `Uri` 和 `a.m.` 缩写场景打得过宽。

修正：

- function-edge 拆成“行首续接词”和“行尾悬挂词”，不再把正常完整句首当问题。
- `open_ended_fragment` 不再因为普通 `it` / `Uri` 触发；`it. Uri...` 仍由 `punctuated_mid_sentence_break` 检出。
- `a.m.`、`p.m.`、`Mr.`、`Dr.` 等安全缩写不触发 `truncated_continuation`。
- source repair 的 `candidate_count` 保留全部候选，`review_count` 只统计高置信候选，避免前端告警被低置信续接候选淹没。

## 下一步建议

- 真正实现“span-level translation 后按 refined cues 分配中文”的重写式 allocator；当前二期先完成报告、低置信保护和产物链路，不静默覆盖旧中文。
- 给 `07j_segmentation_qa_metrics.json` 增加 TSV 导出，方便人工审阅长表。
- 把前端 QA 面板增加筛选和“只看 blocking”模式。
- 对 display-only grouping 增加真实样本触发集；当前 Russian sample 没有满足保守合屏条件的短完整句。
