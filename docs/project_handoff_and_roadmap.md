# Project Handoff And Roadmap

## What This Project Is

`autosub_zh` is a local subtitle pipeline and Web UI for:

- media inspection
- audio extraction
- local ASR with `faster-whisper`
- chunked subtitle translation through an OpenAI-compatible API
- subtitle QA
- ASS/SRT export
- optional hard-burn video output

The original project shape was strongly optimized for English-to-Chinese subtitle work. It is now being expanded toward a profile-driven multilingual workflow system, starting with Russian-to-Chinese.

## Core Runtime Flow

The main pipeline entry is:

- [pipeline_core.py](D:/autosub_zh/pipeline_core.py)

High-level runtime stages:

1. Probe media with `ffprobe`
2. Extract or enhance audio with `ffmpeg`
3. Run `faster-whisper` ASR
4. Refine timing
5. Build glossary and source-span signals
6. Translate risky spans first
7. Translate the full subtitle stream
8. Run display rewrite and difficult-span repair
9. Run QA
10. Export subtitle assets
11. Optionally burn subtitles into video

## Important Modules

Main pipeline and orchestration:

- [pipeline_core.py](D:/autosub_zh/pipeline_core.py)
- [ui_server.py](D:/autosub_zh/ui_server.py)
- [cli.py](D:/autosub_zh/cli.py)

ASR and media:

- [asr.py](D:/autosub_zh/asr.py)
- [media.py](D:/autosub_zh/media.py)
- [timing.py](D:/autosub_zh/timing.py)

Translation and text quality:

- [translate.py](D:/autosub_zh/translate.py)
- [span_translate.py](D:/autosub_zh/span_translate.py)
- [span_repair.py](D:/autosub_zh/span_repair.py)
- [display_rewrite.py](D:/autosub_zh/display_rewrite.py)
- [text_quality.py](D:/autosub_zh/text_quality.py)
- [difficult_spans.py](D:/autosub_zh/difficult_spans.py)

Glossary and terminology:

- [glossary.py](D:/autosub_zh/glossary.py)
- [terminology.py](D:/autosub_zh/terminology.py)

Subtitle output:

- [subtitle_io.py](D:/autosub_zh/subtitle_io.py)
- [qa.py](D:/autosub_zh/qa.py)
- [qa_outputs.py](D:/autosub_zh/qa_outputs.py)

Web UI:

- [web/index.html](D:/autosub_zh/web/index.html)
- [web/app.js](D:/autosub_zh/web/app.js)
- [web/styles.css](D:/autosub_zh/web/styles.css)

## New Multilingual Layer

The multilingual work introduced a workflow-profile layer:

- [workflow_profiles.py](D:/autosub_zh/workflow_profiles.py)
- [workflow_profiles/en_to_zh_default.json](D:/autosub_zh/workflow_profiles/en_to_zh_default.json)
- [workflow_profiles/ru_to_zh_default.json](D:/autosub_zh/workflow_profiles/ru_to_zh_default.json)

Each workflow profile can define:

- source language
- target language
- default ASR model
- prompt profile
- dataset profile
- subtitle mode
- source reference label
- optional config defaults
- optional style defaults

## Prompt And Dataset Layout

Prompt profiles live under:

- [translation_prompts](D:/autosub_zh/translation_prompts)

Current prompts:

- [translation_prompts/en_zh_natural_subtitle.md](D:/autosub_zh/translation_prompts/en_zh_natural_subtitle.md)
- [translation_prompts/ru_zh_natural_subtitle.md](D:/autosub_zh/translation_prompts/ru_zh_natural_subtitle.md)

Dataset profiles live under:

- [datasets](D:/autosub_zh/datasets)

Current Russian dataset:

- [datasets/ru_zh/general/glossary.json](D:/autosub_zh/datasets/ru_zh/general/glossary.json)
- [datasets/ru_zh/general/asr_confusions.json](D:/autosub_zh/datasets/ru_zh/general/asr_confusions.json)
- [datasets/ru_zh/general/style_examples.jsonl](D:/autosub_zh/datasets/ru_zh/general/style_examples.jsonl)
- [datasets/ru_zh/general/qa_cases.jsonl](D:/autosub_zh/datasets/ru_zh/general/qa_cases.jsonl)

Current behavior:

- dataset assets are copied into the output project folder
- profile glossary seeds are merged into the resolved project glossary path
- prompt profiles are injected into translation defaults

