# Slack Integration

The Slack integration runs as a separate process alongside the agent-server. It listens for events via Slack's Socket Mode (no inbound ports) and routes them to the agent-server's `/chat` endpoint.

## Setup

Add to `.env`:

```
SLACK_BOT_TOKEN=xoxb-...          # Bot token (from OAuth)
SLACK_APP_TOKEN=xapp-...          # App-level token (for Socket Mode)
AGENT_API_KEY=same-as-API_KEY     # Auth key for the agent-server
AGENT_BASE_URL=http://localhost:8000  # Agent-server URL
SLACK_DEFAULT_BOT=default         # Fallback bot when no channel mapping exists
```

When both Slack tokens are set, `dev-server.sh` starts the bot automatically. To run standalone:

```bash
cd integrations/slack && python slack_bot.py
```

## Slack App Configuration

Required **Bot token scopes**: `app_mentions:read`, `chat:write`, `channels:history`, `channels:read`, `commands`, `files:read`, `files:write`, `reactions:read`

Optional scopes (each unlocks a specific affordance — see corresponding sections below):

| Scope | Unlocks |
|---|---|
| `chat:write.customize` | Custom display names + icons per bot |
| `groups:read` | Private channels in the binding dropdown |
| `chat:write.scheduled` | `slack_schedule_message` tool |
| `pins:write` | `slack_pin_message` tool |
| `bookmarks:write` | `slack_add_bookmark` tool |
| `reactions:write` | Bot can post reactions back (e.g. ⏳ on receipt) |

**Event subscriptions**: `message.channels`, `app_mention`, `reaction_added`, `app_home_opened`

**App Home tab** — at api.slack.com/apps → App Home → enable the **Home tab**. The dashboard listing bound channels appears the first time a user clicks the bot in their sidebar.

**Shortcuts** — at api.slack.com/apps → Interactivity & Shortcuts → Shortcuts:

| Type | Callback ID | Description |
|---|---|---|
| Global | `ask_bot_quick` | Ask the bot anything (opens a DM) |
| Message | `ask_bot_about_message` | Run the bot against the selected message in-thread |

**Slash commands** — register each at api.slack.com/apps → Slash Commands (Socket Mode; Request URL is ignored):

| Command | Description |
|---|---|
| `/ask <bot-id> <message>` | Route a message to a specific bot. Bot replies in the channel with its display name. `/ask` alone lists available bots. |
| `/bot [id]` | Show or switch the default bot for this channel. Session is unchanged. |
| `/bots` | List all available bots and their IDs. |
| `/context` | Show the current context window breakdown (chars per role). |
| `/compact` | Force session compaction (summarize + memory write) now. |

The session-local web chat plan mode described in [Plan Mode](./plan-mode.md) does not currently have a Slack slash-command equivalent.

## Binding Suggestions

When creating a Slack binding in the admin UI, a channel picker dropdown shows all channels the bot can see. This uses the `conversations.list` API (requires `channels:read`, already a required scope).

To also show private channels, add the `groups:read` scope to your Slack app.

| Setting | Default | Description |
|---|---|---|
| `SLACK_SUGGEST_CHANNELS` | `true` | Set to `false` to disable the channel picker |
| `SLACK_SUGGEST_COUNT` | `20` | Number of channels to show (max 100) |

Results are cached server-side for 5 minutes.

## Session Model

Each Slack channel has **one shared session** derived deterministically from the channel ID:

```
session_id = uuid5(NAMESPACE_DNS, "slack:{channel_id}")
```

This session is shared across all bots operating in that channel. Switching the default bot with `/bot` keeps the same session and preserves full conversation history.

Child sessions (created via `delegate_to_agent`) maintain a parent/root link back to the channel session.

## Message Routing

Each message in a channel is classified as either **active** or **passive**:

### Active messages — agent runs and replies

A message is active when:
- The user **@mentions the Slack app** (`app_mention` event), OR
- The channel has `require_mention = false` (agent responds to all messages)

An `app_mention` with no text after the mention still runs the agent (so you can ping after passive-only channel activity).

Active messages go through the full agent pipeline: RAG retrieval, tool calls, LLM response. The response is posted to the channel attributed to the responding bot.

