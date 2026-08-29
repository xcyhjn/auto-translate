# Subtitle Segmentation Ops Log

## 2026-06-17 00:05 +08:00 - Baseline Audit

What:

- Audited `08_bilingual_zh_en.ass`, `03_timed_source_segments.json`, and `04a_source_spans.json`.
- Reviewed `src/autosub_zh/timing.py`, `src/autosub_zh/source_spans.py`, `src/autosub_zh/models.py`, and `src/autosub_zh/pipeline_core.py`.

Why:

- Establish the real failure modes before changing code.

Result:

- Baseline timed source metrics:
  - 833 segments
  - 106 cues with <=5 words
  - 183 <=8-word open fragments
  - 89 mixed-sentence-like cues
  - 256 function-edge cues
- Confirmed root cause in timing order: pause split -> duration split -> display split.

Rollback:

- None.

Next:

- Implement sentence-first timing refinement.

## 2026-06-17 00:18 +08:00 - First Strategy Pass

Hypothesis:

- Most bad fragments come from conservative sentence splitting and aggressive display/max-duration splitting.

What:

- Added new `SubtitleRules` tuning fields.
- Added sentence terminal helpers, orphan detection, adjacent fragment merging, natural duration split scoring, and display split penalties.
- Preserved ASR timing in final cleanup instead of forcing 2-second cue duration.

Result:

- First validation improved short fragments but over-merged some short complete sentences.
- Metrics from first probe:
  - 536 segments
  - 14 cues with <=5 words
  - 5 <=8-word open fragments
  - 72 mixed-sentence-like cues
  - 26 cues longer than 6.5s

Failure analysis:

- Merge logic treated short complete sentences as orphan fragments and merged them into previous sentences.
- Duration tolerance was too loose after merging.

Rollback:

- No rollback. Adjusted in second pass.

Next:

- Protect short complete sentences and split mixed sentence segments explicitly.

## 2026-06-17 00:28 +08:00 - Second Strategy Pass

Hypothesis:

- Short complete sentences should remain independent unless a rendering-only layer later decides otherwise.

What:

- Stopped merging when the left segment ends in a terminal and the right looks like a new sentence.
- Added `split_segment_on_sentence_boundaries()` and ran it after merge and display passes.
- Tightened merge duration cap.

Result:

- Metrics:
  - 618 segments
  - 64 cues with <=5 words
  - 8 <=8-word open fragments
  - 7 mixed-sentence-like cues
  - 0 cues longer than 6.5s

Failure analysis:

- Much better, but complete sentences just over 6.5s could still be unnecessarily split.
- Some sentence-boundary threshold logic used word count where visible text length was intended.

Rollback:

- No rollback. Adjusted in third pass.

Next:

- Add small complete-sentence duration tolerance and fix boundary threshold.

## 2026-06-17 00:36 +08:00 - Third Strategy Pass

Hypothesis:

- A complete sentence at about 6.6-6.9s is often better than splitting into unnatural open clauses, if CPS is acceptable.

What:

- Added `complete_sentence_duration_tolerance = 0.45`.
- Allowed complete terminal segments to exceed max duration slightly.
- Fixed sentence-boundary split threshold to use text length.
- Added source span detection for `short_open_fragment` and `internal_sentence_boundary`.

Result:

- Final preview metrics:
  - 620 segments
  - 66 cues with <=5 words
  - 9 <=8-word open fragments
  - 5 mixed-sentence-like cues
  - 115 function-edge cues
  - 0 cues > 6.95s
  - 22 cues < 1.0s
- Source span preview:
  - 150 spans
  - 84 span_first
  - 62 span_context
  - 4 normal

Rollback:

- None.

Next:

- Write handoff docs, generate preview artifacts, and commit only task-related files.

## 2026-06-17 00:40 +08:00 - Preview Artifact Generation

What:

- Generated segmentation preview JSON/ASS and metrics:
  - `output\Russian-book-about-a-dying-god\03_timed_source_segments.segmentation_preview.json`
  - `output\Russian-book-about-a-dying-god\04a_source_spans.segmentation_preview.json`
  - `output\Russian-book-about-a-dying-god\08_bilingual_zh_en.segmentation_preview.ass`
  - `output\Russian-book-about-a-dying-god\segmentation_preview_metrics.json`

Why:

- Verify the changed timing layer without overwriting official pipeline outputs.

Result:

- English segmentation improved substantially.
- Preview Chinese text shows repetition where old Chinese cues overlap new English segments, confirming final Chinese should be regenerated or redistributed semantically rather than copied mechanically by time overlap.

Rollback:

- None.

Next:

- Run compile checks, inspect git status, stage only owned files, commit.

## 2026-06-17 00:46 +08:00 - Final Verification

What:

- Ran `python -m py_compile` for `src/autosub_zh/models.py`, `src/autosub_zh/timing.py`, `src/autosub_zh/source_spans.py`, and `tests/test_timing_segmentation.py`.
- Ran `pytest -q tests/test_timing_segmentation.py`.
- Removed preview Chinese example fields from `segmentation_preview_metrics.json` so the metrics file only carries English segmentation evidence.

Why:

- Confirm the code changes are syntactically valid and the key timing behaviors stay pinned by tests.

Result:

- `pytest` passed: `3 passed in 0.04s`
- Preview metrics file now contains only English sample rows plus a note that the Chinese preview ASS is overlap-based and not final translation output.

Rollback:

- None.

Next:

- Stage only the segmentation-related files and create a focused git commit.

## 2026-06-17 01:25 +08:00 - Semantic QA Phase 2 Start

What:

- Started phase 2 implementation for Chinese semantic allocation, display-only short sentence grouping, ASR repair candidates, and frontend QA visualization.
- Added `docs/subtitle_semantic_qa_plan.md`.
- Captured a pre-change diff snapshot at `%TEMP%\autosub_pre_semantic.diff` because the worktree already contained unrelated edits.

Why:

- The previous English timing pass improved ASR cue shape, but Chinese still needed a semantic redistribution layer and the UI needed visible QA metrics.

Result:

- Plan is now documented before code changes.
- Implementation will avoid reverting existing unrelated dirty files.

Rollback:

- None.

Next:

- Implement backend QA artifacts, then wire the frontend panel and tests.

## 2026-06-17 02:05 +08:00 - Phase 2 Backend and First Sample Validation

What:

- Added `src/autosub_zh/semantic_allocation.py` and `src/autosub_zh/segmentation_qa.py`.
- Updated `src/autosub_zh/source_repair.py`, `src/autosub_zh/zh_reading_axis.py`, `src/autosub_zh/subtitle_io.py`, `src/autosub_zh/pipeline_core.py`, `src/autosub_zh/pipeline_runner.py`, and `src/autosub_zh/ui_server.py`.
- Added `tests/test_semantic_qa_phase2.py`.
- Wired the frontend QA panel in `src/autosub_zh/web/index.html`, `src/autosub_zh/web/app.js`, and `src/autosub_zh/web/styles.css`.
- Regenerated Russian sample QA artifacts:
  - `02b_asr_source_repair_candidates.json`
  - `05a_semantic_allocated_segments.json`
  - `05a_semantic_allocation_report.json`
  - `07j_segmentation_qa_metrics.json`
  - `08_bilingual_zh_en.segmentation_preview.ass`

Why:

- Make the phase-2 semantic allocation and QA outputs visible end to end, not just described in docs.

Result:

