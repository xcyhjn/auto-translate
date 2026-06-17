# Subtitle Segmentation Handoff

Updated: 2026-06-17 00:40 +08:00

## Current Problem Definition

The current bilingual subtitle workflow was producing English cues that were too display-driven:

- Short open fragments: e.g. `The silence is only broken by the mechanical` / `clicking of an old typewriter.`
- Mixed sentence cues: e.g. `as he usually does. While translation isn't exactly`
- Function-word edges: cues starting with `and`, `that`, `of`, or ending near `the/to/of`.
- Chinese fragmentation/repetition pressure: once English is split incorrectly, Chinese translation follows the bad slice and may repeat context or split at unnatural positions.
- Timeline conflict: the cleanup pass forced every cue to at least `SubtitleRules.min_duration = 2.0`, which could move later cues away from ASR word timestamps.

The goal is not "one cue must always equal one sentence." The target policy is:

- Prefer one complete sentence per English cue.
- Split long/fast/paused sentences only when necessary.
- Use ASR word timestamps, pauses, punctuation, and clause boundaries for necessary splits.
- Avoid short tails and dangling function words.
- Keep Chinese aligned to English spans, but do not mechanically copy bad English cuts.

## Root Cause Analysis

Files reviewed:

- `D:\autosub_zh\timing.py`
- `D:\autosub_zh\source_spans.py`
- `D:\autosub_zh\pipeline_core.py`
- `D:\autosub_zh\models.py`
- Sample ASS: `D:\autosub_zh\output\Russian-book-about-a-dying-god\08_bilingual_zh_en.ass`

Key causes:

- `refine_timing()` ran `split_segment_on_pause()` -> `split_segment_by_max_duration()` -> `split_segment_for_display_limits()`. This made display constraints too dominant.
- Sentence boundary splitting required a pause of `pause_split_threshold = 0.55`, so normal sentence transitions with smaller pauses stayed mixed.
- `split_segment_by_max_duration()` was greedy: when a segment exceeded max duration it cut before the current word, regardless of syntax, sentence boundary, or orphan tail.
- `split_segment_for_display_limits()` split whenever `line_count > 1`, even when the sentence was readable and within duration.
- The cleanup phase forced `end >= start + min_duration` and then capped to `max_duration`, modifying ASR timing for readability.
- `source_spans.py` did not explicitly flag short open fragments or internal multi-sentence boundaries strongly enough.

## Changes Made

### `models.py`

Added tunable segmentation rules:

- `sentence_boundary_split_gap = 0.22`
- `sentence_boundary_min_next_words = 2`
- `orphan_word_threshold = 5`
- `orphan_duration_threshold = 1.6`
- `display_overflow_tolerance = 1.35`
- `complete_sentence_duration_tolerance = 0.45`

### `timing.py`

Implemented sentence-first timing refinement:

- Added terminal detection with abbreviation protection.
- Split at sentence boundaries even when the pause is below `0.55`, if the next word looks like a new sentence.
- Added short-fragment/orphan detection.
- Added adjacent-fragment regrouping for open clauses and dangling function-word cuts.
- Added a dedicated mixed-sentence split pass.
- Replaced greedy max-duration splitting with scored natural-boundary splitting.
- Reduced display-limit dominance by allowing modest overflow and only splitting when clearly over duration/length/CPS constraints.
- Strengthened penalties for:
  - 1-5 word open fragments
  - orphan tails
  - function words at split edges
  - splitting before continuation words
- Changed final cleanup to preserve ASR timing instead of forcing every cue to 2 seconds.

### `source_spans.py`

Added source span flags:

- `short_open_fragment`
- `internal_sentence_boundary`

These now affect join decisions, risk scoring, and span translation strategy.

## Validation Results

Validation used the existing Russian-book sample without overwriting the official output.

Generated preview files:

- `D:\autosub_zh\output\Russian-book-about-a-dying-god\03_timed_source_segments.segmentation_preview.json`
- `D:\autosub_zh\output\Russian-book-about-a-dying-god\04a_source_spans.segmentation_preview.json`
- `D:\autosub_zh\output\Russian-book-about-a-dying-god\08_bilingual_zh_en.segmentation_preview.ass`
- `D:\autosub_zh\output\Russian-book-about-a-dying-god\segmentation_preview_metrics.json`

