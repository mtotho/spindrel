# Discord Integration Guide

This guide covers setting up and configuring the Discord integration for Spindrel.

## Prerequisites

- A Discord account with permission to create applications
- Spindrel running (locally or in Docker)
- An `AGENT_API_KEY` configured in your `.env`

## Step 1: Create a Discord Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** and give it a name
3. Navigate to the **Bot** tab

### Configure the Bot

1. Click **Reset Token** and copy the token — this is your `DISCORD_TOKEN`
2. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent** (required to read message text)
3. Optionally disable **Public Bot** if you don't want others to invite it

### Set Bot Permissions

Navigate to **OAuth2 > URL Generator**:

1. Under **Scopes**, select:
   - `bot`
   - `applications.commands`

2. Under **Bot Permissions**, select:
   - Send Messages
   - Send Messages in Threads
   - Manage Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Add Reactions
   - Use Slash Commands

3. Copy the generated URL and open it in your browser to invite the bot to your Discord server

## Step 2: Configure Environment

Add the following to your `.env` file:

```bash
DISCORD_TOKEN=your-bot-token-here
AGENT_API_KEY=your-api-key
AGENT_BASE_URL=http://localhost:8000  # optional, this is the default
```

## Step 3: Start the Integration

The Discord bot starts automatically when Spindrel detects `DISCORD_TOKEN` in the environment.

```bash
# Start everything via docker compose
docker compose up

# Or run the server locally (bot auto-starts as subprocess)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or run the bot manually (separate terminal)
python integrations/discord/discord_bot.py
```

When the bot connects successfully, you'll see:
```
Discord bot ready as BotName#1234 (id=123456789)
Connected to 1 guild(s)
Synced 8 application commands
```

## Session Model

Each Discord channel maps to one agent session:

- **Client ID**: `discord:{channel_id}` (e.g., `discord:123456789012345678`)
- **Session ID**: Deterministic UUID5 derived from the client ID
- **Bot assignment**: Per-channel, configurable via `/bot` command or admin UI

## Message Routing

### Active vs Passive Messages

By default (`require_mention: true`):
- **@mentioning** the bot triggers the agent (active message)
- All other messages are stored as passive context
- Channel participants can reference passive messages for context and memory when passive memory is enabled

With `require_mention: false`:
- **All messages** trigger the agent
- Useful for dedicated bot channels

In multi-bot channels, routing decides who actively answers; it is not isolation
from channel context. Member bots can still absorb passive messages through
memory compaction or dreaming/learning when passive memory and their learning
settings allow it.

### Cancellation

Send **STOP** (case-insensitive) to cancel an in-progress agent loop.

### File Attachments

- **Text files** (`.txt`, `.md`, `.csv`, `.json`, etc.): Content is inlined in the message
- **Images**: Sent as vision attachments to multimodal models
- **Other files**: Metadata is tracked for reference

## Channel Configuration

### Via Admin UI

Navigate to the admin panel > Channels. Create or edit a channel with:
- **Client ID**: `discord:CHANNEL_ID` (right-click channel in Discord > Copy Channel ID)
- **Integration**: `discord`
- **Bot**: Select the bot to use
- **Require Mention**: Toggle @mention requirement
- **Passive Memory**: Store non-triggering messages as context

### Via Slash Commands

- `/bot` — View current bot
- `/bot assistant` — Switch to the `assistant` bot
- `/bots` — List all available bots with their models

## Multi-Bot Channels

Multiple bots can serve the same Discord channel:
- Default bot handles default @mentions; passive messages are channel context
- `/ask other-bot question` routes to a specific bot
- `/bot new-bot` switches the default for the channel

## Slash Commands Reference

### `/bot [bot_id]`
View or switch the active bot for the current channel.

### `/bots`
List all available bots with their names and models. The current bot is highlighted.

### `/ask <bot_id> <message>`
Send a one-off message to a specific bot without switching the channel default.

### `/context [contents]`
Show the context breakdown for the current session:
- Default: Shows character counts per category (system prompt, skills, history, etc.)
- `contents`: Dumps the actual messages the model would see

### `/compact`
Trigger context compaction for the current session. Creates a summary watermark.

### `/todos [done]`
Show pending todos. Use `done` to show completed items.

### `/model [name|clear|list]`
- No args: Show current model override
- `list`: Show all available models
- `<name>`: Set model override (supports fuzzy matching)
- `clear`: Remove model override

### `/health`
Quick server health check showing services, containers, disk usage, and deploy info.

The session-local web chat plan mode described in [Plan Mode](./plan-mode.md) does not currently have a Discord slash-command equivalent.

## Rich Tool Results

Discord declares `rich_tool_results` and a `tool_result_rendering` support matrix in `integrations/discord/integration.yaml`. The renderer reads final `NEW_MESSAGE` metadata and applies the channel's `tool_output_display` policy:

- `compact` appends a short tool-badge line to the assistant message.
- `full` renders supported read-only tool-result envelopes as Discord embeds, then appends compact badges for unsupported envelopes.
- `none` suppresses tool-result presentation.

Discord supports the same transcript-safe envelope families as Slack: text/markdown/json, component envelopes, diff/file-listing envelopes, and selected core `view_key`s such as `core.search_results`. Interactive HTML/native widgets fall back to badges. Widget actions are not mapped to Discord buttons; approvals continue through the separate approval embed/buttons path.

## Emoji Reactions

During agent processing, the bot adds emoji reactions to your message:

| Emoji | Meaning |
|-------|---------|
| ⏳ | Working (agent loop running) |
| 🔍 | Search tool running |
| 💻 | Command execution |
| 🧠 | Memory operation |
| 👀 | Reading files |
| ✏️ | Writing/editing files |
| 💬 | Delegation to another bot |
| ⚙️ | Other tool running |
| ✅ | Done (replaces ⏳) |

## Tool Approval

When a tool requires approval (configured via approval policies):

1. The bot sends an embed with tool details and buttons:
   - **Allow [tool]** — Create a permanent allow rule
   - **Approve this run** — Allow once
   - **Deny** — Reject the tool call
2. Smart suggestion buttons may appear for narrower rules
3. After clicking, the message updates to show the verdict

## Thinking Display Modes

Configure `thinking_display` per channel:

- **append** (default): Each thinking step is a separate message
- **replace**: Thinking overwrites in a single message
- **hidden**: Only shows "working..." status, no thought content

## Troubleshooting

### Bot doesn't respond to messages
- Ensure **Message Content Intent** is enabled in the Developer Portal
- Check that the bot has Send Messages permission in the channel
- Verify `require_mention` setting — try @mentioning the bot

### Slash commands don't appear
- Commands sync on bot startup — wait a few seconds after "ready"
- Discord caches commands; may take up to an hour to propagate globally
- For faster testing, guild-specific sync is used (instant)

### Rate limiting
- Discord allows ~50 requests/second per guild
- Message edits are limited to 5 per 5 seconds per message
- The stream buffer uses a 1.0s flush interval to stay within limits

### Messages are split unexpectedly
- Discord has a 2000 character limit per message
- Long responses are automatically split at paragraph/line boundaries
- Code blocks are properly re-opened across splits