- Tests passed on the first implementation batch.
- Sample metrics exposed real remaining issues:
  - `short_fragment_count = 27`
  - `mixed_sentence_count = 89`
  - `function_edge_count = 339`
  - `semantic_review_count = 13`
  - `display_group_count = 0`
- This showed the first pass was working, but `function_edge_count` was too broad and needed tightening.

Rollback:

- None.

Next:

- Tighten QA edge rules and repair candidate logic, then rerun the sample.

## 2026-06-17 02:28 +08:00 - QA Rule Tightening Pass

What:

- Narrowed `function_edge_count` so it no longer flags normal terminal sentences.
- Split function-edge detection into start-continuation and end-function-word checks.
- Reduced ASR repair noise:
  - removed plain `it` / `uri` from the open-ended fragment detector
  - added `a.m.` / `p.m.` / title abbreviation guards
  - changed `source_repair.review_count` to count only high-confidence candidates
- Added regression coverage for safe time abbreviations.

Why:

- The first sample validation showed the metrics were still too noisy and were overstating QA risk on normal English punctuation patterns.

Result:

- Relevant tests still passed after tightening.
- Russian sample metrics improved:
  - `function_edge_count` dropped from `339` to `116`
  - `candidate_count` dropped from `172` to `170`
  - `review_count` dropped from `172` to `87`
  - `blocking_issue_count` dropped from `455` to `232`
- `display_group_count` remained `0`, which is expected for this sample because no short complete-sentence pair satisfied the conservative grouping rules.

Rollback:

- None.

Next:

- Run browser QA on the live UI and confirm the new subtitle QA panel, artifact links, and responsive layout.

## 2026-06-17 02:44 +08:00 - Frontend QA Verification

What:

- Opened the live UI at `http://127.0.0.1:8777`.
- Verified the new "字幕 QA" panel under "项目产物".
- Confirmed Russian sample project renders:
  - metric cards
  - sample rows
  - artifact links
- Checked breakpoints at `375px`, `768px`, `1280px`, and `1920px`.
- Fixed `escapeHtml(0)` so zero-valued QA metrics render correctly.

Why:

- The second phase is only useful if the new QA outputs are actually legible in the product UI, not just present on disk.

Result:

- Russian QA panel shows:
  - `短残片 27`
  - `混句 89`
  - `function 边界 116`
  - `语义分配复核 13`
  - `ASR 候选 170`
  - `ASR 复核 87`
  - `短句合屏 0`
- Responsive checks:
  - no horizontal overflow
  - body font stays at `16px`
  - sampled buttons are at least `46px` tall
- One UI nuance remains: the sticky command bar can obscure project cards while scrolling if the project list is not positioned carefully. The UI is usable, but this is the main residual frontend polish item.

Rollback:

- None.

Next:

- Finish git staging with only task-related files and commit the phase-2 bundle.

## 2026-06-17 03:20 +08:00 - Orphan Terminal Tail Fix, First Pass

Hypothesis:

- The `franchise.` failure came from terminal punctuation blocking the existing orphan merge path. If a right cue is only 1-2 words and completes an open previous cue, it should be absorbed even when it ends in `.` / `!` / `?`.

What:

- Added terminal orphan-tail detection in `src/autosub_zh/timing.py`.
- Made `should_merge_adjacent()` merge open-left + terminal orphan tail before the normal sentence-terminal guard.
- Added strong display split penalties so DP avoids creating a 1-2 word sentence tail.
- Added display-only `merge_orphan_tail_display_cues()` before ASS writing.
- Added QA metrics:
  - `orphan_terminal_tail_count`
  - `orphan_terminal_tail_samples`
- Added frontend QA card: `孤立句尾词`.
- Added focused unit tests for:
  - `video game` + `franchise.`
  - long gap not force-merged
  - `Hello.` / `Goodbye.` not merged
  - display-layer Chinese cleanup from `电子游戏。系列。` to `电子游戏系列。`

Result:

- Targeted tests passed.
- Russian sample ASS changed the reported case to one cue:
  - `that was made into an even more famous video game franchise.`
- `07j_segmentation_qa_metrics.json` reported `orphan_terminal_tail_count = 0`.

Failure analysis:

- Wider sample audit still found `market.` as a one-word tail after `property.`. This was caused by raw ASR adding a suspicious period to the previous cue, so the first pass did not treat the previous cue as open.

Rollback:

- None. Continued with a second pass.

Next:

- Handle suspicious closed-left tails where the previous cue is long enough and the right cue begins lowercase.

## 2026-06-17 03:45 +08:00 - Orphan Terminal Tail Fix, Second Pass

Hypothesis:

- Some one-word tails survive because ASR puts a terminal period before the final word, e.g. `property.` + `market.`. These should be merged only when the tail begins lowercase, the gap is short, and the previous cue has enough words to avoid swallowing true short sentences.

What:

- Extended `can_absorb_terminal_orphan_tail()` with `allow_closed_left=True`.
- Allowed suspicious closed-left merges only when:
  - previous cue has at least 4 source words
  - right tail has 1-2 words
  - right tail begins lowercase
  - gap <= `strong_pause_split_threshold`
  - merged duration and length stay within conservative tolerance
- Added English cleanup:
  - `property. market.` -> `property market.`
- Added Chinese cleanup:
  - removes duplicate short tail sentence only when the tail text already appears earlier in the merged Chinese cue
- Expanded `src/autosub_zh/segmentation_qa.py` so suspicious closed-left lowercase tails also count as blockers if they remain.
- Added regression tests for:
  - `property.` + `market.`
  - display cleanup for duplicate Chinese tail
  - preserving real short complete sentences.

Result:

- `pytest -q tests/test_timing_segmentation.py tests/test_semantic_qa_phase2.py tests/test_zh_reading_axis.py tests/test_subtitle_output_modes.py tests/test_asr_repair_flow.py`
  - `38 passed in 0.37s`
- Russian sample regenerated from existing `05_translated_segments.json`:
  - `orphan_tail_group_count = 20`
  - `orphan_terminal_tail_count = 0`
- ASS spot checks:
  - `that was made into an even more famous video game franchise.`
  - `These are rare, have tall ceilings and go for a lot of money on the property market.`
- Remaining 1-2 word terminal cues are uppercase independent/proper-name-like cases, not open-tail cases.

Rollback:

- None.

Next:

- Keep the QA card visible in the frontend and commit only task-related files. Remaining non-orphan segmentation blockers should be handled in a separate pass.

## 2026-06-17 04:10 +08:00 - Discourse Particle Protection, First Pass

Hypothesis:

- The orphan-tail fix should not swallow real standalone response particles such as `Yeah.` / `No.` / `Oh.` / `Well.`. These cues deserve their own classification instead of being treated as content tails.

What:

- Added `src/autosub_zh/terminal_tail.py` as a shared classifier for short terminal cues.
- Split terminal short cues into:
  - `content_tail`
  - `standalone_particle`
  - `ambiguous_particle`
- Wired the classifier into:
  - `src/autosub_zh/timing.py`
  - `src/autosub_zh/zh_reading_axis.py`
  - `src/autosub_zh/segmentation_qa.py`
  - `src/autosub_zh/web/app.js`
- Added tests for:
  - `I don't know. / Yeah.`
  - `Are you coming? / No.`
  - `The answer is / no.`
  - `I guess. / Right?`

Result:

- Targeted tests passed.
- Wider regression suite passed:
  - `45 passed`
- Russian sample regenerated successfully with:
  - `orphan_terminal_tail_count = 0`
  - `standalone_discourse_particle_count = 0`
  - `ambiguous_discourse_tail_count = 0`

