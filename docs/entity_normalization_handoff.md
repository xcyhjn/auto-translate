# Entity Normalization Handoff

This document is the working handoff for adding a dedicated entity-normalization phase to the subtitle pipeline.

The goal is to stop treating human-name and title fixes as ad hoc ASS edits. We want a repeatable stage that:

- fixes English residue in Chinese subtitle lines,
- normalizes English reference lines when ASR or OCR gets proper nouns wrong,
- applies researched Chinese renderings for people, works, and papers,
- keeps a record of what was changed, what still needs review, and why.

## Current status

- Pipeline insertion points reviewed.
- Existing low-risk replacement hook reviewed: [src/autosub_zh/bilingual_postprocess.py](D:/autosub_zh/src/autosub_zh/bilingual_postprocess.py:1)
- ASS generation hook reviewed: [src/autosub_zh/subtitle_io.py](D:/autosub_zh/src/autosub_zh/subtitle_io.py:891)
- Main pipeline write/QA sequence reviewed: [src/autosub_zh/pipeline_core.py](D:/autosub_zh/src/autosub_zh/pipeline_core.py:1113)
- Existing tests reviewed:
  - [tests/test_asr_repair_flow.py](D:/autosub_zh/tests/test_asr_repair_flow.py:1)
  - [tests/test_subtitle_output_modes.py](D:/autosub_zh/tests/test_subtitle_output_modes.py:1)

## Problem summary

The current workflow has a gap between translation/display rewrite and final ASS generation:

1. `source_text` may still contain ASR-mangled proper nouns.
2. `target_text` may still contain English proper nouns that should be localized in Chinese.
3. `EnglishSmall` lines are written directly from `source_text`, so English reference lines inherit ASR name errors.
4. There is no dedicated report for "entity residue" or "entity normalization decisions".
5. Human fixes made directly in ASS do not feed back into the pipeline except indirectly through style learning.

This caused repeated manual fixes such as:

- `Victor Torsk -> Victor/Viktor Tausk`
- `Paul Gosh -> Paul Goesch`
- `Adolf Wolfley -> Adolf Wölfli`
- `Brian -> Bryan Charnley`
- Chinese subtitle residues like `James Tilly Matthews`, `Matthews`, `Jacob Moore`, `Unica Zern`, etc.

## Design goals

- Add a formal pipeline stage for entity normalization.
- Reuse existing project structure and output conventions.
- Keep automatic changes conservative.
- Separate "known-safe replacements" from "researched decisions".
- Make reviewable artifacts for the user and for future AI handoff.

## Scope

- In:
  - Chinese subtitle residue cleanup for proper nouns.
  - English reference normalization for known ASR/OCR proper-noun errors.
  - Project/global registry support for researched names and title mappings.
  - QA/reporting for unresolved entity residue.
- Out:
  - General semantic correction of arbitrary English ASR mistakes.
  - Full web-backed research automation in the first implementation pass.
  - Automatic correction of ambiguous entities without a confirmed mapping.

## Proposed pipeline

### Stage A: low-risk source/target replacements

Keep and expand the existing `bilingual_postprocess` stage for known-safe replacements.

Use it for:

- spelling variants,
- fixed ASR confusions,
- project-specific canonical terms already confirmed.

This remains regex-based and deterministic.

### Stage B: entity normalization before ASS generation

Insert a new stage after display rewrite and before ASS writing.

Input:

- `translated_segments`
- dataset/profile glossary
- project-level entity decisions
- global entity registry

Output:

- normalized `translated_segments`
- a decision report
- a review TSV for uncertain items

Responsibilities:

1. Detect likely named entities in `source_text` and `target_text`.
2. Replace Chinese subtitle English residue when a canonical Chinese rendering exists.
3. Normalize English reference text when a canonical English spelling exists.
4. Apply mention strategy:
   - full name on first mention,
   - short form or surname afterward when configured.

### Stage C: ASS entity audit after ASS generation

Run a dedicated audit right after the ASS file is written and before final ASS QA is finalized.

Responsibilities:

- inspect `Dialogue: 0` lines for English residue,
- inspect `Dialogue: 1` lines for known bad variants,
- emit a machine-readable audit report,
- optionally apply only high-confidence fixups.

