# Local Feedback Dataset

This directory stores local, human-reviewable feedback for the subtitle workflow.

Principles:
- JSONL files are append-friendly and versionable.
- New samples default to review-only flags.
- A sample must not be used for learning and eval at the same time.
- The first learning layer is explainable hints, few-shot examples, and offline eval.

Main files:
- `bilibili_duplicate_labels.jsonl`: Bilibili duplicate-search candidate labels.
- `translation_edit_examples.jsonl`: aligned machine subtitle text and manual ASS edits.
- `term_entity_decisions.jsonl`: reserved for terminology/entity decisions.
- `qa_repair_examples.jsonl`: reserved for QA repair examples.
- `eval_sets/`: frozen gold samples copied from reviewed feedback.
- `eval_reports/latest_bilibili_eval.json`: latest offline Bilibili replay eval.

Typical commands:

```powershell
$env:PYTHONPATH='D:\'
python -m autosub_zh.feedback_dataset collect-bilibili --project "D:\autosub_zh\output\project"
python -m autosub_zh.feedback_dataset collect-style --project "D:\autosub_zh\output\project"
python -m autosub_zh.feedback_dataset validate
python -m autosub_zh.feedback_dataset build-gold
python -m autosub_zh.feedback_dataset eval-bilibili
python -m autosub_zh.feedback_dataset summarize
```
