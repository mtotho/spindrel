---
title: Bot-readable internal docs
summary: Give runtime bots a way to read /app/docs/ so canonical contributor guides are reachable from a bot turn. Unblocks demoting oversized reference skills.
status: active
tags: [spindrel, track, skills, docs, runtime]
created: 2026-05-03
updated: 2026-05-03
---

# Bot-readable internal docs

## North Star

Runtime bots can reach the canonical project docs (`/app/docs/` in the
container) the same way they reach skills today: by ID, on demand, without
trying to ambiently load every guide. Once that mechanism exists, oversized
reference-manual skills demote into `docs/reference/` without stranding their
content.

Today bots **cannot** read `/app/docs/`:

- `get_skill` reads the skill DB.
- `file()` is workspace-scoped and never crosses into `/app/docs/`.
- `docs/` is copied into the container but exposed nowhere to runtime bots.

## Status

| Phase | State | Updated |
|---|---|---|
| 1. Pick depth | not started | — |
| 2. Implement chosen mechanism | not started | — |
| 3. Demote oversized reference skills | blocked on phases 1+2 | — |
| 4. Sweep widget descriptions | not started | — |

## Phase Detail

### 1. Pick depth

Three options identified during the 2026-05-03 audit:

- **Cheap** — mirror `/app/docs/` into `/workspace/common/docs/` at boot, reuse the existing `file()` tool. Approx. 10 lines in the container entrypoint. Zero new tools, zero new RAG cost.
- **Medium (recommended default)** — new `get_doc(path)` + `list_docs(area)` tool pair (~100 lines), mirroring the `get_skill` shape (`app/agent/skills.py:17–146`, `app/tools/local/skills.py:63–142`). Read-only by design. Namespaced separately from skills so semantic discovery is unchanged.
- **Deep** — ingest `docs/` into RAG via a new scope in `app/services/bot_indexing.py:53–76` so docs surface in semantic discovery alongside skills. Highest cost; only justified if "discoverability" beats "explicit fetch".

Defer the actual choice to this track's first slice. The medium path is the recommended default until a concrete reason to upgrade or downgrade surfaces.

### 2. Implement chosen mechanism

Add the tool(s); register in the tool catalog; add unit tests; advertise via the runtime base prompt or a small new skill (`skills/internal_docs.md`).

### 3. Demote oversized reference skills

Once the mechanism exists, demote:

- `widgets/sdk.md` (639 lines, SDK reference) → `docs/reference/widgets/sdk.md`.
- `widgets/styling.md` (384, CSS class catalog) → `docs/reference/widgets/styling.md`.
- `widgets/html.md` (353, bundle layout reference) → `docs/reference/widgets/html.md`.
- `pipelines/authoring.md` (540, schema reference) → `docs/reference/pipelines/authoring.md`.
- `orchestrator/workspace_api_reference.md` (90, API reference) — already moved by the orchestrator-dissolution track; coordinate.

Each demotion: move the body to `docs/reference/<area>-<topic>.md`, leave a 30–50 line procedural skill that links to the doc using the new mechanism.

### 4. Sweep widget descriptions

Twelve widget skills have frontmatter `description` over 280 chars (worst: `widgets/errors.md` at 553). Trim to ~200; push detail to body. Independent of the wiki mechanism — could land before phases 1–3.

## Key Invariants

- Phase 3 demotion **must** wait on phase 2. Without the mechanism, demoting strands content. Do not demote a single oversized skill before there is a way to retrieve the relocated doc body.
- The new mechanism is read-only. No write-from-bot path lands in this track. Adding mutation would re-open the auth/permissions story; keep it out of scope.
- Don't conflate this with skill demotion in general. Plenty of skills should stay skills; only oversized **reference manuals** are candidates for demotion to `docs/reference/`.

## References

- Plan: `docs/plans/spindrel-skills-cohesion.md` — the parent plan that stubs this track.
- Roadmap row: see "Bot-readable internal docs" entry in `docs/roadmap.md`.
- Companion track: [[Orchestrator Dissolution]] — `workspace_api_reference.md` is being moved by that track and does not block this one.
- Read pipeline reference: `app/agent/skills.py:17–146`, `app/tools/local/skills.py:63–142`.
- RAG ingest reference: `app/services/bot_indexing.py:53–76`.
