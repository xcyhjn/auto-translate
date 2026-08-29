# Frontend UI Audit - 2026-06-04

This audit follows `docs/frontend_ui_optimization_directions.md`: UI problems are documented first, and frontend files should not be edited until the project owner confirms the direction.

## Scope

Files inspected:

- `docs/frontend_ui_optimization_directions.md`
- `docs/frontend_handoff_and_project_status.md`
- `docs/frontend_ai_optimization_prompt.md`
- `docs/russian_reference_layer_full_split_task.md`
- `docs/entity_normalization_handoff.md`
- `web/index.html`
- `web/app.js`
- `web/styles.css`
- `ui_server.py`
- `workflow_profiles.py`
- `workflow_profiles/ru_to_zh_default.json`
- `ui_config.json`

Checks run:

```powershell
pytest -q tests/test_workflow_profiles.py tests/test_ui_server_config.py tests/test_reference_mode_ui.py
```

Result:

- `9 passed`

Browser verification status:

- The in-app Browser backend was unavailable in this session (`agent.browsers.list()` returned an empty list).
- I used local HTTP API reads and code inspection instead.
- Real browser verification is still required before implementation is considered safe.

## Findings

### 1. Russian workflow defaults are correct on disk and in current saved config

`workflow_profiles/ru_to_zh_default.json` currently has:

- `src_lang = ru`
- `dst_lang = zh-Hans`
- `model = large-v3`
- `prompt_profile = ru_zh_natural_subtitle`
- `dataset_profile = ru_zh/general`
- `source_reference_label = ru`
- `en_font_name = Huiwen-HKHei`
- `en_font_size = 32`
- `en_max_single_line_chars = 80`
- `en_max_split_parts = 4`
- `min_split_duration = 1.2`
- `reference_mode = full_split`

`ui_config.json` also currently stores the same Russian reference-layer values, and `/api/bootstrap` returned those config values from the currently running server.

Important nuance:

- `docs/russian_reference_layer_full_split_task.md` still describes an older state where Russian used `hide_when_overflow`.
- Treat the JSON profile and tests as the current truth, not that old paragraph.

### 2. `normalize_config` can still fall back to English style defaults for partial style payloads

The safe path works:

```python
normalize_config({"workflow_profile": "ru_to_zh_default"})
```

returns the expected Russian style.

But these payloads fall back to English compact defaults:

```python
normalize_config({"workflow_profile": "ru_to_zh_default", "style": {}})
normalize_config({"workflow_profile": "ru_to_zh_default", "style": {"en_font_name": "Arial"}})
```

Observed result:

- `en_font_name = Arial`
- `en_font_size = 40`
- `en_max_single_line_chars = 78`
- `en_max_split_parts = 3`
- `min_split_duration = 2.0`
- `reference_mode = compact`

Likely cause:

- `ui_server.normalize_config()` applies workflow defaults, then overlays the raw incoming payload again.
- If incoming contains `style`, that second overlay can erase the profile style before `STYLE_DEFAULTS` are filled.

Risk:

- The current UI usually sends a full style object, so the main path may look fine.
- Any partial save, future frontend refactor, API caller, or empty style object can reintroduce English compact defaults into a Russian workflow.

### 3. Running UI server appears older than the working tree

The server process on port `8777` started at `2026-06-04 01:51:15`:

```text
python -m autosub_zh.ui_server
```

The current disk version of `ui_server.py` includes `workflow_profiles`, `active_prompt_profile`, and `active_dataset_profile` in `/api/bootstrap`.

The running `/api/bootstrap` response only returned:

```text
server_version, state, videos, audios, projects, config
```

Missing from the running response:

- `workflow_profiles`
- `active_prompt_profile`
- `active_dataset_profile`

Risk:

- New `web/app.js` expects `workflow_profiles` to populate the workflow selector.
- If the selector remains empty, `readFormConfig()` can fall back to `workflow_profile = en_to_zh_default`.
- That is a credible path for "UI save/refresh accidentally returns to English compact defaults."

Recommendation:

- Restart the UI server after any code change before judging the browser behavior.
- Add a small UI/API guard so the frontend does not save `en_to_zh_default` just because the profile list failed to load.

### 4. Frontend has entity UI code, but the information architecture is still not fully clear

Current frontend code can read real artifact files:

- `07i_entity_metrics.json`
- `06f_entity_review.tsv`
- `07h_entity_qa.tsv`
- `06g_entity_normalized_segments.json`
- `00_entity_decisions.json`

