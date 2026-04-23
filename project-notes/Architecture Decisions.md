# Architecture Decisions

For the canonical runtime context-policy guide, see [Context Management](../../../agent-server/docs/guides/context-management.md). Keep this file for load-bearing decisions and invariants, not the full operational policy/tuning guide.

## Guiding Principles
- **Product identity**: "Best self-hosted personal AI agent"
- **Target user**: Runs Ollama/local models, wants more than chat, values self-hosting
- **Design philosophy**: Reduce config surface, maximize auto-discovery
- **Integration isolation**: NO integration-specific code in `app/` — must live in `integrations/{name}/`

## Key Decisions

### Plan mode state is a runtime capsule plus a Markdown artifact
**Decided 2026-04-23.** Session plan mode no longer treats the Markdown plan file as the only load-bearing state.

**What changed.**
- `Session.metadata_["plan_runtime"]` now stores the compact execution capsule: mode, current/next step ids, accepted/current revisions, next action, blockers, unresolved questions, replan metadata, and compaction watermark.
- `Session.metadata_["planning_state"]` stores visible durable planning notes: confirmed decisions, open questions, assumptions, constraints, non-goals, evidence, and preference changes.
- `Session.metadata_["plan_adherence"]` stores recent execution evidence and the current adherence status.
- Plan-state and plan endpoints return both `runtime` and deterministic `validation`.
- Approval rejects structurally incomplete plans instead of relying on prompt guidance.
- `request_plan_replan` is the explicit transition when execution proves the accepted plan is stale.

**Why.**
- Markdown is readable but too fuzzy to be the only execution contract.
- Short planning/execution context windows and automatic compaction need a compact state capsule that can be injected every turn.
- Adherence cannot depend only on instructions; the runtime must block thin/unresolved plans and provide a typed replan path.

**Load-bearing invariants.**
- Markdown remains the canonical human-readable artifact.
- The runtime capsule is the canonical compact state summary for context injection and UI status.
- Planning-state is visible durable user/agent back-and-forth, not an invisible hidden plan.
- Adherence evidence is compact supervision input, not proof that semantic step success has been fully verified.
- Compaction summaries are never authoritative for plan state.
- Replanning creates a new draft revision and preserves the previously accepted revision until a new one is approved.
- Subagent guidance remains disabled by default until that orchestration path is separately vetted.

### Context assembly is origin-aware and profile-driven
**Decided 2026-04-22.** Context assembly no longer treats chat, plan mode, tasks, and heartbeat runs as one generic additive prompt policy.

**What changed.**
- Added an explicit `ContextProfile` resolver with six shipped profiles:
  - `chat`
  - `planning`
  - `executing`
  - `task_recent`
  - `task_none`
  - `heartbeat`
- Session reload, task runtime, heartbeat runtime, and context assembly now all resolve through the same profile policy.
- Profiles control both:
  - how much live history is replayed
  - which optional static injections are allowed at all
- Optional static injections are now budget-gated through one admission path instead of being appended ad hoc.
- Planning/execution profiles now admit a compact active-plan block derived from the canonical Markdown plan file so older decisions survive the short live-history window.

**Why.**
- The previous pass separated replayable live history from static injections, but the runtime still let too many origins share the same additive prompt policy.
- Planning, execution, task-without-history, and heartbeat runs have materially different context needs. Treating them the same only inflated prompts and blurred the actual task boundary.
- Static injections are not free. If a source is optional, it should first pass a relevance/profile policy and then pass a budget policy.

**Load-bearing invariants.**
- `planning` and `executing` are different profiles. `blocked` and `done` continue to map to `executing` until a separate follow-up proves they need distinct policy.
- The active plan artifact is load-bearing context for `planning` and `executing`; important planning decisions should be written there instead of relying on older live chat turns.
- `task_none` and `heartbeat` are deliberately restrictive: no live replay beyond the system/base layers and no optional ambient injections.
- Special background origins (`subagent`, hygiene-style runs) default to the `task_none` posture unless explicitly widened later.
- Compaction summary reload is also profile-aware. Restrictive profiles may suppress it even if the session has archival summary state.
- Admission decisions must be observable. Traces now record per-source reasons such as `admitted`, `skipped_by_profile`, and `skipped_by_budget`.

