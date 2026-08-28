# Russian Reference Layer Full-Split Task

## Purpose

This document is a focused execution guide for the next AI or developer who will continue the Russian subtitle workflow work.

The immediate task is:

- keep all Russian reference-layer text visible in the final bilingual subtitle output
- stop replacing long Russian reference text with ellipses
- prefer automatic semantic splitting over truncation
- preserve the current Russian workflow defaults, including `Huiwen-HKHei` as the Russian reference-layer font

This is **not** a general project overview. It is a targeted implementation brief.

## Current Problem

The Russian bilingual subtitle output currently uses a reference-layer display path that can truncate long reference text and replace the tail with `...` or `…`.

This happens because:

1. the reference layer still reuses logic originally designed for short English reference subtitles
2. `compact_reference_text()` truncates long strings
3. `reference_mode` can still prefer compacting or hiding instead of semantic splitting

Relevant file:

- [subtitle_io.py](D:/autosub_zh/subtitle_io.py)

Important functions:

- `compact_reference_text()`
- `apply_reference_mode_to_cue()`
- `split_english_text()`
- `split_segment_for_bilingual_ass()`
- `write_bilingual_ass()`

## Non-Negotiable Goal

For Russian bilingual subtitle output:

- do **not** use ellipsis as a normal fallback for overlong reference lines
- do **not** silently hide Russian reference text in the final export
- do **not** compress away meaning just to satisfy a fixed line width
- when the line is too long, automatically split it into multiple subtitle segments

The phrase the user gave is effectively:

> all textual content must appear in the final video whenever possible

## Scope

This task is specifically about:

- the Russian reference layer in bilingual subtitles
- output mode: `bilingual_source_reference`

This task is **not** about:

- rewriting the main Chinese subtitle translation system
- changing English subtitle workflows globally
- redesigning the entire UI

## Current Russian Defaults

Current Russian workflow profile:

- [workflow_profiles/ru_to_zh_default.json](D:/autosub_zh/workflow_profiles/ru_to_zh_default.json)

Current state:

- `src_lang = ru`
- `dst_lang = zh-Hans`
- `model = large-v3`
- `en_font_name = Huiwen-HKHei`
- `reference_mode = hide_when_overflow`

This last setting is the main problem.

## Required Design Change

Introduce a new reference-layer mode:

- `full_split`

Meaning:

- never truncate with ellipsis
- never hide because of overflow
- always attempt semantic splitting first
- only fail into a warning state if splitting is impossible

## Suggested Implementation

### 1. Add a new reference mode

In [models.py](D:/autosub_zh/models.py), the style model already holds:

- `reference_mode`

No schema change may be needed, but the code paths that interpret the value must support:

- `full`
- `compact`
- `hide_when_overflow`
- `full_split`  ← new

### 2. Stop truncation for Russian workflows

In [subtitle_io.py](D:/autosub_zh/subtitle_io.py):

- `compact_reference_text()` should continue to exist for English workflows
- but Russian bilingual reference text should not go through this truncation path when `reference_mode = full_split`

### 3. Generalize splitting away from “English-only”

The current splitting path uses:

- `split_english_text()`

This should be refactored into a more general reference-layer split strategy.

Suggested shape:

```python
def split_reference_text(text: str, *, lang: str, max_chars: int, max_parts: int) -> list[str]:
    ...
```

Behavior:

- `lang="en"` can continue using the existing English split heuristics
- `lang="ru"` should prefer punctuation and clause-level breaks

### 4. Russian split heuristics

For Russian, candidate break points should prefer:

- punctuation:
  - `.`
  - `,`
  - `;`
  - `:`
  - `?`
  - `!`
  - `—`
- conjunction and clause boundaries:
  - `что`
  - `когда`
  - `потому что`
  - `если`
  - `но`
  - `а`
  - `и`
  - `чтобы`
  - `который`
  - `где`
  - `как`

Avoid:

- leaving a conjunction or function word alone
- splitting in the middle of names
- splitting in the middle of quoted titles
- splitting in the middle of hyphenated transliterations

### 5. Use word timestamps when possible

If the source segment has word timing:

- derive split segment times from the actual word boundaries

Fallback:

- if no word timing is available, split duration proportionally by text length

### 6. Keep Chinese alignment sensible

When the Russian reference layer is split into multiple cues:

- Chinese text should remain aligned per cue
- do not explode Chinese into tiny fragments
- do not repeat the entire Chinese sentence for every Russian split piece

Existing helpers in [subtitle_io.py](D:/autosub_zh/subtitle_io.py) can likely be reused:

- `build_chinese_groups_for_english()`
- `merge_english_groups_for_alignment()`
- `split_chinese_for_parts()`

They will likely need renaming or generalization because they are currently English-centric in naming.

## UI Changes

Relevant files:

- [web/index.html](D:/autosub_zh/web/index.html)
- [web/app.js](D:/autosub_zh/web/app.js)

Required UI work:

1. expose `full_split` in the reference mode selector
2. make the workflow page clearly show that Russian uses a full-display reference strategy
3. ensure save/refresh/profile-switch round trips preserve `reference_mode = full_split`

## Default Settings To Change

For the Russian workflow profile:

- set `reference_mode = full_split`
- keep `en_font_name = Huiwen-HKHei`

Optional tuning:

- increase `en_max_split_parts`
- set `en_max_single_line_chars` to a Russian-friendly value such as `48` or `52`

## Recommended Parameter Direction

For Russian bilingual reference layer:

- `reference_mode = full_split`
- `en_font_name = Huiwen-HKHei`
- `en_max_single_line_chars = 48` to `52`
- `en_max_split_parts = 4`
- `min_split_duration = 1.2`

Reason:

- more split headroom
- less pressure to compact
- lower chance of ellipsis or hidden text

## QA Requirements

Do not rely on visual inspection only.

Add checks for:

1. no generated Russian reference cue should end with `...` or `…` unless the source itself truly ends that way
2. no Russian reference cue should be silently dropped in `bilingual_source_reference`
3. no cue should split inside a known protected title or protected proper name

Relevant files:

- [qa.py](D:/autosub_zh/qa.py)
- [test_subtitle_output_modes.py](D:/autosub_zh/test_subtitle_output_modes.py)

## Suggested Test Additions

Add focused tests for:

1. long Russian reference text in `full_split` mode becomes multiple cues
2. no ellipsis is introduced by the formatting logic
3. protected titles like `Xiu Xiu: The Sent-Down Girl` are not broken incorrectly
4. `reference_mode` survives profile loading, save, and reload

## Known Current Pain Points

These have already been observed:

- many Russian reference cues are truncated
- some cues are fragmented into isolated short pieces like `я`
- some historic ASR or normalization issues remain in reference text
- title lines can still be split awkwardly

## Execution Order

Recommended order:

1. implement `full_split` reference mode
2. generalize reference-layer split logic
3. wire `full_split` into Russian workflow defaults
4. add tests
5. generate a fresh 60s Russian bilingual ASS
6. verify there are no generated ellipses in the Russian layer
7. only then re-run longer previews or full video

## Acceptance Criteria

This task is done when:

1. Russian bilingual subtitle output no longer introduces ellipses due to overflow
2. long Russian reference text is split into multiple readable cues
3. the Russian workflow profile defaults to the new full-display behavior
4. the UI selector preserves the chosen mode
5. focused tests pass
6. a 60s verification ASS confirms the behavior visually

## Do Not Break

Avoid these regressions:

- do not remove `compact` for English workflows
- do not change the Chinese subtitle wrapping behavior unnecessarily
- do not change full-project output naming again
- do not alter the existing Russian font default away from `Huiwen-HKHei`
