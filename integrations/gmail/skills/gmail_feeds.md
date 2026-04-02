---
name: Gmail Feeds
description: Email ingestion from Gmail via IMAP with security pipeline, workspace delivery, triage workflows, and feed health monitoring
---

# SKILL: Gmail Feeds

## Overview

The Gmail feed integration polls a Gmail account via IMAP, processes each email through the 4-layer ingestion security pipeline, and delivers approved messages as markdown files to channel workspaces.

## How It Works

1. **IMAP polling** — Connects to Gmail via IMAP4_SSL, fetches new emails by UID cursor
2. **Security pipeline** — Each email passes through HTML stripping, injection detection, AI classification, and envelope validation
3. **Workspace delivery** — Approved emails are written to `data/gmail/` as markdown files
4. **Timeline logging** — Delivery events are logged to `timeline.md`

## Email Storage

Emails appear in the channel workspace at:

```
data/gmail/
  2026-03-30-meeting-recap.md
  2026-03-30-weekly-report.md
  2026-03-29-invoice-update.md
```

Each file includes:
- Email headers (From, To, Date, Subject)
- Attachment metadata (filenames, types, sizes — no content)
- Security risk assessment
- Email body as markdown

## Tools

### Gmail-specific
- **`check_gmail_status`** — Test IMAP connectivity, show email address and folder count
- **`trigger_gmail_poll`** — Manually trigger a poll cycle, returns summary of fetched/passed/quarantined emails

### Feed store queries
- **`query_feed_store`** — Query the ingestion SQLite store for stats, recent items, and quarantine entries

#### Check feed health
```
query_feed_store(action="stats", store="gmail", source="gmail")
→ {"total_processed": 142, "total_quarantined": 3, "processed_24h": 12, "quarantined_24h": 0, "last_cursor": {"key": "gmail", "value": "uid-500", ...}}
```

#### List recent delivered emails
```
query_feed_store(action="recent", store="gmail", limit=10)
→ [{"source": "gmail", "source_id": "gmail:12345", "action": "passed", "risk_level": "low", "ts": "..."}]
```

#### Review quarantined emails
```
query_feed_store(action="quarantine", store="gmail")
→ [{"source": "gmail", "source_id": "gmail:99", "risk_level": "high", "flags": ["injection_attempt"], "reason": "prompt injection detected", ...}]
```

#### List all feed stores
```
query_feed_store(action="sources")
→ [{"store": "gmail", "sources": ["gmail"], "path": "..."}]
```

## Triage Workflow

### Step-by-step triage process

1. **Check feed health** — `query_feed_store(action="stats", store="gmail", source="gmail")` to see 24h activity and quarantine counts. If quarantined_24h is elevated, review quarantine first.

2. **Review quarantine** (if needed) — `query_feed_store(action="quarantine", store="gmail", limit=5)` to see what was blocked and why. Report suspicious patterns to the user.

3. **Find new emails** — `search_channel_workspace(channel_id, query="data/gmail")` to find recently delivered email files.

4. **Read and categorize** — Read each email file, assign a triage category:
   - **Urgent**: escalations, outage alerts, time-sensitive approvals
   - **Action Required**: needs response/follow-up but not urgent
   - **Projects/Threads**: active work updates, informational
   - **FYI**: newsletters, announcements, CC'd threads
   - **Low Priority**: marketing, automated notifications

5. **Update workspace files** — Add entries to `triage.md`, extract action items to `actions.md`.

6. **Create task cards** (when MC tools available) — For Action Required items, use `create_task_card` with tags `email,from:{sender}`.

### Action extraction patterns

Look for these in email content:
- **Deadlines**: "by Friday", "due March 15", "EOD", "ASAP"
- **Reply requests**: "please respond", "thoughts?", "can you confirm"
- **Approvals**: "approve", "sign off", "please review and merge"
- **Assignments**: "can you handle", "please take care of"

### Digest generation

When the user requests a digest or a heartbeat fires:

1. Check `query_feed_store` stats for the period
2. Search `data/gmail/` for emails in the time range
3. Group by triage category
4. Include quarantine stats for transparency
5. Write to `digest.md`

## Searching Email Content

Use `search_channel_workspace` to find emails:

```
search_channel_workspace(channel_id, query="invoice from accounting")
search_channel_workspace(channel_id, query="meeting agenda next week")
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `GMAIL_EMAIL` | (required) | Gmail address for IMAP login |
| `GMAIL_APP_PASSWORD` | (required) | App password (not regular password) |
| `GMAIL_IMAP_HOST` | imap.gmail.com | IMAP server |
| `GMAIL_IMAP_PORT` | 993 | IMAP port |
| `GMAIL_POLL_INTERVAL` | 60 | Seconds between polls |
| `GMAIL_MAX_PER_POLL` | 25 | Max emails per cycle |
| `GMAIL_FOLDERS` | INBOX | Comma-separated folders |

## Channel Binding

Channels receive email by binding with client_id format `gmail:user@gmail.com`. All emails from the configured account are delivered to bound channels.

## Security

All email content passes through the ingestion security pipeline before delivery:
- Prompt injection patterns are detected and flagged
- Zero-width characters and hidden content are caught
- AI classifier provides final safety assessment (fails closed on errors)
- Unsafe emails are quarantined — never delivered to workspace

Risk metadata is included in each delivered email file for transparency. Use `query_feed_store(action="quarantine")` to review what was blocked and why.

## When to Get This Skill

Retrieve this skill when:
- User asks about email, Gmail, or inbox management
- User wants to search email content
- User asks to create email digests or summaries
- User asks about Gmail configuration or connectivity
- User wants to triage or categorize emails
- User asks about quarantined or blocked emails
- User wants feed health stats or monitoring
