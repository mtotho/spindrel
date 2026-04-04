---
name: "DevOps (Mission Control)"
description: "Repository management and CI/CD operations with Mission Control task tracking, timeline, and status reporting."
category: workspace_schema
compatible_integrations:
  - mission_control
  - github
mc_min_version: "2.0"
tags:
  - devops
  - github
  - ci
  - deployment
  - pull-requests
  - mission-control
group: "Technical"
recommended_heartbeat:
  prompt: "Check open PRs with github_list_prs(state='open'). Check recent commits with github_list_commits. Update prs.md with current PR status. Log notable activity (merged PRs, deployments, new issues) to timeline via append_timeline_event. Update status.md with repo health. Create task cards for PRs blocked >3 days."
  interval: "daily"
  quiet_start: "20:00"
  quiet_end: "08:00"
---

## Workspace File Organization — DevOps (Mission Control)

Organize channel workspace files to track repository activity and CI/CD operations. This schema is Mission Control compatible — task tracking, status reporting, and activity logging follow the MC protocol.

Root files are living documents injected into every context — keep them concise. Use `archive/` for historical records.

### Root Files (auto-injected)

- **prs.md** — Active pull request tracker (the main operational dashboard)
  - Open PRs with status, reviewers, CI, merge readiness
  - Blocked PRs with reason
  - Recently merged (clean up after ~7 days)

- **status.md** — Repository and pipeline health (Mission Control compatible)
  - Phase/health/owner header block
  - Per-repo status: open PRs, CI health, last deploy
  - Current focus and blockers

- **tasks.md** — Kanban board for DevOps work items (Mission Control compatible)
  - Blocked PRs promoted to task cards (stale >3 days, failing CI, missing reviewers)
  - Infrastructure tasks, release prep, incident action items
  - Use `create_task_card` and `move_task_card` tools

- **timeline.md** — Reverse-chronological activity log (Mission Control compatible)
  - Auto-captures: PR merges, deployments, incidents opened/resolved, task moves
  - Manual entries via `append_timeline_event`: config changes, release decisions, postmortems
  - Entries: `- HH:MM — Event description` grouped under `## YYYY-MM-DD` date headers

- **deployments.md** — Deployment log with rollback reference
  - Current production versions per service
  - Recent deploys: version, environment, changes, rollback instructions
  - Pending releases

- **incidents.md** — Active incident tracker
  - Live incidents with timeline, symptoms, investigation status
  - Root cause analysis when resolved
  - Post-incident action items (promote to tasks.md for tracking)

- **notes.md** — Runbooks, conventions, and reference
  - Branch strategy, CI/CD overview, environment configs

Create files as needed — start with prs.md and status.md, expand as the channel matures.

### Archive (`archive/`)

Searchable historical records. Move merged PRs, resolved incidents, and old deployment entries here monthly.

---

## File Formats

### prs.md — Pull Request Tracker

The main operational file. Updated every heartbeat and on PR events.

```markdown
## Open PRs

### owner/api-server #142 — Add rate limiting middleware
- **author**: alice
- **reviewers**: bob (approved), carol (pending)
- **status**: Review — waiting on carol
- **opened**: 2026-03-25
- **ci**: passing
- **notes**: Needs perf benchmarks before merge

### owner/api-server #139 — Fix auth token refresh race condition
- **author**: bob
- **reviewers**: alice (changes requested)
- **status**: Changes requested — needs rebase
- **opened**: 2026-03-22
- **ci**: failing (test timeout)
- **task_ref**: mc-x1y2z3 (stale >3 days)

## Recently Merged
- 2026-03-27: owner/api-server #138 — Database connection pooling (bob)
- 2026-03-26: owner/web-app #85 — Dark mode support (alice)

*Clean up merged entries older than 7 days.*
```

**Promotion to tasks.md:** PRs blocked >3 days, with failing CI >24h, or missing reviewers get promoted to task cards. Add `task_ref: mc-XXXXXX` in the PR entry for cross-reference.

### status.md — Repository Health (Mission Control Format)

