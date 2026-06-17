# Subtitle Translation Feedback Learning Handoff

## Assumptions for This MVP

- Subtitle translation feedback is the first learning target; Bilibili duplicate search is only an auxiliary retrieval/ranking feedback stream.
- Missing duplicates are more costly than false positives, so uncertain matches stay in manual review.
- Feedback is versioned in JSONL; this MVP also adds a small UI entry for Bilibili labels and ASS feedback collection.
- Feedback collection and current eval run offline by default, but the workflow may use external APIs or embeddings later when useful.
- Local subtitle snippets may be stored in this private dataset; future sharing should add redaction.
- `scikit-learn` is allowed for lightweight local ranking/active-learning experiments; deep-learning fine-tuning still waits for a stable labeled gold set.

## Current Diagnosis

The project already has useful feedback raw material:

- `bilibili_search.py` creates query plans, runs API-first Bilibili search with HTML fallback, scores candidates, and writes `00b_*` artifacts.
- `style_learning.py` aligns `05_translated_segments.json` with a manually edited ASS file and can extract edit tags, style features, and prompt examples.
- `display_rewrite.py` already consumes `00_style_examples.jsonl` as few-shot/RAG-like prompt context.
- `workflow_profiles.py` provides local dataset/profile assets, mainly glossary and prompt resources.
- `pipeline_core.py` writes QA reports, glossary actions, entity audit files, editor review TSVs, and final ASS QA.

What is not yet true learning:

- The style path is prompt/RAG guidance, not model training.
- Dataset profiles are resource bundles, not a closed feedback loop.
- Bilibili scoring is explainable rules, not a learned reranker.
- QA/entity outputs are rich review artifacts but not yet normalized feedback samples.

Reusable training/eval candidates already exist:

- Bilibili report candidates, query plans, matched queries, scores, reason codes, and YouTube metadata.
- Machine translation segments aligned to manual ASS edits.
- Terminology actions, entity decisions, final ASS QA, and editor review TSVs for future term/entity/QA schemas.

Feedback gaps that would hurt learning quality:

- Candidate labels are not yet consistently confirmed as duplicate/not duplicate/same topic.
- Manual ASS edits are not automatically good examples; surface-only edits and timing edits must be separated from true style or correction edits.
- Eval samples and learning samples must be separated, or metrics will only measure memorization.
- Small local sample counts are too noisy for deep-learning fine-tuning.

Minimum viable loop:

1. Normalize local feedback schemas in `datasets/local_feedback/`.
2. Collect subtitle edit examples from the manually edited ASS and use machine segments only as the baseline for alignment.
3. Classify each subtitle edit as style, terminology, semantic, QA repair, linebreak, surface edit, or unsafe example.
4. Keep new samples review-only by default.
5. Let humans mark samples for eval or learning, either by JSONL or UI buttons.
6. Build frozen gold files and run offline subtitle feedback eval.
7. Generate explainable style guidance before wiring anything back into workflow logic.

## Added Files

- `feedback_dataset.py`: CLI and Python module for collection, validation, dedupe, gold-set build, subtitle feedback eval, summary, and Bilibili replay eval.
- `test_feedback_dataset.py`: regression tests for collection, label preservation, subtitle eval, replay eval, and train/eval separation.
- `datasets/local_feedback/`: local feedback dataset root.
- `POST /api/bilibili-duplicate-feedback`: saves UI labels into local JSONL.
- `POST /api/collect-style-feedback`: collects ASS edit feedback into local JSONL.

Dataset files:

- `bilibili_duplicate_labels.jsonl`
- `translation_edit_examples.jsonl`
- `term_entity_decisions.jsonl`
- `qa_repair_examples.jsonl`
- `eval_sets/bilibili_duplicate_gold.jsonl`
- `eval_sets/translation_style_gold.jsonl`
- `eval_reports/latest_style_eval.json`
- `eval_reports/latest_bilibili_eval.json`
- `learned_bilibili_hints.json`
- `learned_style_guidelines.md`
- `learning_summary.md`

## Schemas

Bilibili records contain:

- `schema_version`
- `created_at`
- `source`
- `youtube`
- `query_plan`
- `candidate`
- `label`: `duplicate`, `not_duplicate`, `same_topic`, or `manual_review`
- `human_note`
- `use_for_eval`
- `use_for_learning`

Translation edit records contain:

- `project_id`
- `segment_id`
- `start`
- `end`
- `source_text`
- `machine_target_text`
- `manual_target_text`
- `edit_tags`
- `features`
- `operation_summary`
- `quality_flags`
- `feedback_types`: `style_edit`, `term_fix`, `semantic_fix`, `qa_repair`, `linebreak_fix`, `surface_edit`, or `bad_example`
- `learning_risk`: `low`, `medium`, or `high`
- `learning_recommendation`: `review_only`, `style_prompt_candidate`, or `eval_candidate`
- `classification_reasons`
- `accepted`
- `use_for_style_prompt`
- `use_for_eval`

New collection never overwrites an existing manual label or note. If the same sample key already exists, it is skipped. UI feedback intentionally upserts the same Bilibili candidate because that click is a human label action.

## Usage

```powershell
$env:PYTHONPATH='D:\'
python -m autosub_zh.feedback_dataset init
python -m autosub_zh.feedback_dataset collect-bilibili --project "D:\autosub_zh\output\bilibili_duplicate_mock_validation"
python -m autosub_zh.feedback_dataset collect-style --project "D:\autosub_zh\output\SomeProject"
python -m autosub_zh.feedback_dataset validate
python -m autosub_zh.feedback_dataset build-gold
python -m autosub_zh.feedback_dataset eval-style
python -m autosub_zh.feedback_dataset eval-bilibili
python -m autosub_zh.feedback_dataset summarize
```