## Data model

### Global registry

Add `src/autosub_zh/datasets/entity_registry.json`.

Each entry should look like:

```json
{
  "key": "james_tilly_matthews",
  "entity_type": "person",
  "canonical_en": "James Tilly Matthews",
  "canonical_native": "",
  "canonical_zh": "詹姆斯·蒂利·马修斯",
  "surface_forms": ["James Tilly Matthews", "Matthews"],
  "policy": "translate_full_name",
  "mention_strategy": "full_then_short",
  "short_zh": "马修斯",
  "confidence": 0.99,
  "evidence": [
    {
      "source": "manual_review",
      "note": "Confirmed during The Haunting World of Schizophrenic Art cleanup"
    }
  ]
}
```

### Project decisions

Add project-level artifacts such as:

- `00_entity_decisions.json`
- `06e_entity_decisions.json`

Use these to store project-local overrides and recent confirmations without requiring an immediate global registry update.

Example:

```json
{
  "version": 1,
  "entities": [
    {
      "key": "custom_person",
      "canonical_en": "Custom Person",
      "canonical_zh": "自定义人物",
      "surface_forms": ["Custom Person", "Person"],
      "short_zh": "人物",
      "mention_strategy": "full_then_short"
    }
  ]
}
```

## New outputs

Planned first-pass artifacts:

- `06d_entity_candidates.json`
- `06e_entity_decisions.json`
- `06f_entity_review.tsv`
- `06g_entity_normalized_segments.json`
- `08b_ass_entity_audit.json`

## Heuristics

### Safe auto-fix

Allow automatic changes when:

- the entity exists in the project/global registry,
- a surface form maps to a single canonical record,
- the change only affects capitalization, diacritics, or known ASR confusions,
- the mention strategy is explicit.

### Review-only

Do not auto-fix when:

- the candidate is ambiguous,
- the token may be a title rather than a person,
- the canonical Chinese rendering is uncertain,
- the phrase is not obviously a proper noun in context.

## Implementation plan

### Phase 1

Add a conservative normalization pass with no web research dependency.

Deliverables:

- new `src/autosub_zh/entity_normalization.py`
- registry loader
- project decision loader
- per-segment normalization pass
- integration into `src/autosub_zh/pipeline_core.py`
- focused tests

### Phase 2

Add ASS-level audit and stronger reporting.

Deliverables:

- `08b_ass_entity_audit.json`
- `06f_entity_review.tsv`
- English reference normalization audit

### Phase 3

Add research-backed decision workflow and registry growth.

Deliverables:

- source attribution fields
- review promotion flow from project decisions to global registry
- UI support if needed later

## Concrete insertion points

- `src/autosub_zh/pipeline_core.py`
  - after `display_rewrite_complete`
  - before `assert_no_target_text_pollution`
  - before `write_bilingual_ass`
- `src/autosub_zh/subtitle_io.py`
  - prefer normalized reference text for `EnglishSmall`
- `src/autosub_zh/qa.py`
  - add entity-residue checks
- `src/autosub_zh/bilingual_postprocess.py`
  - keep for deterministic low-risk replacements only

## Risks

- Over-normalizing creative titles or intended English retainers.
- Replacing ambiguous surnames incorrectly.
- Mixing researched entity fixes with broad semantic cleanup and making review harder.

Mitigation:

- keep the first pass registry-driven,
- log every replacement,
- auto-fix only when confidence is high,
- send ambiguous cases to review TSV instead of mutating output.

## Work checklist

- [x] Review current pipeline insertion points
- [x] Review existing bilingual postprocess hook
- [x] Write this handoff and execution document
- [x] Add `src/autosub_zh/entity_normalization.py`
- [x] Add a minimal entity registry file
- [x] Integrate entity normalization into `src/autosub_zh/pipeline_core.py`
- [x] Preserve normalized English reference text for ASS output without overloading `source_text`
- [x] Emit `06e_entity_decisions.json`
- [x] Emit `06f_entity_review.tsv`
- [x] Add focused tests for Chinese residue cleanup and English reference normalization
- [x] Add ASS-level audit artifact

