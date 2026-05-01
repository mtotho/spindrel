# Agent Server Architecture

## Quick Reference
FastAPI + PostgreSQL (pgvector). Multi-provider LLM support (OpenAI-compatible, Anthropic-compatible). Expo/React Native UI on web path (web-native conversion in progress for admin pages).

## Request Flow
```
run_stream() → assemble_context() → run_agent_tool_loop() → _llm_call() → dispatch_tool_call() → LLM → ... → final response
```

In-loop tool pruning (`prune_in_loop_tool_results`) runs at the start of each iteration past the first to keep long task runs from accumulating tool-result tokens (see [[architecture-decisions]] tool-pruning rationale).

## Key Subsystems
| System                                    | What it does                                                                      | Key files                                                        |
| ----------------------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| Agent loop                                | Iterative tool-calling until text response                                        | `app/agent/loop.py`, `llm.py`                                    |
| Context assembly                          | Builds system prompt + tools per request                                          | `app/agent/context_assembly.py`                                  |
| Context pruning                           | Per-turn + in-loop tool-result pruning with retrieval pointers                    | `app/agent/context_pruning.py`                                   |
| Tool dispatch                             | Routes + executes tool calls; persists `tool_record_id` for retrieval pointers    | `app/agent/tool_dispatch.py`                                     |
| Carapaces/Capabilities                    | Composable expertise bundles                                                      | `app/agent/carapaces.py`, `capability_rag.py`                    |
| Skill enrollment                          | Per-bot persistent working set (Phase 3 design)                                   | `app/services/skill_enrollment.py`, `bot_skill_enrollment` table |
| Tool policy                               | Tier-gated approval before execution                                              | `app/services/tool_policies.py`                                  |
| Channel workspaces                        | Per-channel file stores                                                           | `app/services/channel_workspace.py`                              |
| Heartbeats                                | Periodic autonomous check-ins                                                     | `app/services/heartbeat.py`                                      |
| Tasks                                     | Scheduled + deferred agent execution                                              | `app/agent/tasks.py`                                             |
| Workflows (REPLACED WITH PIPELIENs/TASKS) | Multi-step YAML automations                                                       | `app/services/workflow_executor.py`                              |
| Channel events bus                        | Source of truth for live messages (post Phase 1, 2026-04-10)                      | `app/services/channel_events.py`, `app/schemas/messages.py`      |
| Integrations                              | Pluggable external connections (declarative `integration.yaml` + legacy setup.py) | `integrations/*/`, `app/services/integration_manifests.py`       |
| Delegation                                | Bot-to-bot communication                                                          | `app/services/delegation.py`                                     |
| Memory                                    | Workspace-files scheme (MEMORY.md + daily logs)                                   | `app/agent/context_assembly.py`                                  |
| Sub-agents                                | Parallel specialized workers (5 presets, no persona/memory)                       | `app/agent/subagents.py`, `app/tools/local/subagents.py`         |

## Tool Types
- **Local**: Python `@register(schema)` in `app/tools/local/`, `tools/`, and `integrations/*/tools/`. **Execute in the server process** — system deps (Node, Chrome, etc.) must be on the server host, NOT the workspace container.
- **MCP**: Remote HTTP via `mcp.yaml`
- **Client**: Actions handled client-side (shell_exec runs in workspace container, TTS)
- **Workspace tools** (`exec_command`, `file.*`): Run inside the agent's workspace container. Isolated from the server host.

## Context + Discovery Reference
For the current canonical runtime contract, use:

- `spindrel/docs/guides/context-management.md` — what enters prompt context, under which profile, and how history replay works
- `spindrel/docs/guides/discovery-and-enrollment.md` — how tools and skills are discovered, enrolled, loaded, and kept resident

This vault page is an overview only; it should not be maintained as a second narrative source of truth for detailed discovery behavior.

## For detailed progress and decisions, see:
- [[roadmap]] — what's done, what's next
- [[architecture-decisions]] — why things are the way they are
- [[loose-ends]] — what needs attention