Failure analysis:

- The sample did not contain many strong discourse-particle examples, so the new counters stayed at zero in that corpus. That is acceptable; the classifier is still validated by unit tests.

Rollback:

- None.

Next:

- Keep the docs and logs aligned with the new classifier and commit only the task-related files.

## 2026-06-17 04:22 +08:00 - English Residue Scoring And Strict Chinese Localization

Hypothesis:

- English residue in Chinese subtitles should not be controlled by prompt wording alone. A shared scorer can decide whether each Latin span is allowed to remain, and low-score residue should block translation repair instead of becoming passive QA noise.

What:

- Added `src/autosub_zh/english_residue_policy.py`.
- Added scoring categories for:
  - explicit hard preserve
  - code/path/software identifiers
  - auto glossary soft preserve
  - proper names
  - common translatable places/languages/history terms
  - function/discourse words
- Wired the scorer into:
  - `src/autosub_zh/translate.py`
  - `src/autosub_zh/span_translate.py`
  - `src/autosub_zh/qa.py`
  - `src/autosub_zh/pipeline_core.py`
  - `src/autosub_zh/entity_normalization.py`
  - `src/autosub_zh/qa_outputs.py`
  - `src/autosub_zh/web/app.js`
- Added `07k_english_residue_report.json` and `07k_english_residue_review.tsv`.
- Added frontend cards and review table entries for English residue metrics.

Self-correction:

- First pass treated all glossary `policy=preserve` terms as hard preserve.
- Russian sample showed auto-generated glossary entries such as `Dmitri`, `Moscow`, `God`, and `Yuri Andreevich Knorosov` would be over-preserved.
- Revised policy:
  - common translatable names/places/ordinary words override auto preserve
  - ASR/Youtube auto preserve becomes `glossary_soft_preserve`
  - only hard/manual preserve stays 100
  - code/identifier-like terms such as `L5` can still preserve

Validation:

- `python -m py_compile src/autosub_zh/english_residue_policy.py src/autosub_zh/translate.py src/autosub_zh/span_translate.py src/autosub_zh/qa.py src/autosub_zh/qa_outputs.py src/autosub_zh/entity_normalization.py src/autosub_zh/pipeline_core.py src/autosub_zh/pipeline_runner.py src/autosub_zh/ui_server.py`
- `node --check web\app.js`
- `pytest -q tests/test_english_residue_policy.py tests/test_qa_outputs.py tests/test_entity_pipeline_contract.py tests/test_entity_pipeline_integration.py tests/test_workflow_profiles.py tests/test_ui_server_config.py`
  - `23 passed in 0.63s`
- Offline Russian sample scoring from existing `05_translated_segments.json`:
  - `english_residue_total_count = 224`
  - `english_residue_blocking_count = 222`
  - `english_residue_review_count = 1`
  - `english_residue_preserved_count = 1`
  - preserved sample: `L5` as `code_or_identifier`

Rollback:

- None.

Next:

- Re-run translation with the strict scorer enabled so low-score English residue triggers model repair.
- Add project-specific `00_entity_decisions.json` or glossary `policy=translate` entries for recurring names if automatic transliteration is not stable enough.

## 2026-06-17 06:45 +08:00 - Strict English Residue ASS Regeneration

Hypothesis:

- A full translation rerun with strict English residue validation should remove person/place/language English leftovers from Chinese subtitles while preserving only high-score identifiers such as model numbers.

What:

- Installed local `pytest` with `python -m pip install --user pytest`.
- Fixed preserve-only glossary matching in `src/autosub_zh/translate.py`:
  - before: `translation.` could match auto glossary phrase `The Translation Follows`
  - after: preserve-only shortcut requires exact normalized match
- Fixed terminology short-circuit in `src/autosub_zh/terminology.py`:
  - pure term cues no longer lock auto-discovered `policy=preserve` names unless the residue scorer says `decision=preserve`
  - `Juan Kokom.` now goes through translation instead of becoming `Juan Kokom`
- Fixed `src/autosub_zh/english_residue_policy.py` extraction:
  - pure English target cues are now scored, not only mixed Chinese+Latin lines
- Added tests:
  - `test_preserve_only_translation_requires_exact_normalized_match`
  - `test_translate_validation_blocks_pure_low_score_person_name`
  - `tests/test_terminology_short_circuit.py`

Self-correction:

- First regeneration failed because `translation.` was polluted by auto glossary `The Translation Follows`.
- Second regeneration showed span translation/terminology locks could bypass strict validation.
- Third regeneration showed pure English `Juan Kokom.` was not extracted as residue because the extractor required Chinese text.
- Final regeneration resumed from checkpoint after a network SSL EOF at chunk 30/35; completed chunks 1-29 were reused and only chunks 30-35 were rerun.

Validation:

- `python -m pytest tests/test_english_residue_policy.py tests/test_terminology_short_circuit.py -q`
  - `12 passed`
- Generated:
  - `output/Russian-book-about-a-dying-god/08_bilingual_zh_en.english_residue_strict.ass`
- ASS checks:
  - Chinese `Default` rows: `813`
  - English `EnglishSmall` rows: `813`
  - Chinese-layer Latin residue count: `1`
  - only remaining Chinese-layer Latin sample: `L5`
  - standalone English `franchise.` cue count: `0`
  - `video game franchise.` now appears as one English cue from `0:01:37.67` to `0:01:42.37`
- `07k_english_residue_report.json`:
  - `english_residue_total_count = 1`
  - `english_residue_blocking_count = 0`
  - `english_residue_preserved_count = 1`
  - `english_residue_review_count = 0`
  - `pass = true`
  - preserved item: `L5`, category `code_or_identifier`, score `94`

Rollback:

- None.
- Original/default ASS was backed up during generation under timestamped `08_bilingual_zh_en.pre_strict_residue_*.ass` files.

Next:

- Consider making `span_translation_max_spans=0` unnecessary by validating span-locked translations before they enter `locked_translation_ids`.
- Consider deleting old timestamped generation backups after manual review if disk clutter matters.

## 2026-06-17 08:20 +08:00 - Span Pretranslation Narrowing

Hypothesis:

- Span pretranslation should be an exception path. The Russian sample had 144 `span_first` spans because `open_clause` and `short_open_fragment` were enough to trigger span-first; long 8-segment/20s spans made the workflow slow and fragile.

What:

- Tightened `src/autosub_zh/source_spans.py` so `span_first` now requires:
  - segment count <= 4
  - duration <= 12s
  - risk score >= 10
  - a strong reason such as repeated short phrase, ASR suspicion, or function-word boundary plus continuation.
- Changed long or ordinary open-fragment spans to `span_context` instead of `span_first`.
- Added span translation selection caps in `src/autosub_zh/span_translate.py`:
  - `max_segments_per_span = 4`
  - `max_duration = 12.0`
  - `min_risk_score = 10`
- Reduced default `span_translation_max_spans` from 16 to 4 in pipeline/UI config.
- Synced the frontend translation settings form so it exposes the new max segments, max duration, and min risk fields instead of silently submitting old defaults.
- Added `source_spans_v2` policy version; stale `04a_source_spans.json` is recomputed before span translation/allocation.
- Added `span_translation_v2` fingerprint to `05a_span_translated_segments.json`; checkpoint reuse now depends on source text/timing, source spans, glossary, style prompt, model, residue policy, and span selection config.
- Fixed `force_retranslate_existing_segments=True` so it no longer reuses the span checkpoint.
- Added `tests/test_span_translation_flow.py`.

