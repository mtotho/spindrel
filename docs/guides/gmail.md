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
GMAIL_INITIAL_FETCH=new                  # First poll strategy: "new", "recent:N", or "all"
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
| `GMAIL_INITIAL_FETCH` | `new` | First-poll strategy (see below) |
| `AGENT_BASE_URL` | `http://localhost:8000` | Agent server URL |
| `AGENT_API_KEY` | (auto-provisioned) | Injected automatically by the process manager — do not set manually |

## Initial Fetch Strategy

When the Gmail poller connects for the first time (no cursor stored), `GMAIL_INITIAL_FETCH` controls what happens:

| Value | Behavior |
|---|---|
| `new` **(default)** | Seed cursor to the latest UID, skip all existing mail. Only future emails get processed. |
| `recent:N` | Fetch emails from the last N days (e.g. `recent:7`). Uses IMAP `SINCE` criteria. |
| `all` | Fetch everything in the mailbox (original behavior — can be very slow on large mailboxes). |

Once a cursor is established, this setting has no effect — subsequent polls always fetch from cursor+1 onward.

```bash
# Only process new emails arriving after first connect (recommended)
GMAIL_INITIAL_FETCH=new

# Bootstrap with the last 7 days of email
GMAIL_INITIAL_FETCH=recent:7

# Fetch everything (use with caution on large mailboxes)
GMAIL_INITIAL_FETCH=all
```

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

Three tools are available to bots with the `gmail-feeds` capability:

- **`check_gmail_status`** — Test IMAP connectivity, show email and folder count
- **`trigger_gmail_poll`** — Run a poll cycle immediately, deliver passed emails to bound channel workspaces, and return a summary. Supports optional overrides:
  - `deliver: false` — Check what's available without writing files
  - `since_days: N` — Fetch emails from the last N days (ignores cursor, uses IMAP SINCE)
  - `max_items: N` — Override max emails to fetch this call
  - `folders: "INBOX, [Gmail]/Sent Mail"` — Override which folders to poll
- **`query_feed_store`** — Query feed health stats, recent deliveries, and quarantined items from the ingestion SQLite store

### Feed Store Queries

```
# Check feed health (24h stats, quarantine counts, cursor position)
query_feed_store(action="stats", store="gmail", source="gmail")

# List recently delivered emails
query_feed_store(action="recent", store="gmail", limit=10)

# Review quarantined emails (blocked by security pipeline)
query_feed_store(action="quarantine", store="gmail")

# Discover all feed stores on the server
query_feed_store(action="sources")
```

## Tool + Skill Composition

The Gmail integration can expose its tools directly on an activated channel, while related
skills are enrolled or fetched through the normal skill system. If you want both Gmail and
Mission Control behaviors in the same context, activate the Gmail integration and make sure
the relevant Mission Control tools and skills are also available on that bot/channel.

## API Endpoints

All endpoints require authentication.

| Method | Path | Description |
|---|---|---|
| `GET` | `/integrations/gmail/ping` | Health check |
| `GET` | `/integrations/gmail/status` | Test IMAP connectivity |
| `POST` | `/integrations/gmail/trigger` | Manual poll cycle (returns results) |

## Email Triage Template

The Gmail integration ships an **Email Triage & Digest** workspace template (`email-digest`) that teaches bots a structured email processing protocol:

- **Triage categories**: Urgent, Action Required, Projects/Threads, FYI, Low Priority
- **Workspace files**: `triage.md` (categorized log), `actions.md` (extracted items), `digest.md` (summary), `feeds.md` (sender rules)
- **Action extraction**: Automatic detection of deadlines, reply requests, approvals, assignments
- **MC integration**: Creates task cards from actionable emails, logs triage events to timeline
- **Heartbeat-ready**: Suggested config for automated digest generation

Activate Gmail on a channel and select the "Email Triage & Digest" template to enable the full protocol.

## Workflow: Gmail Ingest & Triage

The `gmail-ingest` workflow provides an end-to-end pipeline you can trigger manually, via bot tool, or on a heartbeat schedule:

1. **Poll** (tool step) — `trigger_gmail_poll` fetches new emails via IMAP, runs the 4-layer security pipeline, and delivers passed emails to bound channel workspaces
2. **Health check** (tool step) — `query_feed_store` returns aggregate stats (processed, quarantined, 24h activity)
3. **Quarantine review** (tool step) — `query_feed_store` lists any emails blocked by the security pipeline
4. **Triage & digest** (agent step) — reads delivered emails, categorizes them, updates `triage.md`, `actions.md`, and `digest.md`

Steps 1-3 are deterministic (no LLM). Step 4 only runs if new emails were delivered.

```bash
# Trigger via API
curl -X POST http://localhost:8000/api/v1/admin/workflows/gmail-ingest/run \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'

# Or trigger via bot tool
manage_workflow(action="trigger", workflow_id="gmail-ingest")
```

## Cursor Format

The Gmail poller tracks its position using per-folder IMAP UID cursors stored in the ingestion SQLite database. Cursor keys follow the format `gmail:{FOLDER}` (e.g., `gmail:INBOX`). You can inspect them via:

```bash
sqlite3 ~/.agent-workspaces/.ingestion/gmail.db "SELECT key, value, updated_at FROM cursors"
```

Or programmatically via `query_feed_store(action="stats", store="gmail", source="gmail")`.

## Authentication

Gmail requires an **App Password** for IMAP access. OAuth2 is **not supported** — only App Passwords work. This requires 2-Step Verification to be enabled on the Google account. If 2FA is later disabled, the app password is revoked and the poller will fail silently.

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
