# WorkSurface Isolation

This guide is the security model for Spindrel file, context, search, widget, exec, and harness boundaries.

## Boundary Model

Every turn/tool should resolve to exactly one `WorkSurface` before touching files or execution:

- `channel` — a lightweight channel-only surface for casual workflows.
- `project` — a shared Project root intentionally visible to channels bound to that Project.
- `project_instance` — a fresh Project-instance root for isolated runs.

Project-bound channels share Project files, search results, context admission, and default execution cwd. Fresh Project instances are the isolation mechanism when a run should not mutate shared Project state.

Bot-private state is separate from the WorkSurface:

- memory files
- credentials and API keys
- auth/session state
- bot-authored skills unless explicitly published

## Required Policy

All high-impact resource paths must go through `app.services.projects.WorkSurface` or a small wrapper around it:

- file reads/writes/lists/globs/greps
- channel and Project search/index roots
- context admission for workspace files and Project prompts
- shell/script/deferred exec cwd
- native harness cwd and Project runtime hints
- widget bundle/database paths that depend on channel or Project provenance

Do not add a new direct call to `workspace_service.get_workspace_root()`, `channel_workspace.get_channel_workspace_root()`, or `shared_workspace_service.get_host_root()` in a production path unless the code is deliberately handling bot-private state or implementing the WorkSurface resolver itself.

## Operator Capabilities

Cross-boundary autonomous access must be explicit. Channel WorkSurface access is now participant-based:

- a channel's primary bot may access the channel WorkSurface
- bots listed as `ChannelBotMember` participants may access it
- nonparticipants are denied even if stale `cross_workspace_access` metadata exists
- file, search, and history boundary decisions emit durable `worksurface_boundary_*` trace events

Logs are not enough for this class of behavior. Logging is supporting evidence; the product surface should show recent operator boundary crossings.

## Secrets

Execution surfaces receive secrets only through explicit bindings:

- Project runtime secret bindings
- per-bot allowed secret lists
- integration-specific credentials scoped to that integration path

The global Secret Values vault is not an ambient environment for every subprocess. Redaction is defense-in-depth only; it does not make broad secret injection safe.

## Current Findings

The static audit at `app.services.worksurface_isolation_audit` intentionally reports these known gaps until they are remediated:

- `harness_workdir` can bypass a resolved WorkSurface and should be treated as operator-target config
- `widget://workspace` is shared-workspace scoped and still needs a policy decision: shared library or WorkSurface-published asset

Remediated findings:

- shared workspace subprocess execution no longer injects every Secret Value by default; it only uses `current_allowed_secrets` plus explicit Project runtime `extra_env`
- legacy `cross_workspace_access` no longer authorizes sibling-channel WorkSurface access; channel files, channel search, history reads, and channel listing now use primary/member participation

## External Baseline

This model follows the same broad pattern used by current agent platforms:

- OpenClaw treats the agent workspace as the default cwd/home and documents that sandboxing is a separate enforcement layer.
- Codex separates sandbox boundaries from approval policy and defaults local agents toward workspace-write/no-network constraints.
- Claude Code and GitHub Copilot cloud agents emphasize restricted credentials, bounded execution, human review, and auditable sessions.

Sources checked 2026-04-30:

- <https://docs.openclaw.ai/concepts/agent-workspace>
- <https://docs.openclaw.ai/gateway/sandboxing>
- <https://developers.openai.com/codex/concepts/sandboxing>
- <https://developers.openai.com/codex/agent-approvals-security>
- <https://code.claude.com/docs/en/security>
- <https://docs.github.com/en/copilot/concepts/agents/cloud-agent/risks-and-mitigations>
