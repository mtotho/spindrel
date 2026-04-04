---
name: "IT Helpdesk"
description: "IT support queue management — ticket tracking, SLA monitoring, knowledge base, and escalation workflows."
category: workspace_schema
compatible_integrations:
  - mission_control
mc_min_version: "2.0"
tags:
  - helpdesk
  - it-support
  - tickets
  - sla
  - mission-control
group: "Technical"
recommended_heartbeat:
  prompt: "Review the ticket queue in tasks.md. Check for SLA breaches (tickets approaching or past response/resolution deadlines). Update status.md with queue health, SLA compliance, and current load. Flag any P1/P2 tickets needing escalation. Log activity to timeline."
  interval: "daily"
  quiet_start: "20:00"
  quiet_end: "07:00"
---

## Workspace File Organization — IT Helpdesk

Organize channel workspace files to manage IT support requests and incidents. This schema is Mission Control compatible — ticket tracking, status reporting, and activity logging follow the MC protocol.

Root files are living documents injected into every context — keep them concise.

### Root Files (auto-injected)

- **tasks.md** — Ticket queue kanban (Mission Control compatible)
  - Support tickets as task cards flowing through resolution stages
  - Each card: requester, category, SLA tier, symptoms, resolution steps
  - Use `create_task_card` and `move_task_card` tools

- **status.md** — Queue health and SLA compliance (Mission Control compatible)
  - Phase/health/owner header block
  - Queue summary: tickets per stage, SLA compliance %
  - Current load and staffing
  - Trending issues and known outages

- **knowledge.md** — Knowledge base for common issues
  - Categorized solutions: `### KB-NNN: Title`
  - Symptoms, diagnostic steps, resolution, prevention
  - Link to tickets that used this solution

- **escalation.md** — Escalation paths and on-call roster
  - Tier definitions (L1 → L2 → L3 → vendor)
  - On-call schedule and contact info
  - Escalation criteria per SLA tier
  - Vendor support contacts and contract details

- **timeline.md** — Reverse-chronological activity log (Mission Control compatible)
  - Auto-captures: ticket creation, stage changes, SLA breaches, resolutions
  - Manual entries: outages, maintenance windows, escalation decisions
  - Entries: `- HH:MM — Event description` grouped under `## YYYY-MM-DD` date headers

- **notes.md** — Shift handoff notes, maintenance schedules, and scratch space

Create files as needed — start with tasks.md and knowledge.md.

### Archive (`archive/`)

Resolved tickets, old shift notes, completed maintenance. Searchable via `search_channel_archive`.

---

## File Formats

### tasks.md — Ticket Queue Kanban (Mission Control Format)

Queue stages as kanban columns. Each ticket is a task card.

```markdown
## New

### TKT: Outlook not syncing on mobile
- **id**: mc-a1b2c3
- **priority**: medium
- **tags**: email, mobile, outlook
- **assigned**: unassigned
- requester: Sarah Johnson (Marketing)
- sla_tier: P3 (standard)
- sla_response_by: 2026-03-28 16:00
- reported: 2026-03-28 10:30
- symptoms: Outlook mobile app shows "last synced 2 days ago", push notifications stopped

### TKT: VPN connection drops every 30 minutes
- **id**: mc-d4e5f6
- **priority**: high
- **tags**: vpn, network, remote
- **assigned**: unassigned
- requester: Mike Chen (Engineering)
- sla_tier: P2 (elevated)
- sla_response_by: 2026-03-28 13:00
- reported: 2026-03-28 11:00
- symptoms: GlobalProtect VPN disconnects every ~30 min, requires manual reconnect

## Triaged

### TKT: New hire laptop setup — Alex Rivera
- **id**: mc-g7h8i9
- **priority**: medium
- **tags**: onboarding, laptop, setup
- **assigned**: Lisa (L1)
- **started**: 2026-03-28
- requester: HR (onboarding)
- sla_tier: P3 (standard)
- sla_resolve_by: 2026-04-01
- checklist: OS image ✓, domain join ✓, VPN pending, apps pending

## In Progress

### TKT: Shared drive permissions broken for Finance team
- **id**: mc-j0k1l2
- **priority**: high
- **tags**: permissions, file-share, finance
- **assigned**: Tom (L2)
- **started**: 2026-03-27
- requester: CFO Office
- sla_tier: P2 (elevated)
- sla_resolve_by: 2026-03-29
- symptoms: Finance team lost write access to \\server\finance$ after AD migration
- investigation: AD group membership looks correct, checking NTFS inheritance

## Waiting

### TKT: Printer jamming on 3rd floor — HP LaserJet
- **id**: mc-m3n4o5
- **priority**: low
- **tags**: printer, hardware, vendor
- **assigned**: Lisa (L1)
- **started**: 2026-03-25
- requester: Operations
- sla_tier: P4 (low)
- status: Waiting on vendor — HP service ticket #HP-2026-5678, ETA April 2

## Resolved

### TKT: Password reset — Bob Wilson
- **id**: mc-p6q7r8
- **priority**: low
- **tags**: password, account
- **completed**: 2026-03-28
- resolution: Reset via AD, confirmed login, reminded about self-service portal
- time_to_resolve: 15 min
```