### Prompt-size reporting distinguishes gross, current, and cached prompt tokens
**Decided 2026-04-22.** Context reporting must not flatten all prompt usage into one number once caching and multi-iteration runs exist.

**What changed.**
- `token_usage` traces now carry:
  - `gross_prompt_tokens`
  - `current_prompt_tokens`
  - `cached_prompt_tokens`
  - `completion_tokens`
- `consumed_tokens` remains as the compatibility alias for gross prompt tokens.
- Context-budget and context-breakdown payloads now expose the split explicitly, along with `context_profile` and `source`.
- Compact UI surfaces keep using gross prompt tokens for the primary chip; detail surfaces show current and cached values separately.

**Why.**
- A single blended prompt number made cache hits invisible and made some turns look larger than the actual current prompt being sent.
- Users need to distinguish "how big was the total prefix," "how much of that was newly paid-for prompt," and "how much was cached reuse."
- Backend and UI were both already consuming these payloads; the split needed to be explicit and stable instead of inferred in multiple places.

**Load-bearing invariants.**
- Gross prompt tokens remain the compatibility headline metric and the header-pill number.
- Current prompt tokens are derived as `gross - cached` when the provider reports cached usage.
- Pre-call stream-time budget events remain estimates. Cached-token truth comes only from post-call API usage.
- Any new reporting surface should consume the explicit gross/current/cached fields instead of re-deriving them from legacy keys.

### LLM replay context now excludes internal transcript rows and compacts older assistant history from canonical turn bodies
**Decided 2026-04-22.** Session reload and compaction now treat replayable chat history as a separate budgeted surface instead of replaying all persisted transcript text verbatim.

**What changed.**
- `_load_messages()` no longer reloads rows marked `metadata.hidden` or `metadata.pipeline_step` into model history by default.
- Older assistant rows with large verbose `content` now prefer compact replay text derived from canonical `assistant_turn_body` metadata, while the most recent assistant row still stays verbatim.
- Context budgeting now distinguishes:
  - `base_tokens`
  - `live_history_tokens`
  - `static_injection_tokens`
  - `tool_schema_tokens`
- Early compaction is no longer driven only by one blended utilization number. Replayable live history now has its own soft caps.

**Why.**
- The dominant context-growth surface was not fresh retrieval but replaying oversized assistant-heavy history across multiple iterations.
- UI-hidden/pipeline transcript rows were being suppressed visually but still re-entering the model, which is the worst kind of invisible context leak.
- Assistant transcript bodies were already persisted in a more structured form (`assistant_turn_body`), but reload still favored raw verbose prose.

**Load-bearing invariants.**
- Hidden/pipeline rows are UI/runtime continuity artifacts, not model context. If a row should stay available to humans or renderers but not the LLM, it must be hidden at load time, not only at render time.
- `assistant_turn_body` is now the canonical substrate for replaying older assistant turns when compaction is needed. Raw assistant `content` is still preserved for UI/audit fidelity.
- The latest assistant turn is kept verbatim to preserve immediate conversational continuity; older assistant turns are eligible for compact replay.
- Context-pressure decisions must distinguish replayable live history from static injections. Compaction is the right lever for the former, not automatically for the latter.

### Compaction window selection is watermark-based, not `interval - keep_turns`
**Decided 2026-04-22.** When compaction fires early because context pressure is high, the summary slice is now chosen by the actual watermark boundary instead of the old `interval - keep_turns` heuristic.

**What changed.**
- The compaction keep window is still defined semantically by the latest `keep_turns` user messages.
- The summarized window is now the exact persisted message range between the previous watermark (if any) and the oldest kept user turn.
- Internal rows (`hidden`, `pipeline_step`) are excluded from the summary input in the same way heartbeat rows already were.
- Trace payloads now record the compaction trigger reason.

**Why.**
- The previous early-compaction path could summarize turns that were still being kept live, which duplicated context rather than shrinking it.
- Once compaction can fire on size before the nominal turn interval, turn-count arithmetic alone is no longer a reliable way to choose the summary boundary.