Self-correction:

- First pass used `min_risk_score = 30`, which reduced the Russian sample to `span_first = 0`. That was too aggressive because current risk scores are on a lower scale.
- Adjusted the threshold to `10`; the sample now keeps only the short high-risk cases and blocks long span pretranslation.

Validation:

- `python -m py_compile src/autosub_zh/source_spans.py src/autosub_zh/span_translate.py src/autosub_zh/pipeline_core.py src/autosub_zh/pipeline_runner.py src/autosub_zh/ui_server.py`
- `$env:PYTHONPATH='D:\'; python -m pytest tests/test_span_translation_flow.py tests/test_terminology_short_circuit.py tests/test_english_residue_policy.py tests/test_semantic_qa_phase2.py -q`
  - `30 passed in 0.34s`
- `node --check web\app.js`
- `$env:PYTHONPATH='D:\'; python -m pytest tests/test_span_translation_flow.py tests/test_ui_server_config.py -q`
  - `10 passed in 0.31s`
- Offline Russian sample source-span recalculation from current `03_timed_source_segments.json`:
  - before: `span_first_count = 144`
  - after: `span_first_count = 3`
  - after: `span_context_count = 160`
  - after candidate budget 16 still yields only 3 candidates
  - max span-first duration: `11.56s`
  - max span-first segment count: `4`

Rollback:

- None.

Next:

- Convert span pretranslation outputs from immediate locks into QA-gated proposals.
- Add real child-span splitting for long spans if a later workflow needs span-first translation instead of context-only handling.

## 2026-06-17 08:45 +08:00 - Proxy/Youtube Diagnostics

Hypothesis:

- The UI proxy test and YouTube cover/info fetch were failing without enough detail because proxy validation and downstream errors were too opaque.

What:

- Inspected `src/autosub_zh/ui_server.py`, `src/autosub_zh/youtube_meta.py`, and the frontend YouTube/proxy status render path.
- Found the active `ui_config.json` had `proxy_url` set to a YouTube video URL: `https://www.youtube.com/watch?v=VWPkTdC488o`.
- Added proxy URL validation so web-page URLs, missing ports, query strings, and unsupported schemes are rejected before they are passed to `yt-dlp` or `httpx`.
- Enhanced proxy diagnostics:
  - reports proxy socket errors
  - probes both `https://www.youtube.com` and `https://i.ytimg.com/...`
  - includes `exception_type`, `raw_error`, `active_proxy_url`, and `proxy_validation_error`
- Enhanced YouTube info/cover API errors with operation, proxy mode, proxy URL, exception type, raw detail, and traceback.
- Enhanced `src/autosub_zh/youtube_meta.py` errors so `yt-dlp` and cover download failures include whether a proxy was used.
- Cover fallback now reports both the primary thumbnail failure and fallback URL failure.
- Added `tests/test_proxy_youtube_diagnostics.py`.

Validation:

- `$env:PYTHONPATH='D:\'; python -m pytest tests/test_proxy_youtube_diagnostics.py -q`
  - `4 passed`
- `python -m py_compile src/autosub_zh/ui_server.py src/autosub_zh/youtube_meta.py`
- `node --check web\app.js`
- Live local proxy diagnostic with the current bad config now reports:
  - `proxy_validation_error = Proxy URL looks like a web page, not a proxy endpoint...`
  - `active_proxy_url = ""`
  - direct YouTube page/image probes returned `200`

Rollback:

- None.

Next:

- In the UI, replace the proxy field value with an actual proxy endpoint such as `http://127.0.0.1:7890`.

## 2026-06-17 09:35 +08:00 - Bilibili Duplicate Search

Hypothesis:

- Before translating a YouTube video, the user needs a non-blocking way to check whether a Chinese translation or repost already exists on Bilibili.
- Searching only the original English title is too brittle because Bilibili titles are often translated, shortened, or rewritten.

What:

- Audited the current YouTube metadata path:
  - `/api/youtube-meta` and `/api/youtube-cover` call `youtube_info_job()` / `youtube_assets_job()`.
  - `src/autosub_zh/youtube_meta.py` reads metadata through `yt-dlp`, writes `00_youtube_meta.json` and `00_youtube_info.txt`.
  - `src/autosub_zh/ui_server.py` writes `10_youtube_manifest.json`; the frontend stores the response in `state.youtubeMeta` and renders `youtubeMetaCard`.
- Audited proxy flow:
  - `proxy_url` is normalized and validated in `src/autosub_zh/ui_server.py`.
  - valid proxies flow into `yt-dlp` as `options["proxy"]`.
  - `httpx.Client` receives `proxy=proxy_url` and disables `trust_env` when a proxy is explicitly set.
- Audited output tree flow:
  - `read_output_tree()` scans `output/*`, reads `10_manifest_bilingual.json` when present, and sends projects to the frontend bootstrap/state payloads.
  - YouTube metadata assets use a separate `10_youtube_manifest.json` in the same output tree.
- Checked for existing Bilibili search/download code:
  - no existing Bilibili search module was found; the new boundary is isolated in `src/autosub_zh/bilibili_search.py`.
- Added rule-based Bilibili duplicate search:
  - query plan generation
  - lightweight search page requests
  - HTML/embedded JSON parser with manual search URL fallback
  - explainable scoring
  - JSON/TSV/query artifacts
- Added `POST /api/bilibili-duplicate-search`.
- Added frontend button and status card near the YouTube metadata area.
- Added tests for query generation, scoring, parsing fallback, and API schema/proxy validation.

Self-correction:

- First test pass exposed that `Russian book dying god` was deduped away by the earlier lowercase core English query.
- Reordered semantic variants before the generic core English query so the intended mixed query survives.
- First duration boundary used `< 90s`; changed it to `<= 90s` so a 1:30 clip is treated as too short for a 20-minute source.

Validation:

- `pytest tests/test_bilibili_query_plan.py tests/test_bilibili_candidate_scoring.py tests/test_bilibili_search_parsing.py tests/test_ui_server_bilibili_api.py`
  - first pass: 2 failures, then corrected query ordering and duration boundary
  - final pass: `9 passed`
- final rerun: `9 passed in 1.29s`
- `python -m py_compile src/autosub_zh/bilibili_search.py src/autosub_zh/ui_server.py`
- `node --check web\app.js`
- Live API request through `POST /api/bilibili-duplicate-search` with fixed YouTube metadata:
  - `ok = true`
  - `decision = no_candidates_manual_review`
  - wrote `00b_bilibili_duplicate_search.json`, `00b_bilibili_duplicate_candidates.tsv`, and `00b_bilibili_search_queries.json`
- Browser UI verification:
  - button exists and is unique.
  - real click at 1280x720 triggered the API and rendered the Bilibili status card.
  - current saved config still has a bad proxy URL, so the card correctly showed the structured proxy validation error.
  - locator clickability checked at 375, 768, 1280, and 1920 px widths with no horizontal overflow.
- Fixed an existing sticky topbar overlap at medium widths, where the command bar could cover the YouTube/Bilibili controls at 1280x720.

Rollback:

- Remove `src/autosub_zh/bilibili_search.py`, the `/api/bilibili-duplicate-search` branch, frontend Bilibili card/button code, and the `00b_*` artifacts.

Next:

- Optional: replace the saved proxy field with a real proxy endpoint, or leave it blank for direct Bilibili checks.

## 2026-06-17 08:55 +00:00 - Bilibili Search State Label Fix

Observation:

