---
name: "Email Triage & Digest"
category: workspace_schema
description: Email triage and digest management — categorized inbox processing, action tracking, and automated summaries.
compatible_integrations:
  - gmail
  - mission_control
mc_min_version: "2.0"
tags:
  - email
  - digest
  - feeds
  - triage
  - mission-control
group: "Operations"
recommended_heartbeat:
  prompt: "Check for new emails in data/gmail/ — run query_feed_store(action='stats', store='gmail') for health, then triage any unprocessed emails. Create task cards for action items via create_task_card. Update status.md with inbox health. Log triage summary to timeline via append_timeline_event. Regenerate digest.md."
  interval: "6h"
  quiet_start: "22:00"
  quiet_end: "07:00"
---

## Workspace File Organization — Email Triage & Digest

Organize channel workspace files to manage email triage and action tracking. This schema is Mission Control compatible — action items are tracked as task cards, activity is logged to timeline, and inbox health is reported in status.

Root files are living documents injected into every context — keep them concise. Emails are delivered to `data/gmail/` by the Gmail integration's ingestion pipeline after passing through the security classifier.

### Root Files (auto-injected)

- **triage.md** — Rolling categorized log of processed emails
  - Each entry: date, sender, subject, category, one-line summary
  - Most recent at top
  - Trim entries older than 2 weeks, archive to `archive/`

- **tasks.md** — Action item kanban (Mission Control compatible)
  - Email-derived action items as task cards
  - Each card: requester (sender), deadline, source email reference
  - Use `create_task_card` and `move_task_card` tools

- **status.md** — Inbox health and triage summary (Mission Control compatible)
  - Phase/health/owner header block
  - Processing stats, quarantine counts, actions pending
  - Feed health per source

- **digest.md** — Latest digest summary grouped by category
  - Regenerate on request or via heartbeat
  - Grouped by triage category with one-line summaries

- **timeline.md** — Reverse-chronological activity log (Mission Control compatible)
  - Auto-captures: triage runs, action card creation, digest generation
  - Entries: `- HH:MM — Event description` grouped under `## YYYY-MM-DD` date headers

- **feeds.md** — Feed rules and sender context
  - Known senders with priority overrides
  - Categorization rules and exceptions
  - Digest frequency preferences

- **notes.md** — Scratch space for email patterns, organizational context, and user preferences

Create files as needed — start with triage.md and tasks.md.

### Archive (`archive/`)

Old triage entries, completed action items, past digest snapshots. Searchable via `search_channel_archive`.

---

## Triage Categories

| Category | Description | Examples |
|----------|-------------|----------|
| **Urgent** | Needs immediate attention or response | Escalations, outage alerts, time-sensitive approvals |
| **Action Required** | Needs a response or follow-up but not urgent | Meeting requests, review requests, questions |
| **Projects/Threads** | Updates on active work — informational but relevant | PR reviews, project updates, thread replies |
| **FYI** | Good to know, no action needed | Newsletters, announcements, CC'd threads |
| **Low Priority** | Can be ignored or batch-processed | Marketing, automated notifications, spam-adjacent |

## Triage Protocol