**Load-bearing invariants.**
- Compaction must never summarize content that remains inside the live keep window.
- A watermark is the only authoritative boundary between "already summarized" and "still live".
- If prompt pressure comes mostly from static injections instead of replayable history, lowering optional injections is preferred over summarizing chat more aggressively.

### Persisted tool outcomes carry a normalized presentation contract beside raw audit data
**Decided 2026-04-22.** Persisted tool data now has three layers:

- raw audit identity/payload on `tool_calls` (`tool_name`, `arguments`, `result`, `error`)
- `surface` deciding which first-party web UI owns the outcome (`transcript` | `widget` | `rich_result`)
- `summary` giving chat renderers one stable label/primitive contract (`kind`, `subject_type`, `label`, optional target/path/diff stats)

**Why.**
- `get_skill` was excluded from rich result envelopes, which forced terminal mode to reverse-engineer meaning from mixed raw `tool_calls` shapes (`function.arguments`, `arguments`, `args`) and ad hoc blobs.
- File reads/edits, widget-producing tools, and transcript-only lookup tools were each deriving labels differently in different chat surfaces.
- The app already had the right raw data, but not a stable persisted presentation layer between audit storage and renderer heuristics.

**Load-bearing invariants.**
- Raw `arguments` / `result` / `error` stay stored unchanged for fidelity, deep inspection, and future consumers.
- First-party web chat is the only v1 consumer updated to use `surface` + `summary`; Slack/integration dispatchers remain unchanged.
- Widget-producing tools keep widget ownership (`surface="widget"`); rich-envelope tools keep rich-render ownership (`surface="rich_result"`); transcript-owned tools such as `get_skill`, `file`, and `inspect_widget_pin` read from `summary`.
- `summary.kind` is a render primitive, not a tool alias. Example: `file` edit and any other file-editing tool can both map to `kind="diff", subject_type="file"` while preserving their real `tool_name`.
- Persisted assistant `message.tool_calls[]` now carry normalized top-level `name`, `arguments`, `surface`, and `summary` so chat UIs stop guessing across legacy shapes.

### Live turns reuse the same tool presentation contract as persisted messages
**Decided 2026-04-22.** The normalized `surface` + `summary` contract is not persistence-only metadata. Live tool SSE events and the optimistic assistant message synthesized by `finishTurn()` now carry the same contract too.

**Why.**
- The web chat previously had three different tool shapes for the same turn: live `TurnState.toolCalls`, a weaker client-synthesized post-stream message, and the eventual persisted/refetched message.
- That split was the reason tool rows behaved differently during streaming vs after refresh, even after the backend normalization landed.

**Load-bearing invariants.**
- `turn_stream_tool_start` / `turn_stream_tool_result` payloads may carry `surface` + `summary`; frontend store state preserves them verbatim.
- `finishTurn()` must synthesize `message.tool_calls[]` with normalized `name`, `arguments`, `surface`, and `summary` so the optimistic finished message matches the later persisted message shape.
- Any renderer fallback against raw `tool_name` / raw args is compatibility glue for old rows/events only, not the primary path for new turns.

### Theme, chat mode, and tool-render surface are separate axes
**Decided 2026-04-22.** Tool-result rendering in chat now follows three independent concerns:

- `theme` selects the app-wide light/dark token palette
- `chat_mode` selects the feed shell (`default` vs `terminal`)
- `rendererVariant` selects how a rich tool envelope adapts to the current surface (`default-chat`, `terminal-chat`, pinned/dashboard surfaces later)

**Why.**
- Terminal chat was starting to branch in `MessageBubble` over ownership and fallback semantics instead of just presentation, which is why default vs terminal kept drifting on diffs, rich results, and collapse behavior.
- Treating terminal as a full app theme would incorrectly couple transcript-shell decisions to global palette selection and would explode the matrix once custom themes exist.
- Rich result renderers already consume `ThemeTokens`; adding a surface-level renderer variant keeps one ownership pipeline while still allowing terminal-specific shells and token tweaks.

