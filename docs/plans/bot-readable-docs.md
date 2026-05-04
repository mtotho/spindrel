---
title: Bot-readable internal docs — implementation plan
summary: Add `get_doc(id)` + `list_docs(area)` runtime tools, then demote four oversized reference-manual skills (widgets/sdk, widgets/styling, widgets/html, pipelines/authoring) into docs/reference/.
status: executed
tags: [spindrel, plan, skills, docs, runtime]
created: 2026-05-03
updated: 2026-05-04
---

> **Executed 2026-05-04.** Phase 1: `app/agent/docs.py` + `app/tools/local/docs.py` registered, base-prompt advertises `get_doc(id)` / `list_docs(area)`. Phase 2: 11 skill descriptions trimmed under the 280-char cap; `tests/unit/test_skill_frontmatter.py` enforces it. Phase 3: four skills demoted — bodies live at `docs/reference/widgets/{sdk,styling,html}.md` and `docs/reference/pipelines/authoring.md`; the same skill IDs now host 47–56-line procedural stubs that route to the doc.

# Bot-readable internal docs — implementation plan

Runtime bots can fetch any doc under `/app/docs/` by ID, the same way they fetch a skill. Once the mechanism exists, four oversized reference-manual skills demote into `docs/reference/`.

## Why

`get_skill` reads the skill DB. `file()` is workspace-scoped. `/app/docs/` is copied into the container at build time but exposed to no runtime tool. A bot reading `widgets/sdk.md` (639 lines of SDK reference) can't be told "the reference moved to `docs/reference/widgets/sdk.md`" because no runtime tool can reach `/app/docs/`.

## Decisions (locked)

- **Mechanism: medium.** New `get_doc(id)` + `list_docs(area)` tools, ~100 LOC, mirroring the `get_skill` shape. Read-only by signature. Namespaced separately from skills so semantic discovery is unchanged. No RAG ingest, no boot-time mirror, no `file()` policy work.
- **Tool names:** `get_doc`, `list_docs`. Match `get_skill` / `list_skills`.
- **ID shape: extension-less.** `get_doc("reference/widgets/sdk")` resolves `/app/docs/reference/widgets/sdk.md`. Matches `get_skill` IDs.
- **Demotion list (4):** `widgets/sdk.md` (639), `widgets/styling.md` (384), `widgets/html.md` (353), `pipelines/authoring.md` (540). Demoted in this order — biggest stranded-content risk closes first.
- **Drop `orchestrator/workspace_api_reference.md` from the demotion list.** [`orchestrator-dissolution`](orchestrator-dissolution.md) deletes it, doesn't move it.
- **Frontmatter for `docs/reference/`:** `title` + `summary` + `tags`. No `status` (reference docs are reference; no lifecycle).
- **Read-only enforcement:** by signature — there is no `set_doc`. No further hardening needed.
- **Safety tier:** `hygiene` (read-only). No approval gate.

## Phases

### Phase 1 — Implement the tools

`app/agent/docs.py` (new), modeled on `app/agent/skills.py:17–146`:

- `load_doc(id) -> Doc | None` — resolves `id` to `/app/docs/<id>.md`, returns `(title, summary, tags, body)` from frontmatter + content. Reject `id` containing `..` or starting with `/`.
- `list_docs(area=None) -> list[DocSummary]` — walks `/app/docs/`, returns `(id, title, summary, tags)`. Filter by top-level area when `area` provided (e.g. `area="reference"` → only `reference/*`).

`app/tools/local/docs.py` (new), modeled on `app/tools/local/skills.py:63–142`:

- `get_doc(id: str) -> dict` — `{id, title, summary, tags, body}` or error.
- `list_docs(area: str | None = None) -> list[dict]` — summaries.
- Register both in the tool catalog with `safety_tier="hygiene"`.

Tests: `tests/unit/test_get_doc.py`, `tests/unit/test_list_docs.py`. Cover frontmatter parsing, path-traversal rejection, missing-doc error, area filter.

Advertise the new tools in the runtime base prompt with one line — no new skill needed.

### Phase 2 — Widget description sweep (independent)

Twelve widget skills have frontmatter `description` over 280 chars (worst: `widgets/errors.md` at 553). Trim to ~200; push detail to body. Independent of the mechanism — can land in parallel with phase 1 or before it.

Verification: lint pass at `tests/unit/test_skill_frontmatter.py` (add or extend a description-length cap).

### Phase 3 — Demote four reference skills

One PR per skill, in size order:

1. `widgets/sdk.md` (639) → `docs/reference/widgets/sdk.md`.
2. `pipelines/authoring.md` (540) → `docs/reference/pipelines/authoring.md`.
3. `widgets/styling.md` (384) → `docs/reference/widgets/styling.md`.
4. `widgets/html.md` (353) → `docs/reference/widgets/html.md`.

Each demotion:

- Move the body verbatim to `docs/reference/<area>/<topic>.md`. Add `docs/reference/` frontmatter.
- Replace the skill body with a 30–50 line procedural stub at the same skill ID. The stub:
  - Keeps the original skill ID so existing fetches don't break.
  - Explains the procedural "when do I need this and what's in there".
  - Links to the doc using `get_doc("reference/<area>/<topic>")`.
  - Does not duplicate any reference content.
- Update the cluster `index.md` to reflect the trimmed body.

Verification per demotion: `skills.recommended_now` still surfaces the procedural stub for representative prompts. Hand-spot-check, no full regression suite.

## Risks

- **Skill ranker drift.** Trimmed bodies change embeddings. Mitigation: spot-check `skills.recommended_now` after each demotion; if a relevant prompt stops surfacing the stub, expand the stub procedural text.
- **Tool budget.** `get_doc` + `list_docs` add two slots. Confirm they fit the starter set per `docs/guides/discovery-and-enrollment.md`. If not, fetch on demand.
- **Reference doc drift.** Once content lives in `docs/reference/`, it's outside the skill review loop. Owner: track owners of each subsystem treat `docs/reference/<area>/*` as part of their guide-update discipline.

## Out of scope

- General doc-reading across the whole repo. This track is internal *reference manuals*, not arbitrary docs/code.
- Write-from-bot path. No `set_doc`. Re-opening the auth/permissions story is a separate product question.
- Demoting non-reference skills. Plenty of skills should stay skills; only oversized reference manuals demote.

## References

- Track: [[bot-readable-docs]]
- Sibling plan: [`docs/plans/orchestrator-dissolution.md`](orchestrator-dissolution.md) — deletes `workspace_api_reference.md` so it's off this list.
- Read pipeline reference: `app/agent/skills.py:17–146`, `app/tools/local/skills.py:63–142`.
- Discovery contract: `docs/guides/discovery-and-enrollment.md`.
