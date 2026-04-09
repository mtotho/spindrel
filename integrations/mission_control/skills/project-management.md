---
name: project-management
description: >
  Cross-channel project management and portfolio oversight. Load when the user asks
  about project status, wants a status report, needs to track work across multiple
  channels, asks to review or compare projects, wants a dashboard update, asks about
  blockers or action items across projects, or needs to coordinate deliverables.
  Also load when the bot is configured with the Project Management Hub workspace schema,
  or when the user says things like: "what's the status of everything", "give me a
  report", "how are my projects doing", "what's blocked", "compare projects",
  "update the dashboard", "what happened this week across projects".
---

# Project Management — Cross-Channel Operations Guide

You have access to channel workspaces across this bot's projects. Each channel represents
a distinct project or workstream. This skill teaches you how to manage, track, and report
across all of them.

---

## Scope & Configuration

By default, you track **all channels with workspace enabled** for this bot. The user may
narrow scope via the **channel prompt** (channel settings > Prompt tab). Examples:

- "Only track these projects: Henderson Remodel, Auth Rewrite, Brand Refresh"
- "Focus on interior design projects. Ignore software channels."
- "Track everything but generate weekly reports automatically via heartbeat."

If a channel prompt specifies tracked projects, respect that scope — don't pull status from
channels outside the list unless the user explicitly asks. If no scope is specified, default
to all workspace-enabled channels.

The **workspace schema** (Project Management Hub) defines which files to maintain. The
channel prompt defines **what to focus on**. This skill defines **how to operate**.

---

## Your Tools

These are the tools that make cross-channel project management possible:

| Tool | Purpose |
|---|---|
| `list_channels` | Discover all channels with workspace enabled — returns names, IDs, client IDs |
| `search_channel_workspace(query, channel_id=...)` | Search another channel's workspace files (active + archived) |
| `search_channel_archive(query)` | Search archived files in the *current* channel only |
| `file` | Read/write/edit files in the current channel's workspace (preferred over shell) |

### Discovery Pattern

Always start with discovery before reporting:

```
1. list_channels          → get all project channels
2. For each relevant channel:
   search_channel_workspace("status OR progress OR tasks", channel_id=<id>)
3. Synthesize findings into your workspace files
```

---

## Hub Workspace Files

If this channel uses the **Project Management Hub** schema, maintain these files:

### dashboard.md — The Portfolio View

The single most important file. One line per active project, always current.

```markdown
# Project Dashboard

*Last updated: 2025-03-15*

| Project | Channel | Status | Phase | Key Metric | Next Action |
|---|---|---|---|---|---|
| Henderson Remodel | henderson-kitchen | On Track | Execution | 65% complete | Cabinet install Mon |
| Auth Service Rewrite | auth-rewrite | At Risk | Development | 3 blockers | Unblock DB migration |
| Q2 Market Research | q2-research | Complete | Closed | Report delivered | Archive channel |
| Brand Refresh | brand-2025 | On Track | Review | 2 concepts ready | Client review Thu |
```

**Update rules:**
- Update after every status check or report generation
- Status values: `On Track`, `At Risk`, `Blocked`, `On Hold`, `Complete`
- Phase values are project-type dependent (use what makes sense)
- "Next Action" = the single most important next step

### projects.md — The Registry

Detailed reference for each project. Less frequently updated than dashboard.

```markdown
# Project Registry

## Henderson Kitchen Remodel
- **Channel**: henderson-kitchen
- **Channel ID**: a1b2c3d4-...
- **Owner**: Sarah
- **Started**: 2025-01-15
- **Schema**: Creative Project
- **Notes**: High priority, client is detail-oriented
```

### actions.md — Cross-Project Action Items

Items that span projects or need escalation.

```markdown
# Cross-Project Actions

## Blockers
- [ ] DB migration blocked by ops team (affects: auth-rewrite, data-pipeline)
- [ ] Vendor quote pending for Henderson cabinet hardware

## This Week
- [ ] Review auth-rewrite architecture decision
- [ ] Send Q2 research final report to stakeholders
- [ ] Schedule brand refresh client review
```

### reports.md — Status Reports

Append new reports. Archive old ones monthly.

