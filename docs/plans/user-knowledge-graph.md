---
title: Plan - User Knowledge Graph (memory/reference retrieval + cleanup)
summary: Close Olivia's "the bot isn't learning" gap by adding semantic auto-retrieval on memory/reference (the folder the bots actually maintain), tightening hygiene cadence to fire after section finalize, and deleting the parallel per-turn capture store that shipped as Phase 1 and never delivered value.
status: active
tags: [spindrel, plan, knowledge, memory, retrieval]
created: 2026-05-03
updated: 2026-05-03
---

# Plan - User Knowledge Graph (memory/reference retrieval + cleanup)

> Replaces all prior revisions of this plan (the R1-R6 repivot, the Phase 1-5 original). Keep this short. The earlier prose is preserved in git history.

## What we found on the live server

Both Crumb (baking) and Sprout (gardening) already maintain rich, evolving curated reference libraries via `memory_hygiene`:

- olivia-bot: `memory/MEMORY.md` (key decisions + preferences with `[updated]` / `[confidence]` / `[source]` per line), `memory/plant-profiles.md` (per-plant entries), `memory/reference/garden-notes.md`, `season-notes.md` (Zone 7a timing), `garden-inventory.md`, `image-log.md`, `olivia-preferences.md`, `elevated-bed-layout.md`, `spatial.md`, `todos.md`. Daily logs in `memory/logs/archive/`. Bot-authored skills in `memory/skills/`. Hygiene Task ran 2026-05-03 09:01 UTC.
- baking-bot: `MEMORY.md` + `memory/reference/recipes.md`, `bake-log.md`, `starter-log.md`, `cheesecake-scaling.md`, `flour-inventory.md`, `zymia-profile.md`, `olivia-preferences.md`, `todos.md`. Bot-authored skill `cheesecake-scaling.md`. Hygiene Task ran 2026-05-03 08:16 UTC.

The hygiene skill's promotion rule (`/app/skills/history_and_memory/memory_hygiene/index.md`) is the product the original plan tried to invent:

> Stable user preferences, corrections, and durable facts go to memory.
> Reusable procedures or patterns go to skills.
> Detailed topical material goes to reference files.

**The capture system is not the problem.** Phase 1's per-turn extractor at `users/<user_id>/knowledge-base/notes/` is a parallel, weaker, review-gated store next to a system that already does the job better.

## What's actually broken

**The bots write good notes, but the notes don't come back into context on the right turns.** `app/agent/context_admission.py:252-272` injects `memory/reference/` only as a *directory listing* (filenames + mtimes + "use get_memory_file to read"). The bot has to guess from the filename. It often skips the read because a filename is a weak signal.

Compare `inject_bot_knowledge_base()` at `context_admission.py:840` — full semantic auto-retrieval against indexed chunks for `knowledge-base/` (the folder the bots barely use; baking-bot has one `untitled.md`). The folder the bots actually maintain (`memory/reference/`) gets no semantic retrieval, even though the chunks are already indexed (`app/services/bot_indexing.py:25`: `MEMORY_PATTERNS = ["memory/**/*.md"]`).

That asymmetry is the bug. Sprout's painstakingly maintained `plant-profiles.md` is invisible to a turn unless the bot decides to call `get_memory_file("plant-profiles.md")` based on filename alone.

Two secondary issues compound it:
- **Hygiene latency.** `memory_hygiene` runs once a day. Same-day teaching doesn't show up same-day in reference files.
- **No content hints in the index.** Even when the bot does fall back to the directory listing, it sees filenames not summaries, so it can't tell which file is relevant.

## Plan

### P1 - Semantic auto-retrieval on `memory/reference/` (the load-bearing fix)

Add `inject_bot_memory_reference()` modelled on `inject_bot_knowledge_base()` (`context_admission.py:840`). Path prefix: `memory/reference/` for standalone bots, `bots/<bot_id>/memory/reference/` for shared-workspace bots. Use the same `retrieve_filesystem_context` + `resolve_for(scope="workspace")` + `include_path_prefixes` flow.

