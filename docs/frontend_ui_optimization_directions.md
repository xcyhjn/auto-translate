# Frontend UI Optimization Directions

This handoff is for the next AI or developer who takes over frontend work.

The project owner asked for this rule:

> If you find UI problems, do not directly modify the frontend. Write detailed frontend optimization directions in Markdown so another AI can continue safely.

Follow that rule unless the owner explicitly asks you to implement frontend changes.

## Current frontend truth

The frontend is a local control panel for a subtitle pipeline. It already has:

- Workflow profile selection.
- Recognition, translation, subtitle style, and output panels.
- A config save path through `ui_config.json`.
- Project artifact listing and preview.
- Some entity review UI code in `web/app.js`, `web/index.html`, and `web/styles.css`.
- A bootstrap entity mode selector in the translation settings.
- A `full_split` reference mode option in the subtitle style settings.

Do not assume the entity UI is complete just because the code exists. Verify it against real project artifacts.

## Important backend defaults to preserve

Russian video translation should now default to:

- `workflow_profile = ru_to_zh_default`
- `src_lang = ru`
- `dst_lang = zh-Hans`
- `model = large-v3`
- `prompt_profile = ru_zh_natural_subtitle`
- `dataset_profile = ru_zh/general`
- `subtitle_mode = bilingual_source_reference` for bilingual output work
- `source_reference_label = ru`
- `en_font_name = Huiwen-HKHei`
- `en_font_size = 32`
- `en_max_single_line_chars = 80`
- `en_max_split_parts = 4`
- `min_split_duration = 1.2`
- `reference_mode = full_split`

The durable source for these language defaults is:

- `workflow_profiles/ru_to_zh_default.json`

The local UI current config is:

- `ui_config.json`

When auditing the UI, confirm that profile switching and config save/reload do not accidentally replace these Russian defaults with global English subtitle defaults such as `Arial`, `compact`, or `78`.

## Known high-risk UI/config issue

The UI has two sources of style truth:

- Workflow profile style defaults.
- The saved current UI style in `ui_config.json`.

This can create a subtle bug:

- The user selects the Russian workflow.
- The backend has correct Russian style defaults.
- But the UI form still shows or saves older global/default English reference-layer values.

The next AI should verify this path carefully:

1. Start the UI.
2. Select **Russian Preset** or `ru_to_zh_default`.
3. Confirm the subtitle style form shows:
   - `Huiwen-HKHei`
   - font size `32`
   - line limit `80`
   - split parts `4`
   - min split duration `1.2`
   - reference mode `full_split`
4. Save config.
5. Refresh the UI.
6. Confirm the same values survive reload.

If this fails, document the failure first. Do not directly rewrite frontend files unless explicitly asked.

## Frontend audit questions

Answer these by inspecting the running UI and code:

- Does the workflow panel make the active workflow obvious?
- Does the UI clearly distinguish raw source text from normalized `reference_text`?
- Does the output panel show whether `00_entity_decisions.json` exists?
- Does the entity review panel read real files or only render empty placeholders?
- Can the user see rows from `06f_entity_review.tsv`?
- Can the user see rows from `07h_entity_qa.tsv`?
- Can the user see a useful summary from `07i_entity_metrics.json`?
- Does the bootstrap mode selector save and reload correctly?
- Does the subtitle style panel make `full_split` understandable enough for Russian reference text?
- Does the UI make it clear that English-labeled fields also control the Russian reference layer?

## Recommended optimization directions

### 1. Make workflow state unambiguous

Show the active workflow, source language, target language, subtitle mode, prompt profile, and dataset profile in one compact summary.

Why this matters:

- The UI can otherwise look like it is running Russian settings while still carrying an old saved English config.
- A human needs to know what will actually run before clicking preview or run.

Acceptance criteria:

- The workflow summary updates immediately after selecting a profile.
- The summary matches the form values that will be sent to `/api/run`.
- Saving and refreshing keeps the same visible workflow state.

