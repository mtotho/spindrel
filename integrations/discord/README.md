# Discord Integration

Connects the agent server to Discord via the Gateway WebSocket API (discord.py). Mirrors the Slack integration's dual-process architecture:

- **Server-side** (runs in agent-server process): `router.py`, `client.py`, `dispatcher.py`, `hooks.py`
- **Bot process** (separate process): `discord_bot.py` + supporting modules

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Bot token from Discord Developer Portal |
| `AGENT_API_KEY` | Yes | API key for the agent server |
| `AGENT_BASE_URL` | No | Agent server URL (default: `http://localhost:8000`) |
| `DISCORD_DEFAULT_BOT` | No | Default bot ID (default: `default`) |

## Discord Developer Portal Setup

1. Go to https://discord.com/developers/applications
2. Create a new application
3. Go to **Bot** tab:
   - Click "Reset Token" to get `DISCORD_TOKEN`
   - Enable **Message Content Intent** under Privileged Gateway Intents
   - Enable **Server Members Intent** if you need member resolution
4. Go to **OAuth2** tab:
   - Under **Scopes**, select `bot` and `applications.commands`
   - Under **Bot Permissions**, select:
     - Send Messages
     - Send Messages in Threads
     - Manage Messages (for editing/deleting thinking placeholders)
     - Embed Links
     - Attach Files
     - Read Message History
     - Add Reactions
     - Use Slash Commands
   - Copy the generated URL and open it to invite the bot to your server

## Slash Commands

Commands sync automatically when the bot connects. Available commands:

| Command | Description |
|---------|-------------|
| `/bot [bot_id]` | View or switch the active bot |
| `/bots` | List all available bots |
| `/ask <bot_id> <message>` | Send a message to a specific bot |
| `/context [contents]` | Show context breakdown |
| `/plan [args]` | View and manage plans |
| `/compact` | Compact session context |
| `/todos [done]` | Show pending/completed todos |
| `/model [name\|clear\|list]` | View or change model override |
| `/health` | Server health check |

## Message Routing

- **@mention** the bot to trigger the agent (when `require_mention=true`, default)
- **All messages** trigger the agent when `require_mention=false`
- Non-triggering messages are stored as passive context
- Send **STOP** to cancel an in-progress agent loop

## File Structure

| File | Description |
|------|-------------|
| `setup.py` | SETUP manifest (env vars, binding config) |
| `process.py` | Background process declaration |
| `session_helpers.py` | `discord_client_id()`, `derive_session_id()` |
| `config.py` | Identity fields for user profile linking |
| `formatting.py` | Message splitting (2000 char limit), tool status |
| `discord_config.yaml` | Legacy YAML fallback (default_bot) |
| `router.py` | GET /integrations/discord/config |
| `client.py` | Discord REST API helpers (post, edit, react) |
| `dispatcher.py` | DiscordDispatcher (task result delivery) |
| `hooks.py` | Integration metadata + emoji reaction hooks |
| `discord_settings.py` | Env config + live config cache (60s TTL) |
| `state.py` | Per-channel bot assignment (discord_state.json) |
| `agent_client.py` | HTTP calls to agent server (stream, channels) |
| `message_handlers.py` | on_message routing, streaming, thinking display |
| `slash_commands.py` | Discord application commands |
| `approval_handlers.py` | Tool approval via embeds + buttons |
| `uploads.py` | File upload helpers for dispatcher |
| `discord_bot.py` | Main entrypoint (Client + CommandTree) |
| `requirements.txt` | discord.py>=2.3.0 |

## Key Differences from Slack

- **Message limit**: 2000 chars (vs 3500 for Slack)
- **Markdown**: Native standard markdown (no conversion needed)
- **Auth**: `Authorization: Bot {token}` (not `Bearer`)
- **Reactions**: Unicode emoji directly URL-encoded (not Slack shortcodes)
- **Mentions**: `<@user_id>` format, detected via `message.mentions`
- **Approval UI**: Discord embeds + component buttons (not Block Kit)
- **File downloads**: Direct URL (no auth token needed)
- **Rate limits**: ~50 req/s per guild, 5 edits/5s per message → 1.0s stream buffer flush
- **Commands**: Application Commands (synced to guilds), not slash-prefixed text
