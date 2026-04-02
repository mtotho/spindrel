# Gmail Integration

The Gmail integration polls a Gmail account via IMAP, runs each email through the 4-layer ingestion security pipeline, and delivers approved messages as markdown files to channel workspaces.

## How It Works

```
                        Agent Server (Docker / host)
┌──────────────────────────────────────────────────────────────────────┐
│                                                                      │
│  ┌─────────────┐    ┌────────────────────┐    ┌──────────────────┐  │
│  │ Gmail IMAP  │───▶│ Ingestion Pipeline │───▶│ Channel Workspace│  │
│  │  (poller)   │    │ (4-layer security) │    │ data/gmail/*.md  │  │
│  └──────┬──────┘    └────────┬───────────┘    └────────┬─────────┘  │
│         │                    │                         │            │
│    polls every        ┌──────▼──────┐           Bot searches &     │
│    60s via IMAP       │ Quarantine  │           reads these files   │
│         │             │ (SQLite DB) │           via workspace tools │
│         │             └─────────────┘                  │            │
│  ┌──────▼──────┐                              ┌───────▼────────┐   │
│  │  Gmail API  │                              │ MC Dashboard   │   │
│  │ (external)  │                              │ sees files too │   │
│  └─────────────┘                              └────────────────┘   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

**Key points:**
- The poller runs as a **subprocess** alongside the agent server (auto-started when env vars are set)
- It uses stdlib `imaplib` — no extra Python dependencies beyond `httpx` (already in the server)
- Emails are written to channel workspaces via HTTP calls to the Mission Control file proxy
- All email content passes through the security pipeline before delivery — unsafe content is quarantined, never delivered

## Prerequisites

- A Gmail account with **App Passwords** enabled (requires 2FA)
- The agent server running (locally or in Docker)
- The **Mission Control** integration enabled (Gmail uses MC's workspace file proxy for delivery)

## Step 1: Generate a Gmail App Password

1. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
2. You must have **2-Step Verification** enabled
3. Select "Mail" and your device, then click **Generate**
4. Copy the 16-character app password (e.g., `abcd efgh ijkl mnop`)

> **Important**: Use the app password, NOT your regular Gmail password. Regular passwords won't work with IMAP when 2FA is enabled.

## Step 2: Configure Environment

Add to your `.env` file:

```bash
# Required
GMAIL_EMAIL=you@gmail.com
GMAIL_APP_PASSWORD=abcdefghijklmnop      # App password from Step 1

# Optional
AGENT_BASE_URL=http://localhost:8000     # Default
GMAIL_IMAP_HOST=imap.gmail.com           # Default
GMAIL_IMAP_PORT=993                      # Default
GMAIL_POLL_INTERVAL=60                   # Seconds between polls (default: 60)
GMAIL_MAX_PER_POLL=25                    # Max emails per cycle (default: 25)
GMAIL_FOLDERS=INBOX                      # Comma-separated folders (default: INBOX)
```

> **Note**: The Gmail poller needs an API key to call back to the server for workspace delivery. This key is **auto-provisioned** when you save integration settings via the admin UI — you don't need to set `AGENT_API_KEY` manually. The process manager injects it into the poller's environment automatically.

## Step 3: Bind a Channel

Emails are delivered to channels that are bound to the Gmail account. Create a channel with the client_id format `gmail:your-email@gmail.com`:

**Via the admin API:**
```bash
curl -X POST http://localhost:8000/api/v1/channels \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"client_id": "gmail:you@gmail.com", "bot_id": "your-bot"}'
```

**Via the UI:** Create a channel and set the Client ID to `gmail:you@gmail.com`.

The channel must have workspace enabled for files to be written to it.

## Step 4: Start the Server

```bash
# Docker (recommended)
docker compose up

# Or locally
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The Gmail poller starts automatically when `GMAIL_EMAIL` and `GMAIL_APP_PASSWORD` are set in the environment. You'll see in the logs:

```
Gmail poller starting for you@gmail.com (waiting 5s for server)...
Cycle: fetched=3 passed=3 quarantined=0 skipped=0 errors=0
Delivered gmail:INBOX:456 to channel abc-123 at data/gmail/2026-03-30-weekly-report.md
```

## Dependency Notes

The Gmail integration has minimal dependencies:

| Dependency | Where | Notes |
|---|---|---|
| `imaplib` | Gmail feed | Python stdlib — always available |
| `httpx` | Agent client | Listed in `integrations/gmail/requirements.txt` — already a core server dependency |
| Mission Control | Workspace delivery | The poller writes files via MC's workspace file proxy endpoint |