### Passive messages — stored silently, no reply

A message is passive when it arrives without @mentioning the app and `require_mention = true` (the default). Passive messages are:

1. **Stored in the channel session** as user-role messages with `metadata.passive = true`
2. **Not sent to the agent** — no LLM call, no response
3. **Injected as context** on the next active turn, as a system block: `[Channel context — ambient messages not directed at the bot]`
4. **Included in compaction** (if `passive_memory = true`) — when compaction runs, passive messages are visible in the transcript with a `[passive]` prefix, so the bot can extract relevant facts into `MEMORY.md` during the memory flush phase

This lets the bot stay aware of conversations happening around it without interrupting them.

In multi-bot channels, passive storage is channel-level, not limited to the bot
that actively replied. Member bots can still absorb passive channel context
through memory compaction or dreaming/learning when passive memory and their
learning settings allow it.

## Channel Configuration

Configure per-channel behavior in **Admin > Channels** (select a channel, then the **Integrations** tab). Each channel can have:

| Setting | Default | Description |
|---|---|---|
| **Default Bot** | `SLACK_DEFAULT_BOT` | The bot that responds to @mentions in this channel. Other bots can be addressed with `/ask <bot-id>`. |
| **Require @mention** | `true` | When checked, only @mentions trigger the agent. All other messages are stored passively as channel context. When unchecked, the bot replies to every message. |
| **Passive memory** | `true` | When compaction runs, passive channel messages are included in the transcript so channel participants can extract channel activity into memory. |

The derived session ID for each channel is shown in the channel list (first 8 chars of the UUID).

Config is served at `GET /integrations/slack/config` (requires `X-API-Key` header) and cached for 60 seconds by the Slack integration process.

## Multi-Bot Channels

A channel has one **default bot** (used for @mentions), but multiple bots can operate in the same channel:

Default/member routing controls who actively answers. It does not isolate member
bots from passive channel context; passive memory and learning settings decide
whether they later learn from overheard messages.

**Using `/ask`:**

```
/ask calculator-bot what is the square root of 144?
```

Routes a message to `calculator-bot` directly. The bot replies in the channel with its configured display name and icon. The channel's shared session ensures it has full context of prior conversations. `/ask` with no arguments lists available bots.

**Using delegation:** The default bot can delegate to other bots internally via `delegate_to_agent`. The delegated bot's response is posted to the channel attributed to its display name.

**Important:** In Slack, only one @mentionable user exists per app installation. To have multiple independently @mentionable bots, each needs its own Slack app installation.

## Bot Display Names

When the Slack app has the `chat:write.customize` scope, each bot can post with a distinct username and icon:

```
# In admin → Bots → [bot] → Slack Display
slack_display_name: "Calculator"
slack_icon_emoji: ":abacus:"
```

These appear as custom usernames on messages posted by that bot, making it visually clear which bot is responding. This is a display-only override — it does not create a separate Slack user.

## File Attachments

The bot downloads files shared in Slack automatically:

- **Text files** (plain text, markdown, CSV, JSON, Python, YAML): content is appended to the message
- **Images**: sent as vision attachments to the LLM

Requires the `files:read` scope. The `files:write` scope is needed for the `generate_image` tool to post generated images back to the channel.

## Threads

When a user replies inside an existing Slack thread (i.e. the message has a `thread_ts` distinct from its own `ts`), the bot fetches up to 15 prior messages in that thread via `conversations.replies` and prepends them as a `[Thread context — prior messages in this thread, newest last]` block to the user's turn. Each line is `sender_name (<@U…>): truncated text` (text capped at 400 chars per message).

Why: a Slack thread is its own conversation context; the bot needs to know what was already said before forming a reply that fits the thread's flow. Without read-up the bot would respond to a reply as if it were the start of the conversation.

Cost — paid per turn (no cache). Acceptable because threaded replies are far rarer than top-level posts. If thread cost becomes a concern, the limit lives at `_THREAD_PARENT_LIMIT` in `integrations/slack/message_handlers.py`.

When the bot replies, it **mirrors the thread**: if the user's message had a `thread_ts`, the bot's reply is posted with `reply_in_thread=true` so it lands inside the same thread rather than the channel root.

