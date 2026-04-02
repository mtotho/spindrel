---
category: workspace_schema
description: Email triage and digest management — categorized inbox processing, action extraction, and automated summaries.
compatible_integrations: gmail
tags: email, digest, feeds, triage
---
## Workspace File Organization — Email Triage & Digest

### Active Files

- **triage.md** — Rolling categorized log of processed emails. Each entry: date, sender, subject, category, one-line summary. Most recent at top. Trim entries older than 2 weeks.
- **actions.md** — Extracted action items: follow-ups, deadlines, replies needed, approvals pending. Format: `- [ ] [deadline] action description (source: sender/subject)`. Remove completed items weekly.
- **digest.md** — Latest digest summary grouped by category. Regenerate on request or via heartbeat.
- **feeds.md** — Feed rules and sender context: known senders, priority rules, categorization overrides, digest frequency preferences.
- **notes.md** — Scratch space for email patterns, organizational context, and user preferences.

### Triage Categories

| Category | Description | Examples |
|----------|-------------|----------|
| **Urgent** | Needs immediate attention or response | Escalations, outage alerts, time-sensitive approvals |
| **Action Required** | Needs a response or follow-up but not urgent | Meeting requests, review requests, questions |
| **Projects/Threads** | Updates on active work — informational but relevant | PR reviews, project updates, thread replies |
| **FYI** | Good to know, no action needed | Newsletters, announcements, CC'd threads |
| **Low Priority** | Can be ignored or batch-processed | Marketing, automated notifications, spam-adjacent |

### Triage Protocol

When new emails appear in `data/gmail/`:

1. **Check feed health first** — Run `query_feed_store(action="stats", store="gmail", source="gmail")` to see processing counts and check for quarantine spikes.
2. **Scan new emails** — Use `search_channel_workspace` to find recent unprocessed emails in `data/gmail/`.
3. **Categorize each email** — Read the email file, assign a triage category based on sender, subject, and content.
4. **Update triage.md** — Add a categorized entry for each email (newest first).
5. **Extract action items** — For Urgent and Action Required emails, extract specific actions → `actions.md` with deadlines where possible.
6. **Flag urgent items** — If anything is Urgent, proactively notify the user.

### Action Extraction Patterns

Look for these in email content:
- **Deadlines**: "by Friday", "due March 15", "EOD", "ASAP"
- **Reply requests**: "please respond", "thoughts?", "can you confirm", "RSVP"
- **Approvals**: "approve", "sign off", "authorize", "please review and merge"
- **Meeting invites**: Calendar attachments, "let's schedule", "available for a call"
- **Assignments**: "can you handle", "please take care of", "I need you to"

### Digest Generation

When generating a digest (manually or via heartbeat):

```markdown
# Email Digest — {date}

## Urgent / Action Required
- **[sender]** subject — one-line summary. Action: what's needed, deadline.

## Projects & Threads
- **[sender]** subject — one-line summary.

## FYI
- **[sender]** subject — one-line summary.

## Stats
- Processed: X emails | Quarantined: Y | Actions pending: Z
```

### Mission Control Integration

When Mission Control tools are available:
- **Create task cards** for Action Required items: `create_task_card` with tags `email,from:{sender}`
- **Log triage events** to timeline: `append_timeline_event` with "Triaged X emails: Y urgent, Z actions"
- Keep task cards linked to source emails so the user can trace back

### Heartbeat Pattern

Suggested heartbeat config for automated digest generation:
- **Interval**: `6h` or `12h`
- **Prompt**: "Check for new emails in data/gmail/, triage any unprocessed ones, update triage.md and actions.md, then regenerate digest.md with current summary and stats."
- **Dispatch mode**: `optional` (skip if no new emails)

### Guidelines

- Always check `query_feed_store` stats before triage to catch quarantine spikes early
- Reference `feeds.md` for sender context and priority rules before categorizing
- Keep `triage.md` as a rolling log — archive old entries, don't let it grow unbounded
- When in doubt about category, err toward higher priority (Action Required > FYI)
- Archive completed actions and old digest snapshots to `archive/`