- The UI card showed `检测失败，可手动复核` for `Russian book about a dying god`.
- The written report showed the search did run:
  - six queries had `ok = true`
  - each parsed `0` candidates
  - the seventh query was skipped by the 45s total timeout
- That means the correct state is not total failure; it is "searched, no parseable candidates".

What:

- Added `search_summary` to Bilibili duplicate reports:
  - attempted query count
  - successful query count
  - parsed candidate count
  - manual fallback query count
  - error count
  - searched flag
- Changed decision logic:
  - no successful searches + error => `search_unavailable_manual_review`
  - at least one successful search + no candidates => `no_candidates_search_completed`
- Updated the frontend card text to show searched query counts and parsed candidate counts while keeping manual search links.
- Added a regression test for partial timeout after successful empty searches.

Validation:

- `pytest tests/test_bilibili_query_plan.py tests/test_bilibili_candidate_scoring.py tests/test_bilibili_search_parsing.py tests/test_ui_server_bilibili_api.py`
  - `10 passed in 1.29s`
- `python -m py_compile src/autosub_zh/bilibili_search.py src/autosub_zh/ui_server.py`
- `node --check web\app.js`
- Live API request after restarting UI server on port 8790:
  - `decision = no_candidates_search_completed`
  - `searched = true`
  - `successful_query_count = 7`
  - `parsed_candidate_count = 0`

## 2026-06-17 18:30 +08:00 - Bilibili Title-First JSON Search

Observation:

- YouTube `r6pWz2FnFOk` was missed even though Bilibili `BV1MWJK6SE4X` exists.
- The old query plan favored the English title plus description/tag concepts, so `music` from the description produced weak queries.
- Direct Bilibili HTML search can return a captcha page, which previously looked like a successful empty parse.

What:

- Added title-first semantic query generation:
  - `哲学的世界令人惊叹`
  - `哲学 世界 令人惊叹`
  - `哲学 中配`
  - `Xandros 中配`
- Added philosophy/world/incredible concept mappings for query generation and scoring.
- Switched live search to prefer `api.bilibili.com/x/web-interface/search/type`.
- Kept HTML search as fallback, but captcha/risk pages now become a channel-limited error.
- Added report `search_state`:
  - `matched_candidates`
  - `searched_no_parseable_candidates`
  - `search_unavailable`
- Kept manual search links in query artifacts and UI.

Validation:

- `python -m py_compile src/autosub_zh/bilibili_search.py src/autosub_zh/ui_server.py`
- `node --check web\app.js`
- `pytest tests/test_bilibili_query_plan.py tests/test_bilibili_candidate_scoring.py tests/test_bilibili_search_parsing.py tests/test_ui_server_bilibili_api.py`
  - `16 passed in 1.31s`
- Live regression with YouTube `r6pWz2FnFOk`:
  - `search_state = matched_candidates`
  - `decision = medium_confidence_review`
  - all 6 selected queries succeeded through the API
  - top candidate: `BV1MWJK6SE4X`, score `76`, title `哲学 的 世界令人惊叹 - Xandros - 中配`

## 2026-06-17 17:00 +08:00 - Local Feedback Dataset Loop MVP

User direction:

- Prioritize subtitle ASS feedback over Bilibili feedback.
- Treat `05_translated_segments.json` only as the machine baseline for alignment; the manual feedback source is the ASS file.
- Bilibili duplicate-search labels are `duplicate`, `not_duplicate`, `same_topic`, and `manual_review`.
- Missing duplicates are more costly than false positives; high-confidence duplicates may block, lower confidence goes to manual review.
- Feedback should be versionable JSONL and also have small UI click entry points.
- External APIs and lightweight dependencies are allowed; `scikit-learn` was added for future lightweight ranking/active learning.

What:

- Added `src/autosub_zh/feedback_dataset.py` with commands:
  - `init`
  - `collect-bilibili`
  - `collect-style`
  - `validate`
  - `dedupe`
  - `build-gold`
  - `eval-bilibili`
  - `summarize`
- Added `datasets/local_feedback/` schema and starter files.
- Added Bilibili candidate UI feedback buttons and `/api/bilibili-duplicate-feedback`.
- Added ASS feedback collection button in project outputs and `/api/collect-style-feedback`.
- Added offline Bilibili replay eval writing `datasets/local_feedback/eval_reports/latest_bilibili_eval.json`.
- Added learned suggestion files:
  - `learned_bilibili_hints.json`
  - `learned_style_guidelines.md`
  - `learning_summary.md`
- Added `docs/local_feedback_learning_handoff.md`.

Important guardrails:

- Small sample counts are not suitable for deep-learning fine-tuning.
- High-quality labels and a stable gold set come before model training.
- Learning and eval samples must stay separated.
- Automatic learning remains a suggestion layer until it is explicitly wired behind a feature flag.

Validation:

- `python -m autosub_zh.feedback_dataset init`
- `python -m autosub_zh.feedback_dataset validate`
  - `ok = true`
- `python -m autosub_zh.feedback_dataset build-gold`
  - zero samples, files created
- `python -m autosub_zh.feedback_dataset eval-bilibili`
  - `sample_insufficient = true`
  - framework runnable with empty gold set
- `python -m autosub_zh.feedback_dataset summarize`
- `pytest tests/test_feedback_dataset.py tests/test_ui_server_bilibili_api.py`
  - `8 passed`
- `python -m py_compile src/autosub_zh/feedback_dataset.py src/autosub_zh/ui_server.py`
- `node --check web\app.js`

Known unrelated dirty files left untouched:

- `src/autosub_zh/asr.py`
- `ui_server_error_trace.log`
- `ui_server_live_stderr.log`
- `ui_server_live_stdout.log`
- `tests/test_asr_gpu_fallback.py`

## 2026-06-17 17:45 +08:00 - Subtitle Translation Feedback Refocus

User direction:

- Refocus local feedback learning on subtitle translation quality, not Bilibili search.
- Keep Bilibili duplicate search as an auxiliary feedback stream only.
- Build a local dataset that can later support prompt/RAG tuning, offline eval, and only after enough reviewed data, possible custom training.

What:

- Added subtitle feedback classification fields to `translation_edit_examples.jsonl` records:
  - `features`
  - `feedback_types`
  - `learning_risk`
  - `learning_recommendation`
  - `classification_reasons`
- Added feedback type classes:
  - `style_edit`
  - `term_fix`
  - `semantic_fix`
  - `qa_repair`
  - `linebreak_fix`
  - `surface_edit`
  - `bad_example`
- Added guardrails so high-risk/bad examples cannot be used for style prompt learning or eval gold sets.
- Added `eval-style` command and `datasets/local_feedback/eval_reports/latest_style_eval.json`.
- Updated handoff docs to state subtitle translation feedback is the primary learning objective.

Validation target:

- New samples remain review-only by default.
- Human must set `accepted=true` and exactly one of `use_for_style_prompt` or `use_for_eval`.
- `build-gold` excludes high-risk/bad subtitle samples.
- `eval-style` reports sample sufficiency, signal distribution, unsafe cases, and high-value cases.

## 2026-06-17 18:20 +08:00 - Local Translation Feedback Prompt Hook

User direction:

- Continue from archived ASS feedback learning and wire the learned subtitle style back into the workflow.

What:

- Added `enable_local_translation_feedback`, default off.
- When enabled, `run_pipeline` appends `datasets/local_feedback/learned_style_guidelines.md` to the translation style prompt.
- The same combined prompt is reused by:
  - main segment translation
  - span pre-translation
  - difficult span repair
  - AI display rewrite style context