**Load-bearing invariants.**
- `chat_mode` must not decide whether a tool result is transcript-owned vs rich-render-owned. Ownership comes from the shared tool presentation contract (`surface` + per-tool transcript policy).
- `rendererVariant` is presentation-only. It may change tokens, chrome, typography, and renderer fallbacks for a surface, but it must not reorder tool items or swap the owning UI path in chat.
- Per-tool open/collapsed behavior is semantic and shared across modes. Example: file reads stay collapsed; file edits show inline diffs. Do not reintroduce "latest message auto-expand" logic.
- Terminal chat may render rich envelopes differently from default chat, but the difference belongs in `RichToolResult` / renderer dispatch, not in mode-specific branching across the message renderer.
- Persisted chat renders tool outcomes from one ordered item builder (`PersistedRenderItem[]` in `toolTranscriptModel.ts`), not from per-mode partitions in `MessageBubble`. `MessageBubble` may pick row shells, but it must not re-own tool ordering or envelope ownership.
- `message.tool_calls[]` is the primary persisted order/ownership source for current rows. `metadata.envelope` is allowed only as one explicit root rich-result item. Any envelope-only fallback heuristics for older rows must stay confined to the shared model layer.
- When a current assistant row carries `metadata.transcript_entries`, that ordered sequence is the owning turn-body model for both streaming parity and settled replay. New turns must persist matching canonical `message.tool_calls[]` / `metadata.tool_results`; if a transcript tool slot cannot resolve by `toolCallId`, that is a producer bug, not a UI fallback case. The UI must not flatten the row back into `content + trailing tools`, and it must not silently reconstruct order from `tools_used`.

### Scratch sessions are internal-first session records; promotion swaps the channel primary
**Decided 2026-04-21.** Scratch sessions are no longer a client-side convenience pointer layered on top of the main channel session. They are first-class `Session` rows with their own `title`, `summary`, `ConversationSection` history, and selector stats. The channel's canonical external conversation is still exactly one session: `channel.active_session_id`.

**What this means.**
- Scratch sessions live as `session_type="ephemeral"` rows with `parent_channel_id`, `owner_user_id`, and `is_current`.
- Scratch metadata is stored on the existing session row: `Session.title` = name, `Session.summary` = compact summary.
- A scratch session becomes channel-visible only through explicit promotion. Promotion swaps `channel.active_session_id` to the chosen scratch session and demotes the former primary session into the caller's scratch history.
- Slack/integrations never receive temporary scratch traffic. External delivery follows only the current primary channel session.

**Why.**
- Keeping scratch on the same `sessions` table avoids a second metadata/archive model and lets compaction/backfill/history machinery work uniformly across main + scratch conversations.
- Promotion-as-swap preserves exact transcripts and section archives without copying messages between sessions.
- Treating scratch as internal-only avoids leaking personal exploratory context into shared integrations until the user intentionally promotes it.

**Load-bearing invariants.**
- Runtime history and prompt injection are **session-scoped**, not channel-scoped. `ConversationSection.session_id` is the source of truth for the current session's archive/index.
- New scratch sessions may receive a one-shot bootstrap summary from the current primary session, but that bootstrap is consumed only while the scratch session is still effectively empty.
- Demoted former-primary sessions become scratch rows owned by the acting user (`parent_channel_id=<channel>`, `owner_user_id=<user>`, `is_current=True`); the promoted session clears scratch ownership fields and becomes the normal channel primary.
- Reply threads stay out of this product flow. They remain separate thread sub-sessions and do not participate in scratch naming/promotion UX.

### Native app widgets are a first-party third lane on the unified widget interface
**Decided 2026-04-21.** The widget product now has three runtime kinds:

- `html` — bot/user-authored iframe widgets
- `template` — declarative tool-renderer widgets
- `native_app` — first-party React mini-app widgets

The interface is unified at the product level:

- one library/catalog
- one placement model
- one bot-facing action tool (`invoke_widget_action`)

The runtime substrate is deliberately **not** unified. HTML widgets keep the existing SDK + `@on_action` handler machinery; template widgets keep their tool/result-driven rendering path; native app widgets dispatch through a first-party registry and persist state through widget instances.

