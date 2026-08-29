# Frontend Workflow, Outputs, Pause, and Input Panel Handoff

This handoff is for the next AI/developer who will implement the owner's requested frontend changes.

Important project rule:

- Do not directly modify frontend files until the owner confirms the plan.
- This document is the implementation brief and acceptance checklist.

## Owner Request

The owner asked for these changes:

1. Localize the **Workflow** frontend section into Chinese.
2. Explain the function of each Workflow frontend control and provide usage examples.
3. Optimize the **Project Outputs** frontend so opening that page only expands the currently selected project.
4. Add a **Pause Flow** button that pauses the whole translation pipeline, and a matching **Continue Translation** button.
5. Add a collapse button to the right-side/input area. When collapsed, show only the currently selected input. Default should be collapsed. After importing a new input, automatically show only the new input.
6. When clicking an item in the left project/input list, automatically jump/scroll to the lower detail/options area.
7. Generate this detailed handoff Markdown and provide a separate prompt for continuation.

## Current Frontend Structure

Main files:

- `src/autosub_zh/web/index.html`
- `src/autosub_zh/web/app.js`
- `src/autosub_zh/web/styles.css`
- `src/autosub_zh/ui_server.py`

Important current DOM IDs:

- Workflow:
  - `workflow_profile`
  - `subtitle_mode`
  - `source_reference_label`
  - `prompt_profile`
  - `dataset_profile`
  - `workflow_pair_preview`
  - `workflowProfileDescription`
  - `workflowPromptPreview`
  - `workflowDatasetPreview`
  - `applyRussianWorkflowBtn`
- Input:
  - `videoList`
  - `selectedVideoName`
  - `selectedVideoMeta`
  - `pickInputBtn`
  - `pickInputInlineBtn`
  - `scanInputBtn`
  - `inputAssStatus`
  - `reburnFromInputBtn`
- Outputs:
  - `projectList`
  - `entityReviewPanel`
  - `previewTitle`
  - `textPreview`
  - `videoPreview`
  - `learnStyleBtn`
  - `reburnFromAssBtn`
- Runtime:
  - `runBtn`
  - `previewBtn`
  - `phaseStatusList`
  - `stageFeed`
  - `queueList`
  - `runStatePill`
  - `currentStageLabel`
  - `currentStageDescription`
  - `overallProgressFill`

Important current functions in `src/autosub_zh/web/app.js`:

- `renderWorkflowProfiles()`
- `renderWorkflowSummary()`
- `applyWorkflowProfileSelection(profileId)`
- `syncSelectedVideo(videos)`
- `renderVideos(videos)`
- `syncSelectedProject(projects)`
- `renderProjects(projects)`
- `openFile(path, name)`
- `renderState(payload)`
- `runPipeline(previewSeconds)`
- `taskIsBusy(runtime)`
- `setTaskButtonsDisabled(disabled)`

Important current backend functions in `src/autosub_zh/ui_server.py`:

- `try_begin_task(...)`
- `execute_pipeline_job(...)`
- `append_history(...)`
- `update_runtime_meta(...)`
- `update_phase_status(...)`
- `/api/run`
- `/api/state`
- `/api/bootstrap`

## Proposed Information Architecture

### Workflow Section

Rename visible section text into Chinese:

- Tab: `工作流`
- Header: `工作流预设`
- Description: `选择语言方向、字幕输出模式、提示词和术语数据集。`
- Button: `套用俄文预设`

Keep technical values visible, but explain them in Chinese where useful.

Recommended layout:

- Row 1: workflow profile, subtitle mode, active pair
- Row 2: prompt profile, dataset profile, source reference label
- Summary block: effective config that will run
- Preview block: prompt preview and dataset preview

### Workflow Control Descriptions

Use these descriptions in a compact help area, tooltip, or a collapsible "字段说明".

#### Workflow

Meaning:

- Selects the language-specific pipeline preset.
- It can update source language, target language, ASR model, prompt profile, dataset profile, and style defaults.

Example:

- For Russian videos, choose `Russian to Chinese` / `ru_to_zh_default`.
- Expected effective config:
  - source language: `ru`
  - target language: `zh-Hans`
  - model: `large-v3`
  - reference mode: `full_split`

#### Subtitle Mode

Meaning:

- Controls what subtitle output the pipeline generates.

Options:

- `target_only`: Chinese-only subtitle output.
- `bilingual_source_reference`: Chinese subtitle plus source/reference layer.
- `source_review`: source-language review output.