**Queue stages:**
- **New** — Submitted, not yet reviewed
- **Triaged** — Reviewed, assigned, priority set
- **In Progress** — Actively being worked on
- **Waiting** — Blocked on user, vendor, or external dependency
- **Resolved** — Fixed, confirmed with requester (archive after 14 days)

**Card fields:**
- Standard MC fields: id, priority, assigned, tags, started, completed
- Helpdesk-specific: requester, sla_tier, sla_response_by, sla_resolve_by, reported, symptoms, investigation, resolution, time_to_resolve, checklist

Use `create_task_card` and `move_task_card` tools — tasks.md is read-only from the database.

### SLA Tiers

| Tier | Response Time | Resolution Target | Examples |
|------|-------------|------------------|----------|
| **P1** (critical) | 30 min | 4 hours | System outage, security breach, data loss |
| **P2** (elevated) | 2 hours | 24 hours | Service degraded, team blocked, VPN down |
| **P3** (standard) | 8 hours | 3 business days | Individual issue, software install, access request |
| **P4** (low) | 24 hours | 5 business days | Nice-to-have, cosmetic, non-urgent hardware |

### status.md — Queue Health (Mission Control Format)

```markdown
- **phase**: Normal Operations
- **health**: yellow
- **updated**: 2026-03-28
- **owner**: IT Support Team

## Queue Summary

| Stage | Tickets | P1/P2 | SLA At Risk |
|-------|---------|-------|-------------|
| New | 2 | 1 | 1 (VPN — P2 response due 13:00) |
| Triaged | 1 | 0 | 0 |
| In Progress | 1 | 1 | 1 (File share — resolve by 03-29) |
| Waiting | 1 | 0 | 0 |
| **Active Total** | **5** | **2** | **2** |

## SLA Compliance (Last 30 Days)
- **Response SLA**: 94% (target: 95%) — 1 P3 breached last week
- **Resolution SLA**: 91% (target: 90%) — on target
- **MTTR**: 4.2 hours (P1/P2), 18 hours (P3/P4)

## Trending Issues
- VPN disconnects: 3 reports this week — possible infrastructure issue
- Outlook mobile sync: 2 reports — may be related to recent Exchange update

## Current Load
- Active tickets: 5
- Resolved today: 3
- On shift: Lisa (L1), Tom (L2)

## Blockers
- Finance file share (P2) — may need AD team escalation if inheritance fix doesn't hold
```

Health values: `green` (SLA on target, no P1/P2 breaches), `yellow` (SLA at risk, P2 nearing deadline), `red` (P1 active, SLA breached, or widespread outage).

### knowledge.md — Knowledge Base

```markdown
## Account & Access

### KB-001: Password Reset (Self-Service)
- **symptoms**: User locked out, password expired, forgot password
- **resolution**: Direct to self-service portal (https://reset.company.com). If SSO, reset via Okta admin. If AD-only, reset via AD Users & Computers.
- **prevention**: Remind users about self-service portal, enable password expiry notifications
- **used_by**: TKT mc-p6q7r8, mc-w2x3y4

### KB-002: VPN Connection Issues
- **symptoms**: GlobalProtect won't connect, frequent disconnects, slow VPN
- **diagnostic steps**:
  1. Check internet connectivity (can they reach google.com?)
  2. Verify GlobalProtect client version (must be ≥6.1)
  3. Try alternate VPN gateway (us-east vs us-west)
  4. Check for split-tunnel conflicts (corporate vs personal VPN)
  5. Collect logs: GlobalProtect > Settings > Troubleshooting > Collect Logs
- **resolution**: Usually outdated client or gateway issue. If persistent, escalate to L2 (network team).
- **prevention**: Auto-update policy for GlobalProtect client

## Email & Communication

### KB-003: Outlook Mobile Sync Failure
- **symptoms**: Outlook mobile shows stale data, push notifications stopped
- **diagnostic steps**:
  1. Force quit and reopen Outlook app
  2. Check account status in Outlook > Settings > Account
  3. Remove and re-add account if status shows "error"
  4. Verify Exchange ActiveSync is enabled for user in admin portal
- **resolution**: Usually resolved by re-adding account. If widespread, check Exchange health.
```

