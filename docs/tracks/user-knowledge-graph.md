---
title: User Knowledge Graph
summary: Close Olivia's "the bot isn't learning" gap. The bots already maintain rich memory/reference/ libraries via memory_hygiene; the bug is they're not retrieved into context. Plan adds semantic auto-retrieval on memory/reference, tightens hygiene cadence, deletes the parallel per-turn capture store that shipped as Phase 1.
tags: [spindrel, track, knowledge, memory, retrieval]
status: active
created: 2026-05-03
updated: 2026-05-04
---

# User Knowledge Graph

Plan: [`docs/plans/user-knowledge-graph.md`](../plans/user-knowledge-graph.md). Read the plan for the live-server findings, the actual bug, and the P1-P4 design.

## North star

When Olivia teaches Sprout something today, Sprout reliably uses it tomorrow — without a parallel capture pipeline, without a review queue, without a new UI. Reuse what's already working (`memory_hygiene` writes good reference docs) and fix the gap that makes it feel like the bot isn't learning (those docs aren't being retrieved into context).

## Status

| Phase | What | Status |
|---|---|---|
| 0 | Fix KB retrieval prefix scoping in `retrieve_filesystem_context`. | done |
| 0.5 | Knowledge Document primitive (Notes substrate). User-scope helper deleted by P4; channel/project scopes stay. | partial — substrate landed; user-scope path is being removed |
| Phase 1 (per-turn extractor) | Originally shipped. **Replaced by P4 cleanup.** Per-turn extraction is the wrong unit and competes with the hygiene-curated `memory/reference/` system. | shipped, removing |
| Phase 2 / 3 (per-user contract, scope-invisible UI) | Deferred indefinitely. Single-user reality doesn't justify the ceremony. | deferred |
| **P1** | Semantic auto-retrieval on `memory/reference/`. New `inject_bot_memory_reference()` mirroring `inject_bot_knowledge_base()`. New `bot_memory_reference_auto_retrieval` flag, default on, surfaced in the bot config UI Memory section. Per-chunk trace (file path + similarity) added so audits can tell relevant from noise. | shipped 2026-05-04 — load-bearing fix |
| **P2** | Section-finalize hygiene microbursts. Hook `_persist_section_and_summary` to enqueue a narrow `memory_hygiene` Task scoped to the just-persisted section. Daily hygiene stays. | not started |
| **P3** | Reference-file frontmatter `summary:` field. Hygiene skill writes one-liner summaries; existing reference-index injection surfaces them next to filename + mtime. Backfill via one hygiene pass per bot. | shipped 2026-05-04 (skill prompt + index renderer); backfill = first hygiene run per bot |
| **P4** | Cleanup the parallel store: `knowledge_capture.py`, `inject_user_knowledge`, `users/<user_id>/knowledge-base/notes/` capture path, `/admin/knowledge/review`, `KNOWLEDGE_CAPTURED` event, `bots.knowledge_capture_*` columns, `user_knowledge_surface()` helper. Channel/project Notes + the `KnowledgeDocument` primitive stay. | shipped 2026-05-04 — see `docs/fix-log.md` |
| P5 (later) | File-mode conversation section recall (was original Phase 4). | deferred |
| P6 (later) | Cross-source entity links (was original Phase 5). | deferred |

## Order of work

1. ~~**P4 first** — delete the parallel store. Frees naming, removes confusion, smaller surface than P1.~~ Shipped 2026-05-04.
2. ~~**P1** — the load-bearing fix.~~ Shipped 2026-05-04.
3. ~~**P3** — small follow-up (prompt + index renderer).~~ Shipped 2026-05-04.
4. **P2** — last; hygiene microbursts benefit from P1 already being live. **Pre-design check needed:** there are already compaction-time triggers (section finalize + memory flush). P2 adding a third hook risks redundancy — see the open question below.

## Why this plan and not the prior revisions

The original Phase 1-5 plan invented a per-turn extraction + review-queue system. The first revision pivoted to section-grain crystallization with an upsert synthesizer. Both were wrong because **the bots already maintain exactly the kind of living domain notebooks the product wanted, via `memory_hygiene`**. Sprout's `memory/MEMORY.md`, `plant-profiles.md`, `season-notes.md` and Crumb's `recipes.md`, `bake-log.md`, `starter-log.md` were verified live on 2026-05-03. The actual gap is retrieval: `memory/reference/` gets only a directory-listing in context, while `knowledge-base/` (which the bots barely use) gets full semantic retrieval. P1 fixes that asymmetry. P2-P3 sharpen cadence and content hints. P4 removes the parallel store that distracted from the real problem.

## Links

- Plan: [`docs/plans/user-knowledge-graph.md`](../plans/user-knowledge-graph.md).
- Adjacent: [`docs/tracks/agent-quality-observability.md`](agent-quality-observability.md) — per-chunk retrieval trace lands here.
- Hygiene skill (live server): `/app/skills/history_and_memory/memory_hygiene/index.md`.
- Anchors: `app/agent/context_admission.py:840` (P1 model), `app/services/compaction.py:1340` (P2 hook), `app/services/bot_indexing.py:25` (chunks already indexed), `app/services/knowledge_capture.py` (P4 deletes).
