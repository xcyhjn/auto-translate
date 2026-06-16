# Subtitle Segmentation Ops Log

## 2026-06-17 00:05 +08:00 - Baseline Audit

What:

- Audited `08_bilingual_zh_en.ass`, `03_timed_source_segments.json`, and `04a_source_spans.json`.
- Reviewed `timing.py`, `source_spans.py`, `models.py`, and `pipeline_core.py`.

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

- Ran `python -m py_compile` for `models.py`, `timing.py`, `source_spans.py`, and `test_timing_segmentation.py`.
- Ran `pytest -q test_timing_segmentation.py`.
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
