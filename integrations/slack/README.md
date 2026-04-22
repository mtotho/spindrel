# Slack Integration

Connects the agent server to Slack via [Bolt for Python](https://slack.dev/bolt-python/).

## Required Environment Variables

| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | Bot token (`xoxb-...`) — needs `chat:write`, `chat:write.customize`, `reactions:write`, `channels:read` scopes |
| `SLACK_APP_TOKEN` | App-level token (`xapp-...`) for Socket Mode |
| `AGENT_API_KEY` | API key for the agent server |
| `AGENT_BASE_URL` | Agent server URL (default: `http://localhost:8000`) |

## Optional Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_SUGGEST_CHANNELS` | `true` | Show channel dropdown when creating a binding. Set to `false` to disable. |
| `SLACK_SUGGEST_COUNT` | `20` | Number of channels to show in the binding dropdown (max: 100). |

## Slash Commands

Register these in your Slack app's slash command config.

| Command | Description |
|---------|-------------|
| `/bot [bot-id]` | Show or switch the active bot for this channel |
| `/bots` | List all available bots |
| `/ask <bot-id> <message>` | Send a one-off message to a specific bot |
| `/model [model\|list\|clear]` | View, set, or clear the model override |
| `/context [contents]` | Show context breakdown or dump full context |
| `/compact` | Force context compaction |
| `/todos [done]` | Show pending or completed todos |
| `/health` | Server health check |
| `/audit [#channel\|off]` | Set or clear the audit channel for tool call logging |

## Hooks

The Slack integration registers server-side hooks via `hooks.py`:

### Emoji Reactions (tool indicators)

When the bot uses tools, emoji reactions appear on the user's Slack message:

- First tool call: hourglass appears
- Each tool type adds its own emoji (search, exec, memory, etc.)
- When the response completes: hourglass removed, checkmark added
- If no tools were used: no reactions added

### Audit Channel

Log every tool call across all bots to a designated Slack channel:

```
/audit #bot-audit     — enable audit logging to #bot-audit
/audit                — show current audit channel
/audit off            — disable
```

Each tool call posts a one-liner: `` `web_search` by `my-bot` (1200ms) ``

## Binding Suggestions (Channel Picker)

When adding a Slack binding in the admin UI, a **channel dropdown** appears showing Slack channels the bot can see. Clicking a channel auto-fills the Client ID and Display Name fields.

This uses the `conversations.list` API, which requires the `channels:read` scope (already standard for the Slack bot token). Private channels also require `groups:read`.

| Setting | Default | Description |
|---------|---------|-------------|
| `SLACK_SUGGEST_CHANNELS` | `true` | Set to `false` to disable the dropdown |
| `SLACK_SUGGEST_COUNT` | `20` | Number of channels to show (max: 100) |

Results are cached server-side for 5 minutes.

## Files

| File | Description |
|------|-------------|
| `slack_bot.py` | Bolt app setup and event registration |
| `message_handlers.py` | Message event handling, streaming, thinking indicators |
| `slash_commands.py` | All slash command implementations |
| `dispatcher.py` | `SlackDispatcher` for task result delivery |
| `hooks.py` | Server-side hooks: metadata, reactions, audit |
| `client.py` | Shared HTTP helpers for `chat.postMessage` |
| `formatting.py` | Slack message formatting and splitting |
| `state.py` | Per-channel state persistence (`slack_state.json`) |
| `slack_settings.py` | Environment config and live config cache |
| `config.py` | Identity fields for user profile linking |
| `session_helpers.py` | Client ID derivation |
| `uploads.py` | File upload handling |
| `process.py` | Process definition for `dev-server.py` auto-start |