- Added a UI checkbox labelled `本地翻译反馈`.
- Added CLI flag `--enable-local-translation-feedback` to `tools/pipeline_demo.py`.
- Added `build_translation_style_prompt` as a small testable prompt assembly helper.

Guardrails:

- The local feedback prompt hook is opt-in.
- JSONL examples are not injected directly yet; only the summarized learned guidelines are used.
- Sample-level RAG/few-shot retrieval should be a later controlled enhancement.

## 2026-06-17 18:37 +08:00 - Frontend Information Architecture Refresh

Goal:

- Reduce the daily console surface by separating input/download controls and low-frequency advanced translation strategies from the core workflow/translation pages.
- Add read-only visibility for local subtitle-translation feedback learning and per-project output health.

What:

- Added two parallel UI panels:
  - `输入与下载`: YouTube URL, downloader, proxy, IDM, YouTube metadata, Bilibili duplicate search, input scanning, and MP3 attachment entry points.
  - `高级策略`: cache/rerun flags, high-risk span repair, semantic allocation, display rewrite, and entity bootstrap settings.
- Kept `翻译设置` focused on target language, translation model, prompt injection, chunk/retry controls, OpenAI Base URL runtime state, local translation feedback toggle, and attached audio path.
- Added `GET /api/local-feedback-summary`:
  - reads `datasets/local_feedback/translation_edit_examples.jsonl`;
  - reads `eval_sets/translation_style_gold.jsonl`;
  - reads `eval_reports/latest_style_eval.json`;
  - reads the first learned bullets from `learned_style_guidelines.md`.
- Added frontend renderers for local feedback summary, advanced strategy summary, input/download status, project health badges, and selected-project health summary.
- Updated Bilibili duplicate-search display to separate real search state from manual review links.

Verification:

- `node --check web\app.js`
- `python -m py_compile src/autosub_zh/ui_server.py`
- `pytest tests/test_ui_server_bilibili_api.py tests/test_feedback_dataset.py`
- In-app browser smoke test on `http://127.0.0.1:8789/`:
  - page title `Autosub Studio`;
  - no console error/warn logs;
  - `输入与下载` and `高级策略` tabs switch active state across top tabs, side nav, and panels;
  - local feedback card reads real dataset counts;
  - output panel shows project badges and health summary;
  - mobile viewport `390x820` has no horizontal overflow and advanced/feedback grids collapse to one column.

Follow-up:

- When the learning review UI is ready, promote feedback learning from a summary card into a dedicated review workspace.
- Consider adding a lightweight frontend regression test for tab/panel mapping if this UI keeps expanding.

## 2026-06-17 19:05 +08:00 - Archive ASS Feedback Learning Batch

User direction:

- Learn subtitle translation style from three archived bilingual ASS files:
  - `A-Man-In-A-Gas-Mask-Terrorized-A-Swiss-Village-For-10-Years-The-Hunt-For-Le-Loyon`
  - `Only-One-Hitchcock-Film-Is-Lost.-This-Redditor-Might-Have-A-Copy`
  - `Porter-and-Stout-What-s-the-difference-The-Craft-Beer-Channel`

What:

- Fixed ASS selection so `collect-style` skips unusable preferred ASS files and falls back to the first usable `08_bilingual_*.ass` / `08_subtitle_*.ass`.
- Le Loyon's `08_bilingual_zh_en.ass` was 3 bytes, so feedback learning used:
  - `08_bilingual_zh_en.recovered_from_vscode_qKNS_20260606_021032.ass`
- Repaired one malformed JSONL line caused by a previous parallel append attempt, then reran collection serially.
- Added a small JSONL lock around feedback append/upsert operations to prevent concurrent collection from interleaving writes.
- Collected and accepted low-risk style feedback from the three requested projects:
  - Le Loyon: 221 eligible samples, 203 style-learning, 18 eval
  - Hitchcock lost film: 151 eligible samples, 139 style-learning, 12 eval
  - Porter/Stout: 62 eligible samples, 57 style-learning, 5 eval

Dataset state after rebuild:

- Translation edit records: 981
- Translation style-learning records: 898
- Translation eval-marked records: 78
- Style gold records: 78
- Latest style eval unsafe sample rate: 0.0

Verification:

- `python -m py_compile src/autosub_zh/feedback_dataset.py src/autosub_zh/ui_server.py`
- `node --check web\app.js`
- `pytest tests/test_feedback_dataset.py`
- `py -m autosub_zh.feedback_dataset dedupe`
- `py -m autosub_zh.feedback_dataset validate`
- `py -m autosub_zh.feedback_dataset build-gold`
- `py -m autosub_zh.feedback_dataset eval-style`
- `py -m autosub_zh.feedback_dataset summarize`

## 2026-06-17 21:10 +08:00 - Span Pre-Translation Feedback Learning Layer

Goal:

- Extend local subtitle feedback learning from single-segment style edits to span pre-translation examples.
- Keep the first implementation explainable, local, opt-in, and request-count neutral.

What:

- Added span feedback dataset files:
  - `span_translation_examples.jsonl`
  - `eval_sets/span_translation_gold.jsonl`
  - `eval_reports/latest_span_translation_eval.json`
  - `learned_span_guidelines.md`
- Added `collect-span-style` to collect span-first/high-risk span examples from `04a_source_spans.json`, translated segments, and manual ASS alignment.
- Added span schema validation, dedupe, gold build, span eval, and learned span guideline summary.
- Added span top-k example retrieval for span pre-translation prompts, gated by the existing local translation feedback toggle.
- Added `span_examples_hash` to the span pre-translation fingerprint so updated local examples invalidate stale span pre-translation cache.
- Extended `/api/local-feedback-summary` and the frontend feedback card with span-learning counts and span eval metrics.

Smoke collection:

- Ran `collect-span-style` on `An-Ignorant-Guide-to-Shoegaze`.
- Added 7 review-only span examples from 52 candidate spans.
- These examples are not injected into prompts until reviewed and marked `accepted=true` + `use_for_span_prompt=true`.

Current dataset state:

- Span translation example records: 7
- Span style-learning records: 0
- Span eval-marked records: 0
- Latest span eval unsafe sample rate: 0.0

Verification:

- `python -m py_compile src/autosub_zh/feedback_dataset.py src/autosub_zh/span_translate.py src/autosub_zh/pipeline_core.py src/autosub_zh/ui_server.py`
- `node --check web\app.js`
- `pytest tests/test_feedback_dataset.py tests/test_span_translation_flow.py tests/test_ui_server_bilibili_api.py`
- `py -m autosub_zh.feedback_dataset validate`
- `py -m autosub_zh.feedback_dataset collect-span-style --project "D:\autosub_zh\output\已发归档\An-Ignorant-Guide-to-Shoegaze"`
- `py -m autosub_zh.feedback_dataset build-gold`
- `py -m autosub_zh.feedback_dataset eval-span-style`
- `py -m autosub_zh.feedback_dataset summarize`

Follow-up:

- Collect span feedback from archived projects and then mark low-risk accepted span examples for `use_for_span_prompt` / eval split.

## 2026-06-17 20:45 +08:00 - Archive ASS Feedback Learning Batch 2

User direction:

- Continue learning subtitle translation style from three archived bilingual ASS files:
  - `A-huge-path-drawing-puzzle-where-the-rules-keep-changing-Rorschach-s-River`
  - `An-Ignorant-Guide-to-Shoegaze`
  - `Dubai-Has-a-Sewage-Problem`

What:

- Confirmed all three projects have usable `08_bilingual_zh_en.ass` and `05_translated_segments.json`.
- Collected subtitle edit feedback serially to avoid concurrent JSONL writes.
- Accepted low-risk style feedback and kept learning/eval separation:
  - Rorschach's River: 5 eligible samples, 5 style-learning, 0 eval
  - Shoegaze: 62 eligible samples, 57 style-learning, 5 eval
  - Dubai sewage: 53 eligible samples, 49 style-learning, 4 eval

Dataset state after rebuild:

- Translation edit records: 1101
- Translation style-learning records: 1009
- Translation eval-marked records: 87
- Style gold records: 87
- Latest style eval unsafe sample rate: 0.0

Verification:

- `python -m py_compile src/autosub_zh/feedback_dataset.py src/autosub_zh/ui_server.py`
- `node --check web\app.js`
- `pytest tests/test_ui_server_bilibili_api.py tests/test_feedback_dataset.py`
- `py -m autosub_zh.feedback_dataset dedupe`
- `py -m autosub_zh.feedback_dataset validate`
- `py -m autosub_zh.feedback_dataset build-gold`
- `py -m autosub_zh.feedback_dataset eval-style`
- `py -m autosub_zh.feedback_dataset summarize`

## 2026-06-17 22:30 +08:00 - UI Buttons For Current ASS/Span Feedback

User direction:

- Add website buttons to learn the current span and current ASS.
- Do not learn from the `05` file.

What:

- Added `/api/collect-span-feedback` for collecting current project span-learning records from final manual ASS alignment.
- Kept `/api/collect-style-feedback` for ASS edit-learning and made both API responses explicit:
  - `learning_source = manual_ass`
  - `05` / `05a` translated segments are machine baselines only for diff alignment.
- Added the same source contract to JSONL record `source` metadata:
  - `learning_source = manual_ass`
  - `machine_baseline_only = true`
- Added two visible buttons in the frontend local feedback card:
  - `学习本次 ASS`
  - `学习本次 Span`
- The buttons act on the selected output project and refresh the local feedback summary after collection.
- Retained the existing file-preview `采集 ASS 反馈` button as a precise file/project-level shortcut.

Verification:

- `node --check web\app.js`
- `python -m py_compile src/autosub_zh/ui_server.py src/autosub_zh/feedback_dataset.py src/autosub_zh/span_translate.py src/autosub_zh/pipeline_core.py`
- `pytest tests/test_ui_server_bilibili_api.py tests/test_feedback_dataset.py tests/test_span_translation_flow.py`

Notes:

- The collectors still read `05_translated_segments.json` or `05a_span_translated_segments.json` only to compare the machine output against final ASS edits. They are not accepted as target learning data.

## 2026-06-17 22:45 +08:00 - Move Feedback Learning To Selected Input Video

User direction:

- Do not require opening an ASS page/file before learning.
- Allow clicking learn after selecting a video in the workspace.

What:

- Added `学习本次 ASS` and `学习本次 Span` buttons directly to the top input-video card.
- Changed feedback-learning target selection to prefer the current selected input video's matched output project.
- Kept the project/file fallback only for cases where no input video is selected.
- Updated the feedback card status to show `学习目标：当前选中视频 -> project`.
- Disabled the top learning buttons unless the selected input video has a matched output project with a usable ASS path.

Verification:

- `node --check web\app.js`
- `python -m py_compile src/autosub_zh/ui_server.py src/autosub_zh/feedback_dataset.py`
- `pytest tests/test_ui_server_bilibili_api.py tests/test_feedback_dataset.py tests/test_span_translation_flow.py`

Correction:

- This input-video entry point was removed in the follow-up change below because the intended workflow is to choose an existing ASS artifact first, then learn.

## 2026-06-17 22:55 +08:00 - Require Selected ASS Artifact For Feedback Learning

User clarification:

- Learning should happen after ASS artifacts exist.
- The user should choose the corresponding ASS file and then choose learning.
- This should not be tied to scanning or selecting input videos.

What:

- Removed the `学习本次 ASS` / `学习本次 Span` buttons from the input-video card.
- Added `学习本次 Span` next to `学习本次 ASS` in the project artifact preview toolbar.
- Both toolbar buttons are enabled only when the selected preview file is `.ass`.
- The feedback-learning summary card now also disables its learn buttons unless a `.ass` artifact is selected.
- The learning target is again the selected ASS artifact's project folder; `05` / `05a` remain machine baselines only.

Verification:

- `node --check web\app.js`
- `pytest tests/test_ui_server_bilibili_api.py tests/test_feedback_dataset.py tests/test_span_translation_flow.py`

## 2026-06-17 23:15 +08:00 - Top-Pinned ASS Artifact Naming

User direction:

- Make ASS artifacts appear at the top in Windows Explorer and in the website project artifact list.
- Update all filename dependencies.

What:

- Changed new generated final ASS names from `08_*` to `00_ASS_*`:
  - `00_ASS_bilingual_<dst>_<src>.ass`
  - `00_ASS_subtitle_<dst>.ass`
  - `00_ASS_source_<src>.ass`
- Kept legacy `08_*` ASS copies for compatibility when the pipeline writes new outputs.
- Added shared ASS filename helpers in `src/autosub_zh/workflow_profiles.py`:
  - `is_final_ass_filename`
  - `ass_candidate_paths`
  - `find_existing_ass_path`
- Updated UI server project scanning, reburn, style learning, feedback learning, CLI defaults, and frontend badges/artifact links to prefer `00_ASS_*` while still accepting existing `08_*` projects.
- Excluded safe/segmentation-preview ASS files from "final ASS" detection.
- Updated docs and tests for the new naming.

Verification:

- `python -m py_compile src/autosub_zh/workflow_profiles.py src/autosub_zh/pipeline_core.py src/autosub_zh/ui_server.py src/autosub_zh/feedback_dataset.py src/autosub_zh/cli.py src/autosub_zh/style_learning_cli.py tools/fixes/fix_ru_xiu_xiu_title.py`
- `node --check web\app.js`
- `pytest tests/test_subtitle_output_modes.py tests/test_feedback_dataset.py tests/test_ui_server_bilibili_api.py tests/test_span_translation_flow.py`

## 2026-06-17 23:25 +08:00 - Pipeline ASS Manifest Cleanup

User question:

- Check whether the pipeline layer also needs optimization after ASS artifact renaming.

What:

- Confirmed the main pipeline ASS write path already uses `plan.ass_name`, so new runs write `00_ASS_*` as the primary final ASS.
- Extracted pipeline manifest file listing into `build_manifest_file_list`.
- Pinned final ASS artifacts to the start of manifest `files` for both skip-burn and normal burn paths.
- Removed the temporary safe burn ASS from manifest `files` because it is created in the temp directory, not the project output folder.
- Renamed the temporary burn copy from `08_bilingual_safe.ass` to `00_ASS_safe_for_burn.ass` to avoid resembling a legacy final ASS.

Verification:

- `python -m py_compile src/autosub_zh/pipeline_core.py src/autosub_zh/workflow_profiles.py src/autosub_zh/ui_server.py src/autosub_zh/feedback_dataset.py`
- `pytest tests/test_subtitle_output_modes.py tests/test_feedback_dataset.py tests/test_ui_server_bilibili_api.py tests/test_span_translation_flow.py`

## 2026-06-17 23:55 +08:00 - Bilibili Check Decoupling and Release Artifact Health

User direction:

- First decouple Bilibili duplicate checking from the translation workflow.
- Then add project artifact archiving and health scoring.
- Show the necessary release artifacts: description, two covers, ASS file, and burned video; move other files into a child folder.
- Review UI comes later.

What:

- Added a stable Bilibili workflow policy payload:
  - `workflow_decoupled=true`
  - `blocks_translation=false`
  - `blocks_download=false`
  - `manual_review_only=true`
- Bilibili duplicate API now returns this policy on success and failure, so search channel failures are visible but do not look like translation blockers.
- Project scanning now returns `release_artifacts` and `health` for each output project.
- Release artifacts track:
  - `00_youtube_info.txt`
  - `00_youtube_cover.jpg`
  - `00_youtube_cover_1280x960.jpg`
  - final `00_ASS_*` / compatible legacy ASS
  - burned `09_*.mp4`
- Added health score, readiness, missing release artifact list, QA blocker/warning counts, and internal artifact count.
- Added `/api/organize-project-artifacts`, which keeps release artifacts in the project root and moves other root files into `99_internal_artifacts`.
- Updated project health UI to show the release checklist, health score, internal file count, and a `整理发布产物` action.
- Made manifest/segment lookup tolerate files moved into `99_internal_artifacts` for UI scan, reburn, cover rebuild, and feedback collection.

Verification:

- `python -m py_compile src/autosub_zh/ui_server.py src/autosub_zh/feedback_dataset.py src/autosub_zh/pipeline_core.py src/autosub_zh/span_translate.py`
- `node --check web\app.js`
- `pytest tests/test_ui_server_bilibili_api.py tests/test_feedback_dataset.py tests/test_span_translation_flow.py`
- `pytest tests/test_subtitle_output_modes.py`

## 2026-06-17 23:01 +08:00 - Feedback Review UI and Learning Quality Panel

User direction:

- Build a Chinese review UI with simple explanations and keep it decoupled.
- Continue safe two-stage artifact organization and cache compatibility optimization.
- Add an initial learning quality panel.

What:

- Added `反馈审核` and `学习质量` workspace tabs.
- Feedback review UI now lists local ASS/Span learning records, shows source / machine baseline / manual ASS comparison, and supports:
  - accept
  - use for Prompt learning
  - use for Eval
  - clear usage
  - return to pending review
- Added read/update APIs:
  - `GET /api/local-feedback-records`
  - `POST /api/local-feedback-record-update`
  - `GET /api/learning-quality-summary`
- Kept review actions local to JSONL learning metadata. They do not trigger translation requests.
- Changed project artifact organization to safe two-stage flow:
  - preview planned moves first
  - only move files into `99_internal_artifacts` after confirmation
- Improved pipeline cache compatibility after artifact organization:
  - translated segments
  - timed source segments
  - source spans
  - span translated segments/report
  - style rewrite prompt
- Added initial learning quality cards for sample counts, pending review counts, eval signals, project sources, tag distribution, and learned rule previews.

Verification:

- `python -m py_compile src/autosub_zh/ui_server.py src/autosub_zh/feedback_dataset.py src/autosub_zh/pipeline_core.py src/autosub_zh/workflow_profiles.py`
- `node --check web\app.js`
- `git diff --check -- src/autosub_zh/ui_server.py src/autosub_zh/pipeline_core.py web\app.js web\index.html web\styles.css tests/test_ui_server_bilibili_api.py`
- `pytest tests/test_ui_server_bilibili_api.py`
- `pytest tests/test_feedback_dataset.py tests/test_span_translation_flow.py`
- `pytest tests/test_subtitle_output_modes.py`
- Direct data check showed current local dataset has 5 pending ASS records, 7 pending Span records, 1101 ASS edit records, and 7 Span examples.

## 2026-06-17 23:18 +08:00 - Learning Quality Diagnostics and Actions

User direction:

- Upgrade the learning quality panel from static counts to a diagnostic and action-oriented panel.
- Keep it Chinese, decoupled from translation, and backed by lightweight history snapshots.

What:

- Extended `GET /api/learning-quality-summary` with compatible additive fields:
  - `quality`
  - `coverage`
  - `risk`
  - `distributions`
  - `recommendations`
  - `history`
- Added the local-only action API `POST /api/local-feedback-action`:
  - `summarize`
  - `build_gold`
  - `eval_style`
  - `eval_span_style`
- Added lightweight quality snapshots at `datasets/local_feedback/eval_reports/learning_quality_snapshots.jsonl`.
- Implemented a 100-point, explainable learning quality score:
  - ASS Prompt coverage
  - ASS Eval coverage
  - Span Prompt coverage
  - Span Eval coverage
  - unsafe rate
  - pending review volume
  - recent summary/eval freshness
- Upgraded the frontend `学习质量` panel to show:
  - overall diagnosis
  - score and reasons
  - coverage ratios
  - risk counts
  - project/tag/recommendation/risk distributions
  - recent quality snapshots
  - action buttons for review, summarize, build-gold, eval-style, and eval-span-style
- The action panel explicitly notes that these operations do not start subtitle translation or increase translation requests.

Current real-data diagnosis:

- Overall status: `eval_insufficient`
- Score: 70 / 100
- ASS Prompt samples: 1009
- ASS Eval samples: 87
- Span Prompt samples: 0
- Span Eval samples: 0
- Pending ASS records: 5
- Pending Span records: 7

Verification:

- `python -m py_compile src/autosub_zh/ui_server.py src/autosub_zh/feedback_dataset.py`
- `node --check web\app.js`
- `git diff --check -- src/autosub_zh/ui_server.py web\app.js web\styles.css tests/test_ui_server_bilibili_api.py`
- `pytest tests/test_ui_server_bilibili_api.py`
- `pytest tests/test_feedback_dataset.py tests/test_span_translation_flow.py`
- `pytest tests/test_subtitle_output_modes.py`

## 2026-06-18 00:00 +08:00 - A/B Eval Action Loop v1

User direction:

- Turn small-sample A/B eval into an actionable learning-quality loop.
- Keep all actions explicit, local, and decoupled from model calls and the subtitle pipeline.

What:

- Added deterministic A/B sample outcome classification in `src/autosub_zh/feedback_ab_eval.py`.
- A/B reports now expose `action_summary` for:
  - helpful feedback samples
  - prompt-harmful candidates
  - unsafe output candidates
  - weak Span feedback samples
- Added `POST /api/local-feedback-ab-eval-apply` for JSONL-only metadata actions:
  - `clear_prompt`
  - `return_pending`
  - `use_for_eval`
  - `accept_only`
- Added an A/B action panel to the learning quality UI with Chinese explanations, per-record buttons, and batch actions.
- Added A/B filters to the feedback review UI:
  - A/B 负贡献
  - A/B 输出风险
  - A/B Span 弱收益
  - A/B 正向样本

Safety:

- The apply API does not call the translation model.
- The apply API does not start the subtitle pipeline.
- The apply API does not rebuild gold sets.
- `05_translated_segments.json` and `05a_span_translated_segments.json` remain machine baselines only.

Verification:

- `python -m py_compile src/autosub_zh/ui_server.py src/autosub_zh/feedback_ab_eval.py src/autosub_zh/feedback_dataset.py src/autosub_zh/pipeline_core.py src/autosub_zh/span_translate.py`
- `node --check web\app.js`
- `pytest tests/test_feedback_dataset.py tests/test_ui_server_bilibili_api.py -q`
- `pytest tests/test_feedback_dataset.py tests/test_ui_server_bilibili_api.py tests/test_span_translation_flow.py tests/test_subtitle_output_modes.py -q`
