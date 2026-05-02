# Claude Code and Codex Harness Parity

This page is the harness parity ledger. It compares native Claude Code and
Codex surfaces with what Spindrel currently supports, which evidence proves it,
and what should be deepened next.

It is intentionally engineering-facing. The goal is not to make Spindrel look
complete; it is to keep the wrapper honest so native Claude Code and Codex keep
feeling like their CLIs, with Spindrel adding browser persistence, approvals,
screenshots, transcripts, project workspaces, and operator visibility on top.

## Sources

- Claude Code Agent SDK overview: <https://code.claude.com/docs/en/agent-sdk/overview>
- Claude Code command reference: <https://code.claude.com/docs/en/commands>
- OpenAI Codex docs: <https://developers.openai.com/codex/>
- Spindrel harness guide: [External Agent Harnesses](agent-harnesses.md)
- Local E2E workflow: [Agent E2E Development](agent-e2e-development.md)
- Active implementation track: [Harness SDK Track](../tracks/harness-sdk.md)

## Support Labels

| Label | Meaning |
|---|---|
| Native | Routed through the runtime SDK, CLI, or app-server surface and rendered by Spindrel. |
| Terminal handoff | Known native flow, but it needs an interactive TTY or no safe non-interactive API exists yet. |
| Partial | Important pieces work, but there is a known parity gap. |
| Spindrel layer | Not a native feature; Spindrel adds it around the runtime without replacing native behavior. |
| Missing | Known native surface with no real Spindrel support yet. |

## Parity Matrix

