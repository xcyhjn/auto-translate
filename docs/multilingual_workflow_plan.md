# Multilingual Workflow Plan

## Goal

This document records the multilingual workflow direction introduced for `autosub_zh`, with Russian-to-Chinese as the first non-English profile. It is meant to be practical deployment guidance for future language expansion.

## Current Direction

The project is moving from a single implicit English-to-Chinese pipeline to a profile-driven workflow model.

Core idea:

- Keep one pipeline.
- Add language-aware workflow profiles.
- Let each profile provide:
  - source and target language defaults
  - ASR model defaults
  - prompt profile
  - dataset profile
  - subtitle output mode
  - source reference label

This avoids copying the whole pipeline for each language.

## Implemented Pieces

### 1. Workflow profile layer

New module:

- `src/autosub_zh/workflow_profiles.py`

Current built-in profiles:

- `src/autosub_zh/workflow_profiles/en_to_zh_default.json`
- `src/autosub_zh/workflow_profiles/ru_to_zh_default.json`

Current profile responsibilities:

- choose `src_lang`
- choose `dst_lang`
- choose default Whisper model
- choose prompt profile
- choose dataset profile
- choose subtitle mode
- choose source reference label

### 2. Prompt profiles

New prompt files:

- `src/autosub_zh/translation_prompts/en_zh_natural_subtitle.md`
- `src/autosub_zh/translation_prompts/ru_zh_natural_subtitle.md`

Purpose:

- separate language-specific translation guidance from generic translation code
- keep prompts editable without touching business logic

### 3. Dataset profiles

New dataset structure:

- `src/autosub_zh/datasets/en_zh/general/`
- `src/autosub_zh/datasets/ru_zh/general/`

Russian dataset currently includes:

- `glossary.json`
- `asr_confusions.json`
- `style_examples.jsonl`
- `qa_cases.jsonl`

Purpose:

- provide language-specific glossary seeds
- keep ASR repair and review assets near the workflow profile
- make future QA regression cases reusable
- copy dataset assets into each output project for audit and review
- merge profile glossary seeds into the project glossary resolution path

### 4. Subtitle output modes

Current modes:

- `bilingual_source_reference`
- `target_only`
- `source_review`

Current behavior:

- `bilingual_source_reference`: Chinese main subtitle plus source reference line
- `target_only`: Chinese-only ASS output
- `source_review`: source-language-only ASS for review; burn is skipped

Naming is now language-aware, for example:

- `04_source_ru.srt`
- `06_translated_zh.srt`
- `08_bilingual_zh_ru.ass`
- `08_subtitle_zh.ass`
- `08_source_ru.ass`

## Files Touched In This Rollout

- `src/autosub_zh/workflow_profiles.py`
- `src/autosub_zh/pipeline_core.py`
- `src/autosub_zh/translate.py`
- `src/autosub_zh/subtitle_io.py`
- `src/autosub_zh/ui_server.py`
- `src/autosub_zh/web/index.html`
- `src/autosub_zh/web/app.js`
- `src/autosub_zh/glossary.py`
- `docs/multilingual_workflow_plan.md`

## Frontend Direction

The Web UI is being reshaped around a workflow-first mental model.

New UI direction:

- keep the existing tabs
- add a `Workflow` tab
- let users choose:
  - workflow profile
  - subtitle mode
  - prompt profile
  - dataset profile
  - source reference label

Russian workflow UX goal:

- one-click switch to Russian defaults
- visible prompt preview
- visible dataset preview
- still allow low-level overrides in recognition/translation/style tabs

## Deployment Pattern For New Languages

To add another language pair, follow this shape:

1. Add a workflow profile JSON file.
2. Add a prompt profile Markdown file.
3. Add a dataset directory with glossary and QA examples.
4. Reuse the same pipeline unless the language truly needs special logic.

Recommended structure:

```text
src/autosub_zh/workflow_profiles/ja_to_zh_default.json
src/autosub_zh/translation_prompts/ja_zh_natural_subtitle.md
datasets/ja_zh/general/glossary.json
datasets/ja_zh/general/asr_confusions.json
datasets/ja_zh/general/style_examples.jsonl
datasets/ja_zh/general/qa_cases.jsonl
```

## Russian Validation Workflow

Recommended validation loop for the Russian profile:

1. Run a 60-second preview on a real Russian video.
2. Inspect:
   - source ASR segments
   - translated Chinese SRT
   - generated ASS
   - final QA report
3. Fix prompt, glossary, or subtitle mode issues.
4. Re-run the same 60-second slice.
5. Only then run the full video.

## Known Gaps

These still need follow-up:

- UI wiring needs to fully round-trip workflow profile state in every path.
- Dataset profile data is now copied into project output and the profile glossary is merged into project glossary resolution, but the QA sample assets are not yet actively evaluated during runtime.
- Russian-specific QA heuristics still need stronger source-language awareness.
- A real 60-second Russian slice has been prepared from the provided sample video, but the current machine does not have the multilingual `large-v3` Whisper model cached locally, so ASR validation currently stops at model download.
- Git checkpointing is blocked by current `.git` write permission limits in this environment.

## Recommended Next Steps

1. Finish `src/autosub_zh/web/app.js` workflow state wiring and preview rendering.
2. Add Russian-aware QA rules for Cyrillic source and Chinese target leakage checks.
3. Run the provided Russian sample in preview mode.
4. Review the generated output files.
5. Iterate on prompt and glossary until the preview is stable.
6. Run the full video.

## Testing Status

Current focused tests added or used:

- `tests/test_workflow_profiles.py`
- `tests/test_subtitle_output_modes.py`

These currently verify:

- profile loading
- Russian profile defaults
- language-aware output naming
- target-only subtitle output behavior
- source-review ASS output behavior
- dataset asset copy behavior