## Live progress

### 2026-06-04

- Reviewed current pipeline and confirmed there is no formal entity-normalization stage.
- Identified the best first insertion point: after display rewrite, before ASS generation and final QA.
- Confirmed an existing low-risk hook already exists in `src/autosub_zh/bilingual_postprocess.py`, which we can extend rather than replace outright.
- Started Phase 1 by documenting the design and implementation plan here before touching the pipeline.
- Added a first-pass registry at [src/autosub_zh/datasets/entity_registry.json](D:/autosub_zh/src/autosub_zh/datasets/entity_registry.json:1) with confirmed entities from the recent Schizophrenic Art cleanup.
- Added [src/autosub_zh/entity_normalization.py](D:/autosub_zh/src/autosub_zh/entity_normalization.py:1) with a conservative registry-driven normalization pass.
- Integrated entity normalization into [src/autosub_zh/pipeline_core.py](D:/autosub_zh/src/autosub_zh/pipeline_core.py:1008) after display rewrite and before difficult-span / QA stages.
- Added new artifacts:
  - `06e_entity_decisions.json`
  - `06f_entity_review.tsv`
  - `06g_entity_normalized_segments.json`
- Added ASS-level entity audit output:
  - `08b_ass_entity_audit.json`
- Added focused tests in [tests/test_entity_normalization.py](D:/autosub_zh/tests/test_entity_normalization.py:1).
- Verified the first-pass module with `pytest -q tests/test_entity_normalization.py`:
  - result: `3 passed`
- Extended Phase 2 with:
  - review-row generation for unresolved English residue in Chinese target text,
  - ASS-level audit for Chinese subtitle English residue and non-canonical English reference names,
  - pipeline wiring so ASS entity residue becomes QA errors/warnings.
- Re-ran validation after the Phase 2 pass:
  - result: `5 passed`
- Added a separate `reference_text` field to keep normalized English reference text distinct from raw `source_text`.
- Updated segment serialization and ASS generation so bilingual reference lines now prefer `reference_text`.
- Added/updated focused tests for the new `reference_text` flow and subtitle output behavior.
- Re-ran focused validation after the `reference_text` migration:
  - result: `12 passed`
- Moved ASS entity audit message mapping into a dedicated QA helper instead of keeping the logic inline in `src/autosub_zh/pipeline_core.py`.
- Re-ran focused validation after the QA helper cleanup:
  - result: `13 passed`
- Added project-level `00_entity_decisions.json` support so a project can override or extend the global entity registry.
- Added bootstrapping so confirmed entities encountered in a project can seed `00_entity_decisions.json`.
- Tightened `06f_entity_review.tsv` candidate generation so it prefers English residue that actually echoes the source or normalized reference text.
- Re-ran focused validation after project override and review-filter improvements:
  - result: `15 passed`
- Integrated entity-residue tracking into `build_quality_metrics` so it is part of formal translation quality reporting, not only sidecar audit logic.
- Routed entity-residue samples into editor-review style outputs via the existing QA output path.
- Re-ran focused validation after the quality-metrics integration:
  - result: `16 passed`
- Decoupled `yt_dlp` imports from module top-level loading in the downloader/config path so unrelated tests and imports are no longer blocked by that optional dependency.
- Tightened `06f_entity_review.tsv` candidate filtering further:
  - honors project-level preserve decisions,
  - skips obvious quoted/title-like phrases,
  - still requires source/reference echo before surfacing a candidate.
- Re-ran focused validation after the import decoupling and review-filter tightening:
  - result: `18 passed`
- Added contract-style tests for entity-related pipeline outputs and manifest expectations.
- Re-ran broader focused validation after the contract test addition:
  - result: `21 passed`
- Added an explicit `bootstrap_entity_decisions` control path so project-level `00_entity_decisions.json` creation can be enabled deliberately instead of always happening implicitly.
- Added a dedicated `07h_entity_qa.tsv` output to separate entity-specific QA signals from the generic review table.
- Added focused tests for bootstrap behavior and entity QA row generation.
- Re-ran focused validation after the bootstrap control and dedicated entity QA output work:
  - result: `24 passed`
