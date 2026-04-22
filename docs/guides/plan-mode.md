# Plan Mode

Plan mode is a session-local workflow for turning a chat into an explicit implementation plan before the agent starts editing code.

It is designed for the web chat surfaces, not Slack or Discord. A session can enter plan mode at the start of a conversation or halfway through an existing thread without changing session identity.

## What it does

When a session enters plan mode:

- The runtime marks the session as `planning`
- Every turn gets additional planning instructions injected into model context
- The agent can read/search freely, but file writes are limited to the active plan file
- The active plan is stored as one canonical Markdown document under the session workspace

When the user approves the plan:

- The accepted revision is recorded in session metadata
- The session transitions to `executing`
- The executor works one step at a time
- Completing a step promotes the next pending step automatically
- If a step is blocked or invalidates downstream work, execution stops and the session returns to planning

## Where plans live

Each plan is a single Markdown file under the active session workspace:

`channels/<channel-id>/.sessions/<session-id>/plans/<task-slug>.md`

v1 intentionally keeps one file per task and rewrites it in place instead of introducing version snapshots or a plans table.

## Markdown contract

The source of truth is Markdown, but it is not arbitrary prose. The runtime expects a strict template with a small machine-readable header:

- `Status`
- `Revision`
- `Session`
- `Task`

The body includes:

- title
- summary
- scope / target
- assumptions
- open questions
- execution checklist
- acceptance criteria
- artifacts
- outcome

Checklist items carry stable step ids so progress updates do not depend on matching free-form text.

## Entry points

Plan mode is available in the web chat composer:

- default chat: low-chrome plan control to the left of the model picker
- terminal mode: plan control under the input on the right

It is also available through the shared slash-command executor:

- `/plan` toggles plan mode for the current web session

Slack and Discord still support their own channel/session tooling, but they do not expose this session-local plan-mode workflow.

## Runtime contract

The plan behavior is enforced at the session/runtime layer rather than a skill:

- session mode is the source of truth
- `_load_messages()` injects plan-mode system context every turn
- planning mode blocks non-plan file edits
- approval binds execution to a specific plan revision

This makes plan mode stronger than optional prompt guidance. A dedicated plan skill is not required for correctness.

## Execution model

Execution is supervised and step-scoped:

1. Load the accepted plan revision
2. Pick the next pending step
3. Inject that step plus a short plan summary
4. Execute the step
5. Mark it `done`, `blocked`, `needs_replan`, or `aborted`
6. Update the same Markdown file
7. Continue only when the step completed cleanly

The runner should not free-run an entire long plan in one autonomous pass.

## Widget work and artifacts

Plan mode is especially useful for multi-step widget work because the plan file now records lightweight execution artifacts.

Current widget-related integrations:

- widget bundle versioning records revisions for `widget://bot/...` and `widget://workspace/...`
- active plans can append `widget_revision` artifacts as bundle edits land
- `describe_dashboard` includes `bundle_revision`
- `widget_library_list` surfaces `versioned` and `head_revision`
- bots can inspect history with `widget_version_history`
- bots can roll back a bundle with `rollback_widget_version`

That means a widget implementation plan can capture not just checklist progress, but the bundle revisions it produced along the way.

## Files and services

Key implementation points:

- `app/services/session_plan_mode.py`
- `app/routers/sessions.py`
- `app/services/sessions.py`
- `app/services/slash_commands.py`
- `ui/src/components/chat/useSlashCommandExecutor.ts`
- `ui/src/components/chat/MessageInput.tsx`

For widget revision artifacts, also see:

- `app/services/widget_versioning.py`

## Current scope

Plan mode currently covers:

- web chat sessions
- canonical Markdown plans
- same-session planning and execution
- one-step-at-a-time execution progression
- inline plan status/progress in the same file

It does not yet provide:

- Slack/Discord equivalents for this workflow
- autonomous background execution of an entire plan
- a separate database-backed plan history model
