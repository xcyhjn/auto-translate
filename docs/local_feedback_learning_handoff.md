# Local Feedback Learning Handoff

## Assumptions for This MVP

- Subtitle ASS feedback is the first learning target; Bilibili duplicate search remains the first retrieval/ranking eval target.
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
3. Collect Bilibili candidates from existing output projects.
4. Keep new samples review-only by default.
5. Let humans mark samples for eval or learning, either by JSONL or UI buttons.
6. Build frozen gold files and run offline replay eval.
7. Generate explainable hint files before wiring anything back into workflow logic.

## Added Files

- `feedback_dataset.py`: CLI and Python module for collection, validation, dedupe, gold-set build, summary, and Bilibili replay eval.
- `test_feedback_dataset.py`: regression tests for collection, label preservation, eval replay, and train/eval separation.
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
- `operation_summary`
- `quality_flags`
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
3. Set `accepted=true` only for edits that are useful examples.
4. Set either `use_for_style_prompt=true` or `use_for_eval=true`, not both.
5. Run `validate` and `summarize`.

## Eval

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
- Bilibili duplicate search should be treated as retrieval/ranking first: query generation, lexical/semantic hints, candidate reranking, optional embedding/cross-encoder, and active learning.
- Current subtitle style learning is a prompt/RAG prototype; it should become a reusable dataset before any training.
- All automatic learning must stay explainable, switchable, and reversible.
- Learning samples and eval samples must stay separate.

## Next Steps

- Add a subtitle-focused UI review surface for accepting ASS edit examples into style learning or eval.
- Add term/entity feedback extraction from `06e_entity_decisions.json` and `08b_ass_entity_audit.json`.
- Add QA repair examples from final ASS QA and editor review TSVs.
- Add a feature flag such as `enable_local_feedback_learning` before consuming `learned_bilibili_hints.json` in the workflow.
