# Shared: MCP-bridged Spindrel runtime tool catalog

Catalog of Spindrel runtime tools that an in-spindrel agent (Codex/Claude
running inside a Project coding-run) can typically reach through the MCP
bridge. **Descriptive, not prescriptive** — different Project bindings expose
different subsets, so always treat each tool as "if available." If a needed
tool isn't in the agent's surface, fall back to the HTTP API per
[`api-access.md`](api-access.md).

For local-CLI repo-dev mode, none of these tools are available; use the
matching HTTP endpoints instead.

## Channels & sessions

| Tool | Purpose |
|---|---|
| `list_channels` | Enumerate channels visible to the agent's binding. |
| `read_conversation_history` | Recent primary-session conversation in one channel. |
| `list_sub_sessions` | Scratch / sub-session inventory under a channel or project. |
| `read_sub_session` | Read a specific sub-session transcript by id. |
| `search_history` / `search_channel_archive` | Search older channel/project history. |

## Traces

| Tool | Purpose |
|---|---|
| `get_trace` | One turn's trace by `correlation_id`. |
| `list_session_traces` | Recent traces in a session. |
| `audit_trace_quality` / `agent_quality_audit` | Runtime quality findings (when available). |

## Project Factory & runs

| Tool | Purpose |
|---|---|
| `get_project_factory_state` | Snapshot of the Project Factory state. |
| `get_project_orchestration_policy` | Concurrency caps + orchestration policy for a project. |
| `check_project_coding_run_loop_continuation` | Loop-continuation policy check (used by supervised loops). |
| `publish_project_run_receipt` | Publish a Project run receipt with status + evidence. |

## System health

| Tool | Purpose |
|---|---|
| `get_system_health_preflight` | Live health snapshot — recent errors, build identity, recommended next action. |
| `run_agent_doctor` | Run the agent's self-diagnostic. |

## Skills & capabilities

| Tool | Purpose |
|---|---|
| `list_agent_capabilities` | Inventory of capabilities the agent has in this binding. |
| `get_skill` | Load a runtime skill body by id. |

## Script execution

| Tool | Purpose |
|---|---|
| `run_script` | Execute a script in the session's sandboxed runner (subject to `safety_tier` + approvals). |

## Conventions

- Prefer the scoped MCP tool over a curl call when both are available — the
  tool can't leak past the agent's channel binding; an HTTP key can.
- If a tool returns a permission error, report the access gap rather than
  retrying; the binding may have intentionally dropped that capability.
- New tools land in this catalog when a skill references them. Keep the
  descriptions one line.
