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