## Reactions as Intents

Slack reactions on bot messages are first-class intents — the bot's own messages already carry structured Block Kit context (approval buttons, capability cards), so we infer intent by parsing those blocks rather than maintaining a side-channel reaction map.

Current mapping:

| Reaction | Effect | Conditions |
|---|---|---|
| `:+1:` / `:thumbsup:` | Approves a pending tool/capability approval | Reaction is on a bot-posted approval message |

Mechanism: when `reaction_added` fires, the handler ignores reactions the bot itself posted (resolved via `auth.test`), then for an approve reaction it calls `conversations.history` to fetch the target message, scans its `actions` blocks for an `approval_id` (either bare-UUID button values or JSON blobs), and posts the approval via `POST /api/v1/approvals/{id}/decide` with `decided_by="slack:U…"`.

Other reactions log at `debug` and are ignored. Future passes will add 🗑️ (delete), 🔁 (retry), 📌 (pin) once the server exposes the corresponding endpoints for chat messages.

## Ephemeral Replies

An **ephemeral message** is a message visible only to one specific user — it appears in their channel view with a *"Only visible to you"* tag, no one else sees it, and it doesn't persist in Slack's channel history. Use it when the reply is personal: credentials, long debug output, an answer to a question only one person asked.

The agent calls the **`respond_privately`** tool:

```
respond_privately(to_user="U01ABC", text="Your reset link is …")
```

`to_user` is the integration-native user id — for Slack, the `U…` token from the user's `(<@U01ABC>)` attribution that the agent sees in every message.

How it flows end-to-end:

1. The tool calls `app/services/ephemeral_dispatch.py:deliver_ephemeral`.
2. That function calls `resolve_targets(channel)` to list every integration bound to the channel, then picks the single binding whose renderer has the `EPHEMERAL` capability AND whose integration-native user-id format matches `to_user`. (Slack `U…` → Slack binding; Discord numeric snowflake → Discord; etc.)
3. It publishes an `EPHEMERAL_MESSAGE` typed event with `target_integration_id` set to that binding. `IntegrationDispatcherTask._dispatch` filters the event on every renderer except the target — so a multi-bound channel fan-outs nothing private to the wrong surface.
4. The Slack renderer consumes the event and calls `chat.postEphemeral(channel, user, text)`. Slack enforces the visibility.

**Contract: strict-deliver, no broadcast fallback.** If no bound integration can deliver privately to that recipient, `respond_privately` returns `{ok: false, mode: "unsupported"}` and the agent falls back to asking the user conversationally. Earlier the code would re-publish the "private" text as a regular `NEW_MESSAGE` with a leading `🔒` marker — that leaked the content to every participant on every binding. It is gone.

**Tool exposure is capability-gated.** On a channel with no EPHEMERAL-capable binding, `respond_privately` is not even in the LLM's tool list for the turn (`app/agent/capability_gate.py` filters tools by their `required_capabilities`). The unsupported branch above is a last-line defense, not the common case.

## Modals (Forms)

A **modal** is a Slack pop-up form — the agent describes the form in a platform-agnostic schema, and the user fills it out in a native Block Kit dialog. Use it when collecting structured input that's awkward conversationally (filing a bug, configuring a multi-field resource, choosing from a long select list).

The agent calls the **`open_modal`** tool:

```
open_modal(
  title="Report a bug",
  schema={
    "summary":  {"type": "text",     "label": "One-line summary", "required": True},
    "details":  {"type": "textarea", "label": "What happened?",   "required": True},
    "severity": {"type": "select",   "label": "Severity",
                 "choices": [{"label": "Low", "value": "low"}, {"label": "High", "value": "high"}]},
    "url":      {"type": "url",      "label": "Related link"},
    "when":     {"type": "date",     "label": "When noticed"},
  },
  submit_label="File bug",
  prompt="Tell me about the bug:",
)
```

Supported field types: `text`, `textarea`, `select`, `url`, `number`, `date`. Each field carries `label`, `required` (default false), `placeholder`, and (for `select`) `choices`.

How it flows end-to-end:

1. The tool calls `resolve_targets(channel)` and picks a MODALS-capable binding. **Preference: the origin binding** — the integration whose `metadata["source"]` matched the last inbound user message (that's the surface the user is actually on). Fallback: any other MODALS-capable binding. If none are MODALS-capable, return `{ok: false, unsupported: true}`.
2. The tool generates a UUID `callback_id` and registers an in-memory waiter (`app/services/modal_waiter.py`).
3. The tool posts a NEW_MESSAGE containing an "Open form" Block Kit button, **scoped to the target binding only** via `outbox_publish.enqueue_new_message_for_target`. Other bindings on the channel (web, etc.) do not receive the button — they would render a dead-end since the action handler is Slack-native. The button `value` carries the JSON `{callback_id, schema, title, submit_label, metadata}` — capped at 1900 bytes (Slack's button-value limit is 2000).
4. User clicks the button. The Slack `open_modal:<cb_id>` action handler decodes the value and calls `views.open` with the fresh `trigger_id` (Slack only allows opening a modal from a fresh trigger — that's why we need the button intermediary).
5. User fills in fields and submits. Slack delivers `view_submission` to the bot. The view handler extracts values via the schema, then posts to `POST /api/v1/modals/{callback_id}/submit` with `{values, submitted_by, metadata, channel_id}`.
6. The endpoint resolves the waiter; the agent's tool call returns the `values` dict.
7. If the user dismisses the modal, `view_closed` posts to `…/cancel`; the tool returns `{ok: false, error: "user_dismissed"}`.

Timeouts and durability: the tool waits up to **15 minutes**. Waiters are process-local (not durable) — a server restart while a modal is open cleanly times out the agent and the user sees the modal close with no effect. Good enough for short forms; durable form-state is a future consideration.

**Tool exposure is capability-gated.** On a channel with no MODALS-capable binding, `open_modal` is not in the LLM's tool list for the turn. The unsupported return above is a last-line defense.

## App Home

The bot's App Home tab is its persistent per-user dashboard inside Slack — reachable by clicking the bot's name in the sidebar. The view shows:

- A welcome blurb explaining what the bot can do
- A **Quick Ask** button that opens a DM with the bot
- The list of Slack channels currently bound to a server-side channel, each labeled with the responding bot's display name

The view is rebuilt fresh every time `app_home_opened` fires (Slack's recommended pattern for ambient surfaces). No per-user state is maintained.

Implementation: `integrations/slack/app_home.py`. To enable, turn on the Home tab in the Slack app config (api.slack.com/apps → App Home).

## Shortcuts

Two entry points beyond `@mention`:

- **Global shortcut `ask_bot_quick`** — appears in the Slack shortcuts menu (the ⚡ button). Opens a DM with the bot and dispatches a "Quick ask" prompt so the bot greets the user.
- **Message action `ask_bot_about_message`** — right-click any message → "Ask bot about this". Runs the bot in-thread on the selected message text.

Both reuse `dispatch()` so approval gating, passive rules, and per-channel config apply uniformly. The Slack app manifest must declare both callback_ids — see the table in *Slack App Configuration* above.

## Agent Tools (Slack-Only)

These tools declare `required_integrations={"slack"}` in `@register` so they are filtered out of the LLM's per-turn tool list on any channel without a Slack binding — the agent literally cannot call them there. On Slack-backed channels they operate as described below.

| Tool | Description | Required scope |
|---|---|---|
| `slack_schedule_message(text, post_at, thread_ts?)` | Schedule a future post (≤ 120 days). `post_at` accepts ISO 8601 or epoch seconds. Returns `scheduled_message_id` for cancellation. | `chat:write.scheduled` |
| `slack_pin_message(message_ts)` | Pin an existing message in the current channel. | `pins:write` |
| `slack_add_bookmark(title, link, emoji?)` | Add a link bookmark to the channel header (persistent, one-click access). | `bookmarks:write` |

All three share `integrations/slack/web_api.py` — a rate-limited helper that reuses the renderer's `slack_rate_limiter` so tool calls and renderer chat updates compete for the same per-method buckets (preventing a tool from accidentally starving the streaming UX).