Metrics:

| Metric | Before | After |
|---|---:|---:|
| English timed segments | 833 | 620 |
| `<=5` word cues | 106 | 66 |
| `<=8` word open fragments | 183 | 9 |
| mixed-sentence-like cues | 89 | 5 |
| function-edge cues | 256 | 115 |
| duration > 6.95s | 0 | 0 |
| duration < 1.0s | 0 | 22 |

Source span summary:

| Metric | Before | After |
|---|---:|---:|
| source segments | 833 | 620 |
| source spans | 220 | 150 |
| span_first | 157 | 84 |
| span_context | 28 | 62 |
| normal | 35 | 4 |

Notable improvements:

- Before: `The silence is only broken by the mechanical` + `clicking of an old typewriter.`
- After: `The silence is only broken by the mechanical clicking of an old typewriter.`

- Before: `Dmitri doesn't know it yet, but it's waiting` + `outside of his apartment.`
- After: `Dmitri doesn't know it yet, but it's waiting outside of his apartment.`

- Before: `Dmitri stops typing. It's way too late for a visit. The soundscape changes.`
- After:
  - `Dmitri stops typing.`
  - `It's way too late for a visit.`
  - `The soundscape changes.`

- Before: `He can hear the water droplets in the kitchen sink` + `and the dogs howling on the street.`
- After: `He can hear the water droplets in the kitchen sink and the dogs howling on the street.`

## Known Remaining Issues

- Some short complete sentences now keep true ASR timing under 1 second, e.g. `The city sleeps.` and `He wonders.` This is intentional timing preservation, but it may be a reading-load concern for final rendering.
- Some raw ASR fragments start mid-sentence, e.g. `pinching his skin...` or `it. Uri...`; timing cannot invent missing context. These should be handled by source repair or ASR repair.
- Some long sentences still require clause splits and can leave imperfect cuts such as `because it's`; source span translation now flags these for context handling, but the final translation stage should be rerun to benefit.
- The preview ASS uses old Chinese text overlapped by time and is only a segmentation preview. It is not a final translated ASS.
- Full end-to-end regeneration was not run here because it would invoke external translation and possibly reuse existing translated segments. The code path is ready for the next full pipeline run.

## Next Steps

1. Run a full pipeline regeneration with translation disabled/reused only if the goal is timing QA; rerun translation if final Chinese quality is being evaluated.
2. Add focused unit tests for:
   - mixed sentence splitting
   - orphan fragment merge
   - natural max-duration split
   - ASR timing preservation for short complete sentences
3. Review remaining `segmentation_preview_metrics.json` samples and decide whether short complete cues under 1 second should be displayed as-is or grouped only in the rendering layer.
4. Consider a Chinese post-alignment pass that translates source spans first, then redistributes target text to refined English cues by semantic boundaries instead of old cue timing.

## Phase 2 Update - 2026-06-17

### Added

- `semantic_allocation.py` builds per-cue semantic allocation reports with `source_span_id`, `allocation_confidence`, `qa_flags`, and `allocation_note`.
- `segmentation_qa.py` writes the stable segmentation QA metrics used by both JSON artifacts and the frontend.
- `source_repair.py` now emits `02b_asr_source_repair_candidates.json` for raw/timed ASR source repair candidates without changing word timestamps.
- `zh_reading_axis.py` and `subtitle_io.py` now support display-only grouping for adjacent short complete sentences.
- The pipeline now writes:
  - `02b_asr_source_repair_candidates.json`
  - `05a_semantic_allocated_segments.json`
  - `05a_semantic_allocation_report.json`
  - `07j_segmentation_qa_metrics.json`
- The frontend "项目产物" view now has a "字幕 QA" panel with metric cards, samples, and direct artifact links.

### Russian Sample Result

Generated phase-2 artifacts for `output/Russian-book-about-a-dying-god`.

