---
name: "Plan Workflow — Draft, Approve & Execute Structured Plans"
description: >
  Protocol for creating structured execution plans that users review and
  approve in Mission Control. Use when asked to plan, propose, strategize,
  outline steps, or break down a goal. Covers draft creation, approval,
  step-by-step execution, and progress tracking.
---

# SKILL: Plan Workflow

## When to Create a Plan

Create a structured plan when the user:
- Explicitly asks to "plan", "propose", "outline", or "break down" something
- Presents a multi-step goal that would benefit from review before execution
- Asks "how should we tackle this?" or "what's the approach?"
- Describes a complex task with dependencies or risk

**Do NOT plan** trivial single-step tasks. Just do those directly.

## Drafting a Plan

Call `draft_plan` with:
- `channel_id` — the current channel
- `title` — concise, action-oriented (e.g. "Deploy v2 API", "Migrate auth to OAuth2")
- `steps` — ordered list of concrete action items (3-10 steps typical)
- `notes` — optional context, estimates, risks, or rationale

```
draft_plan(
  channel_id="...",
  title="Set up CI/CD pipeline",
  steps=[
    "Configure GitHub Actions workflow",
    "Add unit test stage",
    "Add integration test stage",
    "Set up staging deployment",
    "Configure production deployment with approval gate"
  ],
  notes="Using GitHub Actions. Estimated 2-3 hours."
)
```

This creates the plan as `[draft]` in `plans.md` and logs it to the timeline.

## What Happens After Drafting

The plan appears in the Mission Control dashboard with **Approve** and **Reject** buttons. The user reviews the steps, then:

- **Approves** — the plan transitions to `[approved]`, and a message is sent to the channel triggering execution
- **Rejects** — the plan transitions to `[abandoned]`

**Do NOT execute draft plans.** Wait for approval.

## Executing an Approved Plan

After approval, `plans.md` shows the plan as `[executing]` (or `[approved]` — treat both as ready to execute). **Execute ONE step per run, then self-schedule continuation.**

### Per-Step Protocol

1. Read plans.md — find the next `[ ]` pending or `[~]` in_progress step
2. Call `update_plan_step(plan_id, step_number, "in_progress")`
3. Do the work for that step
4. Write results to workspace files (e.g. `data/plans/{plan_id}/step-{n}.md`)
5. Call `update_plan_step(plan_id, step_number, "done")` — or `"failed"` if it cannot be completed
6. Check if more steps remain:
   - **Yes** → call `schedule_task()` to continue (see Self-Continuation below)
   - **No** → plan auto-completes when all steps are done/skipped/failed

### Self-Continuation

After completing a step, if pending steps remain, schedule the next iteration:

```
schedule_task(
  prompt="Continue executing plan '{title}' ({plan_id}). Pick up from the next pending step.",
  title="Plan: {title} — next step"
)
```

This gives each step a **fresh context window** with workspace files as ground truth. The plan file itself is the state machine — each iteration reads it, finds the next step, and executes it.

### Context Dumping

Write intermediate results to workspace files so future steps (and the user) can reference them:
- Step outputs → `data/plans/{plan_id}/step-{n}.md`
- Shared artifacts → workspace root (e.g. `architecture.md`, `tasks.md`)

This prevents context bloat and ensures results persist across step boundaries.

## Step Status Reference

| Marker | Status | Meaning |
|--------|--------|---------|
| `[ ]` | pending | Not started |
| `[~]` | in_progress | Currently being worked on |
| `[x]` | done | Completed |
| `[-]` | skipped | Intentionally skipped |
| `[!]` | failed | Attempted but could not be completed |

## Progress Reporting

- Step completions are auto-logged to the timeline
- For significant milestones, also use `append_timeline_event`
- If a step takes multiple turns, keep the user informed of progress

## Handling Issues

- If a step fails, mark it `failed` with `update_plan_step(plan_id, step_number, "failed")` and continue to the next step
- If a step is blocked by something outside your control, mark it `skipped` with `[-]`
- If the whole plan needs to stop, call `update_plan_status(plan_id, "abandoned")`
- If you need to revise the plan, abandon the current one and draft a new plan

## Anti-patterns

- **Don't execute draft plans** — always wait for user approval
- **Don't skip steps silently** — mark them with `[-]` skipped or `[!]` failed status
- **Don't plan single-step tasks** — just do them
- **Don't create vague steps** — each step should be a concrete, verifiable action
- **Don't try to do everything in one run** — execute one step, dump context, self-schedule the next