- Wire a new flag `bot_memory_reference_auto_retrieval` on the bot's workspace/memory config. **Default: enabled.** Surface the toggle in the bot config UI's **Memory** section so it's discoverable next to existing memory-scheme controls.
- Honor the existing `context_profile.allow_memory_recent_logs` (or a sibling profile flag) so context profiles can opt out cleanly.
- Top-K and similarity threshold come from the same `BotIndexPlan` already used by `inject_bot_knowledge_base`; no new tuning surface.
- Existing `memory/reference/` directory-listing injection (`context_admission.py:252-283`) stays as a fallback — when semantic retrieval admits chunks, the listing becomes redundant and is suppressed; when retrieval is empty or below threshold, the listing still shows so the bot can fall back to `get_memory_file`.
- Trace finding emitted when admission decides `skipped_empty` or `skipped_by_budget` so `agent_quality_audit` surfaces gaps.
- **Per-chunk trace.** Today `retrieve_filesystem_context` returns only `(list[str], float)` — formatted chunks plus the single best similarity. The injection trace records aggregate `count` + `similarity` only, which is enough for "did retrieval fire" health audits but not for "was this chunk relevant or noise" audits. Extend the retrieval return shape (or add a sibling that returns `[{file_path, similarity, chars}]`) and have the new injector emit `chunks: [{file_path, similarity, chars}]` on its trace event. Apply the same extension to `inject_bot_knowledge_base` for parity. Closes the audit loop.

**Deliverables**
- New injector + integration into the turn pipeline.
- Migration / config surface for `bot_memory_reference_auto_retrieval` (default true).
- Bot config UI Memory-section toggle.
- Per-chunk trace extension (`retrieve_filesystem_context` return shape + injector trace event payload). Backfill `inject_bot_knowledge_base` to use the same shape.
- Unit tests: injector returns chunks for matching turns, returns empty for unrelated turns, respects the off-switch, suppresses the directory listing when chunks are admitted, trace event includes per-chunk file paths + similarities.

**Verification**
- Live verification on Sprout: a turn asking about basil pruning should admit the basil entry from `plant-profiles.md` automatically.

### P2 - Section-finalize hygiene microbursts

Hook `app/services/compaction.py:_persist_section_and_summary` (around line 1340). After a `ConversationSection` is persisted, schedule a *narrow* memory_hygiene Task whose prompt is scoped to just that section: title + summary + tags + transcript handed in, asked to update *only* the reference files whose topics overlap.

- Reuses `memory_hygiene` Task pipeline + skill body unchanged. The new code is the trigger and the scoped prompt template.
- Daily hygiene stays as the cleanup pass — the microburst is additive, not a replacement.
- Skip rules: ownerless / autonomous / heartbeat / pipeline-origin sections; only fire on user-driven sessions.
- Per-bot opt-out via existing `memory_hygiene_enabled` (no new column).

**Deliverables**
- Trigger inside `_persist_section_and_summary` (or a sibling helper called from there) that enqueues a Task with `kind="memory_hygiene"` and a `microburst_section_id` pointer.
- Scoped prompt template under `app/config/prompts/` (or the existing memory_hygiene prompt path).
- Unit + integration tests covering trigger, skip rules, and that the resulting Task receives the section payload.

### P3 - Reference frontmatter summaries (small hedge)

Update the memory_hygiene skill / prompt so when the bot rewrites a reference file, it writes/updates a one-line `summary:` field in its YAML frontmatter. Surface those summaries in the existing reference-index injection (`context_admission.py:252-283`) alongside the filename + mtime line, so even when P1's semantic retrieval misses, the bot sees a content hint not just a filename.

**Deliverables**
- Prompt update for `memory_hygiene` skill (`/app/skills/history_and_memory/memory_hygiene/index.md`).
- Index injector reads frontmatter `summary:` and renders it inline.
- One-off backfill: a script (or a single `memory_hygiene` invocation per bot) that adds summaries to existing reference files.

### P4 - Cleanup the parallel store

Delete what Phase 1 shipped that competes with the system above:

- `app/services/knowledge_capture.py` — extractor + writer + reindex helpers.
- The capture trigger inside `persist_turn` (search for `run_knowledge_capture_for_persisted_turn`).
- `inject_user_knowledge` and the `users/<user_id>/knowledge-base/notes/` retrieval path (`context_admission.py:908+`).
- `/api/v1/admin/knowledge/review` router + `ui/app/(app)/admin/knowledge/review.tsx` + `ui/src/api/hooks/useKnowledgeReview.ts` + the sidebar entry.
- `KNOWLEDGE_CAPTURED` `ChannelEventKind` + `KnowledgeCapturedPayload`.
- `bots.knowledge_capture_enabled`, `bots.knowledge_capture_model`, `bots.knowledge_capture_model_provider_id` columns (migration drops them).
- Channel `config["knowledge_capture"]` override handling.
- The `user_knowledge_surface()` helper in `app/services/knowledge_documents.py` (Notes consumers don't use it; channel/project surfaces are unaffected).
- Deindex `FilesystemChunk` rows under `users/*/knowledge-base/notes/`.

Channel/project Notes and the unified `KnowledgeDocument` primitive (`app/services/knowledge_documents.py` minus the user-scope helper) **stay** — they're the substrate Notes already consumes.

**Deliverables**
- Delete listed code paths.
- Drop migration for the three bot columns.
- Cleanup migration to deindex orphaned chunks.
- `docs/fix-log.md` entry.
- Updates to any docs referencing the deleted surfaces.

## What stays untouched

- `memory_hygiene` Task pipeline + skill prompt structure (P2 reuses; P3 adds a single field).
- `memory/MEMORY.md` injection and yesterday's-log injection (`context_admission.py:174-250`).
- Channel / project Notes endpoints and UI.
- The unified Knowledge Document primitive's `channel`, `project`, `bot` scopes.
- `knowledge-base/` retrieval (`inject_bot_knowledge_base`).

## Order of work

1. P4 first — delete the parallel store. Smaller surface, frees up naming, removes confusion.
2. P1 — the load-bearing fix.
3. P3 — small follow-up (prompt + index renderer).
4. P2 — last; the hygiene-microburst is the most prompt-tuning-sensitive piece, and it benefits from P1 already being in place (so a microburst's update is immediately visible to the next turn).

## Same-edit doc updates

- `docs/tracks/user-knowledge-graph.md` — Status table replaced with the P1-P4 layout.
- `docs/inbox.md` — pointer entry replaced with the new track pointer.
- `docs/fix-log.md` — entry on P4 cleanup ship.
- `docs/guides/context-management.md` — note `memory/reference/` semantic retrieval as a first-class admission path.
- `docs/guides/knowledge-bases.md` — reframe so `memory/reference/` (bot-curated, hygiene-maintained) is documented as the primary surface; `knowledge-base/` (operator-curated) is secondary.
- `docs/architecture-decisions.md` — entry: "Bot-curated `memory/reference/` is the primary ambient knowledge surface; semantic retrieval is auto-on by default."

## Anchor files (verified 2026-05-03)

- `app/agent/context_admission.py:174-316` — current memory-scheme injection (MEMORY.md full content, yesterday's log, reference index, loose files index).
- `app/agent/context_admission.py:840-905` — `inject_bot_knowledge_base()`, the model for P1.
- `app/agent/context_admission.py:908+` — `inject_user_knowledge()` (deleted by P4).
- `app/agent/fs_indexer.py:787-790` — `_memory_prefixes` list; covers `memory/` already.
- `app/services/bot_indexing.py:25` — `MEMORY_PATTERNS = ["memory/**/*.md"]`. The chunks are already indexed.
- `app/services/compaction.py:1340` — `_persist_section_and_summary`, the P2 hook point.
- `app/services/memory_hygiene.py` — Task scheduler the P2 microburst enqueues into.
- `app/services/memory_scheme.py:91-95` — `reference_dir` resolution.
- `app/services/knowledge_capture.py` — deleted by P4.
- `app/services/knowledge_documents.py` — kept; only `user_knowledge_surface` removed.
- `ui/app/(app)/admin/knowledge/review.tsx` — deleted by P4.
- `/app/skills/history_and_memory/memory_hygiene/index.md` (live server) — hygiene skill prompt; P3 adds the `summary:` directive.
