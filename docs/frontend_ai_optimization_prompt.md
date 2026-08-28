# Frontend AI Optimization Prompt

Use this prompt in a new AI conversation when you want the next AI to fully inspect and optimize the frontend for this project.

Copy from the line below.

---

You are taking over a local coding project with an existing backend subtitle pipeline and a lightweight local web UI.

## Non-negotiable bootstrap

Before doing anything else, you MUST read this exact local file from disk first:

- `D:\autosub_zh\docs\frontend_handoff_and_project_status.md`

Do not summarize from memory. Do not skip it. Do not start frontend changes before reading it.

After that, read these files in this order:

- [frontend_handoff_and_project_status.md](D:/autosub_zh/docs/frontend_handoff_and_project_status.md)
- [entity_normalization_handoff.md](D:/autosub_zh/docs/entity_normalization_handoff.md)
- [russian_reference_layer_full_split_task.md](D:/autosub_zh/docs/russian_reference_layer_full_split_task.md)
- [web/index.html](D:/autosub_zh/web/index.html)
- [web/app.js](D:/autosub_zh/web/app.js)
- [web/styles.css](D:/autosub_zh/web/styles.css)
- [ui_server.py](D:/autosub_zh/ui_server.py)
- [pipeline_core.py](D:/autosub_zh/pipeline_core.py)

If you cannot read `D:\autosub_zh\docs\frontend_handoff_and_project_status.md`, stop and report that explicitly before proceeding.

Your job is to perform a full frontend audit and then improve the frontend in a way that fully reflects the current backend capabilities.

## Required approach

Use the following skill mindset while working:

- `experience-and-design-system`:
  - use it actively for layout hierarchy, typography, spacing, component polish, and avoiding generic AI-looking UI decisions
- `motion-and-interaction-system`:
  - use it for interaction polish, hover/focus/active states, and only meaningful animation
- `docs-write`:
  - keep written findings and UI copy clear, concrete, and user-focused
- `Verification & Quality Assurance`:
  - validate what the frontend actually exposes versus what the backend already produces
  - do not assume a capability exists in the UI just because it exists in backend files
- `create-plan`:
  - create a crisp execution plan before large edits if needed, but do not stop at planning; implement

Browser requirement:

- use the Browser plugin skill `control-in-app-browser` to inspect and verify the local UI after meaningful frontend changes

Conditional skill:

- `canvas-design`
  - only use this if you need to create a static visual artifact or highly composed design asset; do not use it as a substitute for normal application UI work

## Project context you must honor

The backend already supports:

- `reference_text` as normalized English reference text distinct from raw `source_text`
- entity normalization outputs:
  - `06e_entity_decisions.json`
  - `06f_entity_review.tsv`
  - `06g_entity_normalized_segments.json`
  - `07h_entity_qa.tsv`
  - `07i_entity_metrics.json`
  - `08b_ass_entity_audit.json`
- project-level `00_entity_decisions.json`
- `bootstrap_entity_decisions` modes:
  - `off`
  - `always`
  - `high_confidence_only`

The current frontend does not fully surface these capabilities yet.

## Your responsibilities

1. Audit the current frontend thoroughly.
2. Identify where the frontend is out of sync with backend outputs and config.
3. Propose a frontend information architecture that cleanly separates:
   - pipeline controls
   - progress/status
   - artifact inspection
   - entity review / QA
4. Implement the highest-value improvements directly.
5. Verify the resulting UI in the browser, not only in code.

## Execution contract

Do this in order:

1. Read `D:\autosub_zh\docs\frontend_handoff_and_project_status.md`.
2. Read the additional backend/frontend handoff files listed above.
3. Audit the current frontend implementation and list concrete UI/backend mismatch points.
4. Implement the highest-value frontend fixes instead of stopping at recommendations.
5. Verify the changed UI using the in-app browser.
6. Report:
   - what the frontend was missing,
   - what you changed,
   - how you verified it,
   - what still remains.

Do not stay at analysis-only. Do not stop after writing a plan.

## Must-check frontend questions

Answer these by inspecting code, not by guessing:

1. Can the frontend show `reference_text` anywhere today?
2. Can the frontend expose or configure `bootstrap_entity_decisions`?
3. Can the frontend show entity metrics from `07i_entity_metrics.json`?
4. Can the frontend show entity review rows from `06f_entity_review.tsv`?
5. Can the frontend show entity QA rows from `07h_entity_qa.tsv`?
6. Does the frontend distinguish raw source text from normalized reference text?
7. Is the current layout optimized for scanning project artifacts and QA outputs?
8. Does the frontend expose `entity_type` in a useful way anywhere?
9. Does the frontend expose whether `00_entity_decisions.json` exists for the current project?
10. Does the frontend expose the current bootstrap mode cleanly?

## Implementation priorities

Prioritize in this order:

1. Add an Entity summary panel driven by `07i_entity_metrics.json`
2. Add an Entity review section for:
   - `06f_entity_review.tsv`
   - `07h_entity_qa.tsv`
3. Add `reference_text` visibility in relevant review/debug views
4. Add bootstrap mode controls in config UI
5. Add project decisions visibility (`00_entity_decisions.json` existence/state)
6. Improve visual grouping of pipeline controls vs outputs vs review

Throughout implementation:

- apply `experience-and-design-system` to visual hierarchy and component decisions
- apply `motion-and-interaction-system` after structure is solid, not before
- verify the result through `control-in-app-browser`

## UX expectations

Do not make cosmetic-only changes.

The frontend should become better at:

- exposing backend truth clearly
- helping a human inspect subtitle outputs
- helping a human spot entity issues quickly
- showing what the system already normalized automatically
- showing what still needs human review
- making `reference_text` understandable to a human reviewer
- making entity outputs feel like first-class review surfaces rather than hidden backend artifacts

The interface should feel work-oriented, readable, and practical.

## Technical expectations

- Reuse existing local patterns when possible
- Avoid giant rewrites unless truly necessary
- Keep changes incremental and testable
- If you add new client-side state or parsing helpers, keep them focused
- If the UI depends on backend payloads that are missing, identify that precisely before changing backend contracts

## Verification requirements

Before you finish:

1. Verify the frontend renders cleanly
2. Verify the new entity-related UI reads real backend artifacts or payloads
3. Verify config changes survive save/reload where appropriate
4. Verify desktop and mobile do not collapse into broken layouts
5. Explain exactly what frontend gaps were found and which ones you fixed

When verifying:

- do not rely only on code inspection
- use the in-app browser to inspect the real UI state
- if the interface changed materially, take verification screenshots
- verify the frontend is actually reading or surfacing real backend artifacts, not placeholder mock data

## Expected deliverable shape

Your final result should include:

- a short frontend audit summary
- the implemented frontend changes
- verification evidence
- the remaining frontend improvement opportunities

Do not return only a proposal unless you are hard-blocked by missing local context or a broken runtime.

## Final deliverable

Do not stop at analysis.

You should:

- inspect
- identify gaps
- implement meaningful frontend improvements
- verify them
- summarize the new frontend state clearly

---