```markdown
- **phase**: Active Development — v2.5.0 cycle
- **health**: green
- **updated**: 2026-03-28
- **owner**: DevOps Team

## Tracked Repos

| Repo | Open PRs | CI Status | Last Deploy | Notes |
|------|----------|-----------|-------------|-------|
| owner/api-server | 3 | passing | 2026-03-27 v2.4.1 | |
| owner/web-app | 1 | passing | 2026-03-28 v1.8.0 | |
| owner/infra | 0 | passing | 2026-03-20 | terraform |

## Current Focus
- Preparing v2.5.0 release for api-server
- Web-app performance optimization PR in review

## Blockers
- PR #139 stale 6 days — auth fix needs rebase

## Recent Milestones
- 2026-03-28: web-app v1.8.0 deployed with dark mode
- 2026-03-27: api-server v2.4.1 — connection pooling fix
```

Health values: `green` (all CI passing, no stale PRs, deploys healthy), `yellow` (failing CI, stale PRs, or pending hotfix), `red` (prod incident, broken deploy, or critical security issue).

### tasks.md — Kanban (Mission Control Format)

For DevOps work items — promoted PRs, infrastructure tasks, incident follow-ups.

```markdown
## Backlog

### Set up alerting on connection pool utilization
- **id**: mc-a1b2c3
- **priority**: medium
- **tags**: monitoring, post-incident
- **due**: 2026-04-15

## In Progress

### Resolve stale PR #139 — auth token race condition
- **id**: mc-x1y2z3
- **priority**: high
- **tags**: pr-blocked, api-server
- **started**: 2026-03-28

## Done

### Deploy api-server v2.4.1 hotfix
- **id**: mc-d4e5f6
- **priority**: critical
- **completed**: 2026-03-27
```

Use `create_task_card` and `move_task_card` tools — tasks.md is read-only from the database.

### timeline.md — Activity Log (Mission Control Format)

```markdown
## 2026-03-28

- 16:00 — Deployed web-app v1.8.0 to prod — dark mode + bundle optimization
- 14:30 — Card mc-x1y2z3 created — "PR #139 stale >3 days, needs rebase"
- 11:00 — PR #142 (rate limiting) — bob approved, waiting on carol
- 09:00 — Heartbeat: 4 open PRs, all CI passing, no incidents

## 2026-03-27

- 17:00 — Deployed api-server v2.4.1 to prod — connection pooling fix
- 15:30 — Card mc-d4e5f6 moved to **Done** — "Deploy v2.4.1 hotfix"
- 14:00 — PR #138 merged — database connection pooling (bob)
- 10:00 — INC-012 resolved — API latency spike, pool exhaustion
```

Events are auto-logged by `move_task_card` and status changes. Use `append_timeline_event` for deployments, PR merges, incidents, and release decisions.

### deployments.md — Deployment Log

```markdown
## Current Production Versions

| Service | Version | Deployed | Environment |
|---------|---------|----------|-------------|
| api-server | v2.4.1 | 2026-03-27 | prod |
| web-app | v1.8.0 | 2026-03-28 | prod |

## Recent Deployments

### 2026-03-28 — web-app v1.8.0 → prod
- **deployed by**: carol
- **changes**: Dark mode, bundle optimization
- **rollback**: v1.7.2 — `git revert && deploy`
- **status**: healthy

## Pending Releases
- api-server v2.5.0 — awaiting PR #142 merge
```

### plans.md — Structured Execution Plans (Read-Only Rendering)

Plans are stored in the MC database. `plans.md` is auto-generated after every state change — never edit it directly. Use `draft_plan` to create plans, and `update_plan_step`/`update_plan_status` for mutations. After approval, the plan executor automatically sequences step execution. Pull the planning skill for the full protocol.

### Guidelines

- **PR tracking**: Refresh with `github_list_prs(state="open")`. Diffs via `github_get_pr(repo, number)` (truncated at 50K chars).
- **Promotion**: PRs blocked >3 days → `create_task_card` with tags `pr-blocked,{repo}`. Add `task_ref` in prs.md.
- **Deployments**: Log every production deploy with version, changes, and rollback instructions. `append_timeline_event` for the timeline.
- **Incidents**: Use incidents.md as a live doc during incidents. Post-incident action items → task cards.
- **Branch comparison**: `github_compare(repo, base, head)` for release diffs.
- **Archive**: Move merged PRs, resolved incidents, and old deployments to `archive/` monthly.