## Subtitle Modes

Current subtitle output modes:

- `bilingual_source_reference`
- `target_only`
- `source_review`

Implemented outputs:

- `bilingual_source_reference`
  - Chinese main subtitle
  - source reference line
- `target_only`
  - Chinese-only ASS output
- `source_review`
  - source-only ASS output
  - burn is skipped

Relevant code:

- [workflow_profiles.py](D:/autosub_zh/workflow_profiles.py)
- [subtitle_io.py](D:/autosub_zh/subtitle_io.py)
- [pipeline_core.py](D:/autosub_zh/pipeline_core.py)

## Russian Workflow Status

Russian-to-Chinese is the first non-English profile under active development.

Current status:

- profile exists
- prompt exists
- dataset exists
- subtitle mode wiring exists
- output naming is language-aware
- project glossary can absorb Russian profile glossary seeds

Real validation status:

- a 60-second preview slice has been created:
  - [input/ru_xiu_xiu_preview_60s.mp4](D:/autosub_zh/input/ru_xiu_xiu_preview_60s.mp4)
- `large-v3` has now been downloaded and verified as loadable in the system Python environment

## Important Environment Notes

There are multiple Python environments on this machine.

Observed state:

- shell `python` points to a Hermes-managed venv
- `faster-whisper` and `yt-dlp` are installed in:
  - `C:\Users\bulbel\AppData\Local\Programs\Python\Python311\python.exe`

This matters because:

- model download and runtime validation should use the Python 3.11 interpreter
- otherwise imports may fail even when the packages are already installed

Recommended practice for future maintenance:

- use the system Python explicitly when validating model downloads
- or align the UI server/runtime environment so package resolution is consistent

## Current Strengths

- pipeline stages are already modular
- subtitle QA is richer than a typical one-shot subtitle tool
- output artifacts are reviewable and not just opaque final video files
- multilingual expansion can happen through profiles instead of cloned pipelines

## Current Weak Spots

- the UI workflow tab is only partially wired
- many QA heuristics still assume Latin-script source behavior
- some file naming and legacy compatibility logic now has transitional complexity
- the runtime environment is split across multiple Python interpreters
- the project still carries strong English-first assumptions in some display and validation layers

## Recommended Development Priorities

### Near-term

1. Finish full UI round-trip for workflow profile state
2. Validate Russian profile on real media end-to-end
3. Add Russian-aware QA rules for Cyrillic source
4. Add a small regression harness that runs profile-level smoke tests

### Mid-term

1. Generalize source-language handling beyond `en` naming assumptions
2. Introduce structured dataset QA execution instead of passive file storage
3. Separate runtime config, profile defaults, and user overrides more cleanly
4. Add explicit output-mode controls to the output/project views

### Longer-term

1. Add more language profiles such as Japanese-to-Chinese
2. Add local glossary editing in the UI
3. Add profile-specific font presets and source-script-aware subtitle styling
4. Build a real review queue for difficult spans and glossary conflicts

## Recommended Optimization Directions

### Quality

- make difficult-span detection source-language-aware
- add profile-specific translation repair rules
- expand glossary merge logic to include dataset QA examples and stronger alias correction

### Runtime

- cache resolved glossary state more deliberately
- avoid repeated prompt/dataset reloading in long runs
- add clearer fallback rules for unavailable Whisper models

### UX

- make workflow profile the first decision in the UI
- expose active profile, prompt, and dataset more clearly during runs
- show subtitle mode in the output project cards

### Maintenance

- document every new workflow profile in one place
- keep a dedicated changelog
- add a small handoff checklist for future AI agents and human maintainers

## Suggested Handoff Checklist

Before another AI or developer takes over:

1. Read this file.
2. Read [docs/multilingual_workflow_plan.md](D:/autosub_zh/docs/multilingual_workflow_plan.md).
3. Check [workflow_profiles.py](D:/autosub_zh/workflow_profiles.py).
4. Check current focused tests:
   - [tests/test_workflow_profiles.py](D:/autosub_zh/tests/test_workflow_profiles.py)
   - [tests/test_subtitle_output_modes.py](D:/autosub_zh/tests/test_subtitle_output_modes.py)
5. Verify which Python interpreter is actually running the pipeline.
6. Confirm model cache availability for the target workflow profile.
7. Run a 60-second preview before touching the full video workflow.
