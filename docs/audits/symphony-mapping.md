---
title: Symphony Mapping
summary: Spindrel-native mapping from Symphony concepts to existing Project, workflow, harness, run, and receipt primitives.
status: reference
tags: [spindrel, projects, symphony, workflow]
created: 2026-05-03
updated: 2026-05-03
---

# Symphony Mapping

Spindrel uses Symphony as an inspiration and checklist, not as a strict
compatibility target. The goal is the same operational shape: a repo-owned
workflow contract, explicit run state, isolated execution, durable evidence,
and agent-readable status. The implementation stays native to Spindrel's
Project, task, harness, and receipt primitives.

## Mapping

| Symphony concept | Spindrel equivalent | Status | Notes |
|---|---|---|---|
| `WORKFLOW.md` | `.spindrel/WORKFLOW.md` | met | Project-local policy file for artifacts, intake, runs, hooks, dependencies, and repo-specific instructions. |
| Workflow loader | `app/services/project_workflow_file.py` | met | Parses permissive frontmatter and level-2 sections from the canonical repo. |
| Config layer | `GET /api/v1/projects/{id}/orchestration-policy` and `get_project_orchestration_policy` | spindrel-native | Merges Blueprint policy, live concurrency, timeouts, intake config, canonical repo, and `## Policy`. |
| Orchestrator state | `GET /api/v1/projects/{id}/factory-state` and `get_project_factory_state` | spindrel-native | Stage-aware read model for setup, planning, active runs, review, and blockers. |
| Issue / work item source | `docs/inbox.md`, `docs/tracks/*.md`, `docs/plans/*.md`, `.spindrel/prds/*`, or external trackers | spindrel-native | Repo or tracker artifacts are canonical; Spindrel records coordination state and execution state. |
| Run pack | file-resident source artifact plus optional Project coding run launch | spindrel-native | `propose_run_packs` writes markdown proposals; launched runs carry `source_artifact`. |
| Workspace manager | Project WorkSurface plus session execution environments | met | Formal runs use assigned cwd/worktree, branch, dev targets, and private Docker daemon when provided. |
| Agent runner | Harness-backed Project coding runs | met | Codex/Claude native tools own edits and repo-local commands; Spindrel owns orchestration and receipts. |
| Live session / run detail | Project Runs APIs and UI | met | Run rows expose lifecycle, queue state, work surface, source artifact, receipt, and review context. |
| Observability | factory-state, orchestration-policy, run detail, activity log, receipts | spindrel-native | No separate hidden orchestration ledger is required. |
| Continuation logic | Project coding-run continuations and bounded loop receipts | met | Receipt `loop_decision` controls continue/done/needs_review/blocked. |
| Hook scripts | `## Hooks` in `.spindrel/WORKFLOW.md` | deferred | Agents may run documented hook commands manually. Add a typed hook runner only after a concrete run needs repeatability. |
| External tracker polling | GitHub/Linear/etc. integration or repo-local files | not applicable | Spindrel does not require Linear-style polling; projects choose their canonical tracker or repo artifacts. |

## Operating Decisions

- `.spindrel/WORKFLOW.md` is the only Project workflow contract. There is no
  root `WORKFLOW.md` requirement and no `.spindrel/project-runbook.md`
  compatibility file.
- Runtime `skills/project/*` are generic fallback recipes. Repo-specific
  policy in `.spindrel/WORKFLOW.md` wins.
- Spindrel may write `.spindrel/WORKFLOW.md` only through explicit starter
  creation when the file is absent. It must not silently rewrite repo-owned
  policy.
- Strict Symphony endpoint compatibility is out of scope. Future work should
  cite this mapping before adding new orchestration surfaces.