When new emails appear in `data/gmail/` (delivered by the Gmail integration's IMAP poller → ingestion pipeline → workspace):

1. **Check feed health first** — `query_feed_store(action="stats", store="gmail", source="gmail")` for processing counts and quarantine spikes.
2. **Scan new emails** — `search_channel_workspace` to find recent unprocessed emails in `data/gmail/`.
3. **Categorize each email** — Read the email file, assign a triage category based on sender, subject, and content. Reference `feeds.md` for sender priority overrides.
4. **Update triage.md** — Add a categorized entry for each email (newest first).
5. **Create action cards** — For Urgent and Action Required emails, `create_task_card` with tags `email,{category},from:{sender}` and deadline if identifiable.
6. **Log to timeline** — `append_timeline_event` with "Triaged X emails: Y urgent, Z actions created".
7. **Flag urgent items** — If anything is Urgent, proactively notify the user.

## Action Extraction Patterns

Look for these in email content:
- **Deadlines**: "by Friday", "due March 15", "EOD", "ASAP"
- **Reply requests**: "please respond", "thoughts?", "can you confirm", "RSVP"
- **Approvals**: "approve", "sign off", "authorize", "please review and merge"
- **Meeting invites**: Calendar attachments, "let's schedule", "available for a call"
- **Assignments**: "can you handle", "please take care of", "I need you to"

---

## File Formats

### triage.md — Categorized Email Log

```markdown
## 2026-03-28

| Time | Sender | Subject | Category | Summary |
|------|--------|---------|----------|---------|
| 14:30 | alice@acme.com | Q2 Budget Approval | Urgent | Needs CFO sign-off by EOD Friday |
| 14:15 | bob@partner.io | RE: API Integration | Action Required | Requesting updated spec doc |
| 13:45 | noreply@github.com | PR #142 merged | Projects/Threads | Rate limiting PR merged to main |
| 13:00 | newsletter@tech.com | Weekly Roundup | FYI | Industry news digest |

## 2026-03-27

| Time | Sender | Subject | Category | Summary |
|------|--------|---------|----------|---------|
| 17:00 | carol@team.com | Sprint Retro Notes | Projects/Threads | Action items from retro attached |
| 11:30 | alerts@monitoring.com | CPU Alert Resolved | FYI | Auto-resolved, no action needed |
```

Trim entries older than 2 weeks. Archive to `archive/YYYY-MM/triage.md`.

### tasks.md — Action Item Kanban (Mission Control Format)

Action items extracted from emails, tracked as MC task cards.

```markdown
## Backlog

### Reply: API Integration spec update (bob@partner.io)
- **id**: mc-a1b2c3
- **priority**: medium
- **tags**: email, action-required, from:bob@partner.io
- **due**: 2026-04-01
- source: "RE: API Integration" — 2026-03-28
- action: Send updated API spec document

## In Progress

### Approve: Q2 Budget (alice@acme.com)
- **id**: mc-d4e5f6
- **priority**: critical
- **tags**: email, urgent, from:alice@acme.com
- **due**: 2026-03-29
- **started**: 2026-03-28
- source: "Q2 Budget Approval" — 2026-03-28
- action: Review budget spreadsheet, get CFO sign-off by EOD Friday

## Done

### Reply: Meeting confirmation (carol@team.com)
- **id**: mc-g7h8i9
- **priority**: low
- **tags**: email, action-required, from:carol@team.com
- **completed**: 2026-03-28
- source: "Sprint Retro Scheduling" — 2026-03-27
```

**Card fields:**
- Standard MC fields: id, priority, assigned, tags, due, started, completed
- Email-specific: source (email subject + date), action (what needs to happen)
- Tags: always include `email` + triage category + `from:{sender}`

Use `create_task_card` and `move_task_card` tools — tasks.md is read-only from the database.

### status.md — Inbox Health (Mission Control Format)

```markdown
- **phase**: Active Triage
- **health**: green
- **updated**: 2026-03-28
- **owner**: Email Bot

## Inbox Summary (Last 24h)
- **Processed**: 12 emails
- **Quarantined**: 0
- **Actions created**: 3 task cards
- **Urgent**: 1

## Feed Health

| Source | Status | Last Poll | Processed (24h) | Quarantined (24h) |
|--------|--------|-----------|-----------------|-------------------|
| gmail | healthy | 2026-03-28 14:00 | 12 | 0 |

## Current Focus
- Q2 Budget approval (urgent, due Friday)
- 2 action items pending response

## Blockers
- None currently
```

Health values: `green` (feeds healthy, no quarantine spikes, actions under control), `yellow` (quarantine spike, overdue actions, feed errors), `red` (feed down, many overdue urgents, security concern).

### timeline.md — Activity Log (Mission Control Format)

```markdown
## 2026-03-28

- 14:30 — Triage run: 4 emails processed (1 urgent, 1 action, 1 project, 1 FYI)
- 14:30 — Card mc-d4e5f6 created — "Approve: Q2 Budget" (urgent, due 03-29)
- 14:30 — Card mc-a1b2c3 created — "Reply: API spec update" (medium, due 04-01)
- 08:00 — Triage run: 8 emails processed (0 urgent, 2 actions, 3 projects, 3 FYI)
- 08:00 — Card mc-g7h8i9 moved to **Done** — "Reply: Meeting confirmation"

## 2026-03-27

- 20:00 — Triage run: 5 emails processed (0 urgent, 1 action, 2 projects, 2 FYI)
- 20:00 — Digest regenerated — 17 emails processed today
```

Events are auto-logged by `move_task_card` and status changes. Use `append_timeline_event` for triage run summaries and digest generation.

### digest.md — Email Digest

```markdown
# Email Digest — 2026-03-28

## Urgent / Action Required
- **alice@acme.com** Q2 Budget Approval — needs CFO sign-off by EOD Friday. *Task: mc-d4e5f6*
- **bob@partner.io** RE: API Integration — requesting updated spec doc. *Task: mc-a1b2c3*

## Projects & Threads
- **noreply@github.com** PR #142 merged — rate limiting PR merged to main
- **carol@team.com** Sprint Retro Notes — action items from retro attached

## FYI
- **newsletter@tech.com** Weekly Roundup — industry news digest
- **alerts@monitoring.com** CPU Alert Resolved — auto-resolved, no action needed

## Stats
- Processed: 12 emails | Quarantined: 0 | Actions pending: 2 | Urgent: 1
```

### plans.md — Structured Execution Plans (Read-Only Rendering)

Plans are stored in the MC database. `plans.md` is auto-generated after every state change — never edit it directly. Use `draft_plan` to create plans, and `update_plan_step`/`update_plan_status` for mutations. After approval, the plan executor automatically sequences step execution. Pull the planning skill for the full protocol.

---

## Guidelines

- **Feed health first**: Always run `query_feed_store(action="stats")` before triage to catch quarantine spikes or feed outages
- **Sender context**: Reference `feeds.md` for known senders and priority overrides before categorizing
- **Action → task card**: Every Urgent or Action Required email with a clear action becomes a `create_task_card` with `email` tag and `from:{sender}` tag
- **Timeline logging**: Every triage run gets an `append_timeline_event` summary with counts by category
- **Rolling triage log**: Keep triage.md to ~2 weeks of entries, archive older entries to `archive/YYYY-MM/triage.md`
- **Quarantine review**: If `query_feed_store(action="quarantine")` returns items, review them — they may be legitimate emails flagged by the safety classifier
- **Priority bias**: When in doubt about category, err toward higher priority (Action Required > FYI)
- **Credential safety**: Gmail credentials are configured via Admin → Integrations → Gmail. Never accept credentials in chat.
