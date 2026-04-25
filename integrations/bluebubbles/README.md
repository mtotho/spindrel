# BlueBubbles (iMessage Bridge) Integration

Connect iMessage conversations to agent channels via [BlueBubbles](https://bluebubbles.app/) — an open-source iMessage bridge running on a Mac.

## Prerequisites

1. A Mac running BlueBubbles Server (with iMessage signed in)
2. BlueBubbles server accessible from the machine running the agent server
3. The agent server running with API key configured

## Setup

### 1. Configure Environment Variables

Add to your `.env` file or set via the Integration Settings UI:

| Variable | Required | Description |
|----------|----------|-------------|
| `BLUEBUBBLES_SERVER_URL` | Yes | BlueBubbles server URL (e.g. `http://192.168.1.50:1234`) |
| `BLUEBUBBLES_PASSWORD` | Yes | BlueBubbles server password |
| `AGENT_API_KEY` | Yes | API key for the agent server |
| `AGENT_BASE_URL` | No | Agent server URL (default: `http://localhost:8000`) |
| `BB_DEFAULT_BOT` | No | Default bot ID for legacy config paths. Webhook channel bindings normally choose the bot. |
| `BB_WAKE_WORDS` | No | Extra wake words (comma-separated), added on top of automatic bot name/id. See [Wake Words](#wake-words). |
| `BB_WEBHOOK_TOKEN` | No | Shared secret for webhook auth. If set, BB must send `?token=` in the webhook URL. |
| `BB_SEND_METHOD` | No | iMessage send method: `apple-script` (default, reliable) or `private-api` (requires Private API helper). |
| `BB_SUGGEST_CHATS` | No | Show recent chats dropdown when creating a binding (default: `true`). Set to `false` to disable. |
| `BB_SUGGEST_COUNT` | No | Number of recent chats to show in the binding dropdown (default: `10`, max: `50`). |
| `BB_SUGGEST_PREVIEW` | No | Show last message preview text in the binding dropdown (default: `true`). Set to `false` to hide message content. |

Example `.env`:
```env
BLUEBUBBLES_SERVER_URL=http://192.168.1.50:1234
BLUEBUBBLES_PASSWORD=your-bb-server-password
AGENT_API_KEY=your-agent-api-key
BB_DEFAULT_BOT=atlas
BB_WAKE_WORDS=atlas, hey bot
```

### 2. Install Dependencies

```bash
pip install -r integrations/bluebubbles/requirements.txt
```

### 3. Start the Agent Server

The BlueBubbles integration is auto-discovered. When `BLUEBUBBLES_SERVER_URL` and `BLUEBUBBLES_PASSWORD` are set, the integration activates automatically.

### 4. Configure Webhook in BlueBubbles

**This is the primary message delivery mechanism.** BlueBubbles delivers new-message events via HTTP webhooks (not Socket.IO).

1. Open your BlueBubbles Server UI
2. Navigate to **Settings → API & Webhooks**
3. Click **Add Webhook**
4. Set the URL to: `http://{agent-server-host}:8000/integrations/bluebubbles/webhook?token={BB_WEBHOOK_TOKEN}`
   - If `BB_WEBHOOK_TOKEN` is set, the `?token=` param is required — requests without it get 401. Omit the param if you haven't set a token (local/trusted network).
5. Subscribe to the `new-message` event (at minimum)
6. Save

> **Note:** The Socket.IO client (`bb_client.py`) is disabled. All message delivery happens through this webhook.

### 5. Bind Channels

Create channel bindings in the admin UI or via API:

```bash
# 1:1 chat
curl -X POST http://localhost:8000/api/v1/channels \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"client_id": "bb:iMessage;-;+15551234567", "bot_id": "default"}'

# Group chat
curl -X POST http://localhost:8000/api/v1/channels \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"client_id": "bb:iMessage;+;chat123456", "bot_id": "default"}'
```

## How It Works

### Client ID Format

| Chat Type | Format | Example |
|-----------|--------|---------|
| 1:1 chat | `bb:iMessage;-;{phone}` | `bb:iMessage;-;+15551234567` |
| Group chat | `bb:iMessage;+;{chat_id}` | `bb:iMessage;+;chat123456` |
| SMS 1:1 | `bb:SMS;-;{phone}` | `bb:SMS;-;+15551234567` |
| SMS group | `bb:SMS;+;{chat_id}` | `bb:SMS;+;chat789` |

The chat GUID comes directly from BlueBubbles. You can find it in the BB server UI or via the `/integrations/bluebubbles/chats` endpoint.

### Channel Binding as Allowlist

**The bot only responds to chats that have a pre-created Channel in the database.** Messages from unknown/unbound chats are silently dropped. This prevents the bot from accidentally responding to random contacts who text your number.

To authorize a chat, create a channel binding first (via admin UI or API -- see [Bind Channels](#4-bind-channels) above). Until a channel exists for that chat GUID, the bot ignores all messages from it.

### Message Routing

Every incoming message goes through this decision flow:

```
Message arrives
  |
  +-- Empty text?  -------------------- skip (attachments-only, etc.)
  |
  +-- No channel binding for chat? ---- skip (unbound / unauthorized chat)
  |
  +-- isFromMe + echo tracker match? -- skip (bot's own reply bouncing back)
  |
  +-- isFromMe + NOT echo? ------------ ACTIVE (you texting from your phone)
  |
  +-- External message
       |
       +-- require_mention = false? ---- ACTIVE (respond to everything)
       |
       +-- Wake word detected? --------- ACTIVE (bot was addressed)
       |
       +-- No wake word --------------- PASSIVE (stored as context, no reply)
```

**Active** = the agent processes the message, generates a response, and sends it back to the chat.

**Passive** = the message is stored in the channel's conversation history (so the bot has context if addressed later) but no response is generated.

### Wake Words

Since iMessage has no native @-mention system, wake words act as the mention trigger. When `require_mention` is enabled on a channel, the bot only responds if a wake word appears anywhere in the message text.

**Automatic wake words**: The bot's **name** and **ID** (from the channel binding) are automatically used as wake words. If a channel uses a bot named "Atlas" with id "atlas", both "atlas" and "Atlas" will trigger it — no configuration needed.

**Custom wake words**: Set `BB_WAKE_WORDS` to add extra wake words on top of the automatic ones. These apply globally to all BB channels.

```env
BB_WAKE_WORDS=hey bot, yo assistant
```

**Matching rules**:
- Case-insensitive: "Atlas", "ATLAS", "atlas" all match
- Substring match: "hey atlas what's up" matches wake word `atlas`
- Any wake word: only one needs to match
- The full message (including the wake word) is sent to the agent — nothing is stripped

**Examples** with bot name "Atlas" and `BB_WAKE_WORDS=hey bot`:

| Message | Matches? | Why |
|---------|----------|-----|
| "atlas what's the weather" | Yes | bot id/name "atlas" found |
| "Hey Bot, help me" | Yes | custom "hey bot" found (case-insensitive) |
| "can you help me Atlas" | Yes | bot name found at end |
| "what's for dinner" | No | no wake words present |
| "hey everyone" | No | "hey" alone doesn't match "hey bot" |

### Channel Configuration

Each BB chat maps to a Channel in the agent database. Two key per-channel settings control message routing:

| Setting | Default | Description |
|---------|---------|-------------|
| `require_mention` | `true` | When true, external messages need a wake word to trigger the bot. When false, every message triggers the bot. |
| `passive_memory` | `true` | When true, passive messages are included in the bot's memory/context. When false, they're stored but excluded from memory. |

These are standard Channel fields — configure them via the admin UI (Channel Settings) or the API:

```bash
# Make a channel respond to everything (no wake word needed)
curl -X PUT http://localhost:8000/api/v1/admin/channels/{channel_id} \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"require_mention": false}'

# Require wake word but don't store passive messages in memory
curl -X PUT http://localhost:8000/api/v1/admin/channels/{channel_id} \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"require_mention": true, "passive_memory": false}'
```

**Common configurations**:

| Use Case | `require_mention` | `passive_memory` | Behavior |
|----------|-------------------|-------------------|----------|
| Personal assistant (1:1) | `false` | `true` | Responds to every message |
| Group chat (default) | `true` | `true` | Only responds when wake word used, remembers all messages |
| Noisy group (save tokens) | `true` | `false` | Only responds when addressed, ignores passive messages |
| Monitored channel | `true` | `true` | Silently observes, responds only when asked |

**Channels not yet in the database** (first message from an unknown chat) default to `require_mention=true`, so the bot won't reply to random messages until you configure the channel.

### Bot/User Disambiguation

Since both bot and human messages appear as `isFromMe: true` in iMessage, the integration tracks every message sent via the API using:
- **GUID matching**: The `tempGuid` from our API call
- **Text hash matching**: SHA-256 prefix fallback

Untracked `isFromMe` messages are treated as human messages from your phone and always trigger the bot (bypassing the wake word check — you're intentionally sending from your device).

## Per-Chat Bot Mapping

By default, all chats use `BB_DEFAULT_BOT`. To assign specific bots to specific chats:

```bash
# Assign a bot to a chat
curl -X POST http://localhost:8000/integrations/bluebubbles/config/chat-bot-map \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"chat_guid": "iMessage;-;+15551234567", "bot_id": "my-special-bot"}'

# Remove the override (falls back to default)
curl -X DELETE http://localhost:8000/integrations/bluebubbles/config/chat-bot-map/iMessage;-;+15551234567 \
  -H "Authorization: Bearer $AGENT_API_KEY"
```

Note: Chat bot mappings are in-memory and reset on server restart. For persistent bot assignment, set the `bot_id` on the Channel directly.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/integrations/bluebubbles/webhook` | POST | Webhook receiver for BB new-message events |
| `/integrations/bluebubbles/config` | GET | Current configuration (bot map, wake words, channel settings) |
| `/integrations/bluebubbles/config/chat-bot-map` | POST | Set per-chat bot mapping |
| `/integrations/bluebubbles/config/chat-bot-map/{chat_guid}` | DELETE | Remove per-chat mapping |
| `/integrations/bluebubbles/chats` | GET | List BB chats (proxied from BB server) |
| `/integrations/bluebubbles/binding-suggestions` | GET | Recent chats formatted for the binding dropdown |
| `/integrations/bluebubbles/status` | GET | Check BB server connectivity |
| `/integrations/bluebubbles/diagnose` | GET | Full diagnostic of the integration path |
| `/integrations/bluebubbles/test-send` | POST | Send a test message to verify the send path |

## Message Flow Diagram

```
                    ┌──────────────┐
                    │  BlueBubbles │
                    │    Server    │
                    └──────┬───────┘
                           │ HTTP POST (webhook)
                           v
                    ┌──────────────────────┐
                    │  /integrations/      │  FastAPI endpoint
                    │  bluebubbles/webhook │  - Echo detection
                    │                      │  - Channel resolution
                    │                      │  - Wake word check
                    │                      │  - Active vs passive
                    └──────┬───────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              v                         v
     ┌────────────────┐       ┌─────────────────┐
     │  Task (active)  │       │  Passive store   │
     │  → Agent Loop   │       │  (context only)  │
     └───────┬────────┘       └─────────────────┘
             │
             v
     ┌────────────────┐
     │  Agent Loop     │  LLM processing + tool calls
     └───────┬────────┘
             │
             v
     ┌────────────────┐
     │ BB Renderer     │  send_text() → iMessage
     │  (echo tracked) │
     └────────────────┘
```

> The Socket.IO client (`bb_client.py`) is legacy reference code and is **not**
> launched for message delivery or status.

## Binding Suggestions (Channel Picker)

When adding a BlueBubbles binding in the admin UI, a **Recent Chats** dropdown appears showing your most recently active iMessage conversations. Clicking a chat auto-fills the Client ID and Display Name fields.

This is controlled by three optional settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `BB_SUGGEST_CHATS` | `true` | Set to `false` to disable the dropdown entirely |
| `BB_SUGGEST_COUNT` | `10` | Number of chats to show (1–50) |
| `BB_SUGGEST_PREVIEW` | `true` | Set to `false` to hide last message text from the dropdown |

Results are cached server-side for 5 minutes to avoid repeated calls to the BlueBubbles server.

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| No messages coming through | BB server unreachable | Check `BLUEBUBBLES_SERVER_URL`. Use `/integrations/bluebubbles/status` to verify. |
| Bot ignoring messages from a chat | No Channel binding exists for that chat | Create a channel binding first (admin UI or API). The bot only responds to bound chats. |
| Bot not responding to messages | `require_mention=true` and no wake word | Either include a wake word in your message, or set `require_mention=false` on the channel. |
| Bot not responding in group chats | Same as above -- groups default to requiring wake word | Say "atlas help me" (or whatever your wake word is). |
| Bot replies appearing as your messages | Expected -- bot sends from your iMessage account | The echo tracker prevents these from being re-processed. |
| Duplicate responses after restart | Echo tracker is in-memory, lost on restart | Self-corrects within ~30 seconds as new echoes are tracked. |
| Bot responds to everything | `require_mention=false` on the channel | Set `require_mention=true` if you want wake word filtering. |
| Wake words not working after config change | Channel binding/config does not match the chat path | Check the binding, `require_mention`, and configured wake words with `/diagnose`. |
| `/diagnose` shows issues | Various misconfigurations | Follow the specific issue messages in the diagnose output. |