### escalation.md — Escalation Paths

```markdown
## Tier Definitions

| Tier | Scope | Contact |
|------|-------|---------|
| **L1** (Helpdesk) | Password resets, basic troubleshooting, known issues | helpdesk@company.com |
| **L2** (Specialist) | Network, AD, Exchange, endpoint management | Slack #it-escalations |
| **L3** (Engineering) | Infrastructure, security, custom apps | Slack #it-engineering |
| **Vendor** | Hardware warranty, SaaS provider issues | See vendor contacts below |

## Escalation Criteria
- **L1 → L2**: Issue not in knowledge base, requires admin access, or L1 spent >30 min without progress
- **L2 → L3**: Infrastructure-level issue, security concern, or requires code/config change
- **→ Vendor**: Hardware failure, SaaS outage, license issue

## On-Call Schedule
- **This week**: Tom (L2 primary), Sarah (L2 backup)
- **After hours**: PagerDuty rotation — P1 only

## Vendor Contacts
- **HP (printers/laptops)**: 1-800-xxx-xxxx, contract #HP-ENT-2026
- **Microsoft (365/Azure)**: Premier support portal, TAM: John Doe
- **Palo Alto (VPN)**: support.paloaltonetworks.com, case #PA-12345
```

### timeline.md — Activity Log (Mission Control Format)

```markdown
## 2026-03-28

- 14:00 — SLA warning: mc-d4e5f6 (VPN disconnect, P2) approaching response deadline
- 11:30 — Card mc-p6q7r8 moved to **Resolved** — "Password reset — Bob Wilson" (15 min)
- 11:00 — New tickets: mc-a1b2c3 (Outlook sync, P3), mc-d4e5f6 (VPN drops, P2)
- 09:00 — Heartbeat: 5 active tickets, 2 P2, SLA compliance 94%/91%

## 2026-03-27

- 16:30 — Finance file share (mc-j0k1l2) escalated L1 → L2 — AD permission inheritance issue
- 14:00 — Card mc-g7h8i9 moved to **Triaged** — "New hire laptop setup"
- 10:00 — Trending: 3rd VPN disconnect report this week — investigating pattern
```

Events are auto-logged by `move_task_card` and status changes. Use `append_timeline_event` for SLA breaches, escalations, outages, and maintenance windows.

### plans.md — Structured Execution Plans (Read-Only Rendering)

Plans are stored in the MC database. `plans.md` is auto-generated after every state change — never edit it directly. Use `draft_plan` to create plans, and `update_plan_step`/`update_plan_status` for mutations. After approval, the plan executor automatically sequences step execution. Pull the planning skill for the full protocol.

---

## Guidelines

- **Triage immediately**: New tickets should be triaged (assigned priority, category, owner) within SLA response time.
- **SLA tracking**: Set `due` to the SLA resolution deadline. Heartbeat flags approaching/breached SLAs.
- **Knowledge base first**: Before investigating, check knowledge.md for known solutions. Link KB articles to tickets.
- **Escalation protocol**: Follow the tier definitions in escalation.md. Log escalations to timeline via `append_timeline_event`.
- **Waiting state**: When blocked on user or vendor, move to Waiting with a clear note on what's expected and when.
- **Resolution documentation**: When resolving, always record the fix in the card. Update knowledge.md if this is a new pattern.
- **Trending detection**: If 3+ tickets share a symptom within a week, flag it as a trending issue in status.md.
- **Tool reference**: `create_task_card` (new ticket), `move_task_card` (stage change), `append_timeline_event` (escalations, outages, SLA breaches).
