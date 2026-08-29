# Frontend Handoff And Project Status

This document is the current handoff for the next AI that will take over frontend inspection and optimization work.

It summarizes:

- what the project currently does,
- what has already been implemented,
- what is still in progress,
- where the frontend stands today,
- which frontend directions are highest-value next.

## Project summary

This project is a subtitle generation and hard-burn workflow for bilingual video subtitles.

Current major capabilities include:

- ASR-driven source subtitle generation
- translation into Chinese subtitle text
- display rewrite for subtitle-friendly Chinese output
- multiple subtitle output modes
- ASS generation and hard-burn video generation
- workflow profiles for language-specific pipelines
- style learning from manually edited ASS files
- entity normalization for proper nouns and related residue cleanup

The project is part backend pipeline, part local web UI.

## Current architecture

### Backend

Core backend modules:

- [pipeline_core.py](D:/autosub_zh/pipeline_core.py)
- [translate.py](D:/autosub_zh/translate.py)
- [subtitle_io.py](D:/autosub_zh/subtitle_io.py)
- [qa.py](D:/autosub_zh/qa.py)
- [qa_outputs.py](D:/autosub_zh/qa_outputs.py)
- [workflow_profiles.py](D:/autosub_zh/workflow_profiles.py)
- [ui_server.py](D:/autosub_zh/ui_server.py)

### Frontend

Current frontend files:

- [web/index.html](D:/autosub_zh/web/index.html)
- [web/app.js](D:/autosub_zh/web/app.js)
- [web/styles.css](D:/autosub_zh/web/styles.css)

The frontend is a local control panel for:

- configuring pipeline options
- starting tasks
- reviewing status/progress
- inspecting outputs

It is not yet fully aligned with the new backend entity-normalization outputs.

## Major implemented backend progress

### Entity normalization system

Implemented:

- global entity registry:
  - [datasets/entity_registry.json](D:/autosub_zh/datasets/entity_registry.json)
- project-level entity decisions:
  - `00_entity_decisions.json`
- `reference_text` separated from raw `source_text`
- Chinese subtitle English-residue cleanup
- English reference-layer canonical spelling normalization
- dedicated outputs:
  - `06e_entity_decisions.json`
  - `06f_entity_review.tsv`
  - `06g_entity_normalized_segments.json`
  - `07h_entity_qa.tsv`
  - `07i_entity_metrics.json`
  - `08b_ass_entity_audit.json`

### QA and review integration

Implemented:

- entity residue enters quality metrics
- entity residue enters review outputs
- dedicated entity QA TSV exists
- dedicated entity metrics JSON exists
- editor review rows can now show both `source_text` and `reference_text`

### Project decisions bootstrap strategy

Finalized:

- `bootstrap_entity_decisions` supports:
  - `off`
  - `always`
  - `high_confidence_only`
- current default:
  - `high_confidence_only`

This means project-level entity decisions are written only when high-confidence entity decisions are detected.

### Import decoupling

Implemented:

- optional `yt_dlp` import paths were decoupled at module import time
- subtitle-only tests and imports are less blocked by downloader dependencies

## Current verification status

Recent regression result:

```bash
pytest -q tests/test_entity_pipeline_integration.py tests/test_entity_pipeline_contract.py tests/test_entity_normalization.py tests/test_subtitle_output_modes.py tests/test_qa_outputs.py tests/test_asr_repair_flow.py tests/test_workflow_profiles.py
```

Current result:

- `39 passed`

This means the entity-normalization line is no longer just a loose feature. It has focused tests, contract tests, and a lightweight integration test.

## Frontend status right now

## Installed frontend-specific skills and tools

The environment now includes frontend-relevant skills that the next AI should actively use rather than ignoring:

- `experience-and-design-system`
  - use for visual hierarchy, spacing, typography, component polish, and anti-slop interface decisions