| Native surface | Claude Code support | Codex support | Spindrel benefit | Evidence | Gap / next action |
|---|---|---|---|---|---|
| Native turn loop | Native via Claude Agent SDK `ClaudeSDKClient` | Native via `codex app-server` JSON-RPC | Browser transcript, persistence, stop, usage rows, project cwd | `test_live_harness_core_parity_controls_trace_and_context`; `harness-chat-result.png` | Keep SDK/app-server version drift visible in capabilities/status. |
| Native slash commands | Native SDK dispatch for session commands; CLI/list or handoff for management commands | App-server calls for supported commands; handoff for CLI-only flows | Real slash names in picker; unknown harness slashes pass through | `test_live_harness_core_native_slash_direct_commands`; `harness-native-slash-picker-dark.png` | Expand doc rows whenever runtime command inventories change. |
| `/context` | Native SDK `/context` after a session exists | Terminal handoff; app-server has no read-only native context method in current support path | Prevents fake host-context cards from impersonating native output | `harness-claude-native-context-result-dark.png`; `harness-codex-native-context-result-dark.png`; live Claude verification on 2026-05-02 showed native Context Usage, MCP Tools, and Skills sections | Revisit if Codex app-server exposes a first-class context method; otherwise prefer native CLI mirror. |
| `/compact` | Native SDK `/compact` | Native app-server compact when thread exists | Keeps native resume identity instead of Spindrel transcript compaction | `tests/unit/test_harness_auto_compaction.py`; context tier live parity | Add a non-empty-thread Codex compact screenshot if context cards change. |
| Resume/new/clear | SDK resume id persisted per Spindrel session | Codex thread id persisted per Spindrel session | Browser sessions can resume without losing native state | Core parity resume assertions; native CLI mirror screenshots | Reduce CLI `/resume` list title clutter from host instruction preambles. |
| Model and effort | Runtime capability model/effort controls; SDK option-shape adaptation | Live `model/list`, config defaults, app-server turn params, CLI sync | Per-session picker and slash controls | `test_runtime_model_surface_uses_live_effort_projection`; native CLI settings sync screenshot | Keep proving bidirectional native CLI -> Spindrel settings sync after runtime upgrades. |
| Advanced SDK options | Explicit `runtime_settings.claude_options` passthrough for allowlisted Claude SDK knobs: `skills`, `add_dirs`, fallback model, budgets/timeouts, thinking/output config, sandbox/task budget, and checkpoint/fork flags | Codex app-server options remain mapped through supported turn params and native config methods | Power-user SDK parity without turning Spindrel into a parallel config registry | `test_claude_option_passthrough_maps_supported_sdk_options` | Add live scenarios only for deterministic options such as `add_dirs` or `skills`; keep checkpointing explicit. |
| Permissions and approvals | SDK permission modes plus `can_use_tool` bridge | Codex approval/server-request translation | Durable Spindrel approval cards and audit trail | `tests/unit/test_codex_runtime_approvals.py`; runtime capability tests | Add more live mutating-command dry-path coverage. |
| Runtime questions | Native `AskUserQuestion` routes through a durable Spindrel `core/harness_question` card and returns `updated_input` to the SDK | App-server user-input requests route through the same durable question-card service when emitted | Answer from the browser, persist the answered card, and resume the native turn | `questions/harness-claude-ask-user-question-card-dark.png`; `test_live_claude_ask_user_question_card_round_trip`; `test_user_input_request_routes_to_question_card` | Add a deterministic Codex live user-input trigger if app-server exposes one. |
| Queued follow-ups while busy | Supported: a blocked Claude SDK turn keeps the Spindrel session lock, a second user message is persisted and queued, then resumes as the next native turn after `AskUserQuestion` resolves | Host queue is runtime-neutral; add a Codex live proof around a deterministic blocker | Lets users type ahead without losing message order or native resume state | `native-cli/harness-claude-queued-followup-dark.png`; `test_live_claude_busy_turn_queues_followup_and_resumes`; `test_chat_queue_contract.py` | Add Codex live proof and a UI status indicator for queued depth if the composer needs clearer feedback. |
| Native tools and file edits | Native Claude tools including Bash, Edit, Read, Grep | Native Codex tool/event stream from app-server | Ordered tool breadcrumbs and persisted transcript replay | Transcript order screenshots; `test_codex_runtime_events.py` | Keep terminal/default persisted order checks broad as new event kinds land. |
| Todo/progress tools | Claude `TodoWrite` rich rendering | Codex plan/collab events rendered where emitted | Progress rows survive refresh | `harness-claude-todowrite-progress.png` | Add Codex-native progress equivalent if app-server emits stable todo events. |
| Tool discovery | Claude `ToolSearch` rich rendering | Codex native tools/app-server inventory | Search/discovery output is visible in chat | `harness-claude-toolsearch-discovery.png` | Add a Codex discovery screenshot if Codex exposes an analogous command. |
| Subagents/background agents | Claude `Agent`/`Task` rendered and persisted; explicit SDK programmatic agents can be passed with `runtime_settings.claude_agents` / `runtime_settings.agents` | Codex collab/subagent events rendered from app-server | Browser-visible child-agent activity without Spindrel owning scheduling | `harness-claude-native-subagent.png`; `test_claude_agent_runtime_settings_map_to_sdk_agent_definitions`; `test_codex_runtime_events.py` | Deepen Codex live subagent scenario; verify CLI mirror switching during child activity. |
| Skills | Native Claude project/user skill dirs and slash invocation; `Skill` remains enabled in restricted modes because the SDK requires it for filesystem skills | Codex app-server skill input/list support | Runtime-owned registries plus visible item previews | `harness-claude-native-custom-skill-result-dark.png`; `harness-codex-native-skills-result-dark.png`; `test_restricted_allowed_tools_do_not_bypass_mutating_or_orchestration_surfaces` | Do not sync registries by default; only add export/sync for explicit simple Markdown skills later. |
| Plugins and marketplaces | Claude plugin management is list/handoff depending on flow; explicit local SDK plugins can be passed with `runtime_settings.claude_plugins` / `runtime_settings.plugins` | Codex plugin/marketplace reads and safe management mappings | Approval-gated management cards; terminal handoff for TTY flows | `harness-codex-native-plugins-result-dark.png`; plugin install handoff screenshot; `test_claude_plugin_runtime_settings_map_to_sdk_local_plugin_configs`; `test_live_harness_claude_sdk_local_plugin_skill_invocation` | Add broader Claude plugin fixtures only when the SDK supports additional non-interactive plugin behavior. |
| MCP | Claude `/mcp list`, project `.mcp.json`, and explicit SDK `runtime_settings.claude_mcp_servers` / `runtime_settings.mcp_servers` | Codex MCP status/resource/tool surfaces where app-server supports them | Native MCP inventory in chat, with JSON details | `harness-codex-native-mcp-status-result-dark.png`; `test_claude_mcp_runtime_settings_map_to_sdk_server_configs_and_allowlist`; runtime capability tests | Add OAuth/interactive MCP handoff screenshots when UI changes. |
| Hooks | Claude hooks are known TTY/native management surface; SDK hook callbacks record sanitized lifecycle events into harness metadata | Codex `hooks/list` supported when app-server exposes it | Visible status or explicit handoff instead of timeout | `harness-claude-native-hooks-result-dark.png`; `test_live_harness_claude_sdk_hook_observability_records_tool_lifecycle`; Codex apps/hooks unit test | Add UI surfacing for hook lifecycle events only if it improves debugging without cluttering normal turns. |
| Config/features/apps/cloud/status | Claude status/doctor/auth/version through native surfaces or handoff | Codex config/features/apps/cloud/status app-server mappings | Human summaries plus expandable runtime payloads | Codex native result screenshots for apps, cloud, approvals, features | Keep replacing "returned N fields" summaries with real item previews. |
| Images and attachments | SDK image content blocks for readable inline/cwd-local images | Codex image/localImage input items when app-server supports them | Upload manifest, durable screenshot evidence, project cwd handling | `harness-*-image-semantic-reasoning.png`; input manifest tests | Add regression whenever attachment storage or project cwd rules change. |
| Project instruction discovery | Native filesystem reads `CLAUDE.md`/rules and `.claude/` features from explicit SDK `setting_sources=["user","project","local"]` in the effective cwd | Native filesystem reads `AGENTS.md` in effective cwd | Project-bound channel cwd controls runtime work surface | `harness-*-project-instruction-discovery.png`; `test_native_filesystem_feature_sources_are_explicit_when_sdk_supports_them` | Keep this as a critical smoke because failures look like "Codex forgot normal behavior." |
| Native CLI mirror | Embedded terminal can resume native CLI with the Spindrel session title passed through Claude's native `--name` flag, mirror messages back, and promote the discovered native session id from user or assistant transcript rows; SDK chat does not yet resume from the CLI-mutated leaf while the CLI process remains live | Embedded terminal can resume native CLI, mirror messages back, promote the discovered native session id, and continue CLI-first sessions through Codex's native `exec resume` surface when app-server thread state is not sufficient | Escape to exact CLI UX without leaving the session | `native-cli/harness-*-native-cli-*.png`; `native-cli/harness-codex-native-cli-first-roundtrip-dark.png`; `test_native_session_id_from_transcript_discovers_claude_and_codex_ids`; `test_persist_mirrored_assistant_promotes_discovered_native_session_id`; `test_persist_mirrored_user_promotes_discovered_native_session_id`; `test_live_codex_native_cli_first_turn_promotes_thread_id` | Fix Claude SDK/CLI live-process leaf continuity if the SDK exposes a supported option; keep Codex `exec resume` fallback screenshot current. |
| Usage, context, latency | SDK usage/cost and context hints where available | App-server usage/context-window notifications and latency milestones | Admin usage rows, context popover, slowness diagnosis | `harness-usage-logs-dark.png`; context/status tests | Add latency regression around first text/tool and replay after refresh. |
| Spindrel bridge tools | SDK MCP helper surface when installed SDK supports it | Codex `dynamicTools` when installed binary supports it | Optional host tools without replacing native tools | `harness-claude-bridge-default.png`; `harness-codex-bridge-default.png` | Keep bridge opt-in and clearly separate from native parity. |
| Spindrel plan tools | Layered host plan artifact around native runtime modes | Codex collaboration mode maps from Spindrel session state | Durable plan cards when explicitly using Spindrel plan mode | Plan-mode switcher screenshots; runtime params tests | Do not present host plan mode as a native replacement. |

