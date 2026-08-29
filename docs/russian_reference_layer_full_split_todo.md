# Russian Reference Layer Full-Split Todo

## v0.1 planning

Status: complete

- [x] Read `docs/russian_reference_layer_full_split_task.md`.
- [x] Confirmed current subtitle/profile tests pass before implementation.
- [x] Identified main blocker: bilingual export does not enable long reference splitting by default.

Validation:

- `pytest -q tests/test_subtitle_output_modes.py tests/test_workflow_profiles.py` passed before edits.

## v0.2 core split

Status: complete

- [x] Add `full_split` reference mode behavior.
- [x] Generalize reference text splitting for Russian and English.
- [x] Ensure `full_split` auto-enables long reference splitting in bilingual ASS output.

Validation:

- `full_split` bypasses compact/hide overflow handling.
- Russian reference text uses punctuation/clause-aware splitting.
- Pipeline passes `src_lang` as the reference layer language.

## v0.3 UI/profile

Status: complete

- [x] Add `full_split` to the UI reference mode selector.
- [x] Update Russian workflow defaults.
- [x] Confirm profile round trip preserves `full_split`.

Validation:

- Russian profile now uses `reference_mode=full_split`, `en_font_name=Huiwen-HKHei`, `en_max_single_line_chars=52`, `en_max_split_parts=4`, and `min_split_duration=1.2`.
- UI selector exposes `full_split`.

## v0.4 QA/tests

Status: complete

- [x] Add focused tests for Russian full-split output.
- [x] Add regression coverage for existing subtitle output behavior.
- [x] Add QA coverage for hidden/ellipsized reference cues.

Validation:

- `pytest -q tests/test_subtitle_output_modes.py tests/test_workflow_profiles.py tests/test_reference_layer_qa.py tests/test_reference_mode_ui.py` passed.
- `pytest -q` passed.

## v0.5 60s verification

Status: complete

- [x] Run focused pytest suite.
- [x] Generate or inspect a 60s bilingual Russian ASS when feasible.
- [x] Record final validation notes and residual risks.

Validation:

- Generated `output/ru_xiu_xiu_preview_60s/08_bilingual_zh_ru_full_split_verify.ass`.
- 17 source segments produced 25 `EnglishSmall` reference lines; 9 source segments split into multiple groups.
- Hidden reference rows: 0.
- Ellipsis rows: 1, and it came from the original source segment text rather than formatting truncation.

Residual risks:

- Existing Russian ASR/normalization corruption remains visible in some source text; this task keeps text visible rather than repairing ASR content.
- The protected-title list is intentionally narrow and currently covers `Xiu Xiu: The Sent-Down Girl`.

## v0.6 density tuning

Status: complete

- [x] Increase Russian reference line density from 52 to 64 chars, then to 80 chars.
- [x] Reduce Russian reference font size to 32.
- [x] Regenerate 60s verification ASS.
- [x] Burn and open 60s verification video.

Validation:

- Generated `output/ru_xiu_xiu_preview_60s/08_bilingual_zh_ru_full_split_verify.ass` with `en_max_single_line_chars=80` and `en_font_size=32`.
- Burned and opened `output/ru_xiu_xiu_preview_60s/09_burned_bilingual_zh_ru_full_split_verify_60s.mp4`.
- 17 source segments produced 16 `EnglishSmall` reference lines; 0 source segments split into multiple groups.
- Hidden reference rows: 0.
- Ellipsis rows: 1, and it came from the original source segment text rather than formatting truncation.
- `pytest -q tests/test_workflow_profiles.py tests/test_subtitle_output_modes.py tests/test_reference_layer_qa.py tests/test_reference_mode_ui.py` passed.

## v0.7 permanent defaults

Status: complete

- [x] Keep Russian workflow profile defaults at `Huiwen-HKHei`, font size 32, line limit 80, split parts 4, min split duration 1.2, and `full_split`.
- [x] Update local UI config to open on the Russian workflow defaults instead of the older English compact reference settings.
- [x] Add UI config normalization coverage for Russian reference defaults.

Validation:

- `workflow_profiles/ru_to_zh_default.json` is the durable workflow default source.
- `ui_config.json` now uses `workflow_profile=ru_to_zh_default` with matching Russian reference-layer style defaults.