- `motion-and-interaction-system`
  - use for purposeful animation, transition behavior, hover/focus/active states, and reduced-motion-safe interaction design
- `canvas-design`
  - use only if a static visual artifact or carefully composed design output is needed; it is not the default path for app UI work
- Browser plugin skill: `control-in-app-browser`
  - use to inspect and verify the local UI in the in-app browser after changes

These are not decorative extras. They should inform both audit and implementation work on the frontend.

### What the frontend already has

- local UI shell
- config editing
- workflow profile selection
- task running
- status/progress display

### What the frontend does not yet fully surface

- `reference_text` as a first-class field
- project entity decisions state
- entity review artifacts
- entity QA artifacts
- entity metrics summary
- bootstrap mode selection in an explicit user-friendly way
- richer per-project subtitle/entity inspection workflows

## Frontend optimization directions

### 1. Add an Entity panel

High priority.

Surface:

- entity decision count
- changed segment count
- entity residue count
- ASS entity audit issue count
- entity type distribution

Primary source:

- `07i_entity_metrics.json`

### 2. Add entity review tables

High priority.

Surface:

- `06f_entity_review.tsv`
- `07h_entity_qa.tsv`

Useful filters:

- issue type
- entity type
- segment id
- only unresolved items

### 3. Surface `reference_text`

High priority.

Where:

- preview panes
- review drawers
- debug/detail views

Show:

- `source_text`
- `reference_text`
- `target_text`

This is important because the backend has already separated raw ASR text from normalized English reference text.

### 4. Expose bootstrap mode in UI

Medium priority.

Expose:

- `off`
- `always`
- `high_confidence_only`

This should map directly to backend config and survive config save/reload/profile switching.

### 5. Add project decisions visibility

Medium priority.

At minimum:

- show whether `00_entity_decisions.json` exists
- show which strategy is active
- show whether project decisions were generated in the current run

Nice next step:

- read-only preview of project decisions

### 6. Improve frontend information architecture

Medium priority.

Current likely improvement path:

- separate pipeline controls from output review
- group review outputs by:
  - translation QA
  - display QA
  - glossary QA
  - entity QA
- give each output family a dedicated section rather than a flat file/status list

## System-level remaining work

These are the larger engineering items still open:

1. Expand integration coverage beyond the current lightweight entity path.
2. Further reduce `06f_entity_review.tsv` false positives for title-like and punctuation-heavy cases.
3. Continue making downstream tools and views explicitly aware of `reference_text`.
4. Consider further splitting entity reporting away from generic QA structures.

## Frontend-specific remaining work

These are the frontend tasks that matter most now:

1. Add entity metrics and review surfaces.
2. Add `reference_text` to review/debug UX.
3. Add explicit bootstrap mode controls.
4. Add project decisions visibility.
5. Reorganize the UI around task execution vs artifact inspection.

## Recommended order for the next AI

1. Audit the current frontend code in [web/index.html](D:/autosub_zh/web/index.html), [web/app.js](D:/autosub_zh/web/app.js), and [web/styles.css](D:/autosub_zh/web/styles.css).
2. Map the current API payloads and output artifacts already available from the backend.
3. Apply `experience-and-design-system` while designing the frontend information architecture for entity-aware review.
4. Implement the entity panel and review tables first.
5. Add `reference_text` to relevant debug/review displays.
6. Use `motion-and-interaction-system` to refine interactions only after the main information architecture is solid.
7. Add bootstrap mode UI only after confirming the current config save/load path.
8. Verify everything in the in-app browser using `control-in-app-browser`.

## Notes for the next AI

- Do not assume the frontend is in sync with backend capabilities.
- The backend now has more structured entity artifacts than the frontend currently exposes.
- Avoid redesigning everything at once; the highest leverage is to expose the new entity outputs clearly and make `reference_text` visible.
- Use the installed frontend skills deliberately. The environment is now better equipped for serious frontend work than the earlier handoff assumed.
