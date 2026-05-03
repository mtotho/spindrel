---
title: User Message Feedback (thumbs up/down)
summary: Subtle per-turn up/down vote in the web UI, mirrored as Slack reactions, persisted as durable per-user feedback and surfaced through existing quality/audit consumers.
status: planned
tags: [spindrel, plan, agents, quality, feedback, ui, slack, integrations]
created: 2026-05-03
updated: 2026-05-03
---

# User Message Feedback

## Summary

Add a subtle thumbs-up / thumbs-down affordance on assistant turns in
conversational chat. Votes are scored at the **turn** level
(`Message.correlation_id`), not per individual `Message` row, because
the end user generally cannot tell which sub-message inside a turn was
the problem — they react to "this answer" as a whole. The affordance
renders on the last user-visible assistant text message of the turn,
but the persisted record and trace event are turn-keyed.

Votes persist as durable, user-attributable rows and are mirrored
into the existing `agent_quality_audit` trace stream so the quality
observability machinery (Daily Health counts, `audit_trace_quality`,
and the conversation-quality-audit dev skill) picks them up
automatically.

The web UI ships first. Slack ships in the same track via the existing
`reaction_handlers.py` seam (`:+1:` / `:-1:` on assistant messages —
mapped back to the owning turn via `Message.metadata->>'slack_ts'`).
Other integrations opt in through a new `message_feedback` capability
on the integration SDK; nothing forces them to implement it on day one.

V1 ships on conversational channels only. Project coding-run review
surfaces already have their own accept / dismiss / needs-info ledger;
layering turn-feedback on top would create two competing review
signals. Revisit after v1 if the ledger turns out to want finer
per-message feedback.

## Goals

- Two-click feedback (hover → vote) on any assistant turn in the web UI.
- Vote is per-user, mutable, optionally carries a one-line comment on
  either direction (up *or* down).
- Per-channel toggle to show or hide the affordance, default **on**.
- Slack reactions on assistant turns are accepted as votes from the
  Slack-mapped user, without breaking the existing `:+1:` approval path.
- Votes are first-class evidence in `agent_quality_audit` trace events
  so no downstream consumer needs feedback-specific code paths to
  react to user-flagged bad turns.
- Daily Health surfaces a "user feedback" count alongside the existing
  deterministic findings.

## Non-Goals

- No public scoring, ranking, or sharing of votes across users.
- No live model-prompt cue from a vote (consistent with quality-audit
  invariant: post-turn evidence, never live prompt injection).
- No reaction → vote mapping in integrations beyond Slack in v1.
- No moderation, dispute flow, or weighting model in v1.
- No analytics dashboard in v1; the feedback shows up in existing
  trace/health/audit surfaces.

## Resolved Decisions

- **Vote target = turn (`correlation_id`).** End user can't reliably
  identify which sub-message in a turn was the problem; a single vote
  per turn matches what they actually react to.
- **Surface scope v1 = chat only.** Project coding-run review surfaces
  already have a richer accept/dismiss/needs-info ledger.
- **Anonymous Slack reactions persist with `user_id = null`.**
  Backfillable later when identity mapping lands. *(Necessary, not
  just convenient — there is currently no Slack→Spindrel `User`
  mapping anywhere in the codebase.)*
- **Channel toggle is a first-class column, not a JSON config key.**
  `Channel` does not have a generic `config` JSONB field — every
  preference (`passive_memory`, `private`, `workspace_rag`, …) is an
  explicit column. The toggle follows that pattern.

## Architecture

### Storage

**New table `turn_feedback`** (named for the turn-level keying):

| column | type | notes |
|---|---|---|
| `id` | UUID PK |  |
| `correlation_id` | UUID, indexed, **not null** | the turn key; same `correlation_id` already used by `Message`, `ToolCall`, `TraceEvent` |
| `channel_id` | UUID FK `channels.id` ON DELETE CASCADE, indexed | denormalized for cheap per-channel queries / cascade delete; resolved at insert time from the turn's anchor message → session → channel |
| `session_id` | UUID FK `sessions.id` ON DELETE CASCADE | mirror of the resolved session |
| `user_id` | UUID FK `users.id` ON DELETE SET NULL, nullable | nullable for integration-anonymous votes (Slack user not yet linked); SET NULL preserves historical signal after user deletion |
| `source_integration` | Text not null | `web`, `slack`, … |
| `source_user_ref` | Text nullable | external id when `user_id` is null (e.g. Slack `Uxxx`) |
| `vote` | Text not null | check constraint: in `('up', 'down')` |
| `comment` | Text nullable | one-line, ≤500 chars; either direction |
| `created_at` / `updated_at` | TIMESTAMP(timezone=True), default `now()` |  |