Example:

- Use `bilingual_source_reference` when checking Russian source text against Chinese translation.
- Use `target_only` when producing a clean Chinese-only video.

#### Source Reference Label

Meaning:

- Label used for source/reference output naming and source-layer identity.

Example:

- Russian workflow should use `ru`.
- English workflow should use `en`.

#### Prompt Profile

Meaning:

- Selects the translation prompt template.
- This strongly affects translation style and language-specific rules.

Example:

- Russian-to-Chinese workflow should use `ru_zh_natural_subtitle`.
- English-to-Chinese workflow should use `en_zh_natural_subtitle`.

#### Dataset Profile

Meaning:

- Selects project or language-specific glossary, QA cases, ASR confusions, and style examples.

Example:

- Russian-to-Chinese workflow should use `ru_zh/general`.
- The dataset preview should show glossary file names and term counts.

#### Active Pair

Meaning:

- Read-only summary of source language, target language, and subtitle mode.

Example:

- `ru -> zh-Hans / bilingual_source_reference`

### Effective Workflow Summary

Add a compact summary card:

- `工作流`: label and id
- `语言方向`: `ru -> zh-Hans`
- `识别模型`: `large-v3`
- `字幕模式`: `bilingual_source_reference`
- `参考层`: `Huiwen-HKHei / 32 / 80 / 4 / full_split`
- `提示词`: `ru_zh_natural_subtitle`
- `数据集`: `ru_zh/general`
- `实体决策`: `bootstrap_entity_decisions`

Add warning chips:

- Russian workflow but reference style is not `Huiwen-HKHei / 32 / 80 / 4 / 1.2 / full_split`.
- Russian workflow but prompt or dataset is English.
- Workflow profile metadata failed to load.

## Project Outputs Optimization

Current behavior:

- `renderProjects(projects)` renders every project.
- Every project renders its nested file list.
- This makes the output page heavy and hard to scan.

Requested behavior:

- When opening the outputs page, only the currently selected project should be expanded.
- Other projects should appear as compact rows.

Implementation direction:

1. Track expanded project path in `state`, for example:

```js
expandedProjectPath: null
```

2. In `syncSelectedProject(projects)`:

- Keep existing selected project if possible.
- Set `state.expandedProjectPath = state.selectedProject?.path || null`.

3. In `renderProjects(projects)`:

- Render every project header.
- Render `fileList` only when `project.path === state.expandedProjectPath`.
- When a project is clicked:
  - set `selectedProject`
  - set `selectedFileProjectPath`
  - set `expandedProjectPath = project.path`
  - call `refreshEntityArtifactsForSelectedProject()`
  - call `renderProjects(state.projects)`
  - scroll/focus the detail area.

4. Add visual affordance:

- collapsed row: right chevron or `展开`
- expanded row: down chevron or `收起`

Acceptance criteria:

- Output page opens with only one project expanded.
- Selecting another project collapses the previous project and expands the new one.
- Selected file state remains visible if its project is selected.
- Entity panel updates to selected project.

## Project Click Scroll Behavior

Requested behavior:

- Clicking a project/input item on the left should automatically jump to the lower detail/options area.

Implementation direction:

- Add a stable target near the workspace/details section:

```html
<section class="workspace-card" id="workspaceDetails">
```

- Add helper in `src/autosub_zh/web/app.js`:

```js
function scrollToWorkspaceDetails() {
  el("workspaceDetails")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
```

- Call it after:
  - selecting an input video in `renderVideos`
  - selecting a project in `renderProjects`
  - optionally selecting a file in `openFile`

Risk:

- During task polling, repeated re-rendering should not keep forcing scroll.
- Only call the scroll helper from direct user click handlers, not from `renderState()`.

## Input Panel Collapse

Requested behavior:

- Add a collapse button to the input area.
- Default state: collapsed.
- Collapsed state shows only the currently selected input.
- Importing a new input should select the new input and keep the list showing only that new input.

Current behavior:

- `renderVideos(videos)` renders every input.
- New upload sets `state.selectedVideo = payload.video`.

Implementation direction:

1. Add state:

```js
inputListCollapsed: true
```

2. Add button in the input card header or toolbar:

```html
<button id="toggleInputListBtn" class="mini-btn" type="button">展开全部</button>
```

3. In `renderVideos(videos)`:

- If `state.inputListCollapsed` is true:
  - render only `state.selectedVideo` if available.
  - if no selected video, render first video or empty state.
- If false:
  - render all videos.

