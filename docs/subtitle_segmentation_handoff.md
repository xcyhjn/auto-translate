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