- `short_fragment_count`: 27
- `mixed_sentence_count`: 89
- `function_edge_count`: 116
- `too_short_count`: 0
- `too_long_count`: 0
- `semantic_review_count`: 13
- `source_repair_candidate_count`: 170
- `source_repair_review_count`: 87
- `display_group_count`: 0
- `blocking_issue_count`: 232

### Validation

- `python -m py_compile semantic_allocation.py segmentation_qa.py source_repair.py zh_reading_axis.py subtitle_io.py pipeline_core.py ui_server.py pipeline_runner.py`
- `node --check web\app.js`
- `pytest -q test_semantic_qa_phase2.py test_zh_reading_axis.py test_asr_repair_flow.py`
- Browser check at `http://127.0.0.1:8777`
  - Russian sample QA metrics and artifact links render in "项目产物 -> 字幕 QA".
  - 375px / 768px / 1280px / 1920px have no horizontal overflow.
  - Body font is 16px and sampled buttons are at least 46px tall.

### Remaining Phase 2 Gaps

- The current semantic allocator is a protected/reporting pass. It does not yet perform a full rewritten Chinese redistribution from span-level translations into refined cues.
- `display_group_count` is 0 for the Russian sample because no adjacent short complete-sentence pair satisfied the conservative grouping thresholds.
- The sticky command bar can visually overlap project cards during scroll; the UI remains usable, but scroll positioning could be polished.
- `07j_segmentation_qa_metrics.json` is JSON only; a TSV export would make manual QA faster.

## Phase 2.1 Update - Orphan Terminal Tail Blocking - 2026-06-17

### Problem

The official Russian sample ASS still produced a one-word sentence tail:

- Before:
  - `that was made into an even more famous video game`
  - `franchise.`
  - Chinese followed the broken cut as `系列。`

This happened because terminal orphan cues were protected from the existing orphan merge path: `should_merge_adjacent()` only merged right-side orphans when the right cue did not end with sentence punctuation.

### Strategy

- Treat 1-2 word terminal tails as a blocking segmentation defect when the previous cue is open, or when the previous cue looks suspiciously closed and the tail begins lowercase.
- Merge these tails with the previous cue when gap, duration, and display length stay within conservative limits.
- Prefer a slightly longer complete cue over a standalone one-word cue.
- Keep ASR word timestamps intact; merges use existing word start/end times.
- Add a display-only ASS fallback so old translated segments can still be rendered without isolated tails.
- Clean safe display artifacts:
  - `电子游戏。系列。` -> `电子游戏系列。`
  - `property. market.` -> `property market.`
  - duplicate Chinese tail sentences are removed only when the short tail text already appears in the previous sentence.

### Files Changed

- `timing.py`
  - Added `is_terminal_orphan_tail()` and `can_absorb_terminal_orphan_tail()`.
  - Merges open-left + terminal tail before normal sentence-boundary protections.
  - Handles suspicious ASR punctuation such as `property.` + `market.`.
  - Adds strong DP penalties against producing terminal 1-2 word tails.
- `zh_reading_axis.py`
  - Added `merge_orphan_tail_display_cues()`.
  - Added English and Chinese cleanup for display-only merged cues.
- `pipeline_core.py`
  - Runs the orphan-tail display pass before writing bilingual ASS.
- `segmentation_qa.py`
  - Added `orphan_terminal_tail_count` and samples.
  - `pass=false` when a residual terminal orphan tail remains.
- `web/app.js`
  - Added the frontend QA card `孤立句尾词`.
- Tests:
  - `test_timing_segmentation.py`
  - `test_semantic_qa_phase2.py`

### Validation

Commands:

- `python -m py_compile timing.py zh_reading_axis.py segmentation_qa.py pipeline_core.py`
- `node --check web/app.js`
- `pytest -q test_timing_segmentation.py test_semantic_qa_phase2.py test_zh_reading_axis.py test_subtitle_output_modes.py test_asr_repair_flow.py`

Result:

- `38 passed in 0.37s`
- Russian sample regenerated from existing `05_translated_segments.json`.
- `07j_segmentation_qa_metrics.json`:
  - `orphan_terminal_tail_count = 0`
  - `orphan_tail_group_count = 20`