The `entity_ui_fixture` output project includes these files, and `/api/file` can read them.

Current gaps:

- Entity review is embedded at the top of the output panel, above the project/file browser.
- It shows only a limited table preview and tells the user to open TSV manually for full rows.
- It does not yet provide filters for issue type, entity type, segment id, changed-only rows, or unresolved rows.
- It does not surface `08b_ass_entity_audit.json` as a first-class section even though the backend emits it.
- It does not clearly separate "automatic decisions", "human review candidates", "QA failures", and "ASS audit".

### 5. `reference_text` is surfaced, but only in the entity panel

Current code can show:

- raw `source_text`
- normalized `reference_text`
- Chinese `target_text`

Current gaps:

- This comparison is only in `Reference Text Comparison` under entity review.
- The generic file preview still displays raw file text only.
- Alignment/debug outputs are not transformed into a reviewer-friendly source/reference/target view.
- `07d_editor_review.tsv` now contains `reference_text`, but the output panel does not give it a dedicated structured view.

### 6. Workflow/profile/config state is not visually explicit enough

Current workflow panel includes:

- workflow selector
- subtitle mode
- prompt profile
- dataset profile
- active pair
- prompt preview
- dataset preview

Current gaps:

- There is no compact "what will run" summary that includes workflow, source language, target language, subtitle mode, prompt profile, dataset profile, bootstrap mode, reference mode, and reference-layer style values together.
- The UI does not clearly flag mismatches such as:
  - workflow says Russian but style says `Arial / compact`
  - workflow says Russian but prompt/dataset are English
  - config loaded but workflow profile list failed to load

### 7. Reference-layer labels are still English-centric

The subtitle style section still uses fields backed by `en_*`, and the section label reads like an English subtitle layer.

For the Russian workflow, this can mislead the user:

- `en_font_name` actually controls the Russian reference layer.
- `en_max_single_line_chars` controls the Russian reference line limit.
- `reference_mode = full_split` is the intended Russian strategy, but the UI does not explain why.

Do not rename backend keys without approval.

Recommended UI copy:

- "Reference layer font" instead of "English font"
- "Reference font size"
- "Reference line limit"
- "Reference split parts"
- "Reference mode"

Keep the internal keys unchanged.

### 8. Text encoding/readability appears broken in served HTML and JS strings

Several visible Chinese labels appear mojibake-style in source and served HTML, for example tab labels and status text.

Risk:

- The UI is harder to use and audit.
- It may hide real state because labels are unreadable.

Recommendation:

- Treat this as a separate encoding cleanup task.
- Do not mix encoding repair with workflow/entity information architecture unless the owner approves.

## Recommended Information Architecture

### Top activity area

Purpose:

- show current execution state and prevent accidental wrong-config runs.

Show:

- selected input
- run state/progress
- active workflow profile
- source -> target
- subtitle mode
- save state
- warning chip if profile metadata failed to load

### Workflow setup

Purpose:

- choose the language pipeline and validate that profile/config/form agree.

Show a compact "Effective Workflow" summary:

- workflow profile
- source language
- target language
- model
- subtitle mode
- source reference label
- prompt profile
- dataset profile
- bootstrap entity mode

Add mismatch states:

- Russian workflow but English prompt/dataset
- Russian workflow but reference style is not `Huiwen-HKHei / 32 / 80 / 4 / 1.2 / full_split`
- workflow profile list unavailable

### Subtitle/reference style

Purpose:

- tune subtitle appearance without implying the reference layer is English-only.

Structure:

- Chinese subtitle style
- Reference layer style
- Reference strategy

For Russian:

- show `full_split` as the expected full-display mode
- show current values in a concise status row
- keep enum values visible for technical accuracy

### Outputs and review

Purpose:

- inspect generated artifacts after a run.

Split into:

- Project file browser
- Subtitle preview
- QA summary
- Entity review

Entity review should have sub-sections:

- Metrics summary from `07i_entity_metrics.json`
- Project decisions status from `00_entity_decisions.json`
- Entity decisions from `06e_entity_decisions.json`
- Review candidates from `06f_entity_review.tsv`
- Entity QA from `07h_entity_qa.tsv`
- ASS audit from `08b_ass_entity_audit.json`
- Source/reference/target comparison from `06g_entity_normalized_segments.json`

### File preview

Purpose:

- inspect raw and structured output artifacts.

Recommended behavior:

- keep raw preview for every file
- add structured renderers for known artifact families:
  - normalized segments
  - editor review TSV
  - entity review TSV
  - entity QA TSV
  - metrics JSON
  - ASS audit JSON

## File-Level Modification Suggestions

Do not implement these until the owner confirms.

### `ui_server.py`

Suggested backend-safe fix:

- Change `normalize_config()` so workflow profile defaults are preserved when incoming `style` is empty or partial.
- Return the normalized config from `/api/save-config`, not the pre-normalized merged payload.
- Add a test for partial style payloads.

Suggested test:

```python
def test_normalize_config_preserves_russian_profile_style_with_partial_style() -> None:
    config = normalize_config({"workflow_profile": "ru_to_zh_default", "style": {}})

    assert config["style"]["en_font_name"] == "Huiwen-HKHei"
    assert config["style"]["en_font_size"] == 32
    assert config["style"]["en_max_single_line_chars"] == 80
    assert config["style"]["en_max_split_parts"] == 4
    assert config["style"]["min_split_duration"] == 1.2
    assert config["style"]["reference_mode"] == "full_split"
```

### `web/app.js`

Suggested frontend guards:

- Do not let `workflow_profile` silently become `en_to_zh_default` when `workflow_profiles` failed to load.
- Add an explicit profile-load warning state.
- In `renderState()`, preserve existing `workflowProfiles` if the payload omits `workflow_profiles`, but also mark metadata as stale.
- In `readFormConfig()`, use current `state.config.workflow_profile` if the select has no loaded options.
- Expand workflow summary to include style/reference/entity bootstrap state.
- Add mismatch detection for Russian workflow vs English compact style.
- Add structured renderers for `07d_editor_review.tsv`, `08b_ass_entity_audit.json`, and normalized segment JSON.
- Add filters and row limits for entity review/QA tables.

### `web/index.html`

Suggested UI structure changes:

- Add a compact effective-workflow summary area in the workflow panel.
- Rename visible labels for `en_*` controls to reference-layer wording.
- Add short helper text near `reference_mode`:
  - `full_split`: full display; split long reference text instead of hiding or compacting.
  - `compact`: shorten when needed.
  - `hide_when_overflow`: hide overflowed reference text.
- Add a status/warning area for missing workflow profile metadata.
- Add a dedicated tab or sub-navigation for entity review if the output panel becomes too dense.

### `web/styles.css`

Suggested style changes:

- Keep layout work-oriented and dense.
- Reduce nested-card feel in the output/entity area.
- Use full-width bands or unframed sections for major output groups.
- Keep tables horizontally scrollable on narrow screens, but preserve readable column priority.
- Add visual warning states for config/profile mismatches.

### `workflow_profiles/ru_to_zh_default.json`

No change recommended for the current Russian style defaults.

Current values match the intended direction:

- `Huiwen-HKHei`
- `32`
- `80`
- `4`
- `1.2`
- `full_split`

One product decision remains:

- profile default `subtitle_mode` is `target_only`, while current `ui_config.json` uses `bilingual_source_reference`.
- Confirm whether Russian preset should default to bilingual reference output in the profile itself, or whether target-only should remain the durable profile default.

### `docs/russian_reference_layer_full_split_task.md`

Suggested docs cleanup:

- Mark the older `reference_mode = hide_when_overflow` paragraph as historical.
- Add a short "Current state" note pointing to `workflow_profiles/ru_to_zh_default.json`.

## Verification Steps

Run focused tests:

```powershell
pytest -q tests/test_workflow_profiles.py tests/test_ui_server_config.py tests/test_reference_mode_ui.py
```

Add and run a new partial-style regression test:

```powershell
pytest -q tests/test_ui_server_config.py
```

Restart the UI server before browser verification:

```powershell
python -m autosub_zh.ui_server
```

Then verify `/api/bootstrap` includes:

- `workflow_profiles`
- `active_prompt_profile`
- `active_dataset_profile`
- `config.workflow_profile = ru_to_zh_default`
- `config.style.reference_mode = full_split`

Browser verification:

1. Open `http://127.0.0.1:8777`.
2. Select or apply the Russian workflow.
3. Confirm visible style values:
   - `Huiwen-HKHei`
   - `32`
   - `80`
   - `4`
   - `1.2`
   - `full_split`
