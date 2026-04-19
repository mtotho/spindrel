---
tags: [agent-server, track, integrations, slack]
status: complete
created: 2026-04-17
updated: 2026-04-17
---
# Track — Slack Depth Pass

Pilot integration for the [[Integration Depth Playbook]]. Five phases, all shipped 2026-04-17. The two core capabilities introduced here (`EPHEMERAL`, `MODALS`) are now the template for Discord/Web/etc.

> **Phase 3/4 redo (2026-04-17, session 11).** The first pass of Phase 3 and Phase 4 was built on the wrong mental model — both derived a single integration from `Channel.client_id.split(":",1)[0]` and decided capability from one renderer. On a multi-bound channel (web + slack, the default) that either fanned private text out to every binding (ephemeral broadcast fallback) or posted modal buttons on bindings that couldn't action them. Redone in the same day: ephemeral is strict-deliver with per-binding scoped publish, modals target the triggering user's origin binding via an outbox row scoped to one integration, and tool exposure is declaratively capability/integration-gated so the agent cannot even see unsupported tools. See [[Architecture Decisions#Channel Binding Model — Capabilities Live on the Binding, Not the Channel]] for the invariants that prevent this regression from recurring.

## North Star

Slack should use every affordance the Slack platform offers — not just send messages. The payoff: bots that feel like first-class Slack apps (App Home, shortcuts, modals, ephemeral replies, reactions as intents) rather than chat-only integrations.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | @-mentions + thread read-up + reactions as intents | ✅ |
| 2 | Scheduled msgs + pin/bookmark tools + App Home + shortcuts | ✅ |
| 3 | `Capability.EPHEMERAL` + `EPHEMERAL_MESSAGE` + Slack `chat.postEphemeral` | ✅ |
| 4 | `Capability.MODALS` + `OpenModal` + `MODAL_SUBMITTED` + Slack `views.open` | ✅ |
| 5 | Integration Depth Playbook + vault track updates | ✅ |

## Phase 1 — @-mentions, thread read-up, reactions

**@-mentions**: `integrations/slack/message_handlers.py` now includes the Slack user id in the agent's message prefix: `[Slack channel:C01 user:alice (<@U01ALICE>)] ...`. The agent can reproduce `<@U01ALICE>` verbatim to tag the user back — Slack renders it natively. `Capability.MENTIONS` is now honest (it was declared but unimplemented before).

**Thread read-up**: When a user replies in an existing thread (`thread_ts != message_ts`), the subprocess calls `conversations.replies` and prepends a summary block (sender + text, truncated) to the agent's turn. Up to 15 parent messages. No cache — paid per turn; acceptable because threaded replies are rare.

**Reactions as intents**: New `integrations/slack/reaction_handlers.py`. `reaction_added` was declared in YAML but had no handler. Today: `:+1:` / `:thumbsup:` on an approval message approves it (extracts `approval_id` from the message's block buttons via `conversations.history`). Other reactions are logged only; follow-up pass can add 🗑️/🔁/📌 once the server has retry/delete endpoints.

Tests: `integrations/slack/tests/test_message_handlers.py`, `integrations/slack/tests/test_reaction_handlers.py`.

## Phase 2 — Scheduled messages, pins, bookmarks, App Home, shortcuts

**Three new agent tools** under `integrations/slack/tools/`:

- `slack_schedule_message(text, post_at, thread_ts?)` — wraps `chat.scheduleMessage`. Accepts ISO 8601 or epoch.
- `slack_pin_message(message_ts)` — wraps `pins.add`.
- `slack_add_bookmark(title, link, emoji?)` — wraps `bookmarks.add`.

All three share `integrations/slack/web_api.py` — a rate-limited Slack web-API helper that reuses the renderer's `slack_rate_limiter`. Non-Slack channels error cleanly via `resolve_slack_channel_id` which inspects `Channel.client_id`.

**App Home tab** (`integrations/slack/app_home.py`): `app_home_opened` event handler renders a per-user Block Kit view listing bound channels (mrkdwn `<#CID>` references) plus a "Quick Ask" button. Empty-state message when no channels are bound.

**Shortcuts** (`integrations/slack/shortcuts.py`): global shortcut `ask_bot_quick` (opens a DM and greets), message action `ask_bot_about_message` (runs the bot against the selected message in-thread), Home-tab `home_quick_ask` button (opens DM). Requires the Slack app manifest to declare the callback_ids.

**Deferred**: custom link unfurls for internal URLs. Needs URL-scheme design + server summary endpoint. Logged in [[Loose Ends]] for a future pass.

Tests: `integrations/slack/tests/test_app_home.py`, `tests/unit/test_slack_tools.py`.

## Phase 3 — Capability.EPHEMERAL (core change — redone session 11)

**Added to `app/domain/`**:

- `Capability.EPHEMERAL` — declares "renderer can deliver private-to-one-user messages."
- `ChannelEventKind.EPHEMERAL_MESSAGE` — transient bus kind, not outbox-durable.
- `EphemeralMessagePayload(message, recipient_user_id, target_integration_id)` — carries the integration-native user id plus the scoped target binding.
- `_REQUIRED_CAPS[EPHEMERAL_MESSAGE] = frozenset({EPHEMERAL})` — dispatcher silently skips renderers that lack the capability.

**Publisher-side strict-deliver** (`app/services/ephemeral_dispatch.py`): `deliver_ephemeral` calls `resolve_targets(channel)` to list every integration bound to the channel, then picks the one binding whose renderer has `EPHEMERAL` and whose integration-native user-id format matches `recipient_user_id` (Slack `U`/`W` → slack; Discord numeric snowflake → discord; etc.). Publishes `EPHEMERAL_MESSAGE` with `target_integration_id` set to that binding. The dispatcher at `app/services/channel_renderers.py:IntegrationDispatcherTask._dispatch` filters the event on every other renderer — so a web+slack channel routes nothing private to web. **No broadcast fallback.** If no bound integration can honor the request, the tool returns `{mode: "unsupported"}` and the agent falls back to asking conversationally.

**Slack renderer** (`integrations/slack/renderer.py`): `_handle_ephemeral_message` branch calls `chat.postEphemeral` with `channel` + `user` + `text`. Uses existing bot-attribution path.

**Agent tool**: `respond_privately(to_user, text)` at `app/tools/local/responses.py` — declares `required_capabilities={Capability.EPHEMERAL}` so the tool is filtered out of the LLM's per-turn tool list on channels whose bindings can't honor it.

Tests: `tests/unit/test_ephemeral_message_kind.py`, `tests/unit/test_slack_ephemeral.py`, `tests/unit/test_ephemeral_dispatch.py`, `tests/unit/test_channel_renderers.py::TestPerBindingTargetFilter`.

## Phase 4 — Capability.MODALS (core change)

**Added to `app/domain/`**:

- `Capability.MODALS`.
- `OpenModal(callback_id, title, schema, submit_label, metadata)` as a new `OutboundAction` variant.
- `ChannelEventKind.MODAL_SUBMITTED` + `ModalSubmittedPayload(callback_id, submitted_by, values, metadata)` — the way values get back to the agent.

**Modal waiter** (`app/services/modal_waiter.py`): in-memory slot registry. `register(callback_id)` opens a slot; `wait(callback_id, timeout)` blocks on an `asyncio.Event`; `submit(...)` / `cancel(...)` resolve it. Slots are process-local and non-durable — a restart mid-modal cleanly times out the agent tool. Covered by `tests/unit/test_modal_waiter.py`.

**HTTP endpoint** (`app/routers/api_v1_modals.py`): `POST /api/v1/modals/{callback_id}/submit` (values, submitted_by, metadata, optional channel_id → also publishes `MODAL_SUBMITTED` on the bus) + `POST /api/v1/modals/{callback_id}/cancel`. Tested in `tests/unit/test_modal_submit_endpoint.py`.

**Slack plumbing**:

- `integrations/slack/modal_views.py` — `schema_to_view` + `values_from_view`. Supports `text`, `textarea`, `select`, `url`, `number`, `date`. Preserves optional/required and placeholders.
- `integrations/slack/modal_action_handler.py` — handles `open_modal:<callback_id>` button clicks. Decodes the schema from the button `value` (≤ 1900 bytes — see tool docstring) and calls `views.open` with the fresh `trigger_id`. View callback_ids carry a `spindrel_modal:` prefix.
- `integrations/slack/view_handlers.py` — `view_submission` → `POST /api/v1/modals/{cb}/submit`. `view_closed` → `.../cancel`.

**Agent tool — binding-aware** (`app/tools/local/forms.py`): `open_modal(title, schema, submit_label?, prompt?)`.

1. Calls `resolve_targets(channel)` and picks a MODALS-capable binding — preferring the origin binding (the integration whose `metadata["source"]` matched the triggering user's last message). Falls back to any MODALS-capable binding.
2. If no binding has MODALS → `{ok: false, unsupported: true}` (and the tool isn't even in the LLM's tool list if the capability gate is active — it declares `required_capabilities={Capability.MODALS}`).
3. Enqueues the "Open form" button as a NEW_MESSAGE scoped to the target binding **only** via `app/services/outbox_publish.py:enqueue_new_message_for_target`. Other bindings on the channel don't see a button they can't action.

**NEW_MESSAGE pass-through for pre-built blocks**: `integrations/slack/renderer.py:_handle_new_message` respects `msg.metadata["slack_blocks"]` — the modal tool uses this to ship the button alongside the prompt without introducing a new event kind.

Tests: `tests/unit/test_modal_views.py`, `tests/unit/test_open_modal.py`, plus the modal waiter + endpoint tests above.

### Phase C — Capability-gated tool exposure (redo session 11)

Declarative fix that keeps the whole class of bug out of reach: `@register` in `app/tools/registry.py` now accepts `required_capabilities: frozenset[Capability] | None` and `required_integrations: frozenset[str] | None`. Annotated:

| Tool | Gate |
|---|---|
| `respond_privately` | `required_capabilities={EPHEMERAL}` |
| `open_modal` | `required_capabilities={MODALS}` |
| `slack_pin_message`, `slack_add_bookmark`, `slack_schedule_message` | `required_integrations={"slack"}` |

`app/agent/capability_gate.py:build_view` unions renderer capabilities across `resolve_targets(channel)`; `app/agent/context_assembly.py` drops any tool whose requirements aren't satisfied before the per-turn tool list is handed to the LLM. The agent literally cannot call a tool whose capability isn't on the channel.

Tests: `tests/unit/test_capability_gate.py`, `tests/unit/test_registry.py::TestRegister::test_required_capabilities_stored`.

## Phase 5 — Playbook + vault

- [[Integration Depth Playbook]] — the reusable loop.
- This track (set to `status: complete`).
- [[Track - Integration DX]] Phase 7 items (shared webhook validation, testing harness) are covered by the playbook's "ship SDK-only wins" recipe + the rate limiter in `integrations/slack/web_api.py`. Closing that phase separately.

## Manifest changes required before production use

The Slack app manifest at api.slack.com/apps needs the following additions before the Phase 2 shortcuts and Phase 4 modals work end-to-end:

```yaml
shortcuts:
  - name: "Quick ask"
    type: global
    callback_id: ask_bot_quick
    description: "Ask the bot anything"
  - name: "Ask bot about this"
    type: message
    callback_id: ask_bot_about_message
    description: "Run the bot against the selected message"

# Required OAuth scopes for new affordances:
#   chat:write.scheduled (schedule_message)
#   pins:write (slack_pin_message)
#   bookmarks:write (slack_add_bookmark)
#   conversations:history (reactions→approval mapping)
#   channels:read / groups:read (thread read-up already uses this)

# App Home tab:
#   features.app_home.home_tab_enabled: true
```

## Cross-references

- [[Integration Depth Playbook]] — the reusable recipe this track piloted
- [[Track - Integration DX]] — prior declarative-integrations work this builds on
- [[Track - Integration Delivery]] — bus + outbox + renderer layer enabling all of this
- [[Architecture Decisions#Integration Delivery: Bus + Outbox + Renderer Abstraction]] — design invariants
- [[Roadmap]] Integration Depth entry

## Follow-ups (not blocking track close)

- Custom link unfurls for internal URLs (`link_shared` handler + summary endpoint)
- Reaction mappings for delete / retry / pin once the server exposes those endpoints for chat messages
- Discord depth audit (next pilot per the playbook)
