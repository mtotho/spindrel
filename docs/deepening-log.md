---
title: Deepening log
summary: Append-only record of architectural deepenings (shallow→deep refactors). Read by the improve-codebase-architecture skill to avoid re-suggesting completed work and to spot drift.
status: archive
tags: [spindrel, architecture]
created: 2026-05-02
updated: 2026-05-03
---

# Deepening log

Append-only. Each entry records a deepening that landed: where the seam now lives, what was consolidated, and the friction it resolved. The `improve-codebase-architecture` skill reads this on every run — entries here are the "don't re-suggest, do drift-check" set.

## Entry schema

```
## YYYY-MM-DD — <module name>
- **Seam**: <file path or interface location>
- **What deepened**: 1–2 lines on what consolidated
- **Why**: the friction it resolved
- **Track / ADR**: optional link
```

Vocabulary: see `.claude/skills/improve-codebase-architecture/LANGUAGE.md` (module, interface, seam, adapter, depth, leverage, locality).

## Entries

## 2026-05-03 — Tool Surface composition

- **Seam**: `app/agent/tool_surface/` package (`composer.compose_stream`, `heartbeat`, `retrieval`, `enrollment`, `finalize`, `types.ToolSurfaceResult`).
- **What deepened**: Tool-surface composition extracted from `app/agent/context_assembly.py`. Heartbeat determinism, RAG retrieval, skill enrollment loading, and exposure finalization (dynamic injection + widget-handler bridge + capability gate) now live behind one `compose_stream(...)` AsyncGenerator. `assemble_context` collapsed three stages (retrieval / heartbeat-branch / finalize) into one streaming call. `context_assembly.py` shrunk 3240 → 2401 lines (−839); the new package totals ~1170 LOC across six small modules. Tests migrated to `tests/unit/test_tool_surface_composer.py` and patched at the new module paths; ADR-pinned `test_heartbeat_does_not_call_retrieve_tools` guard added.
- **Why**: The "what tools does the LLM see this turn?" question was scattered across `_compose_heartbeat_tool_surface`, `_run_tool_retrieval`, `_finalize_exposed_tools`, plus `_load_skill_enrollments` / `_apply_ephemeral_skills` / `_get_*_skill_ids` cache helpers — five concerns in one 3240-line module. Heartbeat-determinism regressions had to be traced across four helpers + channel overrides; new policies (memory_flush mode added in `7f8b9d2e`) required threading through three call sites. Locality and a single test surface were missing.
- **Track / ADR**: `docs/tracks/architecture-deepening.md` candidate #1. Out-of-scope (tracked as future candidates): loop-iteration tool-surface guard at `loop_helpers._resolve_loop_tools`; `app/services/skill_enrollment.py` canonical service stays put.