## Current High-Priority Gaps

1. **Claude CLI resume-leaf continuity.** The `cli` preset now proves Codex CLI transcript mirroring, model/effort sync, and chat-mode resume after a CLI turn. Claude currently proves transcript mirroring, native session-id promotion, and native CLI naming via `--name` only; the next SDK chat turn resumes the session id but not the live CLI-mutated leaf.
2. **Codex CLI-first native resume.** CLI-originated Codex sessions now bypass app-server continuation and use installed Codex's native `codex exec resume <session> --json` path for the next Spindrel chat turn. Keep the live CLI-first roundtrip screenshot current because this is a second native execution surface.
3. **Codex context parity.** Keep `/context` honest as terminal handoff until app-server exposes a supported method; use native CLI mirror for exact output.
4. **Claude hooks/checkpointing audit.** Compare installed SDK support with docs and add rows/tests for any non-interactive surfaces we can safely expose. File checkpointing is SDK-supported but has native limitations and conflicts with external session stores, so expose it only behind an explicit runtime setting if we add it.
5. **Codex subagent live proof.** Unit rendering exists; add a live scenario and screenshot for a real collaboration/subagent event when the runtime reliably emits one.
6. **Native command inventory drift.** Add a lightweight docs/test guard whenever Claude SDK `system/init.slash_commands` or Codex app-server schema grows a command we do not classify.

## Verification Commands

Use the local e2e workflow; do not target the shared live server for normal parity iteration:

```bash
python scripts/agent_e2e_dev.py prepare-deps
python scripts/agent_e2e_dev.py start-api --build-ui
python scripts/agent_e2e_dev.py prepare-harness-parity
./scripts/run_harness_parity_local_batch.sh --preset sdk --screenshots docs
./scripts/run_harness_parity_local_batch.sh --preset slash --screenshots docs
./scripts/run_harness_parity_local_batch.sh --preset cli --screenshots docs
python -m scripts.screenshots check
```

Focused implementation work should also run the unit tests for the touched
runtime adapter, UI renderer, and docs guard.