4. In upload/import flow:

- After `state.selectedVideo = payload.video`, set `state.inputListCollapsed = true`.
- Re-render videos.

5. In scan flow:

- If a new input appears and is selected, keep collapsed.
- If the user manually expands, do not collapse again unless importing a new video.

Acceptance criteria:

- On first page load, input list is collapsed.
- Only current input is shown.
- Toggle expands/collapses reliably.
- Importing a new file selects it and shows only that file.

## Pause and Continue Translation

This is the highest-risk item because it cannot be implemented correctly with frontend-only changes.

### Current backend limitation

The current backend starts a pipeline in a background thread through `/api/run`.

There is currently no true pause/resume mechanism:

- `execute_pipeline_job()` calls long-running functions directly.
- ASR, translation, FFmpeg burn, and entity/QA phases do not consistently check a pause token.
- Some work happens inside external processes or native libraries and cannot be safely paused mid-call.

### Recommended semantics

Use "cooperative pause" instead of trying to suspend the Python thread.

Meaning:

- User clicks **暂停流程**.
- Backend sets a pause flag.
- The running pipeline finishes its current safe unit of work.
- Before starting the next unit, it blocks in a `wait_if_paused()` helper.
- User clicks **继续翻译**.
- Backend clears the pause flag and the pipeline proceeds.

Do not use unsafe thread suspension.

### Backend design

Add shared control state:

```python
FLOW_CONTROL = {
    "pause_requested": False,
    "paused": False,
    "pause_reason": "",
}
FLOW_CONTROL_CONDITION = threading.Condition()
```

Add endpoints:

- `POST /api/pause`
- `POST /api/resume`

Add helper:

```python
def request_pause(reason: str = "") -> None:
    ...

def resume_flow() -> None:
    ...

def wait_if_paused(stage: str, payload: dict | None = None) -> None:
    ...
```

Expose state through `/api/state` and `/api/bootstrap`:

```json
"flow_control": {
  "pause_requested": true,
  "paused": true,
  "pause_reason": "user_requested"
}
```

Add pause checks between safe stages:

- before audio extraction
- before ASR
- after ASR before timing
- before translation chunk loop
- between translation chunks
- before display rewrite
- before span repair
- before entity normalization
- before ASS write
- before burn

For translation chunks, the best place is inside the loop that processes chunks. Add callback or control hook so it can pause between chunks.

For FFmpeg burn:

- Cooperative pause can only happen before starting burn.
- Mid-burn pause is not safe unless burn is refactored to controllable subprocess pause/resume, which is out of scope for this request.

For ASR:

- Pause before ASR starts and after ASR completes.
- Mid-ASR pause may not be reliable unless ASR loop already emits progress by chunks and can check the flag between chunks.

### Frontend design

Add buttons near run controls:

- `pauseFlowBtn`: `暂停流程`
- `resumeFlowBtn`: `继续翻译`

Behavior:

- Disable pause when no task is running.
- Show resume when pause is requested or paused.
- Disable run/preview while paused, same as while running.
- Runtime pill should show:
  - `暂停中`
  - `等待继续`

Frontend functions:

```js
function pauseFlow() {
  return fetch("/api/pause", { method: "POST", headers: {"Content-Type": "application/json"}, body: "{}" });
}

function resumeFlow() {
  return fetch("/api/resume", { method: "POST", headers: {"Content-Type": "application/json"}, body: "{}" });
}
```

Acceptance criteria:

- Clicking pause while running changes UI state to pause requested.
- Pipeline stops at the next safe checkpoint.
- Clicking continue resumes from that checkpoint.
- If pause is requested during FFmpeg burn, UI explains it will pause after the current non-interruptible step.
- No task is killed by pause.

### Risk

If a true hard pause is required for native ASR/FFmpeg/GPU operations, this becomes a larger architecture change. The safer first implementation is cooperative pause/resume.

## Suggested File Changes

### `src/autosub_zh/web/index.html`

Add:

- Chinese Workflow copy.
- Workflow help/usage panel.
- Effective workflow summary container.
- `pauseFlowBtn` and `resumeFlowBtn`.
- `toggleInputListBtn`.
- `workspaceDetails` anchor/id.
- Optional output project expand/collapse icon markup.

### `src/autosub_zh/web/app.js`

Add state:

```js
expandedProjectPath: null,
inputListCollapsed: true,
flowControl: {
  pause_requested: false,
  paused: false,
  pause_reason: "",
},
```

Modify:

