# AI Change Log

This file is the dedicated update log for project changes that should remain legible to future AI maintainers and human contributors.

## 2026-06-04

### Multilingual workflow foundation

- Added workflow profile system in [workflow_profiles.py](D:/autosub_zh/workflow_profiles.py)
- Added built-in profiles:
  - [workflow_profiles/en_to_zh_default.json](D:/autosub_zh/workflow_profiles/en_to_zh_default.json)
  - [workflow_profiles/ru_to_zh_default.json](D:/autosub_zh/workflow_profiles/ru_to_zh_default.json)
- Added prompt profiles:
  - [translation_prompts/en_zh_natural_subtitle.md](D:/autosub_zh/translation_prompts/en_zh_natural_subtitle.md)
  - [translation_prompts/ru_zh_natural_subtitle.md](D:/autosub_zh/translation_prompts/ru_zh_natural_subtitle.md)
- Added Russian dataset seed assets under [datasets/ru_zh/general](D:/autosub_zh/datasets/ru_zh/general)

### Subtitle output modes

- Added language-aware output naming in [workflow_profiles.py](D:/autosub_zh/workflow_profiles.py)
- Added subtitle-mode routing in [pipeline_core.py](D:/autosub_zh/pipeline_core.py)
- Added source-only review ASS writer in [subtitle_io.py](D:/autosub_zh/subtitle_io.py)

### Glossary and dataset integration

- Added dataset asset copying into output projects
- Added profile glossary bundle generation in [pipeline_core.py](D:/autosub_zh/pipeline_core.py)
- Added profile glossary merge support in [glossary.py](D:/autosub_zh/glossary.py)
- Added translation glossary text override support in [translate.py](D:/autosub_zh/translate.py)

### Web UI groundwork

- Added Workflow tab structure in [web/index.html](D:/autosub_zh/web/index.html)
- Added workflow-related state and partial wiring in [web/app.js](D:/autosub_zh/web/app.js)
- Added workflow profile bootstrap data in [ui_server.py](D:/autosub_zh/ui_server.py)

### Tests

- Added [tests/test_workflow_profiles.py](D:/autosub_zh/tests/test_workflow_profiles.py)
- Added [tests/test_subtitle_output_modes.py](D:/autosub_zh/tests/test_subtitle_output_modes.py)
- Focused test result during this update:
  - `8 passed`

### Model and validation status

- Downloaded `faster-whisper` multilingual `large-v3` model into local Hugging Face cache
- Verified `WhisperModel('large-v3', device='cpu', compute_type='int8')` can be instantiated with the system Python 3.11 interpreter
- Created a 60-second Russian preview slice:
  - [input/ru_xiu_xiu_preview_60s.mp4](D:/autosub_zh/input/ru_xiu_xiu_preview_60s.mp4)
- Verified `large-v3` ASR on the Russian preview slice and confirmed the decoded source text is real Cyrillic Russian, not mojibake or English hallucination
- Updated the runtime base URL to `https://api-slb.micuapi.ai/v1`
- Verified OpenAI-compatible dry run through the new base URL
- Completed a real Russian 60-second preview run in `target_only` mode with:
  - translated SRT
  - Chinese-only ASS
  - QA pass with warnings only
- Installed `fontTools`, resolved the true family name of the provided 匯文港黑 font file as `Huiwen-HKHei`, and set it as the default Russian reference-layer font in the workflow profile

### Current incomplete areas

- Full workflow tab round-trip behavior is not fully finished
- Russian preview still has quality-level warning items around difficult spans and title rendering, even though QA now passes
- Git commit checkpoints were blocked earlier by environment limitations and may not reflect the logical node boundaries yet
