# BlueBubbles (iMessage Bridge) Integration

Connect iMessage conversations to agent channels via [BlueBubbles](https://bluebubbles.app/) — an open-source iMessage bridge running on a Mac.

## Prerequisites

1. A Mac running BlueBubbles Server (with iMessage signed in)
2. BlueBubbles server accessible from the machine running the agent server
3. The agent server running with API key configured

## Setup

### 1. Configure Environment Variables

Add to your `.env` file:

```env
BLUEBUBBLES_SERVER_URL=http://192.168.1.50:1234
BLUEBUBBLES_PASSWORD=your-bb-server-password
AGENT_API_KEY=your-agent-api-key
AGENT_BASE_URL=http://localhost:8000  # optional, this is the default
BB_DEFAULT_BOT=default                # optional, bot ID to use
```

### 2. Install Dependencies

```bash
pip install -r integrations/bluebubbles/requirements.txt
```

### 3. Start the Agent Server

The BlueBubbles integration is auto-discovered. When `BLUEBUBBLES_SERVER_URL` and `BLUEBUBBLES_PASSWORD` are set, the Socket.IO client process starts automatically alongside the server.

### 4. Bind Channels

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

- **1:1 chats**: `bb:iMessage;-;+15551234567`
- **Group chats**: `bb:iMessage;+;chat123456`

The chat GUID comes directly from BlueBubbles. You can find it in the BB server UI or via the `/integrations/bluebubbles/chats` endpoint.

### Message Flow

1. **Inbound**: BB Socket.IO → `bb_client.py` → agent server `/chat/stream` → agent response → BB REST API → iMessage
2. **Outbound** (scheduled tasks): Task dispatcher → BB REST API → iMessage

### Bot/User Disambiguation

Since both bot and human messages appear as `isFromMe: true` in iMessage, the integration tracks every message sent via the API using:
- **GUID matching**: The `tempGuid` from our API call
- **Text hash matching**: SHA-256 prefix fallback

Untracked `isFromMe` messages are treated as human messages from your phone.

## Per-Chat Bot Mapping

By default, all chats use `BB_DEFAULT_BOT`. To assign specific bots to specific chats:

```bash
curl -X POST http://localhost:8000/integrations/bluebubbles/config/chat-bot-map \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"chat_guid": "iMessage;-;+15551234567", "bot_id": "my-special-bot"}'
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/integrations/bluebubbles/config` | GET | Current configuration |
| `/integrations/bluebubbles/config/chat-bot-map` | POST | Set per-chat bot mapping |
| `/integrations/bluebubbles/config/chat-bot-map/{chat_guid}` | DELETE | Remove per-chat mapping |
| `/integrations/bluebubbles/chats` | GET | List BB chats (proxied) |
| `/integrations/bluebubbles/status` | GET | Check BB server connectivity |

## Troubleshooting

- **No messages coming through**: Check that `BLUEBUBBLES_SERVER_URL` is reachable from the agent server. Use `/integrations/bluebubbles/status` to verify connectivity.
- **Bot replies appearing as your messages**: This is expected — the bot sends from your iMessage account. The echo tracker ensures these aren't processed as new input.
- **Duplicate responses after restart**: A few echoes may be misidentified as human messages right after restart (the echo tracker is in-memory). This is harmless and self-corrects within 30 seconds.