- The user-reported ASS case now renders as:
  - Chinese: `后来还被改编成了更有名的电子游戏系列。`
  - English: `that was made into an even more famous video game franchise.`
- Additional discovered case now renders as:
  - Chinese: `这种公寓很稀有，层高很高，在房产市场上价值不菲。`
  - English: `These are rare, have tall ceilings and go for a lot of money on the property market.`

### Remaining Notes

- The sample still has other QA blockers (`pass=false`) from mixed-sentence/short-fragment/function-edge metrics. They are separate from orphan terminal tails.
- Four remaining 1-2 word terminal English cues in the sample are not flagged because they look like independent short sentences or proper-name cues, e.g. `He wonders.` and `Juan Kokom.`
- The display merge is intentionally conservative: strong pauses, severe length overflow, and uppercase independent short sentences are not force-merged.

## Phase 2.3 Update - English Residue Scoring And Strict Chinese Localization - 2026-06-17

### Problem

Chinese subtitles still leak Latin text because prompt-level instructions are too soft. The project needed a single shared rule for:

- whether a Latin residue may stay
- when a name/place should be translated
- when a residue is merely a review item

### Strategy

- Add `english_residue_policy.py` as the shared scorer.
- Score every Latin residue in Chinese subtitles on a 0-100 scale.
- Default thresholds:
  - preserve only at `>= 85`
  - review at `70-84`
  - below `70` must translate
- Make common places, languages, history terms, and ordinary words override auto glossary preserve.
- Treat auto-generated glossary preserve entries as soft preserve unless they are explicit hard/manual preserves.

### Files Changed

- `english_residue_policy.py`
- `translate.py`
- `span_translate.py`
- `qa.py`
- `qa_outputs.py`
- `entity_normalization.py`
- `pipeline_core.py`
- `pipeline_runner.py`
- `ui_server.py`
- `web/app.js`
- `test_english_residue_policy.py`
- `test_entity_pipeline_integration.py`
- `test_entity_pipeline_contract.py`

### Validation

- `python -m py_compile english_residue_policy.py translate.py span_translate.py qa.py qa_outputs.py entity_normalization.py pipeline_core.py pipeline_runner.py ui_server.py`
- `node --check web\app.js`
- `pytest -q test_english_residue_policy.py test_qa_outputs.py test_entity_pipeline_contract.py test_entity_pipeline_integration.py test_workflow_profiles.py test_ui_server_config.py`
  - `23 passed in 0.63s`
- Offline sample scoring on `output/Russian-book-about-a-dying-god/05_translated_segments.json`:
  - `english_residue_total_count = 224`
  - `english_residue_blocking_count = 222`
  - `english_residue_review_count = 1`
  - `english_residue_preserved_count = 1`
  - `L5` is preserved as an identifier

### Known Remaining Issue

- Auto-generated glossary entries for names like `Dmitri` and `Moscow` must not be treated as hard preserve.
- The scorer now demotes them, but project-specific glossary cleanup will still be useful for recurring names that keep bouncing between transliteration and preservation.

### Next Step

- Re-run a full pipeline sample with the new scorer enabled and inspect `07k_english_residue_report.json`.
- If a recurring name/place should stay in Chinese, move it into explicit project decisions or glossary translate policy instead of relying on auto preserve.

## Phase 2.2 Update - Discourse Particle Protection - 2026-06-17

### Problem

After blocking orphan terminal tails, we still needed to protect genuine standalone discourse particles and short response cues:

- `Yeah.`
- `No.`
- `Oh.`
- `Well.`

These should not be merged into the previous cue just because they are short and terminal.

### Strategy

- Add a shared terminal-short-cue classifier in `terminal_tail.py`.
- Split short terminal English cues into three categories:
  - `content_tail`
  - `standalone_particle`
  - `ambiguous_particle`
- Keep `content_tail` merge behavior.
- Preserve `standalone_particle` as an independent cue.
- Send `ambiguous_particle` to QA/review instead of silently merging.
- Let open left fragments still absorb content words such as `no.` in `The answer is / no.`

