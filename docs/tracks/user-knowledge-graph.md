---
title: User Knowledge Graph
summary: Generic per-user auto-captured knowledge surface bridging agent memory and user knowledge bases. Spindrel core ships the mechanism; domain types come from skill packs. Review-first; per-user is a hard security boundary.
tags: [spindrel, track, knowledge, memory, context-engine]
status: active
created: 2026-05-03
updated: 2026-05-03
---

# User Knowledge Graph

Plan: [`docs/plans/user-knowledge-graph.md`](../plans/user-knowledge-graph.md). Read the plan first for design and locked decisions; this file is the living status page.

## North star

A non-AI user gets a personal context engine for free: their bot conversations produce a knowledgebase the bot reads ambiently and the user can browse from one unified knowledge surface — without ever managing files, learning the word "knowledgebase", or thinking about scope (channel / user / project / bot). Spindrel core defines a unified **Knowledge Document** primitive — Phase 0.5 lifts the existing Notes infrastructure into it; Notes becomes a consumer of the primitive. Domain-specific schemas, cards, and views (Recipe Box, Garden, etc.) come from skill packs that read/write the same Knowledge Documents via the unified API.

## Invariants

- **One unified Knowledge Document primitive.** Phase 0.5 lifts Notes infrastructure into it; existing Notes refactors to consume it. There is no parallel system.
- **Scope is metadata, not UI vocabulary.** Channel / project / user / bot are author-side metadata only; the user-facing UI presents one knowledge surface. Phase 3 includes a UI string lint enforcing this.
- **Multi-mode session binding per document.** Three modes ship: dedicated session, inline-with-main-chat (default for captures and likely most non-AI-user interactions), attach-arbitrary. Switchable per doc.
- **Capture is review-first.** Every save lands with frontmatter `status: pending_review` and never reaches agent retrieval until operator-accepted. **Status is in frontmatter, not in a `_review/` directory.**
- **Phase 1 rollout is opt-in per bot.** `Bot.knowledge_capture_enabled` defaults to **False**. Operator opts in for dogfood. Default-on is a later graduation gated by noise / cost / privacy telemetry, not a Phase 1 launch assumption.
- **Per-user scope is a hard security boundary enforced at storage AND retrieval.** Phase 0.5 adds `owner_user_id` (and `kd_status`, `knowledge_scope`, `entry_id`) to `FilesystemChunk` metadata. **`bot_id IS NULL` alone is not the boundary** — the existing `bot_id IS NULL` admission clause in `fs_indexer.py:920-924` would otherwise leak per-user chunks into any bot's generic workspace RAG. All retrieval paths must filter `owner_user_id IS NULL OR owner_user_id == bot.user_id`. Generic workspace RAG and `search_workspace` must explicitly exclude `users/`. Cross-user leak integration test is a merge gate on Phase 1.
- **Ownerless bots no-op capture.** `Bot.user_id IS NULL` skips capture entirely.
- **`type` is a free-form string, not a fixed enum.** Default `note`. Core does not enumerate domain types.
- **The capture chip is a separate typed bus event** (`KNOWLEDGE_CAPTURED` in `app/domain/channel_events.py`), not an edit to the persisted assistant message body.
- **Authorization is centralized.** Phase 0.5 ships `authorize_knowledge_document(actor, surface, action)`; Phase 3 routes all list/read/write/accept/reject/session-binding actions through it. Existing channel-scope `channels:read/write` checks (`api_v1_notes.py:67,81`) are not enough for the unified surface that mixes user/channel/project docs.
- **Notes frontmatter serializer is replaced, not extended.** Existing `notes.render_frontmatter()` (`app/services/notes.py:106`) only emits a fixed key set; the new fields (`entry_id`, `status`, `session_binding`, `extra`) would be silently dropped. Phase 0.5 ships a round-trip-preserving serializer with backcompat tests against existing channel notes.
- **Per-channel `knowledge_capture: off` is the only escape hatch in v1.** No per-message "forget this turn" gesture.
- **Capture chip is user-only.** The agent does not see "I just saved X" in next-turn context.

## Status

| Phase | Description | Status |
|---|---|---|
| 0 | Fix KB retrieval prefix scoping in `retrieve_filesystem_context`. Standalone bug fix + `fix-log.md` entry. | done |
| 0.5 | Knowledge Document primitive: lift Notes infrastructure into a unified service supporting multiple scopes + multi-mode session binding. Refactor Notes to consume it. No end-user behavior change. | in progress - backend substrate landed |
| 1 | Auto-capture pass (review-first, generic types) writing through the unified primitive at user scope. Includes indexing/retrieval, bus event, admin review queue, cross-user leak test. | in progress - event, skip rules, writer, accepted retrieval landed |
| 2 | Per-user scope contract (design section, ships inside Phase 1). | not started |
| 3 | Unified scope-invisible knowledge UI. Renames Notes UI to Knowledge UI, hides scope vocabulary, ships session-binding mode switcher, accept/reject affordances. UI string lint gates merge. | not started |
| 4 | File-mode conversation section recall (semantic + recency, parity with structured mode). | not started |
| 5 | Cross-source entity links (`entity_links` table; message + attachment kinds in v1). | not started |

## Active gaps / next work

- Finish Phase 0.5 UI/editor lift: rename/wrap `NoteWorkspacePage` as `KnowledgeDocumentEditor`, expose session-binding controls, and keep the existing Notes visual behavior unchanged.
- Continue Phase 1: wire the post-persist capture runner, add the LLM extractor prompt, trigger immediate user-scope reindex, and ship the admin review queue.
- Confirm whether file-mode compaction populates `ConversationSection.embedding` (Phase 4 first task).
- Final naming for the unified primitive (`KnowledgeDocument` working name) and the user-facing surface ("Knowledge" working name) decided at implementation; defer to `docs/guides/ubiquitous-language.md`.
- No skill-pack consumer of the Phase 3 view-registration seam exists yet; follow-up plan owner, not a blocker for this track.

## Links

- Plan: [`docs/plans/user-knowledge-graph.md`](../plans/user-knowledge-graph.md) — full design, locked decisions, hand-off checklist, verified anchor files.
- Adjacent tracks: [`docs/tracks/context-surface-governance.md`](context-surface-governance.md), [`docs/tracks/agent-quality-observability.md`](agent-quality-observability.md).
- Canonical guide to update on Phase 1 ship: `docs/guides/knowledge-bases.md`.
- Worksurface scope guide to update on Phase 1 ship: `docs/guides/worksurface-isolation.md`.
- Architecture decisions to add on Phase 1 ship: "Per-user knowledge surface as a third type of memory" + "Per-user knowledge scope is a hard security boundary".
