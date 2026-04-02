---
name: Gmail Feeds
description: Email ingestion from Gmail via IMAP with security pipeline and workspace delivery
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

- **`check_gmail_status`** — Test IMAP connectivity, show email address and folder count
- **`trigger_gmail_poll`** — Manually trigger a poll cycle, returns summary of fetched/passed/quarantined emails

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

Risk metadata is included in each delivered email file for transparency.

## When to Get This Skill

Retrieve this skill when:
- User asks about email, Gmail, or inbox management
- User wants to search email content
- User asks to create email digests or summaries
- User asks about Gmail configuration or connectivity