### Files Changed

- `terminal_tail.py`
  - New shared classifier and particle lexicons.
- `timing.py`
  - Uses the classifier in merge and split scoring.
- `zh_reading_axis.py`
  - Uses the classifier for display-only orphan-tail merging.
- `segmentation_qa.py`
  - Adds:
    - `standalone_discourse_particle_count`
    - `ambiguous_discourse_tail_count`
  - Keeps `orphan_terminal_tail_count` as the blocking metric for content tails.
- `web/app.js`
  - Adds frontend QA cards for:
    - `独立语气词`
    - `歧义语气词`
- Tests:
  - `test_timing_segmentation.py`
  - `test_semantic_qa_phase2.py`

### Validation

- `python -m py_compile terminal_tail.py timing.py zh_reading_axis.py segmentation_qa.py pipeline_core.py`
- `node --check web/app.js`
- `pytest -q test_timing_segmentation.py test_semantic_qa_phase2.py test_zh_reading_axis.py test_subtitle_output_modes.py test_asr_repair_flow.py`

Result:

- `45 passed`
- Russian sample regenerated successfully.
- `orphan_terminal_tail_count = 0`
- `standalone_discourse_particle_count = 0` on this sample
- `ambiguous_discourse_tail_count = 0` on this sample

### Remaining Notes

- The Russian sample currently does not contain strong discourse-particle examples, so the new counters stay at zero there.
- The classifier is intentionally conservative. Short uppercase cues like `He wonders.` and proper-name cues remain untouched.
- Remaining non-particle QA blockers are still separate work.

## Phase 3 Update - Strict English Residue ASS Output - 2026-06-17

### Problem

The first strict English residue implementation exposed three bypasses during actual ASS regeneration:

- Preserve-only glossary matching used substring logic, so `translation.` could incorrectly match `The Translation Follows`.
- `pure_term_cue` terminology short-circuit locked auto-discovered names such as `Juan Kokom` before main translation validation could repair them.
- The English residue extractor only scanned mixed Chinese+Latin lines, so pure English target cues such as `Juan Kokom.` were not scored.

### Strategy

- `translate.py`
  - `resolve_preserve_only_translation()` now requires exact normalized match.
- `terminology.py`
  - `apply_terminology_short_circuit()` now runs preserve terms through `score_english_residue()`.
  - Auto-discovered preserve names no longer lock unless their preserve score passes the threshold.
- `english_residue_policy.py`
  - `extract_latin_residue()` now scans all Chinese-target output containing Latin letters, including pure English lines.

### Generated Output

- New ASS:
  - `output/Russian-book-about-a-dying-god/08_bilingual_zh_en.english_residue_strict.ass`
- The default generated ASS was also updated by the pipeline:
  - `output/Russian-book-about-a-dying-god/08_bilingual_zh_en.ass`
- Timestamped ASS backups were created during regeneration:
  - `08_bilingual_zh_en.pre_strict_residue_*.ass`

### Validation

- Tests:
  - `python -m pytest test_english_residue_policy.py test_terminology_short_circuit.py -q`
  - Result: `12 passed`
- ASS inspection:
  - Chinese layer Latin residue count: `1`
  - remaining residue: `L5`, scored as `code_or_identifier`
  - `franchise.` is no longer a standalone English cue
  - the previous broken pair is now:
    - Chinese: `后来还被改编成了更有名的视频游戏系列。`
    - English: `that was made into an even more famous video game franchise.`
- `07k_english_residue_report.json`:
  - `english_residue_total_count = 1`
  - `english_residue_blocking_count = 0`
  - `english_residue_preserved_count = 1`
  - `pass = true`

### Known Remaining Issue

- This regeneration disabled span-first translation with `span_translation_max_spans=0` to avoid locked translations bypassing strict residue validation.
- The long-term fix should validate span translations again before adding IDs to `locked_translation_ids`, so span-first allocation can be safely re-enabled.
- `07j_segmentation_qa_metrics.json` still reports segmentation QA blockers/warnings unrelated to English residue cleanup.

## Phase 3.1 Update - Span Pretranslation Narrowing - 2026-06-17