- Added a true lightweight pipeline integration test covering the existing-segments path, entity artifacts, manifest inclusion, and optional project bootstrap behavior.
- Re-ran the broader entity-related regression set:
  - result: `36 passed`
- Finalized the bootstrap strategy: default mode is now `high_confidence_only`, with compatibility for legacy boolean config values.
- Re-ran focused validation after promoting strategy C to the default:
  - result: `26 passed` on the targeted entity/config suite
- Updated editor-review style outputs to carry `reference_text` alongside `source_text` where relevant.
- Updated `07h_entity_qa.tsv` rows to include `segment_id` where available for easier traceability.
- Re-ran the broader entity-related regression set after the review-output enrichment:
  - result: `37 passed`
- Added glossary-aware filtering to `06f_entity_review.tsv` so preserve-policy terms do not surface as false-positive entity residue.
- Added `07i_entity_metrics.json` as a dedicated entity summary/metrics artifact.
- Re-ran the broader entity-related regression set after the entity-summary and review-filter expansion:
  - result: `39 passed`
- Added `entity_type` propagation to entity review and entity QA outputs, so downstream tools can distinguish people, papers, unknown residue, and future categories more cleanly.

## What is implemented now

- Registry-backed replacement of known proper-noun variants in both `source_text` and `target_text`.
- Registry-backed replacement of known proper-noun variants in `reference_text` and `target_text`.
- Full-name-first, short-name-later behavior for configured entities.
- Canonical English/native spelling normalization for reference text inputs before ASS writing.
- Stage report emission and manifest file inclusion through the normal pipeline.
- Review TSV emission for unresolved English residue candidates in Chinese target text.
- ASS-level audit artifact generation for post-render residue and canonicality checks.
- `source_text` now remains the raw source transcript, while `reference_text` carries the cleaned English reference text used for ASS output.
- ASS entity audit messages are now produced through a dedicated QA helper rather than ad hoc string construction in the pipeline.
- Project-level entity decision overrides are supported through `00_entity_decisions.json`.
- Entity-like English residue in Chinese target text is now tracked in quality metrics and can surface in review outputs.
- Optional downloader dependencies are less entangled with subtitle-only test and import paths.
- Entity-related output filenames and manifest expectations are now covered by dedicated contract tests.
- Entity-specific QA now has its own TSV output path in addition to generic review tables.
- A lightweight pipeline integration test now exercises real `run_pipeline` behavior for entity outputs without requiring the full downloader/ASR stack.
- `bootstrap_entity_decisions` now defaults to `high_confidence_only`.
- Generic editor review rows can now surface both `source_text` and `reference_text`.
- `07i_entity_metrics.json` now provides an entity-focused summary layer separate from generic quality metrics.
- Entity review and entity QA outputs now carry `entity_type` metadata.

## What still needs to be done

- Expand tests beyond focused modules once the optional `yt_dlp` import path is isolated or mocked cleanly.
- Improve candidate detection further for mixed punctuation, parentheses, and title-like fragments that still look like names.
- Add explicit tests for project bootstrap file creation and manifest inclusion in a fuller pipeline-style scenario.

## Notes for the next AI

- Keep the first implementation conservative. The fastest useful win is eliminating English residue from Chinese subtitle lines using a registry-backed pass.
- Avoid mixing this feature with broad ASR semantic cleanup.
- Prefer small, testable integration steps:
  - normalize segments,
  - write reports,
  - then add ASS-level audit.
- `reference_text` has now been introduced as the English reference source of truth for ASS output. The next AI should propagate this field carefully if it extends debug reports, editor exports, or UI previews.
- Review candidate detection is narrower now, but it still uses regex heuristics. The next iteration should probably combine registry lookup with source-span alignment and maybe glossary context.
- Quality metrics now track entity-like residue as full title-case phrases, not split words. Preserve that behavior unless there is a strong reason to regress to token-level reporting.
- The `yt_dlp` import coupling is partly resolved now, but broader tests may still need import-boundary cleanup if they exercise downloader execution paths rather than just metadata/helper modules.
- Bootstrap behavior is now explicit. If a future change flips the default, update tests and docs together so the project file creation semantics stay predictable.