Indexes:
- `ix_turn_feedback_correlation_id` on `correlation_id` (snapshot lookup)
- `ix_turn_feedback_channel_created` on `(channel_id, created_at)` (Daily Health window queries)

Unique constraints (two partial uniques, both required because Postgres
unique with NULL doesn't dedupe):
- `uq_turn_feedback_user` on `(correlation_id, user_id)` `WHERE user_id IS NOT NULL`
- `uq_turn_feedback_anon` on `(correlation_id, source_integration, source_user_ref)` `WHERE user_id IS NULL`

A "clear" is a row delete, not a `vote = null` row — keeps the
constraints trivial and the trace event unambiguous.

Multiple thumbs from the same user against different messages within
the same turn collapse to a single row (re-vote / flip). Slack-side
this means reacting to any message belonging to the turn updates the
same record.

**New column on `channels`** (in the same migration):
- `show_message_feedback: Boolean NOT NULL, server_default 'true'`.
  Matches the existing pattern (e.g. `passive_memory`,
  `context_compaction`, `workspace_rag`) — a plain typed column, not
  a JSON key. ORM model in `app/db/models.py` Channel definition
  (alongside the other booleans, around line 31–55).

**Alembic migration:** `migrations/versions/295_turn_feedback_and_channel_show_feedback.py`,
`revision = "295_turn_feedback"`, `down_revision = "294_session_exec_envs"`.

### Domain layer

New service `app/services/turn_feedback.py`. Pure service; no FastAPI
imports.

Public API:
```python
async def record_vote(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    user_id: uuid.UUID | None,
    source_integration: str,
    source_user_ref: str | None,
    vote: Literal["up", "down"],
    comment: str | None,
) -> TurnFeedback: ...

async def clear_vote(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    user_id: uuid.UUID | None,
    source_integration: str,
    source_user_ref: str | None,
) -> bool: ...

async def feedback_for_correlation_ids(
    db: AsyncSession,
    *,
    correlation_ids: Sequence[uuid.UUID],
    user_id: uuid.UUID | None,
) -> dict[uuid.UUID, FeedbackSummary]: ...
    # FeedbackSummary = {mine: "up"|"down"|None, totals: {up: int, down: int}}

async def resolve_correlation_for_message(
    db: AsyncSession, message_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID] | None: ...
    # returns (correlation_id, session_id, channel_id) or None
```

Behavior:
- `record_vote` resolves message → `(correlation_id, session_id,
  channel_id)`, then upserts. Validates the message has a
  `correlation_id` (turn-less messages aren't votable — see Edge cases).
- Comment is truncated to 500 chars and stripped; empty becomes NULL.
- Emits an `agent_quality_audit` `TraceEvent` per write/clear, mirroring
  the existing pattern at `app/services/agent_quality_audit.py:351`:

  ```python
  db.add(TraceEvent(
      correlation_id=correlation_id,
      session_id=session_id,
      bot_id=None,  # bot is derivable from session if needed by consumer
      client_id=None,
      event_type=AGENT_QUALITY_AUDIT_EVENT,  # "agent_quality_audit"
      event_name="user_explicit_feedback",
      count=1,
      data={
          "audit_version": AGENT_QUALITY_AUDIT_VERSION,
          "kind": "user_explicit_feedback",
          "vote": vote,                        # "up" | "down" | "cleared"
          "has_comment": bool(comment),
          "source_integration": source_integration,
          "anonymous": user_id is None,
      },
      created_at=datetime.now(timezone.utc),
  ))
  ```

  Comment text is **never** in the trace row — PII / private content
  stays in `turn_feedback`, surfaced only to the original voter and
  admins.

- All writes commit within the caller's session (synchronous), not via
  `async_session()` background task — the user expects the vote to
  land before the optimistic UI reconciles.

### API

**New router** `app/routers/api_v1_messages.py`, mounted at
`/api/v1/messages`. Routes:

- `POST /api/v1/messages/{message_id}/feedback`
  - Body: `FeedbackIn = {vote: "up" | "down", comment?: str}`
  - Auth: requires an authenticated `User` (not API key, not widget
    token). Use the existing `Depends(get_current_user)` /
    `Depends(require_user)` pattern (whichever is canonical in this
    repo — confirm by reading one existing user-only POST handler).
  - 200 on success returns `FeedbackOut = {vote, comment, updated_at}`.
  - 404 if message has no `correlation_id` (turn-less).

- `DELETE /api/v1/messages/{message_id}/feedback`
  - Same auth. 204 on success (idempotent — also 204 if no row existed).

- No public list-of-votes-per-turn endpoint in v1; admins read via
  trace tools (`audit_trace_quality`).

**Read-side surfaces** — feedback comes back attached to messages, not
through a separate endpoint. Modify two places:

1. `MessageOut` in `app/schemas/messages.py:67` — add optional
   `feedback: Optional[FeedbackBlock]` field (omit when null). Set
   only on the *anchor message* of the turn (see "Anchor message
   selection"). Populated by `from_orm` / `from_domain` only when the
   route handler explicitly hydrates it (default None) — keeps
   serialization cheap when not needed.

2. `app/routers/api_v1_sessions.py:2029` — the
   `GET /sessions/{id}/messages` handler currently builds
   `[MessageOut.from_orm(m) for m in rows]`. Wrap that in a
   batched feedback hydration:
   - Collect all `correlation_id`s of `assistant` rows.
   - One call to `feedback_for_correlation_ids(..., user_id=current_user.id)`.
   - Determine the anchor message per `correlation_id` (last
     user-visible assistant text — see selection rules below).
   - Attach the `FeedbackBlock` to that anchor row only.

3. `ChannelStateOut.active_turns` (`app/routers/api_v1_channels.py:1320`)
   carries in-flight assistant turns — these are **not** yet votable
   (see Edge cases) so we do **not** add feedback to `ActiveTurnOut`.
   The historical messages endpoint is the only feedback surface.

Read-side block shape:
```ts
type FeedbackBlock = {
  mine: "up" | "down" | null;
  totals: { up: number; down: number };
  comment_mine: string | null;  // user only sees their own comment
};
```

### Anchor message selection

Definition: the *anchor message* of a turn is the last user-visible
assistant text message in that `correlation_id`.

Selection rule (used by both the snapshot serializer and the UI):
```
WHERE role = 'assistant'
  AND correlation_id = :cid
  AND content IS NOT NULL
  AND tool_call_id IS NULL          -- not a tool-result row
  AND (tool_calls IS NULL            -- not a pure tool-dispatch row
       OR jsonb_array_length(tool_calls) = 0)
ORDER BY created_at DESC
LIMIT 1
```

Implement once in `app/services/turn_feedback.py` as
`anchor_message_id_for_correlation(db, correlation_id)`; the snapshot
serializer and the Slack reaction handler share it.

### Channel toggle

- New column `Channel.show_message_feedback` (added in the same
  migration, see Storage above), default `true`.
- Mirror the field through:
  - The Channel response schema (find it via the existing
    `passive_memory` field's serialization point).
  - The Channel update endpoint (PUT/PATCH on `/channels/{id}`),
    same place `passive_memory` etc. are accepted.
- Surfaced in the channel settings panel
  (`ui/app/(app)/channels/[channelId]/ChannelSettingsSections.tsx`)
  as a `SettingsControlRow` with the existing `Toggle` from
  `@/src/components/shared/FormControls`. Wording:
  "Show feedback votes on assistant replies".
- The web UI gates affordance rendering on this flag. The API still
  accepts votes regardless — the toggle is a UI hint, not a server
  policy. Slack reactions are not blocked either (Slack's UI can't
  hide reactions per app); when the flag is off the bot suppresses
  its own ack reaction back.

Per-bot or per-user defaults are out of scope for v1 — channel is
the right granularity (matches `terminal_mode`, `layout_mode`, etc.).

### Web UI

Per `docs/guides/ui-design.md` (low chrome, low radius, no decorative
flourish) and `docs/guides/ui-components.md` (shared dropdowns,
settings rows):

- **Anchor:** the affordance lives only on the assistant *anchor
  message* of the turn (see selection rules), in
  `ui/src/components/chat/MessageBubble.tsx`. The bubble already
  receives `MessageOut`; render the affordance when
  `message.feedback !== undefined`.
- **Layout:** right-aligned in the existing meta strip (next to
  timestamp / token count). Hidden until hover or focus; revealed via
  opacity transition, no layout shift.
- **Visual:** two icon buttons (`thumbs-up`, `thumbs-down`) using
  `lucide-react` icons (already imported elsewhere in chat
  components), color tokens only — **no inline hex** per UI guide.
  Active state uses the canonical filled-icon / pill pattern from
  design tokens.
- **Click semantics:** click → optimistic update + POST. Re-click same
  vote = clear (DELETE). Click opposite vote flips (single POST).
- **Comment:** either vote opens a tiny inline one-line comment field —
  placeholder "what made this good?" / "what went wrong?" by direction.
  Submitting blank just records the vote. Esc cancels comment but
  keeps vote. Editing later is a follow-up POST against the same
  message_id (server upserts on `(correlation_id, user_id)`).
- **Gate:** when `channel.show_message_feedback === false`, render
  the bubble without the affordance (and skip hydrating the field
  client-side; keep `feedback` in the API response either way to
  avoid a second roundtrip if the user toggles it back on).
- **Accessibility:** keyboard reachable; `aria-pressed` reflects
  current state; `aria-label` includes vote direction and current
  state.
- **State management:** new file `ui/src/api/hooks/useTurnFeedback.ts`
  using `@tanstack/react-query` `useMutation`. Pattern: copy
  `ui/src/api/hooks/useModels.ts` (uses both `useQuery` and
  `useMutation` with `useQueryClient` invalidation). On success,
  invalidate the messages list query for the session so cached pages
  pick up the new totals.

### Slack

Extend `integrations/slack/reaction_handlers.py`:

- Map: `+1`/`thumbsup` → `up`; `-1`/`thumbsdown` → `down`.
- New `_handle_feedback_reaction(client, channel, ts, user_id, vote)`
  mirroring the existing `_handle_approve_reaction` shape.
- **Disambiguation from approval path:** before treating a `:+1:`/
  `:thumbsup:` as a vote, call the existing `_extract_approval_id`. If
  it returns an `approval_id` for a still-pending approval, keep the
  current approval semantics (no change). Otherwise, fall through to
  feedback.
- **Slack message → Spindrel turn lookup** (new helper, this does not
  exist yet — confirmed via grep):
  ```python
  # SELECT id, correlation_id FROM messages
  # WHERE metadata->>'slack_ts' = :ts
  #   AND metadata->>'slack_channel' = :channel
  # LIMIT 1
  ```
  `slack_ts` is stamped onto Message metadata at delivery time —
  see `integrations/slack/hooks.py:388`. Reacting to *any* message of
  a turn votes the turn (the resolved correlation_id is what gets
  upserted, not the per-message id).
- **Identity:** Slack `user_id` is a raw `Uxxx` string. There is no
  Slack→Spindrel `User` mapping in the codebase today (confirmed via
  grep). Persist with `source_integration='slack'`,
  `source_user_ref=Uxxx`, `user_id=null`. A future identity layer can
  backfill via a one-shot UPDATE.
- `reaction_removed` clears the vote (idempotent — call `clear_vote`).
- Slack honors the channel toggle as a read-side hint only: the bot
  keeps accepting reaction votes either way, but suppresses its own
  ack reaction (e.g. an ephemeral confirmation message) when the
  flag is off.
- `:speech_balloon:` or thread reply for an optional comment is **out
  of scope for v1** — reactions only. Future work could parse a
  threaded reply as a comment if it directly follows the reaction.

### Integration SDK

- Add a portable capability flag `message_feedback` on
  `integrations/sdk.py` (alongside the existing `rich_tool_results`
  pattern). Slack declares it; nothing else does in v1.
- The mapping itself stays in each integration; SDK only carries the
  capability advertisement and the canonical vote enum (`"up"` /
  `"down"`) so future integrations follow the same shape.
- Document the contract in `docs/guides/integrations.md` alongside
  the other capabilities.

### Quality consumers (mostly free)

- `app/services/agent_quality_audit.py`: add `user_explicit_feedback`
  to its known event-kind index so the deterministic re-audit job
  can count and report it without re-deriving votes. Findings already
  group by `correlation_id`, so turn-keyed feedback co-locates
  naturally.
- `SystemHealthSummary.source_counts`: add `user_feedback_down_24h`
  (mirrors the existing `agent_quality` count style — find the
  emission site by following the `agent_quality` count's references).
- `.agents/skills/spindrel-conversation-quality-audit/SKILL.md`:
  short doc-only update — note that user-explicit votes exist as
  `event_type='agent_quality_audit'`, `event_name='user_explicit_feedback'`
  trace events and are higher-priority signal than the deterministic
  detectors when both fire on the same turn.

## Edge Cases

| Case | Behavior |
|---|---|
| **In-flight turn** (assistant text is still streaming, or `ChannelStateOut.active_turns` still includes this `correlation_id`) | Not votable. Anchor message lookup may return a partial row; UI gate: don't render the affordance until the turn has left `active_turns`. Server-side: POST is allowed but discouraged — the client just won't surface it. No special server rejection. |
| **Errored turn** (turn ended before any user-visible assistant text) | No anchor message → no affordance → vote not possible. Server returns 404 from POST handler when `anchor_message_id_for_correlation` is None. |
| **Tool-only turn** (assistant emitted only tool calls / results, no text) | Same as errored: no anchor → not votable. |
| **Regenerated turn** | Depends on whether regeneration reuses the original `correlation_id` (existing vote persists) or mints a new one (fresh vote target). Both behaviors are correct under the unique constraint; document the choice in the regenerate code path's docstring. *Open question — see below.* |
| **Anchor message deleted but turn evidence remains** | Vote stays valid (it's keyed on `correlation_id`, not message_id). Re-vote requires a new anchor — if none exists, future POSTs return 404 but the existing row remains queryable by trace tools. |
| **Message deleted via `messages` cascade** | No effect on `turn_feedback`. The vote is correlation-keyed and outlives individual rows. |
| **Channel deleted** | `turn_feedback` rows cascade-delete via `channel_id` FK. |
| **User deleted** | `turn_feedback.user_id` SET NULL; vote becomes anonymous-historical. Comment text remains (it was the user's contribution; not auto-purged in v1). |
| **Slack reaction on bot's *own* message that isn't a turn anchor** (e.g., scheduled widget post) | Lookup returns no matching `Message` row → silently dropped at debug log level (matches existing `reaction_added unmapped` behavior). |
| **Vote arrives from web while Slack vote already exists for the same correlation_id by the same user** | The web vote has a real `user_id`; the Slack vote has `user_id=null` and a `source_user_ref`. They are different rows under the partial uniques and both persist. Aggregator counts both. *(Acceptable in v1 — fixable later when identity mapping lands.)* |

## Phasing

| Phase | Scope | Stop condition |
|---|---|---|
| 1. Schema + service | Migration `295_turn_feedback_and_channel_show_feedback.py` (new table + Channel column), `app/services/turn_feedback.py` with `record_vote` / `clear_vote` / `feedback_for_correlation_ids` / `resolve_correlation_for_message` / `anchor_message_id_for_correlation`, trace emission, unit tests | Service can record / clear / list keyed on `correlation_id`; voting on different messages of one turn collapses to one row; trace event appears with matching `correlation_id` and `event_name='user_explicit_feedback'`; integration test against real DB |
| 2. API + web UI | New `app/routers/api_v1_messages.py` with POST/DELETE; `MessageOut` extended with `feedback` block; `GET /sessions/{id}/messages` hydration; `ui/src/api/hooks/useTurnFeedback.ts`; affordance in `MessageBubble.tsx`; channel toggle in `ChannelSettingsSections.tsx` | Vote round-trips in browser, persists across reload, design-token-only, toggle hides affordance, optimistic update + invalidation works, `cd ui && npx tsc --noEmit` clean, `bash scripts/generate-api-types.sh` regenerated types |
| 3. Slack reactions | Extend `integrations/slack/reaction_handlers.py` with feedback path; new `slack_ts → message_id` lookup helper; conflict-free with approval blocks; `reaction_removed` clears | Reacting `:+1:`/`:-1:` on a non-approval bot message produces a vote row + trace event; reacting on a pending approval still approves; reacting `+1` then removing clears |
| 4. Daily Health + audit consumers | Surface `user_feedback_down_24h` count in `SystemHealthSummary.source_counts`; quality-audit skill doc updated | Health panel shows count; skill doc references new event kind |
| 5. SDK capability | `message_feedback` capability on SDK, declared by Slack only | Capability lint/test passes; doc note in `docs/guides/integrations.md` |

Each phase is independently shippable. Phases 1–3 are the user-visible
MVP; 4–5 are the quality / integration-portability tail.

## Test Plan

- `tests/unit/test_turn_feedback_service.py`: record / clear / re-vote
  collapse / partial unique behavior / trace emission shape /
  anchor selection rules / message → correlation resolution.
- `tests/integration/test_api_messages_feedback.py`: POST/DELETE auth
  contract; 404 on turn-less message; round-trip with hydrated
  `MessageOut.feedback` from `GET /sessions/{id}/messages`.
- `tests/integration/test_channel_show_message_feedback.py`: column
  default true; toggle through PATCH; visible in channel response.
- `tests/unit/test_slack_reaction_feedback.py`: feedback path vs
  approval path disambiguation; `slack_ts` lookup; anonymous
  persistence; `reaction_removed` clear; ack-reaction suppression
  when channel toggle off.
- `tests/unit/test_anchor_message_selection.py`: tool-call-only
  turns excluded; tool-result rows excluded; final text wins among
  multiple assistant text rows.
- UI: add `MessageBubble` test for affordance render gating
  (`feedback === undefined` vs present, channel toggle off, in-flight
  state from active_turns).

CLAUDE.md test discipline applies: write the failing test first, never
leave tests failing, no Docker for unit tests
(`PYTHONPATH=. .venv/bin/python -m pytest tests/unit/... -q`).

## Open Questions

- **Regenerated turn semantics.** Does the regen code path mint a new
  `correlation_id` or reuse the original? Audit before phase 1; if
  unclear, default to "new correlation_id" so regenerated turns get
  fresh feedback targets.
- **Aggregate totals visibility.** Should the web UI show totals
  (e.g., "2 down-votes") or only the current user's vote? Default in
  v1: only own vote, to avoid implicit cross-user pressure. Admins
  read totals via trace tools.
- **Comment retention.** Persist forever or auto-expire? Default:
  persist; comments are explicitly invited and may become training
  input.
- **Slack thread-reply free-text capture.** Defer; reactions alone are
  useful and cheap.
- **Track ownership.** Best fit is Phase 9 of
  `agent-quality-observability` (see status table in that track).
  Confirm with the track owner before promoting and updating the
  track's status table.

## References

- `docs/tracks/agent-quality-observability.md`
- `app/services/agent_quality_audit.py` (TraceEvent emission pattern at line 351; `AGENT_QUALITY_AUDIT_EVENT` / `AGENT_QUALITY_AUDIT_VERSION` constants)
- `app/db/models.py` — `Message` (line 506), `TraceEvent` (line 734), `Channel` (line 17, see `passive_memory` etc. for the toggle pattern)
- `app/schemas/messages.py:67` — `MessageOut` (extend with `feedback`)
- `app/routers/api_v1_sessions.py:2029` — `GET /sessions/{id}/messages` (hydration site)
- `app/routers/api_v1_channels.py:1324` — `ChannelStateOut` (do **not** modify; active turns aren't votable)
- `integrations/slack/reaction_handlers.py` — extension point
- `integrations/slack/hooks.py:388` — `slack_ts` stamping on Message metadata
- `migrations/versions/294_session_execution_environments.py` — `down_revision` anchor (revision id `294_session_exec_envs`)
- `ui/src/components/chat/MessageBubble.tsx` — affordance render site
- `ui/app/(app)/channels/[channelId]/ChannelSettingsSections.tsx` — channel toggle row
- `ui/src/api/hooks/useModels.ts` — useMutation + useQueryClient pattern to mirror
- `docs/guides/ui-design.md`, `docs/guides/ui-components.md`, `docs/guides/integrations.md`
- `.agents/skills/spindrel-conversation-quality-audit/SKILL.md`