UI entry points:

- Bilibili duplicate candidates now have `duplicate`, `not_duplicate`, `same_topic`, and `manual_review` buttons plus a note field.
- The project output preview toolbar has `采集 ASS 反馈`; it reads the selected project ASS and appends review-only edit examples.

Manual review flow:

1. Edit `bilibili_duplicate_labels.jsonl`.
2. Change `label` from `manual_review` to a confirmed label.
3. Set exactly one of `use_for_eval` or `use_for_learning`.
4. Run `validate`.
5. Run `build-gold` for eval samples, or `summarize` for learning hints.

Style review flow:

1. Edit `translation_edit_examples.jsonl`.
2. Treat the ASS as the source of human feedback; `05_translated_segments.json` is only the machine baseline used for alignment.
3. Review `feedback_types`, `learning_risk`, and `classification_reasons`.
4. Set `accepted=true` only for edits that are useful examples.
5. Set either `use_for_style_prompt=true` or `use_for_eval=true`, not both.
6. Do not use `bad_example` or `learning_risk=high` samples for learning/eval.
7. Run `validate`, `build-gold`, `eval-style`, and `summarize`.

## Eval

`eval-style` reads `eval_sets/translation_style_gold.jsonl` and writes:

- sample count and sample sufficiency
- feedback type distribution
- learning risk and recommendation distribution
- edit tag and strategy distribution
- average machine/manual text similarity
- average absolute character delta
- unsafe cases that should not enter the gold set
- high-value cases for future prompt examples or training data

`eval-bilibili` reads `eval_sets/bilibili_duplicate_gold.jsonl`, regenerates query plans, replays scoring over saved candidates, and writes:

- `recall@1`
- `recall@3`
- `recall@5`
- `mrr`
- top score distribution
- false positive cases
- false negative cases
- query hit contribution

If there are fewer than three positive sources, the report is marked `sample_insufficient=true`; the framework still runs.

## Known Risks

- Current sample counts are too small for deep-learning fine-tuning.
- The project needs high-quality labels and stable eval sets before model training.
- Subtitle translation feedback should be treated as supervised preference/style data first: collect accepted edits, separate eval, then only later consider fine-tuning.
- Bilibili duplicate search should be treated as retrieval/ranking first and should not dominate the local learning roadmap.
- Current subtitle style learning is a prompt/RAG prototype; it should become a reusable dataset before any model training.
- All automatic learning must stay explainable, switchable, and reversible.
- Learning samples and eval samples must stay separate.

## Next Steps

- Add a subtitle-focused UI review surface for accepting ASS edit examples into style learning or eval.
- Add term/entity feedback extraction from `06e_entity_decisions.json` and `08b_ass_entity_audit.json`.
- Add QA repair examples from final ASS QA and editor review TSVs.
- Add a feature flag such as `enable_local_translation_feedback` before consuming `learned_style_guidelines.md` in translation prompts.
- After at least 50 accepted subtitle examples and 20 frozen eval examples, run ablation tests before considering LoRA/fine-tuning.

## 2026-06-17 Span Review Loop v1

- Added review suggestions for ASS/Span feedback records: `use_for_prompt`, `use_for_eval`, `accept_only`, and `review_only`.
- Added `POST /api/local-feedback-bulk-update` for local JSONL-only batch review actions. It skips high-risk, `bad_example`, and `bad_alignment` samples when targeting Prompt/Eval.
- Added `GET /api/local-feedback-impact-preview` to show whether local feedback is enabled, how many ASS/Span samples can enter Prompt/Eval, and the current Span example hash that affects `05a` cache reuse.
- Updated the feedback review UI with selection, low-risk filtering, batch actions, recommendation chips, and one-click recommended Prompt/Eval actions.
- Updated the learning quality UI with a Span shortfall action card and a read-only learning impact preview card.
- These actions do not start subtitle translation and do not add model requests. `05/05a` remain machine baselines only.

## 2026-06-17 Review Detail and Prompt Preview v2

- Added `GET /api/local-feedback-record-detail` to inspect one ASS or Span learning record without editing JSONL by hand.
- The feedback review UI now has a detail drawer with full source/machine/manual comparison, tags, recommendation, classification reasons, and Span compact prompt-example preview.
- Expanded `/api/local-feedback-impact-preview` with `prompt_injection_preview`, including style prompt excerpt, rough token estimates, learned rules, and compact Span examples.
- The learning quality panel now shows what local feedback would actually inject into future translation prompts. This remains read-only and does not run translation or call a model.

## 2026-06-17 Dataset Diagnostics v1

- Added duplicate/conflict diagnostics to `/api/learning-quality-summary` under `dataset_diagnostics`.
- A conflict means the same normalized source plus machine baseline maps to different manual ASS translations. These should be reviewed before both variants enter Prompt/Eval.
- A duplicate means source, machine baseline, and manual ASS are all identical after normalization. Duplicates are review signals only; the system does not delete or mutate JSONL automatically.
- The learning quality panel now shows ASS/Span conflicts, duplicates, and merge candidates as read-only local diagnostics. No translation request or model call is made.
- Diagnostic records include `record_id` and can be opened from the learning quality panel; the UI switches to feedback review and opens the read-only detail drawer for manual review.
