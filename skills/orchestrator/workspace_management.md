---
name: Workspace Management
id: shared/orchestrator/workspace-management
description: >
  Channel and workspace operating conventions, including safe memory writes,
  workspace prompt overrides, and orchestration checklists.
triggers: channel management, workspace management, safe memory writes, workspace prompt override, channel conventions, orchestration checklist
category: core
---

# Workspace Management

## Channels

A channel is a persistent conversation container tied to a bot. Each channel has:

- its own conversation history
- its own workspace files
- per-channel settings such as model overrides, enrolled skills, and tool availability
- optional heartbeat or scheduled work

Use channels as the primary unit of project context.

## Memory write patterns

Your workspace files persist across sessions. Preserve them carefully.

### Append for logs and rolling memory

Use append-style writes for daily logs and cumulative memory files.

### Atomic replacement for rewrites

When a file must be replaced entirely, write a temporary file and rename it.

### Targeted edits for small changes

Read, modify, and write back only the fields you intend to change.

## Prompt layers

`common/prompts/base.md` is only relevant when the workspace base-prompt override is enabled.
It does not replace the bot's main system prompt; it fills one optional template layer.

`bots/<bot-id>/persona.md` can override persona text for workspace bots when persona-file mode is enabled.

## Secrets

Use secret storage for anything sensitive:

- API keys
- passwords
- webhook secrets
- tokens

Use regular env vars only for non-sensitive configuration.

## Orchestrator checklist

Before starting:

- confirm API scopes
- place shared inputs in `/workspace/common/`
- make delegated prompts self-contained
- verify write access for target paths

During execution:

- watch task status or wait for callbacks
- inspect shared outputs before synthesizing
- retry with refined prompts when needed

After completion:

- summarize results for the requesting channel
- persist durable facts in workspace memory
- remove temporary artifacts if they are no longer useful
