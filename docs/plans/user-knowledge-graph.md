---
title: Plan - User Knowledge Graph (personal context engine)
summary: Six-phase plan (Phase 0 prereq + 5 main) to add a generic per-user auto-captured knowledge surface that non-AI users get for free - bridging agent-curated memory and user-curated knowledge bases. Types are open and bot-configurable; Spindrel core ships the mechanism, not domain content.
status: active
tags: [spindrel, plan, knowledge, memory, context-engine, projects]
created: 2026-05-03
updated: 2026-05-03
---

# Plan - User Knowledge Graph (personal context engine)

## TL;DR

Spindrel today has three knowledge surfaces that don't yet compose: agent-curated `memory/MEMORY.md` (the bot's notes to itself), user-curated `knowledge-base/*.md` (a folder the user populates manually), and the **Notes feature** — user-initiated rich-markdown notes scoped to channel/project, with frontmatter, AI-assist proposals, and a bound mini-chat session per note (`app/services/notes.py`, `NoteWorkspacePage.tsx`). Each one solves a slice. None of them solves the slice that matters most for non-AI users: an **automatically captured, ambient, scope-invisible "her knowledge"** that bots write to as a default behavior and the user can browse / edit / refine without learning what a channel or a scope is.

This plan defines a **Knowledge Document** as the unified primitive. A Knowledge Document carries content + frontmatter + provenance + indexed retrieval + a flexible session-binding (dedicated, inline-with-main-chat, or attached-to-arbitrary-session). The existing Notes feature is **refactored to be a consumer of this primitive**, not the substrate the new work sits on. The existing Note infrastructure (frontmatter, AI-assist-with-proposal, file-system + indexed retrieval, `NoteWorkspacePage.tsx`'s editor with bound mini-chat) is **lifted and generalized** into the Knowledge Document service; channel/project Notes become specific scope-bindings of it.

On top of that primitive, this plan adds an **automatic capture pipeline** that turns meaningful turns into review-first proposed Knowledge Documents owned by the bot's user — surfaced through the same UI that displays channel/project Notes, but **without exposing scope vocabulary to the user**. A non-AI user sees "her knowledge"; the system resolves which documents are relevant to the current context. Spindrel core ships the generic mechanism only; domain-specific schemas/cards (Recipe Box, Garden, etc.) come from skill packs that read/write the same Knowledge Documents.

Six phases. Phase 1 (auto-capture, review-first, into the Knowledge Document primitive) is the load-bearing unlock; the rest compound on it. The Notes refactor (lifting Notes infrastructure into the unified primitive) is a precondition for Phase 1, captured in **Phase 0.5** below.

**Locked decisions** (from operator review, 2026-05-03):
- Capture mode: **review-first**. Every save lands as a Knowledge Document with frontmatter `status: pending_review` until explicitly accepted; nothing influences agent retrieval until promoted. Review status is **not** represented by a `_review/` directory.
- Rollout mode: **opt-in for Phase 1**. Capture defaults off at bot/channel creation until dogfood proves the extractor is low-noise, privacy-safe, and cost-appropriate. Default-on is a later rollout decision, not a Phase 1 assumption.
- Instance topology: **same server, multiple users**. Per-user separation is a hard security boundary tested end-to-end; cross-user leak is a defect.
- Retrieval isolation: **`FilesystemChunk.bot_id = NULL` is not a security boundary.** User Knowledge Document chunks may use `bot_id = NULL` so multiple bots owned by the same user can see them, but every retrieval path must also enforce `owner_user_id` / `knowledge_scope` metadata or explicitly exclude `users/` paths. Generic workspace RAG and `search_workspace` must not see user-scope documents.
- Type registry: **open / bot-configurable**. No domain-specific types in core; default `note`, free-form `type` string the extractor can populate, per-type schemas + cards land in follow-up plans authored by skill packs or users.
- Ownerless bots (`Bot.user_id IS NULL`): **skip capture entirely**. Capture requires non-NULL `Bot.user_id`; ownerless bots no-op.
- Phase 0 ships as its own PR with a fix-log entry; not folded into Phase 1.
- Per-channel `knowledge_capture: off` is the user-facing escape hatch. No per-message "forget this turn" gesture in v1.
- Capture chip is **user-only** (rendered from bus event); the agent does not see "I just saved X" in next-turn context.
- **UI substrate is one unified surface. Scope vocabulary is hidden from end users.** A non-AI user sees "her knowledge" — never "channel notes" vs "user notes". The system decides what's relevant in context. Authors and admins see scope as metadata; end users do not.
- **Session binding is multi-mode per Knowledge Document.** Three modes ship in v1: (1) **dedicated session** (current Notes default; isolated focused refinement), (2) **inline in main chat** (no context switch; the user fixes a knowledge entry mid-conversation in the chat they're already in), (3) **attach an arbitrary existing session** (resume an old conversation as the editor for a doc). Default for non-AI users is mode 2 (inline) so they discover the editing surface without context-switching; mode 1 remains for power use; mode 3 is opt-in.
- **The existing Notes feature is refactored, not paralleled.** Phase 0.5 lifts Notes infrastructure into the unified Knowledge Document primitive; channel/project Notes become specific scope-bindings of the primitive after the refactor. We do not ship a parallel system that fragments the surface.
- **Authorization is centralized.** Phase 0.5 introduces one `authorize_knowledge_document(actor, surface, action)` seam used by list/read/write/accept/reject/session-binding actions. Current Notes channel checks are not enough for the mixed user/channel/project global surface.
- **Don't pretend Notes already solved this.** Existing Notes is channel/project-scoped, single-session-binding, and exposes scope to end users. The capture pipeline cannot just write into it — the substrate has to grow to support per-user scope, multi-mode session binding, and a scope-invisible UI lens first.

## Context

- Today's primitives, verified in code:
  - `app/agent/context_admission.py:840-905` - `inject_bot_knowledge_base()` builds `kb_segments` with a `path_prefix` and calls `retrieve_filesystem_context()`. **Pre-existing defect:** the `path_prefix` is never an include filter; `retrieve_filesystem_context` (`app/agent/fs_indexer.py:907`) only uses the segments list for exclusion + embedding-model collection. Today's "bot KB retrieval" is effectively bot-workspace-wide retrieval narrowed by `roots` and `bot_id`. This must be fixed (Phase 0) before adding new prefix-scoped surfaces.
  - `app/agent/fs_indexer.py:920-924` - `FilesystemChunk` retrieval admits `bot_id == current OR bot_id IS NULL`. This is convenient for shared chunks but unsafe as a per-user boundary by itself. Phase 0.5/1 must add owner/scope metadata filters and must make generic workspace retrieval exclude `users/` by default.
  - Indexing is **not live filesystem scan**: retrieval is over the `FilesystemChunk` table. Writing a file is not enough; an indexer pass must run after the write.
  - `app/services/shared_workspace.py:54` - canonical workspace layout is `bots/`, `common/`, `users/`, `integrations/`. Per-user knowledge belongs at `users/<user_id>/knowledge/`, **not** an invented `workspace/user-knowledge/` path.
  - `app/db/models.py` - `Bot.user_id` already exists, so per-user scoping has a primary key to hang on.
  - `app/services/memory_scheme.py`, `app/services/memory_hygiene.py` - `memory/MEMORY.md` is agent-curated via a "memory flush" prompt before compaction. **Not user-readable as a knowledgebase; surfaced only in admin views.**
  - `app/services/compaction.py` - `ConversationSection` rows carry `title`, `summary`, `tags`, `embedding`, `period_start/end`. `app/agent/context_admission.py:619-647` **already auto-injects** sections semantically when `history_mode == "structured"` (top-3 by cosine distance), and injects a section index when `history_mode == "file"`. Phase 4 below is therefore a *recall/ranking improvement on file mode*, not a from-scratch ambient-recall introduction.
  - `app/services/recent_attachments.py` - the canonical pattern for "ambient context primitive": pure-function scan over recent messages, returns a small typed payload, plugged into the turn pipeline before LLM call. The recent untracked `app/services/chat_late_input.py` follows the same shape.
  - `app/services/sessions.py:830` defines `persist_turn()`. The `await db.commit()` is at line 888; the bus publish via `_publish_persisted_messages_to_bus` (line 792) happens after commit (line 908). A capture pass that runs after persistence cannot embed "saved to ..." metadata into the persisted assistant message body — it must emit a **separate typed event** over the channel-events bus.
  - `app/domain/channel_events.py:55` defines `class ChannelEventKind(StrEnum)` — the typed bus event registry. New events for capture (e.g., `KNOWLEDGE_CAPTURED`) must be added here with a matching `Payload` class registered in the `_PAYLOADS` map (also in this file). Capability gate must be added in the same file.
  - `app/services/bot_indexing.py` exposes `reindex_bot()` (line 224) and `reindex_channel()` (line 352), plus `BotIndexPlan` (line 30) and `resolve_for()` (line 53). New writes must call back into these (or a sibling helper) to land in the `FilesystemChunk` table.
  - `app/services/workspace.py:58` defines `get_bot_knowledge_base_index_prefix()` — the model for adding `get_user_knowledge_index_prefix()` for Phase 1 retrieval.
  - Integrations (Gmail, Calendar, Drive) are exposed as **tools only**. No ambient push, no cross-source linking.
- The roadmap line "Knowledge Base convention" (under Completed) describes the user-curated half only. "Memory hygiene" describes the agent-curated half only. There is no spine joining them and no plan that names the missing surface.
- Real usage observation: the operator (an AI-fluent power user) is the only one who reliably writes to `knowledge-base/`. A second user (non-AI background) gets no benefit from these primitives today because nothing populates them on her behalf and the UI does not surface them as something a non-file-manager wants to look at.
- Spindrel runs in deployments where multiple users share one instance with `Bot.user_id` distinguishing ownership. Per-user separation must therefore be a tested security boundary, not a future-proofing nicety.

## Goals

- An opted-in bot turn can produce user-readable knowledge entries automatically, with no user prompting and no skill the user must invoke.
- The user can open one generic UI surface ("things I've learned about you") and see entries, filter them, edit them, forget them - **without ever opening a file or learning the word "knowledgebase".**
- Multiple bots owned by the same user read and write the same per-user knowledge surface, so a user's assistant ecosystem compounds into one picture of them. Bots owned by different users on the same instance never see each other's user knowledge.
- The agent ambiently recalls relevant prior conversations (compaction sections) on a normal turn, ranked by `relevance × recency`, without the user telling it to look.
- Knowledge entries link to their sources (message id, attached image, etc.) so a user can ask the agent to recall what surrounded a saved entry without naming a source.
- **The mechanism is generic.** Domain-specific schemas, cards, and views are authored by skill packs / bot configuration / users, not built into core.

## Non-Goals

- Embedding store as the primary knowledge index. Existing hybrid file-system + semantic retrieval is sufficient at personal scale; adding a vector DB has worse cost/value than at enterprise scale.
- A "vault editor" or markdown surface for non-AI users. Knowledge is surfaced through the generic browsable view; markdown is an implementation detail.
- **A built-in domain type registry.** Core ships with `note` as the default type and accepts free-form `type` strings; "Recipe Box", "Garden", "Person" cards (etc.) belong to skill packs / bot configuration / future user-defined view plans, never to product code. If a bot's audience benefits from a structured form, the bot ships the form.
- Cross-instance / multi-tenant knowledge sharing. Single-instance scope only.
- Replacing `memory/MEMORY.md` (agent-curated bot notes) or `knowledge-base/` (user-curated docs). Both remain. The new surface is additive.
- Inline knowledge editing inside the chat composer. Editing happens in the dedicated entry view.
- Auto-capture from integration sources (Gmail / Calendar / Drive). Conversation-driven capture is the wedge; integrations come later, gated on Phase 5's link table.
- Capture for ownerless bots (`Bot.user_id IS NULL`). These no-op the capture step.
- Per-message "forget this turn" gesture in v1. Per-channel off-switch is the only escape hatch v1 ships.

## Constraints from operator review (2026-05-03)

1. **Build a unified Knowledge Document primitive; don't build a layer on top of Notes-as-it-is.** The existing Notes feature has the right ideas (frontmatter, AI-assist with proposal review, file-system + indexed retrieval, bound mini-session) and the wrong shape (channel-only scope, single session-binding mode, UI exposes scope vocabulary). Phase 0.5 lifts the right ideas into a unified primitive; Phase 1 builds capture on top of that primitive; existing Notes is refactored to consume it.
2. **Hide scope from end users.** Non-AI users do not understand or want to think about channel vs project vs user vs bot scoping. The UI presents "her knowledge" — one surface — and the system resolves what's relevant given context. Scope-as-metadata is fine and necessary internally; scope-as-UI-vocabulary is not.
3. **Multi-mode session binding per document.** A Knowledge Document can be edited via (a) a dedicated session spawned for it (current Notes default; preserved as an option), (b) the user's main chat session inline (no context switch — the default for non-AI users), or (c) any arbitrary existing session attached on demand (power-user). The mode is per-document, switchable, with a sensible default.
4. **Per-user is the security boundary, not a UI concept.** Phase 2's contract is unchanged — the system enforces user separation at the storage and retrieval layer — but the UI never says "user scope" to a user. It says "her knowledge" and shows what matters.
5. **Don't ship a parallel route.** Whatever the unified surface ends up being called, there is one of it, not two ("Notes" + "Knowledge").

These constraints are inputs to all phases, not just Phase 3.

## Phase order

Phase 0 is the standalone bug fix. Phase 0.5 is the Notes→Knowledge Document refactor — the substrate work that makes Phase 1 possible. Phase 1 builds capture on the new substrate. Phase 2 is the per-user scope contract (ships inside Phase 1). Phase 3 ships the unified scope-invisible UI. Phase 4 and 5 are independent improvements after Phase 3.

0. **Phase 0** - Fix KB retrieval prefix scoping in `retrieve_filesystem_context` so segment `path_prefix` is an *include* filter, not just an exclusion source. Standalone PR with `fix-log.md` entry, prereq for Phases 0.5 and 1.
0.5. **Phase 0.5** - Knowledge Document primitive: lift Notes infrastructure (frontmatter, AI-assist, indexed retrieval, file storage, bound-session pattern) into a `KnowledgeDocument` service that supports multiple scopes (channel, project, **user**, bot — open enum-like) and multi-mode session binding (dedicated, inline-in-main, attached). Refactor existing Notes to consume the primitive. **No user-visible behavior change at this phase — it's a substrate lift.**
1. **Phase 1** - Auto-capture pass, **review-first and opt-in**: extract candidates per turn, write Knowledge Documents at user scope with `status: pending_review`, immediate indexing, `KNOWLEDGE_CAPTURED` bus event. A minimal admin review queue surface co-ships. Capture requires non-NULL `Bot.user_id`; ownerless bots no-op.
2. **Phase 2** - (Contract section, ships inside Phase 1.) Per-user storage layout, `bot_id = NULL` shared-index convention plus mandatory owner/scope metadata filters, `Bot.user_id` retrieval filter, generic workspace exclusions, ownerless-bot no-op invariant, cross-user-leak test contract.
3. **Phase 3** - Unified scope-invisible knowledge UI. One surface (built on the existing `NotesTabPanel` / `NoteWorkspacePage` substrate, lifted in Phase 0.5) that presents the user's knowledge plus contextually-relevant scope-bound docs through one lens. Default session-binding mode for new docs is **inline-in-main-chat**; dedicated and attach-arbitrary modes available per-doc. Sidebar entry hidden when empty.
4. **Phase 4** - File-mode conversation recall: improve `history_mode == "file"` section injection to do semantic recall + recency ranking (matching what structured mode already does, plus recency decay).
5. **Phase 5** - Cross-source entity links: small `entity_links` table joining knowledge documents to source messages and attachments. Integration sources (calendar / drive / email) reserved for a follow-up plan.

## Phase 0 - Fix KB retrieval prefix scoping (prereq + standalone bug fix)

### Goal

`inject_bot_knowledge_base()` says it scopes to `knowledge-base/` via `kb_segments[].path_prefix`, but `retrieve_filesystem_context()` treats that prefix as an *exclusion* source only. Today's "bot KB retrieval" is therefore bot-workspace-wide, not KB-folder-scoped. This phase makes prefix scoping work as advertised, and is the prereq for Phase 1 (which needs to retrieve from `users/<user_id>/knowledge/...` separately from `bots/<bot_id>/knowledge-base/...`).

### Design

- Extend `retrieve_filesystem_context()` in `app/agent/fs_indexer.py` so each segment carries an explicit `mode` (`"include"` or `"exclude"`) - or accept a separate `include_path_prefixes` parameter.
- When include prefixes are present, add an `OR` filter to the SQL `WHERE` clause: `or_(*[FilesystemChunk.file_path.startswith(p) for p in include_prefixes])`.
- Update `inject_bot_knowledge_base()` to pass include-mode segments (since today the intent was always positive scoping).
- Backfill the in-tree caller signatures; the parameter is additive.

### Deliverables

- Code change to `fs_indexer.py` with backwards-compatible signature.
- Updated `inject_bot_knowledge_base()` call.
- Tests:
  - Unit: include-prefix scoping returns only chunks whose `file_path` starts with one of the supplied prefixes.
  - Regression: existing exclude-prefix behavior unchanged.
- Fix-log entry in `docs/fix-log.md` (this is a real defect being fixed).

### Verification

- Existing bot-KB integration tests continue to pass; new test asserts that a bot with files outside `knowledge-base/` does not see those files via `inject_bot_knowledge_base()`.

## Phase 0.5 - Knowledge Document primitive (Notes refactor)

### Goal

Lift the existing Notes infrastructure into a unified `KnowledgeDocument` primitive that supports multiple scopes and multi-mode session binding. Refactor existing Notes endpoints to consume the primitive. **No end-user-visible behavior change at this phase** — channel/project Notes look and work the same; the substrate is just generalized so Phase 1 can build on it without bifurcating storage or UI.

### Why this is a separate phase, not folded into Phase 1

If Phase 1 writes captures into either (a) a parallel system or (b) a forced extension of single-scope Notes, the Phase 3 UI ends up either fragmented or wedged. Lifting the substrate first means Phase 1 and Phase 3 land cleanly against the same primitive. The refactor is also independently valuable — Notes today can't be user-scoped or have session-binding flipped, and both are user-visible limits.

### Design

- New service `app/services/knowledge_documents.py` (or rename + generalize `app/services/notes.py`; final naming decided in implementation, but the primitive name in the codebase is **KnowledgeDocument**).
- `KnowledgeDocumentSurface` replaces `NotesSurface`. Adds:
  - `scope` enum: `"channel" | "project" | "user" | "bot"`. Free-form `extra_scope` reserved for future. (`"user"` and `"bot"` are new; `"channel"` and `"project"` are the existing two.)
  - `user_id` field for `scope == "user"`.
  - `bot_id` field for `scope == "bot"` (carve-out for bot-private docs that aren't `memory/MEMORY.md`; reserved, not used in v1).
  - Path resolution: `<workspace>/users/<user_id>/knowledge-base/notes/...` for user scope; existing paths for channel/project.
- `KnowledgeDocument` carries the same frontmatter as Notes today, **plus**:
  - `entry_id` (stable ULID, primary key for the chip event and `entity_links`).
  - `status` (`"draft" | "pending_review" | "accepted"`; existing Notes default to `"accepted"` to preserve current behavior).
  - `session_binding` (`{mode: "dedicated" | "inline" | "attached", session_id: <uuid|null>}`).
- Replace the current fixed-key Notes frontmatter renderer with a preserving structured renderer. Existing `notes.render_frontmatter()` only emits a small hard-coded key set (`spindrel_kind`, `title`, `category`, `summary`, `tags`, timestamps); the Knowledge Document primitive must round-trip arbitrary envelope keys (`entry_id`, `status`, `session_binding`, `extra`, provenance) without dropping unknown metadata.
- **Multi-mode session binding** — three modes, switchable per-doc via the editor UI:
  - `dedicated`: a Session is spawned the first time the doc is opened (current Notes behavior; `get_or_create_note_session()` becomes `get_or_create_dedicated_kd_session()`).
  - `inline`: the doc is bound to the user's current main chat session (or, if opened outside a chat, to the most recent user-owned session). Edits via AI-assist happen in that session's context.
  - `attached`: a switcher in the editor lets the user pick any existing session they own to attach as the editor for this doc.
- Refactor existing Notes endpoints (`/channels/{channel_id}/notes/...`) to call into the unified primitive. Behavior identical for channel/project scopes after refactor; defaults preserved (channel notes default to `dedicated` session binding to match current behavior).
- Add `authorize_knowledge_document(actor, surface, action)` and route all Knowledge Document list/read/write/assist/accept/reject/session-binding actions through it. User-scope docs require the owning logged-in user or admin; channel/project docs keep their existing channel/project authorization semantics behind the same seam.
- Existing `NoteWorkspacePage.tsx` is renamed/generalized (or wrapped) into a `KnowledgeDocumentEditor` that handles all three session modes.

### Deliverables

- `app/services/knowledge_documents.py` (the unified primitive) — or a renamed-and-generalized `notes.py`.
- Chunk metadata contract: indexer writes `knowledge_scope`, `owner_user_id`, `kd_status`, and `entry_id` for Knowledge Document chunks (using existing `FilesystemChunk.metadata_` or dedicated nullable columns if implementation chooses that for query/index ergonomics). Retrieval filters must use these fields rather than path prefix alone.
- Refactor of `/channels/{channel_id}/notes/...` endpoints to consume the unified primitive (same external API; internal call surface changes).
- Refactor of `NoteWorkspacePage.tsx` and `NotesTabPanel.tsx` to consume the unified primitive — initially still rendering the same UI; Phase 3 evolves the UI.
- Tests:
  - Unit: existing Note unit tests continue to pass against the refactored primitive (no behavior change for channel/project).
  - Unit: `KnowledgeDocumentSurface` resolves correctly for each scope; rejects invalid combinations (e.g., `scope == "user"` with `channel_id` set).
  - Unit: each session-binding mode resolves to the expected session id (or spawn).
  - Unit: frontmatter round-trips all Knowledge Document envelope keys and preserves unknown keys across create/read/write/assist flows.
  - Unit: `authorize_knowledge_document()` rejects cross-user read/write/accept/reject attempts and preserves current channel/project behavior.
- Same-edit doc updates: `docs/guides/knowledge-bases.md` reframed around the Knowledge Document primitive. `docs/architecture-decisions.md` entry: "Knowledge Documents are the unified primitive; Notes is one of several scope-bindings of it."

### Verification

- All existing Notes UI flows continue to work identically. Channel notes and project notes are visually unchanged after the refactor; this is a substrate lift, not a UX change.
- New: a manually-created Knowledge Document at user scope can be opened in the editor with each of the three session-binding modes.

### Out of scope for this phase

- The unified scope-invisible UI (Phase 3).
- Capture pipeline (Phase 1).
- Default-mode change for existing Notes (channel/project notes stay on `dedicated` for now to preserve their behavior).

## Phase 1 - Auto-capture pass (review-first, generic types)

### Goal

Every meaningful agent turn (on a bot the operator has explicitly opted in) produces 0..N candidate knowledge entries, written as Knowledge Documents at user scope with `status: pending_review` in frontmatter, stable IDs, and immediate indexing (with `owner_user_id` chunk metadata so retrieval cannot leak across users). A minimal admin review-queue surface co-ships — backed by a frontmatter-status filter, **not** a `_review/` directory tree. **This phase is the standalone unlock once Phase 0.5's substrate lands; everything after it improves recall, surfacing, and linking.**

### Design

- **Storage shape (per-user, written via the unified Knowledge Document primitive from Phase 0.5):**
  - Captures are written through `app/services/knowledge_documents.py:create_kd()` (or whatever the refactored primitive is named) against a `KnowledgeDocumentSurface` whose `scope == "user"`. Documents land at `<workspace>/users/<user_id>/knowledge-base/notes/...`.
  - Review-vs-live is expressed in **frontmatter**, not by directory: `status: pending_review` (default for captures) vs `status: accepted` (after operator promotion). The unified UI filters by frontmatter status; the chunk metadata column added in Phase 0.5 makes this a query-time filter, not a re-read.
  - `entry_id` is a stable ULID written into frontmatter (added to the unified primitive in Phase 0.5). Edits never change the id; renames keep the id; deletes are by id. Primary key for the chip event and `entity_links`.
  - **Default session binding for captured documents:** `inline` (the user's current main chat session). Rationale: a non-AI user encounters captures via the chip in the chat she's already in; clicking through opens the doc bound to that same chat, no context switch. Power users can flip the doc to `dedicated` or `attached` from the editor.
  - **Type is a free-form string.** Default `note`; the extractor may emit any other string the bot judges meaningful (e.g., `recipe`, `plant`, `decision`). Core does not enumerate or validate against a fixed list. The UI exposes type as a filter / facet, not a switch on built-in cards.
  - Frontmatter is a small generic envelope, **not** a per-type schema:
    ```yaml
    entry_id: 01HX...      # stable ULID
    type: note             # free-form string, default "note"
    title: ...
    user_id: ...
    captured_by_bot_ids: [bot-a]
    source_message_id: ...
    confidence: 0.62
    created: 2026-05-03T...
    updated: 2026-05-03T...
    extra: {}              # optional per-type structured payload, opaque to core
    ```
  - The `extra` field is a JSON blob the extractor may populate when the bot's prompt has been configured by a skill pack to know about a domain (e.g., a baking skill pack tells the extractor to emit `extra: {ingredients: [...], steps: [...]}` when `type=="recipe"`). **Core does not validate `extra`** — that's the skill pack's contract with its own future custom view (out of scope for this plan).
  - Body remains markdown for narrative content.
- New service `app/services/knowledge_capture.py`, modeled on `app/services/recent_attachments.py`:
  - Pure function `extract_knowledge_candidates(turn_context, llm_client) -> list[KnowledgeCandidate]`.
  - `KnowledgeCandidate = {type, title, body, extra, confidence, source_message_id}` where `type` is a string and `extra` is an arbitrary dict.
  - Writer calls into the unified primitive (e.g., `knowledge_documents.create_kd(surface=user_kd_surface, title=..., content=..., session_binding={mode: "inline", session_id: <triggering_session_id>})`) with frontmatter pre-populated (`entry_id`, `type`, `status: pending_review`, `confidence`, `source_message_id`, `captured_by_bot_id`, `extra`).
  - No session is spawned at capture time; `inline` mode binds to the existing triggering session. If the user later flips the doc to `dedicated`, that's when a new session spawns.
- **Skip rules** (hard - capture must not run on these turns):
  - Capture is not explicitly enabled for the bot/channel during Phase 1 dogfood.
  - `Bot.user_id IS NULL` (ownerless bots).
  - `context_visibility == "background"` messages.
  - Tool-result acknowledgment turns (heuristic: assistant message is < N chars and contains no novel content).
  - Heartbeat / scheduled turns from cron / pipeline / standing-order origins.
  - Channels with `channel.config["knowledge_capture"] == "off"`.
  - Bot-to-bot delegation turns (no human user in the loop).
  - Skip rules are codified in `knowledge_capture.py` as named predicates with unit coverage.
- **Indexing-after-write:** Notes already write to a knowledge-base path that the existing indexer covers (per `bot_indexing.py:resolve_for` + `iter_watch_targets`). The capture writer's responsibility is to ensure the user-scope notes path (`users/<user_id>/knowledge-base/notes/`) is in the indexer's watch set with `bot_id = NULL` and `client_id = NULL`, plus Knowledge Document metadata (`knowledge_scope="user"`, `owner_user_id=<user_id>`, `kd_status`, `entry_id`) on every chunk. This likely needs a sibling resolver in `bot_indexing.py` that knows about user scope. After write, call the indexer synchronously so retrieval can see the entry on the next turn. If indexing fails, the file remains on disk but is logged + emitted as a trace finding (`agent_quality_audit` lane).
  - **Pending-review entries are excluded from agent retrieval** at query time by indexed `kd_status`, not by path and not by re-reading frontmatter after retrieval. `status: pending_review` chunks may be indexed for review/search tools, but `inject_user_knowledge()` must filter them before ranking/admission.
  - **Generic retrieval exclusion:** every existing workspace-level retrieval/search path that does not explicitly opt into user knowledge (`inject_workspace_rag()`, legacy indexed-directory RAG, `search_workspace`, and any direct `retrieve_filesystem_context()` caller used for ordinary bot workspace search) must exclude `users/` paths or require `knowledge_scope != "user"`. This is mandatory because `bot_id = NULL` chunks are otherwise visible through the existing `bot_id == current OR bot_id IS NULL` predicate.
- **Event contract for the UI chip:**
  - Add `KNOWLEDGE_CAPTURED` to `ChannelEventKind` in `app/domain/channel_events.py:55`. Add a matching `KnowledgeCapturedPayload` dataclass and register it in the `_PAYLOADS` map. Capability gate: `Capability.TEXT` (chip is text-rendered).
  - Payload shape: `{entry_id, type, title, user_id, source_message_id, confidence, mode}`. `mode` is always `"review"` in v1; reserved for future `"live"` if the confidence-threshold path ever ships.
  - The UI subscribes via the existing channel SSE stream and renders an inline chip below (not inside) the assistant message that triggered the capture.
  - We do **not** edit the persisted assistant message body. The chip is a UI-only annotation joined to the message by `source_message_id`.
- **Agent visibility:** the agent does **not** see "I just saved X" in next-turn context. Captures are user-only signals in v1. (If a future need emerges for the agent to see what it captured, it can call a `list_recent_captures` tool — out of scope here.)
- **Retrieval** (depends on Phase 0): new injector `inject_user_knowledge()` in `app/agent/context_admission.py`, modeled on `inject_bot_knowledge_base()` (lines 840-905). Reads `Bot.user_id` (`app/db/models.py:1243`). Skips when `user_id IS NULL`. Builds include-prefix `users/<bot.user_id>/knowledge-base/notes/` **and** requires indexed metadata `knowledge_scope == "user"`, `owner_user_id == <bot.user_id>`, and `kd_status != "pending_review"`. The prefix is a defense-in-depth and performance filter; owner metadata is the security boundary.
- **Cross-user leak test contract:** integration tests must assert that a capture written by a bot owned by user `u1` is **never** retrieved on any turn for any bot owned by user `u2`. This is the multi-user security boundary; merge gate.
- **Review surface (co-ships with capture):**
  - Reuses the existing Notes list/filter mechanics through the unified primitive. v1 adds a `status` filter chip (default-on for `pending_review` in the admin review queue).
  - For Phase 1 alone (before Phase 3 ships the per-user Notes tab), an admin-only `/admin/knowledge/review` page lists pending captures grouped by user with: title, type tag, source-message link, **Accept** (flips frontmatter status to `accepted`), **Reject** (deletes the Note), **Open in Note editor** (navigates to `NoteWorkspacePage` for full edit + bound mini-chat).
  - Accepting flips frontmatter `status` to `accepted` and triggers a re-index so the chunk metadata column updates. No file move needed (frontmatter-as-status, not directory-as-status).
  - Rejecting deletes the Note via `notes` service.
- **Configuration:**
  - New `Bot.knowledge_capture_enabled` field, default `False` for Phase 1. Review-first protects agent context, but it does not make automatic personal-data capture cost-free or privacy-neutral.
  - New `Bot.knowledge_capture_model` field (default: a fast cheap model declared in settings).
  - New per-channel `channel.config["knowledge_capture"]` override (`"on"` | `"off"` | unset to inherit).

### Deliverables

- `app/services/knowledge_capture.py` (extractor + skip rules + writer + index-after-write seam).
- `inject_user_knowledge()` injector in `app/agent/context_admission.py` with include + exclude prefix support.
- Bus event `knowledge_capture` declared in the typed-bus event registry.
- Migration adding `bots.knowledge_capture_enabled`, `bots.knowledge_capture_model`.
- Admin review-queue page (server route + minimal UI).
- Tests:
  - Unit: extractor returns expected candidates for synthetic turns; respects all skip rules including `user_id IS NULL`.
  - Unit: writer assigns stable `entry_id`; rewrites preserve id.
  - Unit: indexed entries are queryable via `inject_user_knowledge()` immediately after write.
  - Unit: review-queue entries are **excluded** from `inject_user_knowledge()` retrieval.
  - Unit: `search_workspace` / ordinary workspace RAG do not return user-scope chunks even though they are indexed with `bot_id = NULL`.
  - Unit: bus event is emitted with correct payload shape and `mode: "review"`.
  - Integration: a turn produces a review-queue entry, operator promotes it, the next turn's context retrieval surfaces it across **two different bots owned by the same user**.
  - **Security integration:** a capture by user u1's bot is never retrieved on any turn by user u2's bot, including via `inject_user_knowledge()`, `inject_workspace_rag()`, and `search_workspace`. Cross-user leak gate.
- Same-edit doc updates: `docs/guides/knowledge-bases.md` (canonical) gets an "Auto-Captured User Knowledge" section; new entry in `docs/architecture-decisions.md`; track row added under Active in `docs/roadmap.md`.

### Verification

- Unit + integration tests above pass under the local `.venv` Python guard.
- Manual dogfood: opt one of the operator's bots in for one day, inspect `pending_review` entries via the admin page (filtered by frontmatter status). **Cancel or rescope if extracted entries are mostly noise** — the extraction prompt is the failure mode most likely to need iteration. Default-on rollout is gated by this dogfood; do not flip the default until cost / noise / privacy telemetry looks good.

## Phase 2 - Per-user scope contract (design section, no separate ship)

This is a contract section, not a separate phase. Per-user scope ships **inside Phase 1**; this section exists so future work touching the surface preserves the boundary, and so the security invariants are stated explicitly outside the implementation prose.

### Storage layout

```
<workspace_root>/
  users/<user_id>/knowledge-base/notes/
    <slug>.md      # all captured + user-created Notes; frontmatter `status` distinguishes pending_review vs accepted
```

`<workspace_root>` is `local_workspace_base()/shared/<workspace_id>` per `app/services/shared_workspace.py:46-56`. The `users/` subdirectory is created by `ensure_host_dirs()` on workspace bootstrap; `users/<user_id>/knowledge-base/notes/` is created lazily on first capture by the Knowledge Document service against the user-scoped `KnowledgeDocumentSurface`.

The path layout intentionally matches the existing channel-Notes layout (`<channel_workspace>/knowledge-base/notes/`) so document service code paths reuse without bifurcation. The differentiator is the `KnowledgeDocumentSurface.scope == "user"` value.

### Indexing convention

- `FilesystemChunk.bot_id = NULL` for all rows under `users/<user_id>/knowledge-base/notes/...`, so multiple bots owned by the same user can share the same indexed chunks.
- `FilesystemChunk.client_id = NULL`.
- Every Knowledge Document chunk carries indexed metadata: `knowledge_scope`, `owner_user_id`, `kd_status`, and `entry_id` (using existing `FilesystemChunk.metadata_` or dedicated nullable columns if implementation chooses that for query/index ergonomics).
- `FilesystemChunk.embedding_model` set per the configured embedding model for the workspace.
- The `bot_id IS NULL` clause already in `fs_indexer.py:920-924` admits these chunks for any querying bot, so per-user scoping must be enforced by `owner_user_id` / `knowledge_scope` filters. Path prefix is defense-in-depth only, not the security boundary.

### Retrieval invariants

- A bot whose `Bot.user_id` is NULL never queries this surface (skip in `inject_user_knowledge()`).
- A bot whose `Bot.user_id == u1` queries with include-prefix `users/u1/knowledge-base/notes/` and indexed filters `knowledge_scope == "user"` and `owner_user_id == u1`.
- Pending-review entries are excluded at query time by `kd_status != "pending_review"` (or equivalent metadata filter). Acceptance flips the frontmatter status; re-indexing updates the chunk metadata.
- Generic workspace retrieval/search paths that do not explicitly opt into user knowledge must exclude `users/` or filter `knowledge_scope != "user"` so `bot_id = NULL` user chunks do not leak through ordinary workspace RAG.

### Cross-user leak test contract

Phase 1's deliverables include an integration test asserting:

> Given user `u1` owns bot `A` and user `u2` owns bot `B` on the same instance, after bot `A` produces and operator-promotes a capture, no turn on bot `B` (or any future bot owned by `u2`) ever has access to that capture's content via context injection or any tool.

This test is the merge gate. Failure is a security defect.

### Conflict / merge rules

When two bots owned by the same user write to the same `entry_id` slug within a short window (resolved by querying existing Notes by frontmatter `entry_id` before creating a new Note):

- The later writer **appends** a dated bullet to the body of the existing Note via `notes.write_note()` (which already supports content-hash CAS for safe concurrent edits).
- Frontmatter `captured_by_bot_ids` is updated to include both bot ids.
- `entry_id` stays stable.

(Different users cannot collide because the NotesSurface `<user_id>` differs.)

### Ownerless bots

`Bot.user_id IS NULL` bots **skip the capture step entirely**. The capture pipeline asserts non-NULL `user_id` as a precondition; a NULL-user bot is a no-op. Capture is not a fallback to per-bot scope — it just doesn't run. (Decision locked-in 2026-05-03 review.)

### Same-edit doc updates

- `docs/guides/worksurface-isolation.md` gets a new row for the per-user knowledge scope describing the path layout, indexing convention, and the cross-user leak invariant.
- `docs/architecture-decisions.md` gets a new entry: "Per-user knowledge scope is a hard security boundary; `Bot.user_id IS NULL` bots no-op capture."

## Phase 3 - Unified scope-invisible knowledge UI

### Goal

The user has **one** knowledge surface. From inside a chat: the surface shows what's relevant to that chat (her own knowledge that the bot has saved or that she's edited, plus channel/project docs that genuinely belong to that context). From the global view: the surface shows everything she owns. The user never sees the words "channel scope" / "project scope" / "user scope" / "bot scope" — those are author-side metadata. She sees titles, bodies, source-of-capture chips, and bot-attribution chips when relevant.

This phase ships the unified UI built on the Phase 0.5 substrate. It is **not** a new route alongside Notes; it is the surface that existing Notes UI (`NotesTabPanel`, `NoteWorkspacePage`) evolves into. The end state is one knowledge experience — captured docs and manually-created notes are the same thing in the same place.

### Design

- **Inside a chat:** the existing `NotesTabPanel` becomes a `KnowledgeTabPanel` (renamed) that shows a single mixed list: docs the system judges relevant to this chat. Relevance comes from any of: same scope (channel/project), captured-by this bot, mentioned in this session's recent turns, or matching the user's recent retrieval queries. The user sees one list of titles. **No "channel" / "user" / "project" tab toggles**. An admin-only toggle reveals scope as metadata for power users; default UI does not.
- **Global view:** new sidebar entry (final copy in `docs/guides/ubiquitous-language.md`; working title "Knowledge"). Lists everything the logged-in user owns — captured docs, user-created docs, channel docs from channels she owns, project docs she has access to — as one flat list with filters (`status`, free-form `type` facet, `captured_by_bot` chip when applicable, recency). **Hidden from the sidebar when she has zero docs** so a non-AI user never sees an empty entry.
- Each doc opens in the unified `KnowledgeDocumentEditor` (the Phase 0.5 evolution of `NoteWorkspacePage.tsx`). The editor:
  - Shows the doc body + frontmatter (raw JSON for the `extra` blob; advanced).
  - Has the bound-session sidebar showing whichever session is currently bound, in whichever mode.
  - Has a session-binding switcher: **dedicated** / **inline (default for captures)** / **attach existing**. Switching modes is a one-click action with a clear preview of which session the doc is now talking to.
  - For `pending_review` docs, surfaces **Accept** / **Reject** affordances in the header. Accept flips frontmatter status to `accepted` and re-indexes; reject deletes.
- Capture surfacing in chat (driven by the `KNOWLEDGE_CAPTURED` bus event from Phase 1): a low-chrome inline chip below the assistant message, single chip per turn max, never modal. Chip text neutral by default ("Saved for review: <title>"). Tap opens the doc in the editor with `inline` binding to the same chat — so accepting / refining happens without leaving the conversation.
- **Hand-off seam for skill-pack-defined views:** a registry pattern lets a skill pack declare `{type: "recipe", view_url: ..., edit_url: ...}`. When a doc's frontmatter `type` matches a registered view, the row's "Open" affordance links out to the skill pack's view instead of the generic editor. The skill pack reads/writes the same doc via the unified Knowledge Document API. **Documented but not implemented here** — seam for a follow-up plan.

### Scope-invisible UI principle (test contract)

The Phase 3 PR includes a UX test contract:

- No string in the user-facing UI contains "channel scope", "user scope", "project scope", or "bot scope" (verified by a UI string lint).
- A non-AI user can find a captured doc, open it, edit it, and accept it without ever clicking a tab or chip labeled with a scope name.

If either fails, the phase is not done.

### Deliverables

- UI rename + reframe: `NotesTabPanel.tsx` → `KnowledgeTabPanel.tsx`; in-chat list shows context-relevant docs without scope tabs.
- New global UI surface for the cross-context personal view (sidebar entry, hidden-when-empty).
- `KnowledgeDocumentEditor` (the Phase 0.5 evolution of `NoteWorkspacePage.tsx`) gains: session-binding mode switcher with a one-click flow per mode; **Accept** / **Reject** affordances for `pending_review` docs.
- Inline-chip rendering driven by `KNOWLEDGE_CAPTURED` bus event subscription. Mount point in the chat scroll respects the `flex-direction: column-reverse` invariants from `AGENTS.md` and `ui/app/(app)/channels/[channelId]/ChatMessageArea.tsx`.
- API: extend the unified knowledge document API with `accept` / `reject` actions plus the relevance-resolver endpoint that powers the in-chat mixed list. Authorization: only the owning user can act on docs in user scope; channel/project authorization unchanged from current Notes.
- UI string lint enforcing the scope-invisible UI principle (no scope vocabulary in user-facing strings).
- Tests:
  - UI typecheck + screenshot fixtures for the in-chat mixed list and the global view, populated and empty.
  - Integration: logged-in `u1` finds her own captured + manual docs in the global view; `u2` cannot see them. In-chat mixed list shows context-relevant docs from any scope she has access to.
  - Integration: opening a captured doc with default `inline` binding shows the editor talking to the originating chat session; switching to `dedicated` spawns a new session; switching to `attached` allows picking from the user's recent sessions.
- Same-edit doc updates: `docs/guides/knowledge-bases.md` reframed around the unified Knowledge Document UI and the scope-invisible principle. `docs/architecture-decisions.md` entry: "Scope is metadata, not UI vocabulary."

### Verification

- Dogfood week: hand to a non-AI user. **Pass criteria** (all required):
  - She opens the unified knowledge view at least once unprompted.
  - She accepts or edits or forgets at least one captured doc.
  - She refines at least one doc using the editor's bound chat — in any of the three session-binding modes, but **without being told the modes exist**. (If she only ever ends up in `inline`, that's a success — it's the default; the test is whether the UX defaults are right, not whether she discovers power features.)
  - She never says the words "channel" / "scope" / "user vs bot" while describing what she's doing.
- UI string lint passes.

### Open questions

- "Knowledge" vs "Notes" vs "Memory" vs "Saved" as the sidebar entry copy. Decided at implementation; defer to `docs/guides/ubiquitous-language.md`.
- Should typed-view registration (the skill-pack seam) land in this phase or be its own follow-up? **Recommendation: follow-up plan**, since v1 ships the mechanism and a real skill pack consumer is the right driver.
- Should chip text reveal the captured *content* ("Saved: 75% hydration for sourdough") or stay neutral ("Saved for review: new entry")? **Recommendation: neutral by default** with a hover-reveal of the title. Avoids surprise echoing of content into the chat surface.

## Phase 4 - File-mode conversation section recall (improvement, not introduction)

### Goal

**Reframe (per F5):** structured-mode bots already get semantic auto-injection of `ConversationSection` rows by cosine distance (`context_admission.py:619-647`). File-mode bots get an ordered section *index*, not a similarity-ranked recall. Phase 4 brings file-mode bots up to parity with structured-mode by adding semantic recall + recency ranking, since file-mode is the dominant memory_scheme for the hobby-assistant use case.

### Design

- In the `hist_mode == "file"` branch of the section injector (currently around `context_admission.py:649`), add an opt-in semantic recall path that runs *in addition to* the existing ordered section index.
- `ConversationSection.embedding` already exists and is used by the structured-mode branch (lines 619-647). **First task: confirm whether file-mode compaction populates `embedding` on the sections it creates.** If not, populate during compaction (small writer change in `app/services/compaction.py`); if a backfill is needed for existing rows, ship a one-off migration.
- Ranking: `cosine_similarity(query, section.embedding) × recency_decay(section.period_end)`. Recency decay is a simple exponential with half-life initially set to 30 days; tunable per bot via a new `Bot.section_recall_halflife_days` field (default applied if unset).
- Token budget: cap injected sections at 2-3 per turn, governed by the existing context-budget governance lane (`docs/tracks/context-surface-governance.md`).
- Storage: no new tables. Possibly a small migration to backfill `embedding` for existing file-mode sections.

### Deliverables

- Extension to context injection in `app/agent/context_admission.py` for the file-mode semantic recall path.
- Recency-decay helper added to `app/services/temporal_context.py` (the existing temporal-context module is the natural home).
- Compaction writer change in `app/services/compaction.py` if file-mode does not currently populate `ConversationSection.embedding`.
- Migration to backfill embeddings if needed.
- New `Bot.section_recall_halflife_days` field + migration.
- Tests:
  - Unit: a query close to a section summary surfaces that section over a less-relevant but more recent one beyond the recency-decay threshold.
  - Unit: token-budget cap is honored.
  - Integration: a turn referring obliquely to past chat retrieves the relevant section.

### Verification

- Trace inspection: Daily Health surfaces a count of "ambient section recalls per day" and the agent_quality_audit lane records which sections were injected. **Cancel or rescope if the ambient recalls are mostly noise rather than signal** - the recency-decay constant is the failure mode most likely to need tuning.

### Open questions

- Should ambient section recall be opt-in per bot? **Recommendation: opt-in for one release**, then default-on once tuning is validated. Hot-path context is high-stakes; a noisy default is hard to retract.

## Phase 5 - Cross-source entity links

### Goal

Knowledge entries link to their sources (originating message, attached images) so a user can navigate from an entry back to its provenance and the agent can include linked attachments when an entry is recalled. This is the smallest viable form of the cross-source pattern that defines context engines.

### Design

- New `entity_links` SQLAlchemy model + migration:
  ```
  entity_links(
    id PK,
    entity_kind str,         # "knowledge_entry" in v1
    entity_id str,           # the knowledge entry's entry_id (ULID)
    source_kind str,         # "message" | "attachment" in v1
    source_ref str,          # message UUID or attachment UUID (kind-dependent)
    confidence float,
    created_at timestamp,
  )
  ```
- `entity_kind` values: `knowledge_entry` only in v1. Future kinds (`person`, `place` as resolved entities) are reserved.
- `source_kind` values: `message`, `attachment` in v1. `calendar_event`, `drive_doc`, `email_thread` are reserved for the future integration-driven-capture follow-up plan; this plan does **not** wire them.
- Phase 1's writer is extended to insert `entity_links` rows linking the capture to its source message id (always present) and any image attachments on the source message (looked up via `app/services/recent_attachments.py`'s helpers or a sibling).
- Phase 3's generic browser is extended to render linked sources as `Source link` and `Linked images` rows on the entry detail view.
- Ambient recall (Phase 4): when a knowledge entry chunk is injected by `inject_user_knowledge()`, look up its top-N linked attachment ids and append them via the same channel as `recent_attachments.py` (`RecentInlineImageContext` shape).

### Deliverables

- Migration: new `entity_links` table + indexes on `(entity_kind, entity_id)` and `(source_kind, source_ref)`.
- New `app/db/models.py` row class.
- Writer + reader in `app/services/entity_links.py`.
- Phase 1 writer extended to populate links at capture time.
- Phase 3 generic browser extended to render `Source link` + `Linked images`.
- `inject_user_knowledge()` extended to append linked attachments via the existing recent-attachments payload shape.
- Tests:
  - Unit: a capture from a turn with an attached image creates `(knowledge_entry, attachment)` and `(knowledge_entry, message)` rows.
  - Unit: ambient recall of an entry with a linked attachment surfaces the attachment in the injected context payload.
  - Integration: detail view renders both rows correctly for a captured-then-promoted entry.

### Verification

- Dogfood: ask "show me the photo of the pumpkin pie I made" in a fresh chat; the agent surfaces the linked image without the user naming a source.

### Open questions

- Is `entity_links` the right shape long-term, or should it be a graph DB? **Recommendation: stay with the relational table.** Personal-scale data does not justify a graph DB; the table supports the queries we need today and the migration cost to a graph layer later is not large.
- When (Phase 6+, separate plan) integrations begin contributing entities, do they get their own `entity_kind` values, or do they normalize into `knowledge_entry` with a `source_kind` of `calendar_event` etc.? **Recommendation: normalize into `knowledge_entry`** to keep the surface uniform. Distinct `entity_kind` values reserved for cases where the entity *is* the source (e.g., a Person resolved across multiple captures).

## Risks

- **Capture noise**: an over-eager extractor floods the review queue with junk. Mitigation: review-first means noise stays out of agent context; skip rules cover background/heartbeat/ack turns; operator can tighten the extractor prompt before the queue grows unmanageable.
- **Cost**: a fast-model extractor runs per turn. At Haiku 4.5 pricing this is small but not free. Mitigation: skip rules cover the cheapest-to-skip turn classes; cost surfaced in the existing usage telemetry; abort if dogfood shows cost / value imbalance before promoting beyond the operator.
- **Cross-user leak**: per-user separation must be a hard boundary. Mitigation: integration test in Phase 1 deliverables explicitly verifies u1 → u2 isolation; merge-gated.
- **Stale section recall** (Phase 4): file-mode semantic recall might surface old advice the user has since moved past. Mitigation: recency decay, per-bot opt-in for one release, trace surfacing in `agent_quality_audit`.
- **Skill packs ship competing schemas for the same `type` string**: two skill packs both define `recipe` differently, fragmenting the data. Mitigation: documented in the Phase 3 hand-off seam — type-string collisions are the skill-pack ecosystem's problem, not core's. Core treats `type` as opaque.

## Validation across phases

- After Phase 1: operator dogfood for one day shows non-trivial captures landing in the review queue at a rate that's worth reviewing (target: 1-5 review entries per active hour, mostly accept-worthy). Cross-user leak integration test passes.
- After Phase 3: a non-AI user opens "Knowledge" in the sidebar at least once unprompted in a week, and edits or forgets at least one entry that was wrong.
- After Phase 4: `agent_quality_audit` trace shows >=1 useful ambient section recall per active day; no noise spike in the same lane.
- After Phase 5: an entry detail view renders source-message + linked-image rows for at least 50% of captures from chats that included an image.

## Out of scope (follow-up plans)

- Auto-capture from integration sources (Gmail / Calendar / Drive). Belongs to a follow-up once the conversation-driven capture loop is validated. The `entity_links` table from Phase 5 is the seam.
- Cross-instance knowledge sharing.
- Knowledge-entry version history and diff view.
- A general "Person" entity resolved across captures (Phase 5's open question).
- Embedding-store backing for knowledge retrieval — revisit only if the existing hybrid retrieval underperforms on this corpus.
- **Domain-specific typed cards / forms** (e.g., a Recipe Box, a Garden, a Person card with relationship fields). Belongs to skill-pack-driven follow-up plans that consume the Phase 3 view-registration seam and read/write the same underlying Notes via the existing API.
- **A parallel system alongside Notes.** This plan refactors Notes infrastructure into the unified Knowledge Document primitive (Phase 0.5); existing Notes becomes a consumer of that primitive. There is **one** knowledge surface end-to-end, not two.
- **Exposing scope vocabulary to end users.** Channel / project / user / bot are author-side metadata, hidden behind the scope-invisible UI principle (Phase 3 lint).
- Per-message "forget this turn" gesture. Per-channel `knowledge_capture: off` is the only escape hatch v1 ships.
- Confidence-threshold "live capture" path. v1 is review-first only; the `mode: "review" | "live"` field on the bus event is reserved.

## Hand-off checklist (start here for a fresh session)

A new session picking this plan up should:

1. **Read this plan top to bottom.** Locked decisions are in the TL;DR; design is in the per-phase sections.
2. **Read `docs/tracks/user-knowledge-graph.md`** for current phase status and any deltas since this plan was authored.
3. **Confirm the anchor files are still where this plan says they are.** Run:
   - `grep -n "async def inject_bot_knowledge_base" app/agent/context_admission.py` (expect ~line 840)
   - `grep -n "_excluded_prefixes\|FilesystemChunk.bot_id" app/agent/fs_indexer.py` (expect ~907 and ~920-924)
   - `grep -n "ensure_host_dirs\|users\|knowledge-base" app/services/shared_workspace.py | head -20`
   - `grep -n "user_id" app/db/models.py | grep -B1 -A1 "Bot\|^[0-9]*:    user_id" | head -10` (expect `Bot.user_id` ~line 1243)
   - `grep -n "class ChannelEventKind" app/domain/channel_events.py` (expect ~line 55)
   - `grep -n "class NotesSurface\|resolve_notes_surface\|get_or_create_note_session" app/services/notes.py` (expect class at ~35, resolver at ~156, session at ~622)
   - `ls ui/app/\(app\)/channels/\[channelId\]/NoteWorkspacePage.tsx ui/app/\(app\)/channels/\[channelId\]/NotesTabPanel.tsx` (Phase 3 substrate)
   - If any anchor has moved, update the plan in the same PR as Phase 0 / Phase 1 work.
4. **Phase 0 first (standalone PR).** Fix `retrieve_filesystem_context` to support include-prefix filtering. This is a bug fix; it ships independently with a `docs/fix-log.md` line.
5. **Phase 1 second.** Implement the capture pipeline + indexing-after-write seam + bus event + admin review page. Cross-user leak test is a merge gate. Co-ship `docs/guides/knowledge-bases.md` updates.
6. **Phase 2 is not a separate ship** — it's the contract section for Phase 1. Verify all invariants in the "Phase 2" section are honored by Phase 1's tests.
7. **Phases 3, 4, 5 ship in order**, each as its own PR.
8. **Always update the track file** (`docs/tracks/user-knowledge-graph.md`) when a phase status changes.

## Links

- **Verified-in-code anchor files** (read these first when picking up the plan):
  - `app/agent/context_admission.py` — `inject_bot_knowledge_base` (840), file-mode section index (649), structured-mode section recall (619-647).
  - `app/agent/fs_indexer.py` — `retrieve_filesystem_context` (902 and below), exclude-prefix logic (907), `bot_id` admission clause (920-924).
  - `app/services/shared_workspace.py` — workspace layout (40-68), `ensure_host_dirs` (51-56), `ensure_bot_dir` (58-68).
  - `app/db/models.py:1243` — `Bot.user_id` (UUID, nullable).
  - `app/domain/channel_events.py:55` — `ChannelEventKind` enum + payload registry.
  - `app/services/sessions.py:830` — `persist_turn` (commit at 888, bus publish via `_publish_persisted_messages_to_bus` at 792, called at 908).
  - `app/services/bot_indexing.py` — `BotIndexPlan` (30), `resolve_for` (53), `reindex_bot` (224), `reindex_channel` (352).
  - `app/services/workspace.py:58` — `get_bot_knowledge_base_index_prefix` (model for `get_user_knowledge_index_prefix`).
  - `app/services/recent_attachments.py` — pattern for ambient context primitives + `RecentInlineImageContext` shape used in Phase 5 retrieval.
  - `app/services/compaction.py` — `ConversationSection` writer; check whether file-mode populates `embedding`.
  - `app/services/temporal_context.py` — Phase 4 home for `recency_decay` helper.
  - **`app/services/notes.py`** — existing Notes service. `NotesSurface` (line 35) is already scoped to `"channel"` or `"project"`; notes live at `<workspace>/knowledge-base/notes/` (channel) or `<project>/.spindrel/knowledge-base/notes/` (project). Notes write to the same knowledge-base path that `inject_bot_knowledge_base` retrieves from, so a Note is automatically indexed and ambient-retrievable. Frontmatter is supported (`parse_frontmatter` / `render_frontmatter`).
  - **`app/services/notes.py:622` — `get_or_create_note_session()`** binds a real Session (with `metadata.kind = "note_session"`) to each Note, providing the per-Note mini-chat the user sees in `NoteWorkspacePage.tsx`. The AI-assist endpoint (`build_ai_assist_proposal`) returns proposed edits + a suggestion comment without auto-applying — a proposal-review pattern that mirrors the Phase 1 review-first capture model.
  - **`app/routers/api_v1_notes.py`** — REST API at `/channels/{channel_id}/notes`. Endpoints: list, create, read, write, assist.
  - **UI: `ui/app/(app)/channels/[channelId]/NotesTabPanel.tsx` + `NoteWorkspacePage.tsx`** — full Note editor with markdown view, AI-assist with selection, embedded `<ChatSession>` for the bound mini-chat, autosave, frontmatter editing, model picker. **This is the substrate Phase 3 reuses; no new `/knowledge` route is needed.**
- Adjacent governance: `docs/tracks/context-surface-governance.md` (token-budget lane), `docs/tracks/agent-quality-observability.md` (trace surfacing).
- Canonical guide to update: `docs/guides/knowledge-bases.md` (in the same edit as Phase 1 ships).
- Worksurface scope doc to update: `docs/guides/worksurface-isolation.md` (in the same edit as Phase 1 ships, since Phase 2 is in-Phase-1).
- Architectural rationale: new entries in `docs/architecture-decisions.md` for (a) "Per-user knowledge surface as a third type of memory" and (b) "Per-user knowledge scope is a hard security boundary".
- Track: `docs/tracks/user-knowledge-graph.md`.
