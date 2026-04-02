---
name: "Plan Workflow — Draft, Approve & Execute Structured Plans"
description: >
  Protocol for creating structured execution plans that users review and
  approve in conversation. Use when asked to plan, propose, strategize,
  outline steps, or break down a goal. Covers draft creation, conversational
  approval, automatic step execution, and progress tracking.
---

# SKILL: Plan Workflow

## When to Create a Plan

Create a structured plan when the user:
- Explicitly asks to "plan", "propose", "outline", or "break down" something
- Presents a multi-step goal that would benefit from review before execution
- Asks "how should we tackle this?" or "what's the approach?"
- Describes a complex task with dependencies or risk

**Do NOT plan** trivial single-step tasks. Just do those directly.

## The Conversational Plan Flow

Plans follow a **draft → review → approve → execute** cycle, all within the chat conversation:

### Step 1: Draft the plan

Call `draft_plan` with:
- `channel_id` — the current channel
- `title` — concise, action-oriented (e.g. "Deploy v2 API", "Migrate auth to OAuth2")
- `steps` — ordered list of concrete action items (3-10 steps typical)
- `notes` — optional context, estimates, risks, or rationale
- `approval_steps` — optional list of step positions (1-based) that require human approval mid-execution

### Step 2: Present the plan and ask for approval

After drafting, **immediately present the plan clearly in chat** and ask the user to approve:

```
Here's the plan:

**Set up CI/CD pipeline** (plan-a1b2c3)

1. Configure GitHub Actions workflow
2. Add unit test stage
3. Add integration test stage
4. Set up staging deployment
5. Configure production deployment ⛨ (approval gate)

Notes: Using GitHub Actions. Estimated 2-3 hours.

Want me to go ahead with this, or would you like to change anything?
```

Use a clear, scannable format. Mark approval-gated steps with ⛨ or similar. End with a direct question.

### Step 3: Wait for the user's response

**Do NOT proceed until the user responds.** They may:
- **Approve**: "looks good", "go ahead", "approved", "yes", "do it"
- **Reject**: "no", "scrap it", "never mind", "cancel"
- **Revise**: "change step 3 to...", "add a step for...", "remove the last step"

### Step 4: Act on the response

- **If approved**: Call `update_plan_status(channel_id, plan_id, "approved")` — this starts automatic execution. Confirm to the user: "Plan approved — execution is starting."
- **If rejected**: Call `update_plan_status(channel_id, plan_id, "abandoned")` — confirm: "Plan cancelled."
- **If revision requested**: Call `update_plan_status(channel_id, plan_id, "abandoned")` on the current plan, then draft a new one with the changes and present it again.

## Example

```
User: "Plan out how to set up monitoring for the API"

Bot: [calls draft_plan with title, steps, notes]

Bot: Here's the plan:

**Set up API monitoring** (plan-x1y2z3)

1. Research monitoring options (Prometheus, Datadog, Grafana)
2. Set up health check endpoints
3. Configure alerting thresholds
4. Set up dashboard ⛨ (approval gate — review before deploying)
5. Deploy monitoring stack
6. Verify alerts fire correctly

Notes: Will evaluate Prometheus+Grafana vs Datadog based on existing infra.

Ready to start, or want to adjust anything?

User: "looks good, go ahead"

Bot: [calls update_plan_status(channel_id, plan_id, "approved")]

Bot: Plan approved — execution is starting. I'll work through each step
automatically and update you on progress.
```

## How Execution Works (Automatic)

After approval, the plan executor handles step sequencing automatically:

1. The executor finds the next `pending` step
2. It creates a Task for that step with a system preamble explaining what to do
3. The bot receives the task and executes the step's work
4. When done, the bot calls `update_plan_step(plan_id, step_number, "done")` (or `"failed"`)
5. The executor detects the step completion and advances to the next step
6. If a step has `requires_approval`, the plan pauses at `[awaiting_approval]` — the user can approve the step in the Mission Control dashboard or ask you to resume

**You do NOT need to:**
- Read `plans.md` to find the next step — the executor tells you via the task's system preamble
- Call `schedule_task()` to continue — the executor handles sequencing
- Edit `plans.md` directly — it is auto-generated from the database

### What You Do When Executing a Step

When you receive a step task, the system preamble tells you which step to execute. Follow this protocol:

1. Do the work described in the step
2. Write results to workspace files (e.g. `data/plans/{plan_id}/step-{n}.md`)
3. Call `update_plan_step(plan_id, step_number, "done")` — or `"failed"` if it cannot be completed
4. **Stop.** Do not try to execute the next step or schedule continuation.

### Sharing Context Between Steps

Each step runs in a **fresh context window**. Active workspace files (`.md` at the workspace root) are auto-injected into every request, so they are the primary mechanism for sharing state across steps.

**Write results to workspace files** so future steps can pick up where you left off:
- Step outputs → `data/plans/{plan_id}/step-{n}.md` (not auto-injected, but searchable)
- Key findings, decisions, or artifacts that later steps need → workspace root files (e.g. `architecture.md`, `research-findings.md`)
- Summary of what was done and what the next step should know → update an existing root file or create a new one

**Best practices for context sharing:**
- At the end of each step, write a summary of outcomes and decisions to a root `.md` file (auto-injected into the next step's context)
- For large outputs (code files, raw data), write to `data/` and reference them from a root summary file
- Update `status.md` with progress so the user and future steps have a clear picture
- If a step produces information the next step critically needs, put it in a root file — not just `data/`

## Approval Gates

Steps marked with `approval_steps` in `draft_plan` create pause points during execution:

1. When the executor reaches a gated step, it pauses the plan (`[awaiting_approval]`)
2. The user can approve the step in the Mission Control dashboard, or ask you to resume
3. After approval, the executor creates a task for that step and resumes execution

Use approval gates for high-risk steps (production deployments, irreversible operations, expensive actions).

## Step Status Reference

| Marker | Status | Meaning |
|--------|--------|---------|
| `[ ]` | pending | Not started |
| `[~]` | in_progress | Currently being worked on |
| `[x]` | done | Completed |
| `[-]` | skipped | Intentionally skipped |
| `[!]` | failed | Attempted but could not be completed |

## Handling Issues

- If a step fails, mark it `failed` with `update_plan_step(plan_id, step_number, "failed")` — the executor will advance to the next step
- If a step is blocked by something outside your control, mark it `skipped`
- If the whole plan needs to stop, call `update_plan_status(plan_id, "abandoned")`
- If you need to revise the plan, abandon the current one and draft a new plan

## Anti-patterns

- **Don't execute draft plans** — always present the plan and wait for user approval
- **Don't approve plans silently** — always present the plan first and get explicit user confirmation
- **Don't call `schedule_task()` to continue plan steps** — the plan executor handles sequencing automatically
- **Don't read `plans.md` to find the next step** — the system preamble tells you what to do
- **Don't edit `plans.md` directly** — it is a read-only rendering from the database
- **Don't skip steps silently** — mark them with the appropriate status
- **Don't plan single-step tasks** — just do them
- **Don't create vague steps** — each step should be a concrete, verifiable action