**Why.**
- A single bot/user-facing interface reduces system sprawl: discovery, placement, and interaction no longer depend on knowing the widget substrate up front.
- The existing HTML widget action surface already proved the named-action model, but it was shaped by iframe/widget.py internals. A generic bot tool is a better public contract.
- Some core widgets want richer local state, persistence, and app integration than declarative templates or tool-result cards comfortably support, but that does not justify opening a public React widget authoring surface.

**Load-bearing implementation choices.**
- **`native_app` is first-party only.** Bots/workspace users can discover, place, and invoke actions on native widgets; they do not author them.
- **State lives in `widget_instances`, not only in dashboard pins.** Native widgets are addressable stateful objects keyed by `(widget_kind, widget_ref, scope_kind, scope_ref)` with generic JSON `config` + `state`. Pins reference instances via `widget_instance_id`.
- **Declared action schemas are mandatory for bot exposure.** Any widget action surfaced through `invoke_widget_action` must declare an input schema first; undeclared actions stay off the public bot surface.
- **Theming stays small.** Native app widgets inherit the app's existing light/dark theme tokens only. Widget-specific theming remains an HTML-lane concern unless the app adopts a broader theming platform later.
- **First proving widget is native Notes.** Use a small flagship widget (`core/notes_native`) to validate the model before expanding the native lane.
- **Outer widget chrome belongs to the host wrapper.** Title bars and the outer surfaced-vs-plain shell are host concerns (`show_title`, `wrapper_surface`); widgets should not duplicate that chrome internally.
- **Legacy HTML Notes is deleted, not compatibility-hidden.** The old `app/tools/local/widgets/notes/` bundle is intentionally unsupported so new and existing first-party Notes behavior routes through `notes_native`; stale direct refs should be replaced rather than shimmed.

### Widget taxonomy is definition-kind first; presets are an instantiation path, not a widget kind
**Decided 2026-04-22.** The widget system now standardizes on an explicit public contract model instead of relying on overlapping historical terms like "template", "tool renderer", "preset", and "HTML widget" to explain everything.

**Canonical model.**
- There are three public definition kinds:
  - `tool_widget`
  - `html_widget`
  - `native_widget`
- Concrete widget instances also carry an instantiation path:
  - `direct_tool_call`
  - `preset`
  - `library_pin`
  - `runtime_emit`
  - `native_catalog`

**Why.**
- The prior language blurred "what this widget is" with "how this widget got instantiated", which made presets sound like a fourth widget type and made YAML tool widgets that use `html_template` look like standalone HTML widgets when they are not.
- DX and debugging were too inference-heavy. Humans had to reverse-engineer behavior from source paths, manifests, or pin envelopes.
- The system needed one honest model that can be surfaced in the API, UI, docs, and future tooling without each layer inventing its own taxonomy.

**Load-bearing invariants.**
- **Preset is never a definition kind.** A preset is a guided setup flow, usually over a `tool_widget`.
- **Preset dependencies must be explicit.** If a preset declares a `tool_family`, every backing tool, binding-source tool, and action dependency must stay inside that family. Single guided flows must not silently depend on multiple incompatible MCP/server lanes.
- **A YAML tool widget that uses `html_template` is still a `tool_widget`.** It is tool-bound, state-from-tool-result, and not equivalent to a standalone `html_widget`.
- **Standalone HTML widgets remain a separate contract.** They are bundle/runtime-owned and arrive through `library_pin` or `runtime_emit`.
- **Native widgets remain core-only.**
- **Placement stays unified.** Rich results, pins, and dashboard placements may feel the same to end users even though the definition/runtime internals differ.
- **`widget_contract` + `config_schema` are the public inspection surfaces.** Future UI/debug tooling should extend those fields rather than reintroducing heuristic classification.

### Bot-authored widget bundles use git-backed source history inside `.widget_library`
**Decided 2026-04-21.** Bot/workspace-authored library bundles (`widget://bot/...`, `widget://workspace/...`) are versioned with Git at the writable widget-library root, not by extending workspace-wide history and not by adding a separate revisions table. Each successful mutating `file` tool call that touches a bundle creates at most one new bundle-scoped commit per affected library root.