- `renderWorkflowSummary()`
- `renderVideos(videos)`
- `renderProjects(projects)`
- `renderState(payload)`
- `setTaskButtonsDisabled(disabled)`
- upload/import handlers
- scan handler
- project/input click handlers

Add:

- `renderEffectiveWorkflowSummary()`
- `renderWorkflowHelp()`
- `toggleInputListCollapsed()`
- `scrollToWorkspaceDetails()`
- `pauseFlow()`
- `resumeFlow()`
- `renderFlowControlButtons()`

### `src/autosub_zh/web/styles.css`

Add styles for:

- workflow help panel
- effective workflow summary chips
- mismatch warnings
- project collapsed/expanded rows
- collapsed input list state
- pause/resume button states

### `src/autosub_zh/ui_server.py`

Add:

- flow control state
- `/api/pause`
- `/api/resume`
- flow control in state payload
- cooperative pause helper
- pause checkpoints in pipeline callback boundaries

May also require changes in:

- `src/autosub_zh/pipeline_core.py`
- `src/autosub_zh/translate.py`
- `src/autosub_zh/span_repair.py`
- `src/autosub_zh/media.py`

Only touch these if needed to add cooperative checkpoints.

## Verification Plan

Run existing tests:

```powershell
pytest -q tests/test_workflow_profiles.py tests/test_ui_server_config.py tests/test_reference_mode_ui.py
```

Add backend tests:

- pause endpoint sets pause flag
- resume endpoint clears pause flag
- state payload includes flow control
- pause request does not mark task complete or error

Add frontend/static tests:

- Workflow tab has Chinese labels.
- Pause/resume buttons exist.
- Input collapse button exists.
- `full_split` option still exists.
- Entity review panel still exists.

Browser verification:

1. Start UI server:

```powershell
python -m autosub_zh.ui_server
```

2. Open `http://127.0.0.1:8777`.
3. Confirm Workflow tab is Chinese.
4. Apply Russian workflow and check effective summary.
5. Expand/collapse input list.
6. Import a new input and confirm only new input is visible.
7. Open Project Outputs.
8. Confirm only selected project is expanded.
9. Click another project and confirm page scrolls to details.
10. Start a short preview.
11. Click Pause.
12. Confirm status changes to pause requested/paused.
13. Click Continue.
14. Confirm task proceeds and completes.

## Usage Examples for Workflow Section

### Example 1: Russian video with bilingual subtitles

Use when:

- Source video is Russian.
- You want Chinese subtitles plus Russian reference line.

Set:

- Workflow: `Russian to Chinese`
- Subtitle Mode: `bilingual_source_reference`
- Source Reference Label: `ru`
- Prompt Profile: `ru_zh_natural_subtitle`
- Dataset Profile: `ru_zh/general`
- Reference Mode: `full_split`

Expected result:

- `04_source_ru.srt`
- `06_translated_zh.srt`
- `08_bilingual_zh_ru.ass`
- `09_burned_bilingual_zh_ru_video.mp4`

### Example 2: Russian video with Chinese-only output

Use when:

- You do not need the Russian reference layer in final video.

Set:

- Workflow: `Russian to Chinese`
- Subtitle Mode: `target_only`

Expected result:

- Chinese-only ASS/video.

### Example 3: Reuse existing segments after a failed burn

Use when:

- Translation already exists.
- You only need to regenerate ASS/video.

Set:

- Enable `复用已有分段`.
- Disable `强制重翻译已有分段`.
- Keep the same workflow/profile.

Expected result:

- Pipeline skips ASR/translation when valid existing artifacts are present.
- It regenerates downstream QA/ASS/burn artifacts.

### Example 4: English video

Use when:

- Source video is English.

Set:

- Workflow: `English to Chinese`
- Source Reference Label: `en`
- Prompt Profile: `en_zh_natural_subtitle`
- Dataset Profile: `en_zh/general`

Expected result:

- English source SRT.
- Chinese translated SRT.
- Optional bilingual ASS with English reference line.

## Open Questions for Owner

1. For pause/resume, is cooperative pause acceptable, or do you expect hard pause inside ASR/FFmpeg/GPU work?
2. Should the Workflow help text always be visible, or hidden behind "字段说明" by default?
3. In Project Outputs, should the current selected project be the one matching selected input, or the last manually selected output project?
4. Should importing a new input also switch the workspace tab to recognition/settings automatically?
5. Should project click scroll to the whole workspace card, or specifically to the output preview/details area?
