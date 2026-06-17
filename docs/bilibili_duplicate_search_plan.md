# Bilibili Duplicate Search Plan

## Current problem
Users often want to know whether a YouTube video has already been reposted or translated on Bilibili before starting work. The current workflow can fetch YouTube metadata, cover, and subtitles, but it has no built-in duplicate or translation check against Bilibili.

## Why not only search the original title
Many Bilibili uploads are retitled, translated, or rewritten. Searching only the original English title misses:
- translated titles
- shortened titles
- mixed Chinese/English titles
- titles built around only the topic, not the original wording

## Query strategy
The search plan generates a small set of deduplicated queries, capped at 12 total:
- original YouTube title
- cleaned title without brackets / episode markers
- core English noun phrases
- translated Chinese topic terms
- mixed Chinese/English variants that keep proper names in English
- semantic variants such as direct translation, loose translation, and topic-only combinations

The implementation is rule-based first. It can be extended later with optional LLM-generated query variants, but failure to generate extra variants never blocks the search.

## Scoring
Each candidate is scored with explainable signals:
- title similarity, 0-35
- semantic keyword overlap, 0-25
- duration closeness, 0-15
- source evidence, 0-10
- publication timing, 0-5
- negative penalties for unrelated, derivative, or generic matches

Thresholds:
- `>= 80` `high_confidence_possible_duplicate`
- `60-79` `medium_confidence_review`
- `40-59` `low_confidence_related`
- `< 40` ignore or debug only

## API and artifacts
New API:
- `POST /api/bilibili-duplicate-search`

The user does not need to click the YouTube info button first. If `youtube_meta` is already available, the API reuses it; otherwise it fetches YouTube metadata internally before building Bilibili queries. The search still depends on metadata, because title and duration are required for useful query generation and scoring.

If the search runs but does not find parseable candidates, the UI should say so explicitly and keep the manual search links. Only a total inability to search should be treated as a failure.

Artifacts written into the selected output folder:
- `00b_bilibili_duplicate_search.json`
- `00b_bilibili_duplicate_candidates.tsv`
- `00b_bilibili_search_queries.json`

The JSON report includes:
- input URL
- YouTube meta
- query plan
- executed queries
- scored candidates
- scoring summary
- best candidate
- decision
- errors
- proxy info
- created_at

## Frontend
The YouTube info area now includes a Bilibili duplicate check entry point. The UI shows:
- detection state
- best candidate
- top candidates
- score
- reason codes
- title / uploader / duration / published time
- direct Bilibili URL
- direct search URL

If parsing fails, the UI still exposes the generated search URLs for manual review.

## Verification
Validation should cover:
- rule-based query generation
- candidate scoring
- HTML parsing fallback
- API schema
- proxy validation errors
- local UI rendering

## Risks and fallback
- Bilibili HTML can change.
- Search pages can render dynamically.
- Proxy connectivity may fail.

Fallback behavior:
- keep the raw search URL
- surface a manual-open link
- do not block the main translation workflow
- treat parsing failure as a normal downgrade, not a hard failure