**What this means.**
- `<ws_root>/.widget_library` and `<shared_root>/.widget_library` each own their own hidden `.git` repository.
- The commit unit is a successful mutating tool call, not an individual file. Multi-file bundle edits stay coherent.
- Rollback restores bundle contents from a prior revision and then writes a new rollback commit. History is append-only; no reset/rebase semantics.
- `widget_library_list` surfaces `versioned` + `head_revision`; `describe_dashboard` surfaces `bundle_revision`; bots get `widget_version_history` and `rollback_widget_version`.
- Active session plans record these revisions as lightweight artifacts rather than treating source-history events as checklist state.

**Why.**
- Widget bundles are already file-backed and naturally diffable; Git gives provenance, diff, and rollback semantics without inventing a second persistence system.
- Scoping the repo to `.widget_library` avoids dragging unrelated workspace files into bot-authored widget history.
- Append-only rollback keeps the audit trail intact and composes cleanly with plan-mode artifact logging.

### Skill/Tool Model Replaces Product "Capabilities"
**Decided 2026-04-21.** The app will not have a first-class capability/carapace product model going forward. The only product concepts are skills, tools, and enrollment of each.

**What this means.**
- Foldered skills are still just skills. `skills/foo.md` is a loose skill; `skills/foo/index.md` is the root skill for a folder; `skills/foo/bar.md` is a child skill.
- `index.md` is content, not a special prompt fragment injection layer.
- Bot edit and channel settings should expose enrolled skills/tools only. Any old "Capabilities" section folds into skills.
- Channel-level assignment is channel skill enrollment, not capability activation.
- Tool availability still follows the existing tool/channel activation path. Grouping in UI is presentational only.

**Runtime consequences.**
- Remove `activate_capability`, capability approval flows, capability session state, and capability-discovery prompt injection.
- Context assembly should only work from enrolled skills, enrolled tools, normal tool discovery, and normal skill retrieval.
- Carapace CRUD/routes can remain temporarily as dormant compatibility surfaces while the runtime/UI path is removed, but new product behavior must not depend on them.

**Why this is the right simplification.**
- Replacing carapaces with another package abstraction would keep the same mental-model problem under a new name.
- The existing skill/tool systems already solve loading, discovery, and enrollment. Reusing them is lower-risk than building another indirection layer.
- Folder-aware skill UI gives the organizational benefit without inventing new runtime semantics.

### Slash commands are backend-owned commands with typed results; web renders them as synthetic chat rows
**Decided 2026-04-21.** Slash commands are not a web-only input trick. The command registry and execution contract live on the backend so web, Slack, and CLI can share one semantic layer and only differ in presentation.

**Contract.**
- Backend owns the command id, availability, auth boundary, and typed `result_type` + `payload`.
- Clients may render the result however their surface allows, but the payload is renderer-neutral. No JSX, Slack Block Kit, or terminal formatting lives in the contract.
- Web is allowed to insert a non-persisted synthetic transcript row for command results. That row is UX state, not the source of truth.

**First implementation.**
- `/api/v1/slash-commands` lists supported commands.
- `/api/v1/slash-commands/execute` returns a normalized result envelope.
- `/context` is the proving-ground command. Channel scope uses the existing context budget/breakdown data; session scope summarizes assembled session context into the same `context_summary` result type.
- Channel chat, scratch/session chat, and thread chat all execute the same backend command and render the returned payload as a lightweight in-chat card.
- Side-effect commands use the same envelope with `result_type="side_effect"` so `/stop` and `/compact` can stay server-owned without pretending to be chat messages.
- Pure navigation helpers may stay client-local for now. Current example: `/scratch` in web, which opens the scratch-pad route and is intentionally not part of the backend command registry yet.

**Why this shape.**
- A web-only slash-command layer would drift immediately once Slack and CLI need parity.
- Persisted assistant messages are too heavy for command feedback in v1; synthetic rows keep the UX fast without inventing new durable message semantics yet.
- Existing context/debug endpoints are implementation inputs, not the public slash-command contract.

**Invariants.**
- Do not compute slash-command semantics separately per client.
- Do not make slash-command output renderer-specific on the backend.
- If a future client cannot render rich cards, it should consume the same result via `fallback_text`, not a separate code path.