### 2. Rename or explain reference-layer style controls

The current style fields are named like English subtitle controls, but Russian uses the same reference layer.

Recommended UI copy direction:

- Use “Reference layer font” instead of “English font.”
- Use “Reference line limit” instead of “English line limit.”
- Keep technical config keys unchanged in code unless a backend migration is planned.

Acceptance criteria:

- A Russian workflow user can understand that these fields control the Russian line.
- The UI still maps to `BilingualSubtitleStyle.en_*` fields internally.

### 3. Make Russian `full_split` visible as a strategy

For the Russian workflow, the UI should make `full_split` feel like the expected mode, not an obscure raw enum.

Recommended behavior:

- Show `full_split` in the selector.
- Add nearby short helper text or a compact status line:
  - “Full display: long reference text is split instead of hidden or ellipsized.”
- Avoid long explanatory blocks inside the app.

Acceptance criteria:

- The user can tell why `full_split` differs from `compact` and `hide_when_overflow`.
- The selector round-trips through save/reload.

### 4. Improve entity artifact review

The backend now produces several entity artifacts. The UI should make these first-class review surfaces.

Prioritize:

- `07i_entity_metrics.json`
- `06f_entity_review.tsv`
- `07h_entity_qa.tsv`
- `08b_ass_entity_audit.json`
- `00_entity_decisions.json`

Recommended layout:

- Entity summary cards at the top of the output panel.
- Review table for candidate rows.
- QA table for problems.
- Project decisions status chip.

Acceptance criteria:

- The UI shows counts from real artifacts.
- Missing artifacts are described clearly.
- Tables do not overflow badly on mobile.
- Opening the raw file is still available.

### 5. Add source/reference/target comparison

Expose three related fields together:

- Raw source text.
- Normalized reference text.
- Chinese target text.

Where to show it:

- Entity review panel.
- Debug/alignment preview.
- File preview helper views for normalized segment JSON.

Acceptance criteria:

- Reviewers can see what changed between `source_text` and `reference_text`.
- The UI does not hide `reference_text` when it matches source text, but can de-emphasize unchanged rows.

### 6. Separate execution controls from review surfaces

The UI should feel like a work tool:

- Pipeline controls belong in setup panels.
- Status/progress belongs in the top activity area.
- Review artifacts belong in output/review panels.

Avoid:

- Large decorative cards nested inside other cards.
- Marketing-style sections.
- Copy that explains obvious controls.

Acceptance criteria:

- The primary run/preview actions remain easy to find.
- Review sections are scannable without scrolling through every config field.
- The output panel can be used after a run without returning to setup panels.

## Verification checklist for the next AI

Run these checks after any frontend implementation:

```powershell
pytest -q test_workflow_profiles.py test_ui_server_config.py test_reference_mode_ui.py
```

Then verify in the browser:

- Load the local UI.
- Select the Russian workflow.
- Confirm the style values are `Huiwen-HKHei`, `32`, `80`, `4`, `1.2`, and `full_split`.
- Save config.
- Refresh.
- Confirm the values persist.
- Open a project with entity artifacts.
- Confirm entity metrics/review/QA surfaces show real data.
- Check the output panel at desktop and narrow widths.

## Suggested handoff prompt for implementation

Use this when asking another AI to implement the frontend work:

```text
Read docs/frontend_ui_optimization_directions.md first.
Do not start with cosmetic redesign.
Audit the current UI against the backend artifacts and Russian workflow defaults.
Implement the smallest frontend changes that make workflow state, reference-layer settings, and entity review artifacts clear.
Verify in the in-app browser and run the focused tests listed in the document.
```

## Do not change without explicit approval

- Do not rename backend config keys such as `en_font_name` or `en_max_single_line_chars`.
- Do not remove English workflow support.
- Do not remove `compact` or `hide_when_overflow`.
- Do not flatten or delete existing output artifacts.
- Do not rewrite the whole frontend in a new framework.
- Do not directly edit UI files when the owner has only asked for optimization directions.