### Problem

The span pretranslation path was too broad and too early:

- The Russian sample had `span_first_count = 144` out of 176 source spans.
- Many span-first items were long 8-segment spans near 20 seconds.
- Ordinary `open_clause` / `short_open_fragment` reasons could trigger pretranslation.
- Successful span pretranslation immediately locked segment IDs, preventing the main translation pass from repairing those cues.
- `05a_span_translated_segments.json` could be reused when only segment IDs matched, even after prompt/config/glossary/residue-policy changes.

### Changes Made

- `source_spans.py`
  - Added `source_spans_v2` policy version.
  - Added hard span-first gates: max 4 segments, max 12s, min risk score 10.
  - Added strong-reason gating so ordinary open fragments become `span_context`.
- `span_translate.py`
  - Added candidate filters for max segment count, max duration, and minimum risk.
  - Added `span_translation_v2` fingerprint generation and selection-policy reporting.
- `pipeline_core.py`
  - Added stale source-span policy detection.
  - Added fingerprint-gated span checkpoint reuse.
  - Stopped span checkpoint reuse when `force_retranslate_existing_segments=True`.
- `pipeline_runner.py` / `ui_server.py`
  - Reduced default `span_translation_max_spans` from 16 to 4.
  - Added config passthrough for `span_translation_max_segments`, `span_translation_max_duration`, and `span_translation_min_risk_score`.
- `web/index.html` / `web/app.js`
  - Synced the frontend form/defaults for the new span pretranslation limits.
- `test_span_translation_flow.py`
  - Covers long-span downgrade, short high-risk retention, candidate filtering, and checkpoint fingerprint mismatch.

### Validation

- `python -m py_compile source_spans.py span_translate.py pipeline_core.py pipeline_runner.py ui_server.py`
- `$env:PYTHONPATH='D:\'; python -m pytest test_span_translation_flow.py test_terminology_short_circuit.py test_english_residue_policy.py test_semantic_qa_phase2.py -q`
  - `30 passed`
- `node --check web\app.js`
- `$env:PYTHONPATH='D:\'; python -m pytest test_span_translation_flow.py test_ui_server_config.py -q`
  - `10 passed`
- Offline Russian sample recalculation from current `03_timed_source_segments.json`:
  - before: `span_first_count = 144`
  - after: `span_first_count = 3`
  - after: `span_context_count = 160`
  - old budget 16 now yields only 3 candidates
  - max span-first duration: `11.56s`
  - max span-first segment count: `4`

### Self-Correction

- First implementation used `span_translation_min_risk_score = 30`, which reduced the sample to `span_first = 0`.
- The current score scale is lower than that; threshold was corrected to `10` while keeping duration/segment/strong-reason gates.

### Remaining Issues

- Span pretranslation still writes locked translations when it succeeds. The next implementation should make it proposal-first and QA-gated before adding IDs to `locked_translation_ids`.
- Long spans are currently downgraded to context instead of split into child span-first units. That is safer and faster for now, but not a full semantic allocation solution.
- Existing output directories may still contain old `04a_source_spans.json` counts until the pipeline rewrites the file; runtime translation/allocation now recalculates stale files before use.

## Phase 3.2 Update - Proxy / YouTube Diagnostics - 2026-06-17

### Problem

The web proxy test and YouTube info/cover fetch were failing without actionable diagnostics. In practice, the active config had `proxy_url` set to a YouTube video URL instead of an actual proxy endpoint, so the app was trying to use a webpage as a proxy.

### Changes Made

- `ui_server.py`
  - Added `validate_proxy_url()` to reject non-proxy URLs before they reach `yt-dlp` or `httpx`.
  - Added `proxy_connection_error()` for explicit socket-level proxy failure text.
  - `test_proxy_connection()` now probes:
    - the proxy socket itself
    - `https://www.youtube.com`
    - `https://i.ytimg.com/...`
  - Proxy test results now include `exception_type`, `raw_error`, `active_proxy_url`, and `proxy_validation_error`.
  - `/api/youtube-meta` and `/api/youtube-cover` now return structured error payloads with:
    - `error`
    - `error_detail`
    - `operation`
    - `proxy_url`
    - `mode`
    - `exception_type`
    - `traceback`