```markdown
# Status Reports

## Week of 2025-03-10

### Summary
- 4 active projects, 1 at risk, 0 blocked
- Henderson on track for March completion
- Auth rewrite needs attention on DB migration

### By Project
...
```

---

## Reporting Workflows

### Quick Status ("How are my projects doing?")

1. `list_channels` — get all channels
2. For each active channel, run `search_channel_workspace("status tasks progress current", channel_id=...)`
3. Scan results for: open tasks, blockers, recent completions, current phase
4. Present a concise summary grouped by status (At Risk first, then On Track)
5. Update `dashboard.md` with fresh data

### Deep Dive ("Tell me about project X")

1. Find the channel ID from `projects.md` or `list_channels`
2. `search_channel_workspace("*", channel_id=...)` — broad search for everything
3. Search for specific concerns: tasks, decisions, blockers, timeline
4. Present findings organized by: current state, recent changes, open items, risks

### Weekly Report

1. Pull status from all active project channels (search each)
2. Compare current state to last report in `reports.md`
3. Identify: what progressed, what's new, what's stalled, what's at risk
4. Generate report in this structure:
   - **Executive summary** (2-3 sentences)
   - **Highlights** (completions, wins)
   - **Risks & blockers** (what needs attention)
   - **By project** (one paragraph each)
   - **Next week priorities**
5. Append to `reports.md`
6. Update `dashboard.md`

### Cross-Project Search ("Where did we discuss X?")

1. `list_channels` — get all channels
2. `search_channel_workspace("<query>", channel_id=...)` for each relevant channel
3. Compile findings with channel attribution:
   - "In **henderson-kitchen**: found in tasks.md — ..."
   - "In **auth-rewrite**: found in decisions.md — ..."

---

## Project Lifecycle

### Starting a New Project

When a new project channel is created:
1. Add it to `projects.md` with full details
2. Add a row to `dashboard.md` with status "New"
3. Note any cross-project dependencies in `actions.md`

### Monitoring Active Projects

On each interaction (or when asked for status):
1. Check which projects haven't been reviewed recently
2. Pull fresh status from those channels
3. Flag anything that looks stale, blocked, or at risk
4. Update `dashboard.md`

### Closing a Project

When a project is done:
1. Update `dashboard.md` status to "Complete"
2. Write a brief retrospective entry in `retrospectives.md`
3. Move the project entry from `projects.md` to `archive/`
4. Capture any lessons learned in `retrospectives.md`

---

## Patterns & Best Practices

### Always Pull Fresh Data

Never report status from memory alone. The workspace files in other channels are the
source of truth. Search them every time you generate a report.

```
# GOOD: Pull live status
search_channel_workspace("tasks status", channel_id="abc-123")

# BAD: Assume your dashboard is current
"Based on the dashboard, the project is on track..."
```

### Attribution Matters

When reporting cross-channel findings, always attribute:
- Which channel/project the information came from
- Which file it was found in
- When it was last updated (if visible)

### Frequency of Updates

- **dashboard.md**: Update every time you check project status
- **actions.md**: Update when new cross-project items emerge
- **reports.md**: Append when user asks for a report, or on a regular cadence
- **projects.md**: Update when project details change (owner, phase, etc.)

### Handling Stale Data

If a project channel's workspace files look stale (no recent updates):
- Flag it explicitly: "Note: henderson-kitchen workspace hasn't been updated in 2 weeks"
- Don't assume the project is stalled — the work may be happening outside the workspace
- Suggest the user check in on that channel

---

## Quick Decision Reference

| Situation | Action |
|---|---|
| User asks "how's everything going?" | Pull status from all channels, summarize, update dashboard |
| User asks about a specific project | Deep dive into that channel's workspace |
| User asks for a report | Generate structured report, append to reports.md |
| User asks "what's blocked?" | Search all channels for "blocked" / "blocker" / "waiting" |
| New project created | Add to projects.md and dashboard.md |
| Project completed | Mark complete, write retrospective, archive |
| User asks to compare projects | Search both channels, present side-by-side |
| Cross-project dependency found | Add to actions.md with affected projects listed |
| Can't find info in workspace | Note the gap, suggest user update the project channel |
