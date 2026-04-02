---
category: workspace_schema
description: DevOps and repository management — PR tracking, CI/CD status, deployment logs, and incident response.
compatible_integrations: github
tags: devops, github, ci, deployment
---
## Workspace File Organization — DevOps

Organize channel workspace files as follows:

- **repos.md** — Tracked repositories: names, purposes, branch strategies, CI status
- **prs.md** — Active pull requests: status, reviewers, blockers, merge readiness
- **deployments.md** — Recent deployments: versions, environments, rollback notes
- **incidents.md** — Active incidents: symptoms, investigation status, resolution steps
- **notes.md** — Runbooks, environment configs, team conventions, useful commands

### Guidelines
- Track open PRs in prs.md with reviewer assignments and blocker notes
- Log deployments with version numbers and environment targets for rollback reference
- Use incidents.md as a live incident response doc — timeline, actions taken, root cause
- Keep repos.md as a high-level index of what's tracked and why
- Archive merged PRs, resolved incidents, and old deployment logs to the archive/ folder