4. Save config.
5. Refresh.
6. Confirm the same values persist.
7. Open `entity_ui_fixture`.
8. Confirm the entity panel shows real metrics, review rows, QA rows, project decisions, and reference text comparison.
9. Check narrow width and desktop width.
10. Confirm there is no horizontal page-level overflow.

## User Confirmation Needed

Before implementation, confirm:

1. Should Russian `ru_to_zh_default.json` permanently default to `subtitle_mode = bilingual_source_reference`, or should it remain `target_only` while the local `ui_config.json` uses bilingual mode?
2. Should visible UI labels be changed from English-layer wording to reference-layer wording while keeping backend `en_*` keys unchanged?
3. Should the entity review become its own dedicated tab, or stay inside the output panel with clearer sections?
4. Should the mojibake UI text be repaired now, or handled as a separate cleanup task?
5. Should screenshots in `reports/frontend_entity_ui` be kept as evidence, or removed from the git working tree?
6. Should browser profile/cache output under `reports/edge-entity-ui-profile` be deleted and ignored?

## Git Working Tree Assessment

Current state:

- Branch: `main...origin/main [ahead 2]`
- Modified tracked files: 18
- Untracked files: 3062
- Untracked files under `reports/edge-entity-ui-profile`: 3039

### Keep or review as feature work

These appear related to real backend/frontend feature work and should not be deleted casually:

- `entity_normalization.py`
- `models.py`
- `pipeline_core.py`
- `qa.py`
- `qa_outputs.py`
- `segment_io.py`
- `subtitle_io.py`
- `workflow_profiles.py`
- `workflow_profiles/ru_to_zh_default.json`
- `ui_server.py`
- `web/app.js`
- `web/index.html`
- `web/styles.css`
- `tests/test_entity_normalization.py`
- `tests/test_entity_pipeline_contract.py`
- `tests/test_entity_pipeline_integration.py`
- `tests/test_qa_outputs.py`
- `tests/test_reference_layer_qa.py`
- `tests/test_reference_mode_ui.py`
- `tests/test_ui_server_config.py`
- `tests/test_subtitle_output_modes.py`
- `tests/test_workflow_profiles.py`
- `docs/entity_normalization_handoff.md`
- `docs/frontend_ai_optimization_prompt.md`
- `docs/frontend_handoff_and_project_status.md`
- `docs/frontend_ui_optimization_directions.md`
- `docs/russian_reference_layer_full_split_task.md`
- `docs/russian_reference_layer_full_split_todo.md`

### Keep, but probably separate from UI/entity work

These look useful but should likely be reviewed as a separate commit/topic:

- `downloaders.py`
- `yt_dlp_config.py`

Reason:

- They relate to downloader/import/auth behavior, not the frontend entity/reference information architecture.

### Remove from git working tree or ignore

These look like generated/runtime artifacts:

- `reports/edge-entity-ui-profile/`
  - 3039 untracked files
  - Edge/Chromium profile data, cache, extensions, Safe Browsing data, and browser runtime state
  - should not be committed
- `ui_server_error_trace.log`
  - already tracked, but behaves like a runtime log
  - consider removing from tracking in a separate cleanup if the project owner agrees

### Optional evidence artifacts

These may be useful for visual QA evidence, but should not be committed by default unless the owner wants report artifacts in git:

- `reports/frontend_entity_ui/*.png`
- `attachments/font_preview/russian_subtitle_fonts_preview.html`
- `attachments/font_preview/russian_subtitle_fonts_preview.png`
- the Huiwen HK Hei TTF under `attachments/font_preview/`

Note:

- The font file may be a required local asset or just test evidence. Confirm licensing and intended use before tracking it.

### Suspicious one-off helper

Review before keeping:

- `tools/fixes/fix_ru_xiu_xiu_title.py`

Reason:

- It appears to be a one-off repair script.
- It may be useful as a migration/debug helper, but it should not be committed without a clear purpose.

### `.gitignore` concern

Current `.gitignore` contains broad rules:

```text
*.json
*.srt
*.ass
```

Risk:

- New source/config JSON files can be silently hidden from `git status`.
- The project already intentionally tracks JSON files such as `workflow_profiles/*.json`.

Suggested cleanup after confirmation:

- Ignore generated JSON only under output/runtime paths.
- Keep source/config/test fixture JSON discoverable.
- Add explicit ignores for:
  - `reports/edge-entity-ui-profile/`
  - browser cache/profile directories
  - runtime logs, if agreed