- `youtube_meta.py`
  - Wrapped `yt-dlp` metadata fetch and cover download failures in more explicit `RuntimeError`s that mention whether a proxy was used.
  - Cover download fallback now reports both the primary and fallback failure.

- `test_proxy_youtube_diagnostics.py`
  - Added coverage for invalid proxy URLs, unreachable proxies, and primary/fallback cover download failures.

### Validation Results

- `$env:PYTHONPATH='D:\'; python -m pytest test_proxy_youtube_diagnostics.py -q`
  - `4 passed`
- `python -m py_compile ui_server.py youtube_meta.py`
- `node --check web\app.js`
- Live local diagnostic with the current bad config now reports:
  - `proxy_validation_error = Proxy URL looks like a web page, not a proxy endpoint...`
  - `active_proxy_url = ""`
  - direct YouTube page/image probes both returned `200`

### Known Remaining Issue

- The frontend still needs the proxy input corrected in the saved config. The code now blocks bad proxy values and shows a concrete error, but it will not silently fix the stored config for the user.

## Phase 3.3 Update - Bilibili Duplicate Search - 2026-06-17

### New Module

- `bilibili_search.py`
  - `build_bilibili_query_plan()` creates rule-based English, Chinese, mixed, and semantic Bilibili search queries.
  - `search_bilibili()` performs lightweight Bilibili search page requests with proxy support, timeout, User-Agent, and low request volume.
  - `parse_bilibili_search_results()` extracts candidates from embedded JSON or HTML anchors.
  - `score_bilibili_candidate()` emits `score`, `confidence`, `reason_codes`, `evidence`, and score parts.
  - `build_bilibili_duplicate_report()` and `write_bilibili_duplicate_artifacts()` create stable `00b_*` outputs.

### New API

- `POST /api/bilibili-duplicate-search`
  - Input: `url`, `config`, optional `youtube_meta`.
  - Output: `ok`, `report`, `output_dir`, `report_path`, `candidates_tsv_path`, `queries_path`.
  - Proxy validation errors reuse the YouTube diagnostics shape with `operation`, `proxy_url`, `mode`, `error_detail`, and `traceback`.

### New Artifacts

- `00b_bilibili_duplicate_search.json`
- `00b_bilibili_duplicate_candidates.tsv`
- `00b_bilibili_search_queries.json`

### Frontend

- Added `检测 B 站已有翻译` near the YouTube metadata controls.
- Added a Bilibili status card showing best candidate, top 5 candidates, scores, reason codes, video links, and manual search links.
- Detection is advisory only; it does not block download or translation.
- Added a medium-width layout fix so the sticky command bar no longer covers the YouTube/Bilibili controls at 1280x720.

### Validation Results

- `pytest test_bilibili_query_plan.py test_bilibili_candidate_scoring.py test_bilibili_search_parsing.py test_ui_server_bilibili_api.py`
  - `9 passed`
  - final rerun: `9 passed in 1.29s`
- `python -m py_compile bilibili_search.py ui_server.py`
- `node --check web\app.js`
- Live local API request:
  - `POST /api/bilibili-duplicate-search`
  - `ok = true`
  - `decision = no_candidates_manual_review`
  - artifact paths existed for JSON, TSV, and query-plan JSON.
- Browser UI verification:
  - button count was `1`.
  - real click at 1280x720 rendered the Bilibili card.
  - current saved proxy field is still invalid, so the UI correctly surfaced the structured proxy validation error.
  - clickability checked at 375, 768, 1280, and 1920 px widths with no horizontal overflow.

### Known Remaining Issues

- Bilibili search HTML may change; fallback search URLs are therefore part of the normal contract.
- Query generation is rule-based. It handles common local mappings and mixed terms but is not a full translation system.
- Candidate scoring is conservative and should be treated as review guidance, not an automatic blocker.
- The saved proxy field should be blank or a real endpoint such as `http://127.0.0.1:7890`; a YouTube URL in that field is rejected by design.