### Apt packages install into a volume-backed prefix (no `apt-get install`, no reinstall on rebuild)
**Decided 2026-04-21.** `install_system_package()` does **not** run `apt-get install`. It runs `apt-get download` followed by `dpkg -x <deb> /opt/spindrel-pkg/` so package files land in a named Docker volume (`spindrel-pkg`) instead of the image layer. Transitive runtime deps get the same treatment, resolved by `apt-cache depends --recurse`; anything already in the base image is filtered out via `dpkg-query`.

**Why not `apt-get install`.** apt writes to `/usr/bin`, `/usr/lib`, `/etc` — all part of the image filesystem layer, wiped on every `docker build`. A volume mounted at `/usr` would shadow the base Python/gosu/sudo installs, so that's a non-starter. Baking heavy packages into the Dockerfile was rejected early — don't want to ship 300MB of chromium to users who don't need it.

**Why `dpkg -x` is fine.** The tradeoff is that postinst scripts don't run. For the packages Spindrel's integrations actually declare (chromium, gh, jq, ripgrep, other dev tools), postinst is either cosmetic (menu entries, alternatives registration) or a no-op. If a future package needs specific postinst behavior (`update-ca-certificates`, etc.), invoke the hook explicitly after extraction rather than reverting this pattern.

### Tool results render by `view_key + mode`, not by terminal-specific rewrites
**Decided 2026-04-22.** Tool result rendering is a mode-aware view registry. Envelopes identify the stable result view with `view_key` and carry structured `data`; the UI chooses the renderer for the active mode (`default`, `terminal`, future compact/dashboard modes) without rewriting one mode into another.

**What this means.**
- `body` is the rendered/default artifact for the envelope's content type; `data` is the shared renderer-neutral payload.
- Default, terminal, and future modes are peers in the registry. Terminal must not iframe/mount default widget chrome as a fallback.
- If a view has no renderer for the current mode, the UI renders a safe fallback rather than guessing from HTML or crashing old rows.
- Widget templates may provide default HTML/components while also stamping `view_key`/`data` so terminal and future modes can render bespoke components from the same result.
- Generic result shapes use core view keys, not integration-specific registrations. `core.search_results` is the first example: Web Search opts into it, but the React app does not know about a `web_search.results` view.

**Why.**
- Terminal mode needs fully custom components and composer behavior, not CSS overrides of default chat.
- Parsing default widget markup to recover terminal content couples modes in the wrong direction.
- A registry keeps the system extensible for more presentation modes without adding another bespoke branch per mode.

### Plan mode uses visible state capsules plus deterministic adherence gates
**Decided 2026-04-23.** Plan mode is not allowed to rely on transcript memory alone. The approved plan remains the executable contract, but pre-publication planning back-and-forth and execution evidence now live in visible metadata-backed capsules that context assembly can always inject.

**What this means.**
- `planning_state` stores confirmed decisions, open questions, assumptions, constraints, non-goals, evidence, and preference changes. It is durable planning notes, not an invisible executable plan.
- `plan_runtime` remains the compact execution state machine: accepted revision, current step, next action, blockers, replan, compaction watermark.
- `plan_adherence` records deterministic execution evidence: current step, tool name/kind, tool-call ids, status/error, arguments summary, and result summary.
- `ask_plan_questions` answers are persisted both as a normal user message and as structured `planning_state` decisions.
- `publish_plan` validation warns if confirmed planning decisions are not visibly reflected in the draft.
- Tool dispatch gates mutating tools in planning mode and also blocks mutating execution when the accepted revision/current-step contract is invalid, blocked, or pending replan.

**Why.**
- Codex/Claude-style harnesses succeed by injecting the right small contract at the right time and gating side effects before they happen.
- Chat history and compaction summaries are too lossy to be the source of truth for multi-turn planning.
- The first reliable supervisor should be deterministic protocol enforcement plus evidence capture; semantic judging can come later as evals mature.

**Remaining gap.**
- There is still no full turn-end stop hook requiring every execution turn to end with progress, blocker, replan, verification, or explicit no-progress reason.
