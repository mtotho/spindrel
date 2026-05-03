---
title: Plan - User Knowledge Graph (personal context engine)
summary: Six-phase plan (Phase 0 prereq + 5 main) to bridge agent-curated memory and user-curated knowledge bases into a single auto-captured, user-readable, typed per-user knowledgebase that non-AI users get for free - the "personal context engine" gap.
status: active
tags: [spindrel, plan, knowledge, memory, context-engine, projects]
created: 2026-05-03
updated: 2026-05-03
---

# Plan - User Knowledge Graph (personal context engine)

## TL;DR

Spindrel today has two disconnected knowledge halves: agent-curated `memory/MEMORY.md` (the bot's notes to itself) and user-curated `knowledge-base/*.md` (a folder the user must populate manually). Neither is what a non-AI user (the canonical example: a baking-assistant or gardening-assistant user who is not going to manage a markdown vault) actually benefits from. The gap is a third surface: an automatically captured, user-readable, typed knowledgebase that the bot writes to as a default behavior and the UI surfaces as domain-appropriate cards (`Recipe Box`, `Garden`, `People`) instead of as a folder of files. This plan extends existing primitives - `recent_attachments.py`, `ConversationSection`, the `knowledge-base/` retrieval path, and the memory-flush pattern - through five phases. Phase 1 (auto-capture) is the load-bearing unlock; the rest compound on it.

## Context

- Today's primitives, verified in code:
  - `app/agent/context_admission.py:840-905` - `inject_bot_knowledge_base()` builds `kb_segments` with a `path_prefix` and calls `retrieve_filesystem_context()`. **Pre-existing defect:** the `path_prefix` is never an include filter; `retrieve_filesystem_context` (`app/agent/fs_indexer.py:907`) only uses the segments list for exclusion + embedding-model collection. Today's "bot KB retrieval" is effectively bot-workspace-wide retrieval narrowed by `roots` and `bot_id`. This must be fixed (Phase 0) before adding new prefix-scoped surfaces.
  - `app/agent/fs_indexer.py:920-924` - `FilesystemChunk` retrieval admits `bot_id == current OR bot_id IS NULL`. Per-user / shared-knowledge rows must be indexed with `bot_id = NULL` to be visible across bots.
  - Indexing is **not live filesystem scan**: retrieval is over the `FilesystemChunk` table. Writing a file is not enough; an indexer pass must run after the write.
  - `app/services/shared_workspace.py:54` - canonical workspace layout is `bots/`, `common/`, `users/`, `integrations/`. Per-user knowledge belongs at `users/<user_id>/knowledge/`, **not** an invented `workspace/user-knowledge/` path.
  - `app/db/models.py` - `Bot.user_id` already exists, so per-user scoping has a primary key to hang on.
  - `app/services/memory_scheme.py`, `app/services/memory_hygiene.py` - `memory/MEMORY.md` is agent-curated via a "memory flush" prompt before compaction. **Not user-readable as a knowledgebase; surfaced only in admin views.**
  - `app/services/compaction.py` - `ConversationSection` rows carry `title`, `summary`, `tags`, `embedding`, `period_start/end`. `app/agent/context_admission.py:619-647` **already auto-injects** sections semantically when `history_mode == "structured"` (top-3 by cosine distance), and injects a section index when `history_mode == "file"`. Phase 4 below is therefore a *recall/ranking improvement on file mode*, not a from-scratch ambient-recall introduction.
  - `app/services/recent_attachments.py` - the canonical pattern for "ambient context primitive": pure-function scan over recent messages, returns a small typed payload, plugged into the turn pipeline before LLM call. The recent untracked `app/services/chat_late_input.py` follows the same shape.
  - `app/services/sessions.py:888` - `persist_turn()` commits + publishes the assistant message **before** background audit scheduling. A capture pass that runs after persistence cannot embed "Saved to Recipe Box" metadata into the existing assistant message; it must emit a separate typed event over the bus or update the persisted message via a follow-up edit.
  - Integrations (Gmail, Calendar, Drive) are exposed as **tools only**. No ambient push, no cross-source linking.
- The roadmap line "Knowledge Base convention" (under Completed) describes the user-curated half only. "Memory hygiene" describes the agent-curated half only. There is no spine joining them and no plan that names the missing surface.
- Real usage observation: the operator (an AI-fluent power user) is the only one who reliably writes to `knowledge-base/`. A second user (non-AI background, hobby-assistant use cases) gets no benefit from these primitives today because nothing populates them on her behalf and the UI does not surface them in domain terms.
- Spindrel is single-user-per-instance in the common case but the workspace singleton supports multiple bots that share a workspace. Knowledge scoping is therefore an open design choice (per-bot vs per-channel vs per-workspace vs per-namespace) - resolved in Phase 2.

## Goals

- A bot turn can produce typed, user-readable knowledge entries as a default behavior, with no user prompting and no skill the user must invoke.
- The user can open a domain-appropriate UI surface (`Recipe Box`, `Garden`, `People`) and see what their assistant has remembered about them, edit it, or forget it - **without ever opening a file or learning the word "knowledgebase".**
- Multiple bots in the same workspace read and write the same shared user-knowledge namespace, so the baking bot, the gardening bot, and the general assistant build a compounding picture of the user.
- The agent ambiently recalls relevant prior conversations (compaction sections) on a normal turn, ranked by `relevance × recency`, without the user telling it to look.
- Knowledge entries link to their sources (message id, attached image, calendar event, drive doc) so "show me the photo of the pumpkin pie I made last Thanksgiving" works without manual correlation.

## Non-Goals

- Embedding store as the primary knowledge index. Existing hybrid file-system + semantic retrieval is sufficient at personal scale; adding a vector DB has worse cost/value than at enterprise scale.
- A "vault editor" or markdown surface for non-AI users. Knowledge is surfaced as typed cards; the markdown form is an implementation detail.
- Cross-instance / multi-tenant knowledge sharing. Single-instance scope only.
- Replacing `memory/MEMORY.md` (agent-curated bot notes) or `knowledge-base/` (user-curated docs). Both remain. The new surface is additive.
- Inline knowledge editing inside the chat composer. Editing happens in the typed-card UI. Chat is a write-side input, not a structured editor.
- Auto-capture from integration sources (Gmail / Calendar / Drive). That belongs to a follow-up plan once Phase 1-3 are validated; conversation-driven capture is the wedge.

## Phase order

Phase 0 is a load-bearing prereq that is also a standalone bug fix worth shipping on its own merits. Phase 1 ships next as the standalone unlock. Phase 2 reframes Phase 1 storage as per-user from day one (we may collapse Phase 1 + 2 into a single shipped slice once design is locked). Phase 3 produces the user-facing UX win. Phase 4 and 5 are independent improvements that can ship in either order after Phase 3.

0. **Phase 0** - Fix KB retrieval prefix scoping in `retrieve_filesystem_context` so `kb_segments` is an *include* filter, not just an exclusion source. Standalone bug fix, prereq for Phase 1.
1. **Phase 1** - Auto-capture pass with **review-first default**: extract typed knowledge candidates from meaningful turns, write them to a `_review/` queue with stable `entry_id` + per-type JSON frontmatter, run the indexer immediately after write, emit a typed `knowledge_capture` bus event for UI surfacing.
2. **Phase 2** - Per-user scope from day one: store at `users/<user_id>/knowledge/<type>/...`, index with `bot_id = NULL`, retrieved by all bots whose `Bot.user_id` matches. (We index user-scoped from the first commit; "per-bot only" is not a target state.)
3. **Phase 3** - Typed-card UI: render typed entries as domain-appropriate cards (`Recipe Box`, `Garden`, `People`) with edit / forget / promote-from-review affordances.
4. **Phase 4** - File-mode conversation recall: improve the existing `history_mode == "file"` section-index injection to do semantic recall + recency ranking (matching what structured mode already does, plus recency decay).
5. **Phase 5** - Cross-source entity links: small `entity_links` table joining knowledge entries to source messages, attachments, and (later) integration items.

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

## Phase 1 - Auto-capture pass (review-first default)

### Goal

Every meaningful agent turn produces 0..N typed knowledge candidates, written to a `_review/` queue (or to live state above a high confidence threshold - see Open questions), with stable IDs, per-type JSON frontmatter, immediate indexing, and a typed bus event for UI surfacing. **This phase alone makes the bot remember things automatically; everything after it improves how that capture is shared and surfaced.**

### Design

- **Storage shape (per-user from day one - see Phase 2 for the path rationale):**
  - Live: `users/<user_id>/knowledge/<type>/<slug>__<entry_id>.md`
  - Review: `users/<user_id>/knowledge/_review/<type>/<slug>__<entry_id>.md`
  - `entry_id` is a stable ULID written into the frontmatter and into the filename. Edits never change the id; renames keep the id; deletes are by id. This is the primary key the UI and `entity_links` table reference.
  - Frontmatter is a per-type JSON schema, **not** just `{title, body}`. Body remains markdown for narrative; structured fields live in frontmatter. Examples:
    - `recipe`: `{entry_id, type:"recipe", title, ingredients:[{name, qty, unit}], steps:[str], yields, source_message_id, created, updated, confidence, scope:"user", user_id, captured_by_bot_id}`
    - `plant`: `{entry_id, type:"plant", title, common_name, location, planted_date, watering_cadence_days, ...}`
    - `person`: `{entry_id, type:"person", title, relationship, preferences:[str], notable_dates:[{date, label}], ...}`
    - `recipe`/`plant`/`person`/`place` use real schemas; `preference`/`fact`/`decision`/`note` use a generic body-only schema.
  - One **type registry** module (`app/services/knowledge_types.py`) defines schemas; the writer validates against the registry; the UI renderer dispatches off `type`.
- New service `app/services/knowledge_capture.py`, modeled on `app/services/recent_attachments.py`:
  - Pure function `extract_knowledge_candidates(turn_context, llm_client) -> list[KnowledgeCandidate]`.
  - `KnowledgeCandidate = {type, title, body, structured_fields, confidence, source_message_id}`.
  - Allowed `type` values are the registry enum starting tight: `recipe`, `preference`, `fact`, `decision`, `person`, `place`, `plant`, `note`. Unknown types are dropped (not silently coerced to `note` - prevents type drift).
- **Skip rules** (hard - capture must not run on these turns):
  - `context_visibility == "background"` messages.
  - Tool-result acknowledgment turns (heuristic: assistant message is < N chars and contains no novel content).
  - Heartbeat / scheduled turns from cron / pipeline / standing-order origins.
  - Channels with `channel.config["knowledge_capture"] == "off"`.
  - Bot-to-bot delegation turns (no human user in the loop).
  - Skip rules are codified in `knowledge_capture.py` as named predicates with unit coverage.
- **Indexing-after-write:** after the writer commits a file, it calls into `app/services/bot_indexing.py` (or the workspace indexer) to index the new file synchronously with `bot_id = NULL` (so it's visible across bots in Phase 2). Without this step, retrieval cannot see the capture; this is the F2 correction. If indexing fails, the file remains on disk but is logged + traced as un-indexed.
- **Event contract for the UI chip (F6 correction):**
  - Capture emits a typed bus event `knowledge_capture` with `{entry_id, type, title, scope, user_id, source_message_id, confidence, mode: "review" | "live"}` after successful write + index.
  - The UI subscribes to this event over the existing channel SSE stream and renders the inline chip below (not inside) the assistant message that triggered it.
  - We do **not** edit the persisted assistant message body. The chip is a UI-only annotation derived from the typed event, joined to the message by `source_message_id`.
- Retrieval (after Phase 0): the per-user knowledge surface is a new injector, e.g., `inject_user_knowledge()` in `context_admission.py`, modeled on `inject_bot_knowledge_base()` but scoping by `Bot.user_id` and admitting `bot_id IS NULL` chunks under `users/<user_id>/knowledge/` prefix. Reuses Phase 0's include-prefix mechanism.
- Configuration:
  - New `Bot.knowledge_capture_enabled` field. **Default = open question (see below).**
  - New `Bot.knowledge_capture_model` field (default: a fast cheap model declared in settings).
  - New per-channel `channel.config["knowledge_capture"]` override (`"on"` | `"off"` | unset to inherit).
  - Both editable from the bot/channel admin UI; channel-level toggle is the user-facing escape hatch for sensitive threads.

### Deliverables

- `app/services/knowledge_types.py` (type registry + per-type frontmatter validators).
- `app/services/knowledge_capture.py` (extractor + skip rules + writer).
- `inject_user_knowledge()` injector in `app/agent/context_admission.py`.
- Bus event `knowledge_capture` declared in the typed-bus event registry.
- Migration adding `bots.knowledge_capture_enabled`, `bots.knowledge_capture_model`.
- Index-after-write seam in the writer.
- Tests:
  - Unit: extractor returns expected typed candidates for synthetic turns; respects all skip rules.
  - Unit: writer rejects type-schema violations (no silent coercion).
  - Unit: writer assigns stable `entry_id`; rewrites preserve id.
  - Unit: file is queryable via `inject_user_knowledge()` immediately after write (proves indexing-after-write seam).
  - Unit: bus event is emitted with correct payload shape.
  - Integration: a turn produces a capture, the next turn's context retrieval surfaces it across **two different bots** owned by the same user.
- Same-edit doc updates: `docs/guides/knowledge-bases.md` (canonical) gets an "Auto-Captured User Knowledge" section; new entry in `docs/architecture-decisions.md`; track row added under Active in `docs/roadmap.md`.

### Verification

- Unit tests above pass under the local `.venv` Python guard.
- Manual dogfood: enable on the operator's primary bot, run normal chat for one day, inspect `users/<user_id>/knowledge/_review/` for sane entries and `users/<user_id>/knowledge/<type>/` (if the high-confidence promotion path is enabled). **Cancel or rescope if extracted entries are mostly noise** - the extraction prompt is the failure mode most likely to need iteration.

### Open questions (require user decisions before implementation)

- **Default-on vs review-first vs opt-in.** The reviewer flagged silent default-on as privacy/noise risky. Options:
  - **(a) Default-on, threshold-promoted:** capture runs for every workspace-files bot; high-confidence captures land in live state, low-confidence in `_review/`. Maximum non-AI-user benefit, real noise/privacy risk.
  - **(b) Default-on, review-first:** capture runs by default, but **everything** lands in `_review/` for the first N days or first N captures. User must explicitly accept entries before they go live. Phase 3 UI is on the critical path.
  - **(c) Opt-in:** capture is off by default; user (operator) flips it on per-bot.
  - **Recommendation:** (b). Captures the non-AI-user benefit while making noise visible before it influences agent behavior. Requires Phase 3 review UI to be co-shipped, or at least an admin "what was captured" page.
- Inline (blocking turn-complete) vs out-of-band (background task) extraction. **Recommendation: out-of-band**, given F6 — the chip is now a typed event, not an inline annotation, so there is no UX dependency on inline timing.
- Should low-confidence captures be visible to the agent at retrieval time? **Recommendation: no in v0; only `_review/` UI surfaces them.**

## Phase 2 - Per-user knowledge scope (locked-in from day one)

### Goal

Make the captured knowledge surface a **per-user** scope so multiple bots owned by the same user compound their captures into one picture of that user, while bots owned by a different user (in the same instance) see their own. This is the structural change that turns the feature from "this one bot remembers things" into "your assistant ecosystem knows you" - and it is set in stone from day one rather than migrated to later, since per-bot capture would create user-visible state that's painful to migrate out of.

### Design

- Filesystem path: `users/<user_id>/knowledge/<type>/<slug>__<entry_id>.md` and `users/<user_id>/knowledge/_review/<type>/<slug>__<entry_id>.md`. This nests under the existing `users/` workspace subdirectory (`shared_workspace.py:54`), not an invented sibling.
- Indexing: `FilesystemChunk.bot_id = NULL` for these entries. `client_id` is also `NULL`. Retrieval admits `bot_id IS NULL` per `fs_indexer.py:920-924`, so any bot whose `Bot.user_id == <user_id>` and whose `inject_user_knowledge()` call passes the matching `users/<user_id>/knowledge/` include-prefix will see the entries. Entries from other users' folders are filtered out by the include-prefix.
- Retrieval: `inject_user_knowledge()` (added in Phase 1) reads `Bot.user_id`, builds the include-prefix `users/<user_id>/knowledge/`, calls `retrieve_filesystem_context()` with that include filter (Phase 0 mechanism), admits the chunks. Entries in `_review/` are excluded from agent retrieval (live folder only).
- Conflict / merge: when two bots write to the same `entry_id` slug within a short window, the later writer appends a dated bullet to the body rather than overwrites, and updates frontmatter `captured_by_bot_ids` to include both. The `entry_id` stays stable.
- Privacy invariant: per-user knowledge is shared across **bots owned by the same user in the same instance**. Never across users, never across instances. `worksurface-isolation` doc gets an explicit row for this scope. Cross-user leak would be a security defect.
- Open question (see below): what happens when `Bot.user_id` is NULL (workspace-owned / system bots)?

### Deliverables

- Writer in `knowledge_capture.py` resolves the user-id path from `Bot.user_id` at write time (no `Bot.knowledge_scope` field needed - the scope is structural, not configurable).
- Retriever `inject_user_knowledge()` reads `Bot.user_id` and applies the prefix filter.
- Update `docs/guides/worksurface-isolation.md` with the new scope row.
- Tests:
  - Unit: capture from bot A (`user_id=u1`) is retrieved on a turn for bot B (`user_id=u1`).
  - Unit: capture from bot A (`user_id=u1`) is **not** retrieved on a turn for bot C (`user_id=u2`).
  - Unit: capture from bot with `user_id=NULL` lands in a documented fallback path (see open question).
  - Unit: `_review/` entries are excluded from agent retrieval.
  - Unit: simultaneous writes to the same `entry_id` append rather than overwrite, and merge `captured_by_bot_ids`.

### Verification

- Two-bot dogfood: a baking bot owned by user X captures a recipe; a general assistant also owned by user X, asked "what did I bake last week?", retrieves the captured recipe entry.

### Open questions (require user decisions)

- **Bots with `user_id = NULL`** (system / workspace-owned bots, if those exist in your deployment): three options - (a) skip capture entirely, (b) capture into a `users/_workspace/knowledge/` shared bucket visible to all NULL-user bots, (c) treat the bot's own `bot_id` as the scope key. **Recommendation: (a)** unless you actually use NULL-user bots for hobby-assistant work; `_workspace/` is a foot-gun for cross-user leak.
- Should there be a "bot can write to user knowledge but not read from it" permission split? **Recommendation: not in v0.** Symmetric read/write keeps the model simple.

## Phase 3 - Typed-card UI

### Goal

The user opens a domain-appropriate UI surface (`Recipe Box`, `Garden`, `People`) instead of a file browser. **This is the phase that makes the feature visible to non-AI users.** A user who would never open `knowledge-base/foo.md` will absolutely open "your Recipe Box" if it has six recipes already in it.

### Design

- Per-type renderers in the existing widget system (the `widget_*` services already render typed payloads as cards):
  - `recipe`: ingredients list, steps, source link, last-cooked date.
  - `plant`: name, location, planted date, care notes, last-watered.
  - `person`: name, relationship, notable preferences, last-mentioned.
  - `preference`, `fact`, `decision`, `note`: generic card with title + body + edit/forget controls.
- New UI route per type: `/knowledge/<type>` rendering the corresponding card grid.
- Sidebar entry: "What I've Learned" group with sub-entries per type that has at least one entry. **Hidden entirely if no captures exist** - a non-AI user never sees an empty vault sidebar.
- Affordances per card:
  - **Edit**: opens an inline form (the typed schema, not raw markdown).
  - **Forget**: deletes the file. Confirms once.
  - **Promote**: moves a `_review/` candidate into the live folder.
  - **Source link**: jumps to the originating chat message (uses Phase 5's link table when present, falls back to `source_message_id` frontmatter).
- Capture surfacing in chat: after a turn that produced a capture, the chat shows a low-chrome inline chip ("Saved to Recipe Box: Sourdough at 75% hydration") with a tap-to-edit affordance. **Single chip per turn max; never modal, never blocking.**
- The `_review/` queue surfaces as a "Things I'm not sure about" tab on the relevant type page, not as its own sidebar entry. **Default to invisible until non-empty.**

### Deliverables

- Per-type card renderers (one widget per type) in `ui/`.
- New `/knowledge/<type>` routes and sidebar entries.
- Inline-chip surfacing of captures in `ChatMessageArea` (or a sibling layer - exact mount point per the chat-scroll invariants in `AGENTS.md`).
- API endpoints: list / get / update / delete per type.
- Tests: UI typecheck + screenshot fixtures for Recipe Box (populated and empty states).
- Same-edit guide updates: `docs/guides/ui-design.md` reference for typed-card archetype if the pattern is novel; otherwise just `docs/guides/knowledge-bases.md`.

### Verification

- Dogfood week: hand to a non-AI user, observe whether she opens any of the typed surfaces unprompted, observe whether she ever edits an entry. **The honest pass criterion is "she opens the Recipe Box at least once without being told it exists" - if not, capture surfacing in chat is too quiet.**

### Open questions

- Should typed-card edits trigger a "the bot will use this updated info next time" toast? **Recommendation: yes, once per session.** Establishes the causal loop in the user's head without nagging.
- Generic types (`fact`, `note`, `decision`) - do they need their own surfaces or roll up under a single "Other" page? **Recommendation: single "Other" page in v0, split if the type proves to have a coherent UX of its own.**

## Phase 4 - File-mode conversation section recall (improvement, not introduction)

### Goal

**Reframe (per F5):** structured-mode bots already get semantic auto-injection of `ConversationSection` rows by cosine distance (`context_admission.py:619-647`). File-mode bots get an ordered section *index*, not a similarity-ranked recall. Phase 4 brings file-mode bots up to parity with structured-mode by adding semantic recall + recency ranking, since file-mode is the dominant memory_scheme for the hobby-assistant use case.

### Design

- In `context_admission.py:649` (the `hist_mode == "file"` branch), add an opt-in semantic recall path that runs *in addition to* the existing section index.
- `ConversationSection.embedding` already exists for structured mode. Confirm whether file-mode sections also populate it; if not, populate during compaction (small writer change).
- Ranking: `cosine_similarity(query, section.embedding) × recency_decay(section.period_end)`. Recency decay is a simple exponential with half-life of (probably) 30 days; tunable per bot. Authority weighting deferred (no current scope hierarchy worth weighting).
- Token budget: cap injected sections at 2-3 per turn, total token budget governed by the existing context-budget governance lane (`docs/tracks/context-surface-governance.md`).
- Storage: no new tables. May require a small migration to populate `embedding` for existing file-mode sections.

### Deliverables

- Extension to context injection in `app/agent/context_admission.py`.
- Recency-decay helper in `app/services/temporal_context.py` (the existing temporal-context module is the natural home).
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

Knowledge entries link to their sources so "the photo of the pumpkin pie I made last Thanksgiving" resolves automatically. This is the smallest viable form of the cross-source-graph pattern that defines context engines.

### Design

- New `entity_links` table:
  ```
  entity_links(
    id, entity_kind, entity_id,
    source_kind, source_ref,
    confidence, created_at
  )
  ```
- `entity_kind` values: `knowledge_entry`. (Single value in v0; reserved for future expansion to `person`, `place`, etc. as first-class entities.)
- `source_kind` values: `message`, `attachment`, `calendar_event`, `drive_doc`, `email_thread`. (Last three are no-ops at write time in v0; reserved for the future integration-driven capture follow-up.)
- Phase 1's writer additionally inserts `entity_links` rows linking the capture to its source message and any attached images at extraction time.
- Phase 3's typed-card UI surfaces linked sources inline (e.g., recipe card shows the photo, link to the chat moment).
- Retrieval: when a knowledge entry is injected as ambient context, its top-N linked attachments are appended via the existing `recent_attachments` payload shape.

### Deliverables

- Migration: new `entity_links` table + indexes on `(entity_kind, entity_id)` and `(source_kind, source_ref)`.
- Writer + reader in `app/services/entity_links.py`.
- Phase 1 writer extended to populate links.
- Phase 3 UI extended to render links on cards.
- Tests:
  - Unit: a capture from a turn with an attached image creates a `(knowledge_entry, attachment)` link.
  - Unit: ambient recall of a knowledge entry includes its linked attachment in the context payload.

### Verification

- Dogfood: ask "show me the photo of the pumpkin pie I made" in a fresh chat; the agent surfaces the linked image without the user naming a source.

### Open questions

- Is `entity_links` the right shape long-term, or should it be a graph DB? **Recommendation: stay with the relational table.** Personal-scale data does not justify a graph DB; the table supports the queries we need today and the migration cost to a graph layer later is not large.
- When (Phase 6+, separate plan) integrations begin contributing entities, do they get their own `entity_kind` values, or do they normalize into `knowledge_entry` with a `source_kind` of `calendar_event` etc.? **Recommendation: normalize into `knowledge_entry`** to keep the surface uniform. Distinct `entity_kind` values reserved for cases where the entity *is* the source (e.g., a Person resolved across multiple captures).

## Risks

- **Capture noise**: an over-eager extractor pollutes the user's typed surfaces with junk. Mitigation: high default confidence threshold, `_review/` queue for low-confidence, per-type surfaces hidden until non-empty, easy "forget" gesture.
- **Cost**: a fast-model extractor runs per turn. At Haiku 4.5 pricing this is small but not free. Mitigation: skip extraction for short turns, skip when the agent's response is itself a tool-result acknowledgment, monitor cost in `Daily Health`.
- **Scope creep into structured editing**: the temptation to give the user a full markdown editor over the typed entries. Mitigation: design the typed-card UI as the canonical edit surface; the markdown form is an implementation detail.
- **Privacy creep across bots**: workspace scope is broader than per-bot. Mitigation: explicit `Bot.knowledge_scope` setting, doc invariant in `worksurface-isolation.md`, no cross-workspace sharing.
- **Old-section ambient recall surfaces stale advice**: Phase 4 risk. Mitigation: recency decay, per-bot opt-in for one release, trace surfacing in Daily Health.

## Validation across phases

- After Phase 1: operator dogfood for one day shows 5+ sane captures from real chat with <20% review-queue rate.
- After Phase 2: two bots in the same workspace produce captures readable to each other.
- After Phase 3: a non-AI user opens a typed surface unprompted at least once in a week.
- After Phase 4: trace shows >=1 useful ambient section recall per active day, and Daily Health does not flag a noise spike.
- After Phase 5: "show me the photo of X" works without naming a source.

## Out of scope (follow-up plans)

- Auto-capture from integration sources (Gmail / Calendar / Drive). Belongs to a follow-up once the conversation-driven capture loop is validated. The `entity_links` table from Phase 5 is the seam.
- Cross-instance knowledge sharing.
- Knowledge-entry version history and diff view.
- A general "Person" entity resolved across captures (Phase 5's open question).
- Embedding-store backing for knowledge retrieval - revisit only if the existing hybrid retrieval underperforms on this corpus.

## Links

- Existing primitives: `app/services/recent_attachments.py`, `app/services/memory_hygiene.py`, `app/services/compaction.py`, `app/agent/context_admission.py`, `app/services/memory_scheme.py`.
- Adjacent governance: `docs/tracks/context-surface-governance.md` (token-budget governance lane), `docs/tracks/agent-quality-observability.md` (trace surfacing).
- Canonical guide to update: `docs/guides/knowledge-bases.md` (in the same edit as Phase 1 ships).
- Worksurface scope doc to update: `docs/guides/worksurface-isolation.md` (in the same edit as Phase 2 ships).
- Architectural rationale: a new entry in `docs/architecture-decisions.md` when Phase 1 ships ("Auto-captured knowledge as a third surface alongside agent memory and user knowledge bases").
