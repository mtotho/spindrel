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
cd slack-integration && python slack_bot.py
```

## Slack App Configuration

Required **Bot token scopes**: `app_mentions:read`, `chat:write`, `channels:history`, `channels:read`, `commands`, `files:read`, `files:write`

Optional scopes:
- `chat:write.customize` — custom display names per bot
- `groups:read` — show private channels in the binding dropdown (public channels work with `channels:read` alone)

**Event subscriptions**: `message.channels`, `app_mention`

**Slash commands** — register each at api.slack.com/apps → Slash Commands (Socket Mode; Request URL is ignored):

| Command | Description |
|---|---|
| `/ask <bot-id> <message>` | Route a message to a specific bot. Bot replies in the channel with its display name. `/ask` alone lists available bots. |
| `/bot [id]` | Show or switch the default bot for this channel. Session is unchanged. |
| `/bots` | List all available bots and their IDs. |
| `/context` | Show the current context window breakdown (chars per role). |
| `/plan [subcommand]` | View and manage agent plans (see plans documentation). |
| `/compact` | Force session compaction (summarize + memory write) now. |

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
4. **Included in compaction** (if `passive_memory = true`) — when the memory/knowledge phase runs, passive messages are visible in the transcript with a `[passive]` prefix, so the bot can extract relevant facts into long-term knowledge

This lets the bot stay aware of conversations happening around it without interrupting them.

## Channel Configuration

Configure per-channel behavior at `/admin/slack`. Each channel can have:

| Setting | Default | Description |
|---|---|---|
| **Default Bot** | `SLACK_DEFAULT_BOT` | The bot that responds to @mentions in this channel. Other bots can be addressed with `/ask <bot-id>`. |
| **Require @mention** | `true` | When checked, only @mentions trigger the agent. All other messages are stored passively as channel context. When unchecked, the bot replies to every message. |
| **Passive memory** | `true` | When compaction runs, passive channel messages are included in the memory/knowledge phase transcript so the bot can extract channel activity into knowledge. |

The derived session ID for each channel is shown in the channel list (first 8 chars of the UUID).

Config is served at `GET /integrations/slack/config` (requires `X-API-Key` header) and cached for 60 seconds by the Slack integration process.

## Multi-Bot Channels

A channel has one **default bot** (used for @mentions), but multiple bots can operate in the same channel:

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
