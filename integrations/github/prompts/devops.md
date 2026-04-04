---
name: "DevOps"
category: workspace_schema
description: DevOps and repository management — PR tracking, CI/CD status, deployment logs, and incident response.
compatible_integrations:
  - github
tags: devops, github, ci, deployment, pull-requests
recommended_heartbeat:
  prompt: "Check open PRs with github_list_prs(state='open'). Check recent commits with github_list_commits. Update prs.md with current status. Log any notable activity (merged PRs, new issues, deployments) to activity.md. Update status.md with repo health."
  interval: "daily"
  quiet_start: "20:00"
  quiet_end: "08:00"
---

## Workspace File Organization — DevOps

Organize channel workspace files to track repository activity and CI/CD operations. Root `.md` files are injected into every context — keep them concise and current.

### Root Files (auto-injected)

- **status.md** — Repository and pipeline health overview
  - Per-repo status: open PRs, recent activity, CI health
  - Current focus (release in progress, hotfix, feature branch)
  - Blockers and degradations

- **prs.md** — Active pull request tracker
  - Open PRs with status, reviewers, merge readiness
  - Blocked PRs with reason
  - Recently merged (clean up after ~7 days)

- **deployments.md** — Deployment log
  - Recent deployments: version, environment, status, rollback notes
  - Current production version per service
  - Pending releases

- **incidents.md** — Active incident tracker
  - Live incidents with timeline, symptoms, investigation status
  - Root cause analysis when resolved
  - Post-incident action items

- **notes.md** — Runbooks, conventions, and reference
  - Branch strategy (trunk-based, gitflow, etc.)
  - CI/CD pipeline overview
  - Environment configs and access
  - Team conventions and useful commands

### Archive (`archive/`)

Merged PRs, resolved incidents, old deployment logs. Searchable via `search_channel_archive`.

---

## File Formats

### status.md — Repository Health

```markdown
## Repository Health
- **status**: Active Development
- **updated**: 2026-03-28
- **owner**: DevOps Team

## Tracked Repos

| Repo | Open PRs | CI Status | Last Deploy | Notes |
|------|----------|-----------|-------------|-------|
| owner/api-server | 3 | passing | 2026-03-27 v2.4.1 | |
| owner/web-app | 1 | passing | 2026-03-28 v1.8.0 | |
| owner/infra | 0 | passing | 2026-03-20 | terraform only |

## Current Focus
- Preparing v2.5.0 release for api-server
- Web-app performance optimization PR in review

## Blockers
- None currently
```

### prs.md — Pull Request Tracker

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
- **notes**: Race condition in token refresh — alice flagged edge case

### owner/web-app #87 — Optimize bundle size
- **author**: carol
- **reviewers**: alice (approved)
- **status**: Ready to merge
- **opened**: 2026-03-27
- **ci**: passing

## Recently Merged
- 2026-03-27: owner/api-server #138 — Database connection pooling (bob)
- 2026-03-26: owner/web-app #85 — Dark mode support (alice)

*Clean up merged entries older than 7 days.*
```

### deployments.md — Deployment Log

```markdown
## Current Production Versions

| Service | Version | Deployed | Environment |
|---------|---------|----------|-------------|
| api-server | v2.4.1 | 2026-03-27 | prod |
| web-app | v1.8.0 | 2026-03-28 | prod |
| infra | tf-2026-03-20 | 2026-03-20 | prod |

## Recent Deployments

### 2026-03-28 — web-app v1.8.0 → prod
- **deployed by**: carol
- **changes**: Dark mode, bundle optimization
- **rollback**: v1.7.2 — `git revert && deploy`
- **status**: healthy

### 2026-03-27 — api-server v2.4.1 → prod
- **deployed by**: bob
- **changes**: Connection pooling, minor bugfixes
- **rollback**: v2.4.0 — revert migration required
- **status**: healthy

## Pending Releases
- api-server v2.5.0 — awaiting rate limiting PR (#142) merge
```

### incidents.md — Incident Tracker

```markdown
## Active Incidents

*No active incidents.*

## Recent Incidents

### INC-012: API latency spike — 2026-03-26
- **severity**: P2 (degraded performance)
- **detected**: 2026-03-26 14:30
- **resolved**: 2026-03-26 16:15
- **duration**: 1h 45m
- **symptoms**: P99 latency > 2s on /api/v1/search
- **root cause**: Connection pool exhaustion under load — max connections too low
- **fix**: Increased pool size, added connection timeout. Deployed in v2.4.1.
- **action items**:
  - [x] Add connection pool metrics to dashboard
  - [ ] Set up alerting on pool utilization > 80%
```

### Guidelines

- **PR tracking**: Update prs.md when PRs open, get reviewed, or merge. Use `github_list_prs(state="open")` to refresh.
- **Deployment logging**: Log every production deploy with version, changes, and rollback instructions
- **Incident response**: Use incidents.md as a live doc during incidents — timeline everything, root cause after resolution
- **CI status**: Note failing CI in PR entries with the specific failure reason
- **Diff review**: `github_get_pr(repo, number)` for full diff. Diffs truncated at 50K chars.
- **Branch comparison**: `github_compare(repo, base, head)` to see what's in a release branch
- **Archive**: Move merged PRs, resolved incidents, and old deployment entries to `archive/` monthly