**When running in Docker** (the default production setup), all dependencies are available inside the container — the Dockerfile installs integration requirements automatically.

**When running locally**, `httpx` is already installed as a core dependency (`pyproject.toml`). No extra `pip install` needed.

## Configuration Reference

| Setting | Default | Description |
|---|---|---|
| `GMAIL_EMAIL` | (required) | Gmail address for IMAP login |
| `GMAIL_APP_PASSWORD` | (required) | App password (NOT your regular password) |
| `GMAIL_IMAP_HOST` | `imap.gmail.com` | IMAP server hostname |
| `GMAIL_IMAP_PORT` | `993` | IMAP server port (SSL) |
| `GMAIL_POLL_INTERVAL` | `60` | Seconds between poll cycles |
| `GMAIL_MAX_PER_POLL` | `25` | Maximum emails to fetch per cycle |
| `GMAIL_FOLDERS` | `INBOX` | Comma-separated IMAP folders to monitor |
| `AGENT_BASE_URL` | `http://localhost:8000` | Agent server URL |
| `AGENT_API_KEY` | (auto-provisioned) | Injected automatically by the process manager — do not set manually |

## Email Storage

Emails are stored as markdown files in the channel workspace:

```
~/.agent-workspaces/{bot_id}/channels/{channel_id}/
  data/
    gmail/
      2026-03-30-weekly-report.md
      2026-03-30-meeting-recap.md
      2026-03-29-invoice-update.md
```

Each file contains:
- Email headers (From, To, Date, Subject)
- Attachment metadata (filenames, types, sizes — content is NOT downloaded)
- Security risk assessment from the ingestion pipeline
- Email body as plain text

Files in `data/` are listed but not auto-injected into bot context. Use `search_channel_workspace` to find and reference specific emails.

## Security Pipeline

Every email passes through 4 security layers before delivery:

1. **HTML stripping** — Removes script/style tags, normalizes Unicode (NFKC)
2. **Injection filters** — Regex detection of 8 prompt injection patterns + 12 types of zero-width chars
3. **AI classifier** — LLM-based safety assessment (fails closed: any error = quarantine)
4. **Typed envelope** — Pydantic validation into structured format

Emails that fail any layer are quarantined in a local SQLite database (`~/.agent-workspaces/.ingestion/gmail.db`) and **never delivered** to the workspace.

## Bot Tools

Two tools are available to bots with the `gmail-feeds` carapace:

- **`check_gmail_status`** — Test IMAP connectivity, show email and folder count
- **`trigger_gmail_poll`** — Run a poll cycle immediately and see what was fetched

## Carapace Composition

The `gmail-feeds` carapace includes `mission-control`, so bots get both Gmail tools and MC tools (kanban, timeline, plans):

```yaml
# In your bot YAML:
carapaces:
  - gmail-feeds    # Includes: gmail tools + MC tools + all skills
```

## API Endpoints

All endpoints require authentication.

| Method | Path | Description |
|---|---|---|
| `GET` | `/integrations/gmail/ping` | Health check |
| `GET` | `/integrations/gmail/status` | Test IMAP connectivity |
| `POST` | `/integrations/gmail/trigger` | Manual poll cycle (returns results) |

## Troubleshooting

**Poller starts but no emails delivered:**
- Check that a channel is bound with `gmail:your-email@gmail.com` as client_id
- Check that the channel has workspace enabled
- Check that Mission Control integration is loaded (the poller uses its file proxy)
- Check that integration settings have been saved via the admin UI (this provisions the API key the poller needs for delivery)

**IMAP connection fails:**
- Verify 2FA is enabled on your Google account
- Verify the app password is correct (no spaces)
- Check that IMAP is enabled in Gmail settings (Settings > Forwarding and POP/IMAP)

**Emails quarantined unexpectedly:**
- Check the quarantine table: `sqlite3 ~/.agent-workspaces/.ingestion/gmail.db "SELECT source_id, reason FROM quarantine ORDER BY quarantined_at DESC LIMIT 10"`
- The classifier may flag legitimate emails with unusual formatting — adjust `INGESTION_CLASSIFIER_MODEL` for a model with better judgment

**Multiple Gmail accounts:**
- Currently one account per server instance. Multiple account support is planned but not yet implemented. As a workaround, run separate agent-server instances with different `GMAIL_EMAIL` settings.
