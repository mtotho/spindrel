# Architecture Decisions

For the canonical runtime context-policy guide, see [Context Management](../../../agent-server/docs/guides/context-management.md). For the canonical machine-target / local-companion architecture guide, see [Local Machine Control](../../../agent-server/docs/guides/local-machine-control.md). Keep this file for load-bearing decisions and invariants, not the full operational policy/tuning guide.

## Guiding Principles
- **Product identity**: "Best self-hosted personal AI agent"
- **Target user**: Runs Ollama/local models, wants more than chat, values self-hosting
- **Design philosophy**: Reduce config surface, maximize auto-discovery
- **Integration isolation**: NO integration-specific code in `app/` — must live in `integrations/{name}/`

## Key Decisions

### Harness SDK is a host contract; runtime specifics stay in integrations
**Decided 2026-04-26.** External agent harnesses are a separate runtime lane from normal Spindrel bots. They reuse Spindrel channels, workspaces, session persistence, approvals, and UI chrome, but the harness owns its native reasoning loop, native tools, file edits, and native session id. The planning home is [[Track - Harness SDK]].

**Load-bearing invariants.**
- Harness runtime modules live under `integrations/<id>/` and import stable host contracts through `integrations.sdk`, not directly from `app.*`.
- Core `app/` code must not bake in Claude-only tool names or permission semantics. Runtime adapters own tool classification and SDK-native translation.
- Harness approvals reuse `ToolApproval` but native harness tool prompts do not create linked `ToolCall` rows.
- Harness model, effort, and approval settings are session-scoped first so split panes, scratch sessions, and concurrent harness sessions do not trample each other.
- For channel-surface web commands, the current component/querystring session id is the session target. `channel.active_session_id` is only the primary/default fallback and the integration-mirroring pointer.
- Any future bridge from a harness into Spindrel tools must route through existing Spindrel dispatch, policy, approval, trace, and result-envelope paths.

### `schedule_task` split into `schedule_prompt` + `define_pipeline`; `/admin/tasks` → `/admin/automations`
**Decided 2026-04-25.** "Task" was overloaded across six execution models in the codebase. The single dual-purpose `schedule_task(prompt=..., steps=...)` tool was the worst LLM-confusion failure mode — the model had to know that omitting `steps` produced a Scheduled prompt and including `steps` produced a Pipeline definition, with no schema-level signal of the discriminator.

**What changed.**
- The `tasks` SQLAlchemy model is unchanged; this is a vocabulary + tool-surface split, not a model split. `task_type` already discriminated the two shapes.
- Bot-facing tool surface: `schedule_task` removed; replaced with `schedule_prompt` (no `steps`) and `define_pipeline` (requires `steps`). Both write through a private `_create_task_row` helper. `define_pipeline` lives in `app/tools/local/pipelines.py` next to `list_pipelines` and `run_pipeline`.
- Surrounding tool descriptions (`list_tasks` / `cancel_task` / `update_task` / `get_task_result` / `run_task`) updated to use the canonical Automation / Scheduled prompt / Pipeline / Run vocabulary from the glossary.
- `docs/guides/ubiquitous-language.md` gained an "Automations and scheduled work" section and a flagged ambiguity entry "Task is overloaded — use a precise term."
- Admin UI route `/admin/tasks` renamed to `/admin/automations`; old route returns a permanent redirect via the new `RedirectToAutomation` helper. Page label "Tasks" → "Automations" in palette, sidebar rail, settings index, spatial NowWell tooltip, and chat-card "View task" copy. Internal directory paths (e.g. `ui/app/(app)/admin/tasks/`) intentionally kept for minimal churn.
- Widget templates renamed: `app/tools/local/widgets/schedule_task/` → `widgets/schedule_prompt/`; new sibling `widgets/define_pipeline/` with the same shape but Pipeline-specific link copy.

**Out of scope (deferred).** Renaming `spawn_subagents` was considered. The readonly boundary it enforces is a code-level invariant in `app/agent/subagents.py`; the rename is not load-bearing and was deferred. Internal `Task` SQLAlchemy class name kept (internal vocabulary).

**Why.** User-driven review of the bot tool surface called out repeated LLM confusion between scheduled work and pipeline definitions. Per `feedback_one_commit_no_legacy` this ships without compat aliases or deprecated `schedule_task` shim — the URL redirect is operational continuity for bookmarks, not a code-shim deprecation pattern.

### Spatial bot autonomy uses global bot nodes with channel-scoped policy
**Decided 2026-04-26. Updated 2026-04-26.** Bots are first-class spatial canvas objects, but their authority to perceive or modify the canvas is granted per channel and surfaced primarily through heartbeat settings.

**What changed.**
- `workspace_spatial_nodes` now supports a third target shape, `bot_id`, alongside `channel_id` and `widget_pin_id`; the exactly-one CHECK and unique partial indexes cover all three.
- Bot positions are global per bot. The service auto-seeds nodes only for bots that participate as a channel primary bot or member bot, initially near one of their channels.
- Spatial access lives in `Channel.config["spatial_bots"][bot_id]`, not bot config and not the node row. The policy gates awareness injection, self movement, object tugs, nearby inspection, step sizes, per-turn budgets, radii, nearest-neighbor floor, and movement trace TTL.
- Bot movement is step-based. Bots never receive arbitrary coordinate writes; tools translate bounded cardinal steps into world-coordinate deltas.
- Object tugs require proximity, leave `last_movement` trace metadata on the target node, and publish a synthetic assistant message into the channel so the change is visible in normal chat history.
- Bot nodes render on the canvas and open a docked `ChatSession` resolved through an existing channel for that bot.
- `ChannelHeartbeat.append_spatial_prompt` is the opt-in canned context path for heartbeat runs. It appends a standard spatial-turn instruction block and seeds awareness-only policy defaults for the primary bot if no policy exists.
- Whole-map spatial viewing is also channel-scoped. `allow_map_view` gates the read-only `view_spatial_canvas` tool, which may only return the same surface-level viewport information a human would see at that zoom. Heartbeat map-overview injection is a separate heartbeat toggle and still requires `allow_map_view`.
- Spatial runtime controls live in the channel Heartbeat tab. Participants is a roster/status surface, not the primary place to configure movement, inspection, tugging, or widget-management behavior.
- Bots use `bots.avatar_emoji` for Spindrel bot presentation. The old URL field remains a data field, but current bot list/canvas UI does not fall back to it for spatial identity.
- Spatial widget management is distinct from object tugging. A bot can create/move/resize/remove only widgets it owns (`source_bot_id == acting bot`) and only when `allow_spatial_widget_management` is enabled.

**Load-bearing invariants.**
- Defaults are off. A bot receives no spatial context and no movement tools with effect unless the channel policy grants them.
- `workspace_spatial_nodes` remains the only source of truth for world positions. Channel config stores permission, not coordinates.
- Neighborhoods are hybrid: radius plus a nearest-neighbor floor, so a too-small radius does not make the bot blind.
- Widget-management authority never implies arbitrary canvas editing. Bot-owned widget tools operate on owned pins; tugs remain proximity-bounded and auditable.
- Bot-to-bot spatial notes / command cards are deferred; v1 only exposes awareness, movement, inspection, and auditable object tugs.

### Single visible sessions are route-level pages; chat panes are split/canvas layout only
**Decided 2026-04-24. Updated 2026-04-25.** Channel session switching now separates four concerns: browsing sessions, navigating to one visible session, arranging multiple visible chat panes, and choosing which session is primary for integrations.

**What changed.**
- `/sessions` is the browse/switch surface. Empty state groups Primary, previous channel sessions, and scratch sessions; search stays session-oriented and can show message/section snippets under the matching session row. Selecting a row navigates to that session as the single page.
- `/split` is the add-pane surface. It opens the same picker in split mode, hides already visible sessions, and starts from the current route-level session before adding the selected session beside it.
- One visible session is always a route-level chat view. It must not render as a single pane underneath another session/channel header.
- The visible chat area becomes a persisted pane layout only when two or more sessions are open, with up to three panes, resizable widths, pane headers, and close/rename/make-primary actions.
- `/focus` and the This Channel palette action collapse side panels plus the floating top chip rail into a focused chat layout, then restore the prior chrome state.

**Load-bearing invariants.**
- Primary is not "the left pane"; it is the channel's integration/default delivery session. A primary pane can be hidden, and integration mirroring still follows only the channel primary unless another session is explicitly promoted.
- Switching from `/sessions` exits canvas and changes the route. It never replaces a focused pane as a side effect.
- Closing or minimizing panes must not leave a one-pane canvas. If one pane remains, collapse to that session's route-level page and keep any minimized session in the mini-chat slot.
- Pane layout state is the source of truth only for real split/canvas mode. Legacy `sessionPanels` exists only as migration input and should not regain behavior ownership.
- Session-picker grouping/search and pane normalization live in `channelSessionSurfaces`, not scattered across route components.

### Rich tool-result rendering is an advisory integration capability with an SDK presentation boundary
**Decided 2026-04-24.** Rich tool results are not a new delivery path. Assistant text still delivers through durable `NEW_MESSAGE`; structured tool envelopes in message metadata are optional presentation data that capable renderers may use.

**What changed.**
- `rich_tool_results` declares that a renderer can render structured tool results natively.
- `integration.yaml:tool_result_rendering` declares the detailed support matrix: display modes, content types, view keys, fallback, placement, and limits.
- `integrations.tool_output` owns support matching and portable read-only card normalization.
- Slack is the v1 adapter. Unsupported envelopes fall back to compact badges; HTML/native widgets are not rendered outside the web host.
- Chat integration runtime code imports host contracts through `integrations.sdk`; direct `app.*` imports under `integrations/` are treated as boundary debt and guarded by `tests/unit/test_integration_import_boundary.py`.

**Load-bearing invariants.**
- Text fallback is always the durable baseline.
- `tool_result_rendering` is manifest-first; renderer ClassVars are fallback only.
- Rich-result rendering is read-only in v1. Widget actions do not become platform buttons.
- Approvals remain on `approval_buttons`, not generic rich-result actions.
- Existing tools are not hidden merely because a channel lacks rich-result support.
- The SDK import surface is allowed to re-export stable host contracts for integrations, including DB/session types, renderer registry access, settings helpers, hooks, auth helpers, and portable tool-output primitives.

### Light mode uses neutral surface depth, not extra accent color
**Decided 2026-04-24.** Light mode should not solve flatness by adding decorative color to individual screens or by introducing a second global accent. Spindrel keeps one primary accent, and light-mode hierarchy comes from a cooler neutral surface ladder plus shared component primitives.

**What changed.**
- The light `surface` / `surface-overlay` / `surface-border` / muted text / input-border tokens were retuned globally.
- The legacy `useThemeTokens()` light mirror was updated to match while that hook remains tolerated debt.
- The component catalog now records that repeated washout should be fixed in shared primitives, not route-level styling.

**Load-bearing invariants.**
- Dark-mode tokens remain their own baseline and are not retuned as part of light-mode contrast work.
- Accent color is for focus, active state, and semantic interaction, not ambient page decoration.
- If many settings/admin rows look flat, tune `SettingsControls` / `FormControls` recipes once before adding local chrome.

### Skill ID is decoupled from filesystem path via frontmatter `id:` override
**Decided 2026-04-24.** Skill IDs used to be strictly derived from the filesystem path (`skills/foo/bar.md` → id `foo/bar`), which meant any file rename or folder move CASCADE-deleted `bot_skill_enrollment` and `channel_skill_enrollment` rows via their FKs to `skills.id` and orphaned RAG chunks in `documents` (source `skill:foo/bar`). This coupling blocked organizational passes — every move was a migration event.

**What changed.**
- `_resolve_skill_id(default_id, meta) -> str` in `app/services/file_sync.py` returns `meta.get("id")` when present, stripped, non-empty, and matching `^[a-z0-9_/-]+$`. Falls back to the path-derived default otherwise.
- `sync_all_files` applies the override at Skill-row PK assignment time, and tracks effective (post-override) IDs for both orphan-detection and explicit duplicate-ID warnings.
- No schema change, no migration. Existing skills that don't set `id:` keep their path-derived IDs (100% backward compatible).

**Why this contract, not the alternatives.**
- A `deprecated_id` DB column + alias lookup would have added a permanent backward-compat layer that decayed with every future move.
- A one-time SQL remap migration would have solved this reorg but required a new migration for every future reorg.
- Frontmatter `id:` is the minimal change that decouples logical ID from physical path _forever_ — future moves cost zero migration.

**Defaults.**
- Skills without `id:` frontmatter: ID is derived from the filesystem path (unchanged behavior).
- Skills with `id:`: that exact string is the Skill row PK. Illegal overrides log a warning and fall back.

**Constraints.**
- Override characters must match `^[a-z0-9_/-]+$` — same class the path-derived IDs produce.
- Duplicates (two files claiming the same ID) log a warning and the second occurrence is skipped, so silent collisions are impossible.
- Bot-scoped `bots/{id}/skills/*.md` and integration-shipped `integrations/{id}/skills/*.md` loaders also honor the override.

### Widget pins persist canonical origin metadata, and runtime config is `widget_config`
**Decided 2026-04-23.** Dashboard/widget pins are no longer treated as envelopes that the runtime re-interprets later. They now persist canonical origin metadata plus contract/schema snapshots, and the runtime config namespace is explicitly `widget_config`.

**What changed.**
- `widget_dashboard_pins` now carries:
  - `widget_origin`
  - `provenance_confidence`
  - `widget_contract_snapshot`
  - `config_schema_snapshot`
- Pins with caller-supplied explicit `widget_origin` write `provenance_confidence = "authoritative"`; inferred rows stay `inferred`.
- Legacy rows self-heal to inferred origin/snapshots on read.
- Pin serialization resolves metadata from `widget_origin` first and falls back to snapshots if the live source cannot be re-resolved.
- Tool-widget substitution/runtime namespaces are now:
  - `result.*`
  - `widget_config.*`
  - `binding.*`
  - `pin.*`
- `config.*` is retained only as a compatibility alias.
- HTML-backed tool widgets now expose:
  - `window.spindrel.result`
  - `window.spindrel.widgetConfig`
  - `window.spindrel.widgetContext`
  - `window.spindrel.toolResult` as a compatibility object

**Why.**
- Pin reads were reconstructing too much from envelope/source heuristics, which made provenance and schema recovery fragile.
- The old `config` overlay silently collided with real payload fields named `config`, which is a bad DX contract and an unsafe reserved-name precedent.
- The canonical widget docs had already outpaced the actual runtime language. Persisted origin + explicit config namespaces close that gap.

**Load-bearing invariants.**
- `widget_origin` is the durable source-of-truth record for a pin's definition kind and instantiation path.
- Snapshots are the fallback contract when the live source is unavailable or ambiguous.
- `widget_config` is the public runtime-config namespace. New docs/templates should not introduce fresh `config.*` usage.
- HTML-backed tool widgets should read `window.spindrel.result` / `widgetConfig`; `toolResult` exists for compatibility, not as the preferred API.

### Widget semantics, authored presentation, and host policy are separate layers
**Decided 2026-04-23.** The widget system now explicitly distinguishes semantic contract, durable provenance, authored presentation intent, and final host rendering policy.

**What changed.**
- Widget metadata now carries `widget_presentation` with:
  - `presentation_family`
  - `panel_title`
  - `show_panel_title`
  - `layout_hints`
- Dashboard pins now persist `widget_presentation_snapshot` beside contract/schema snapshots.
- Frontend rendering now resolves a single host policy object from:
  - placement zone
  - authored `widget_presentation`
  - dashboard chrome
  - per-pin runtime overrides
- The canonical docs now teach:
  - `rail | header | dock | grid` as host zones
  - `card | chip | panel` as presentation families

**Why.**
- The previous model mixed authored intent with placement and host chrome, which made every new zone/mode add another special case.
- `panel_title` / `show_panel_title` and compact chip behavior were already load-bearing, but they lived in partially overlapping metadata paths.
- Extensibility requires one clean seam: authors declare intent once; the host resolves the final rendering policy per placement.

### `layout_hints` mean placement defaults and host-size bounds, not renderer responsiveness
**Decided 2026-04-23.** `layout_hints` now have one narrow meaning across docs and runtime.

**What changed.**
- `preferred_zone` seeds initial pin placement when callers do not pass an explicit zone.
- `min_cells` / `max_cells` clamp initial tile size and later resize bounds in the dashboard editors.
- Generic pin creation now consumes these hints, not just preset pinning.
- Frontend editors now apply the same bounds during resize.

**Why.**
- The old story was muddy: contracts serialized `layout_hints`, docs implied broader support, but only preset pinning actually consumed them.
- Future flexibility depends on separating host layout policy from widget-internal responsiveness. Renderers still recompose from measured host size; `layout_hints` just tell the host how large a tile should start and how far it may stretch.

**Load-bearing invariants.**
- `widget_contract` stays semantic; presentation-family concerns belong in `widget_presentation`.
- `widget_origin` answers "where did this pin come from"; it is not a styling contract.
- Placement zones and presentation families are different:
  - `header` is a zone
  - `chip` is a presentation family
- The host should render from one resolved policy object, not by reading raw booleans from multiple layers at render time.

### Channel-dashboard `header` is a floating top rail, and `chip` is an authoring alias rather than a persisted zone
**Decided 2026-04-23.** The top-of-chat widget area is now modeled as a real floating `header` rail, not a singleton chip slot and not a separate persisted `chip` zone.

**What changed.**
- `widget_dashboard_pins.zone` remains one of `rail | header | dock | grid`.
- `header` now uses normal tile coords with a hard 2-row cap instead of a forced singleton layout.
- Chat runtime renders `header` as a floating overlay spanning only the center workspace between the side panels.
- The channel dashboard editor authors against that same `header` geometry.
- Preset `preferred_zone: chip` now resolves to `zone=header` with compact `4x1` defaults.
- Compact chip widgets remain a dedicated widget family/presentation target, but their persisted placement still lives in `header`.

**Why.**
- The singleton header slot made the system lie: it suggested a real placement surface while only supporting one centered chip.
- The user expectation for the top band is overlay behavior over chat, not a layout row that consumes page height.
- `chip` is useful product vocabulary for authoring and presentation, but making it a persisted zone would duplicate the real host surface and complicate placement rules.

**Load-bearing invariants.**
- `header` is the only persisted top-of-chat zone.
- `header` floats over content; empty rail area must stay transparent/click-through.
- `header` spans only the center workspace, not the left rail or right dock.
- The host clamps `header` tiles to two rows; it does not auto-grow the rail.
- `chip` remains an authoring alias / compact widget family, not a database zone.
- Any widget may be placed in `header`, but only dedicated chip widgets are expected to look truly chip-native there.

### Local machine control is a core provider-backed machine-target subsystem, not an integration-owned exec surface
**Decided 2026-04-23.** "Run on my computer" is modeled as temporary control over one leased machine target, and that feature is core-owned with pluggable provider implementations.

**What changed.**
- Added a generic machine-target abstraction addressed by `(provider_id, target_id)`.
- Core now owns:
  - `app/services/machine_control.py`
  - provider-aware session leases
  - machine admin APIs
  - `/admin/machines`
  - transcript/result UX
  - the tools `machine_status`, `machine_inspect_command`, and `machine_exec_command`
- Provider integrations participate through a typed contract declared in `integration.yaml` plus `integrations/<id>/machine_control.py`.
- `local_companion` is the first provider implementation with `driver="companion"`.
- Enrolled companion targets still live in the `local_companion` integration settings JSON instead of new DB tables.
- Session control state lives in `Session.metadata_["machine_target_lease"]`.
- Tool registry now carries `execution_policy`; machine tools use `interactive_user` or `live_target_lease`.
- Companion routing is explicit by leased `target_id`; there is no "most recent connection wins" fallback.
- Direct bot/script-style execution surfaces hard-deny machine tools unless the same live-user lease invariant is satisfied.

**Why.**
- The product needs a native-feeling "operate on my machine" path, but server-side exec and local-machine exec are not the same trust boundary.
- SSH-first would have conflated headless LAN/server control with "my current local computer" pairing.
- Letting `local_companion` own the admin/UI surfaces would have forced future providers through an integration-specific product surface.
- The right safety contract is explicit, session-scoped, user-held control state, not an ambient ability any background run can reuse.

**Load-bearing invariants.**
- Machine control is core-owned; integrations implement providers but do not own the generic machine admin/session UX.
- A machine target is always explicit. Routing must never fall back to recency.
- One session may lease only one target; one target may be leased by only one session.
- Lease-gated tools require:
  - a live JWT user
  - active presence
  - an unexpired lease for the current session
  - the same leasing user
  - a freshly ready target after provider validation
- Autonomous origins (`heartbeat`, `task`, `subagent`, hygiene-style runs) are denied even if other context exists.
- API-key/script surfaces do not gain local-machine power by virtue of being able to call tools.
- Future implementations such as SSH should plug into the same provider contract instead of inventing parallel machine-control stacks.
- SSH, browser control, file sync, or other desktop automation should reuse the same machine-target + lease abstraction instead of inventing parallel consent paths.

### Machine-control readiness is provider-generic probe state, and provider credentials live in persistent settings
**Decided 2026-04-24.** The machine-control contract no longer treats "connected companion socket" as the universal runtime truth.

**What changed.**
- Providers now expose cached status plus a fresh `probe_target()` path instead of a core contract centered on `get_target_connection()`.
- Canonical target/lease payload fields are now:
  - `ready`
  - `status`
  - `reason`
  - `checked_at`
  - `handle_id`
- Compatibility aliases such as `connected` / `connection_id` remain only as transitional read surfaces.
- Lease grant and lease-gated execution now require a fresh successful provider probe.
- Shared inspect-command validation moved into core before provider dispatch.
- `ssh` shipped as the second provider on this contract.
- Provider credentials/trust for durable machine access live in app-managed integration settings, not ephemeral container filesystem state.

**Why.**
- The previous contract was shaped too tightly around `local_companion` and a live websocket.
- SSH and future providers still need one common UX and policy surface, but they do not all keep a live connection object.
- The real cross-provider gate is "can this target execute right now?", not "does this provider happen to have a socket?"
- Durable machine setup cannot disappear on container rebuild; app-managed settings are the correct persistence boundary.

**Load-bearing invariants.**
- `ready` is the canonical cross-provider execution gate.
- UI may render cached readiness, but lease grant and lease-gated execution must require a fresh provider probe.
- A provider may implement readiness via a live connection, an on-demand probe, or another transport-specific check, but core policy must stay transport-agnostic.
- Durable provider credentials/trust belong in integration settings or another persistent app-managed store, not runtime temp files or container-local mutable state.
- Runtime temp files are allowed only as short-lived materialization for subprocesses and must be deleted after use.

### Machine-control UX is transcript-first, with optional pinned widget convenience and no default chat-header chrome
**Decided 2026-04-24.** Machine control should not surface as ambient top-right chat chrome.

**What changed.**
- Removed the default session-scoped machine chip from `ChannelHeader`.
- Added `core/machine_control_native` as a channel-scoped native widget users may pin explicitly.
- Kept required lease and execution flows in transcript/result surfaces:
  - `core.machine_access_required`
  - `core.machine_target_status`
  - `core.command_result`

**Why.**
- Header chrome implied ambient machine capability and introduced distracting load/flicker behavior.
- The important actions are session-specific and task-specific, so transcript surfaces are the right primary consent path.
- A widget is a better secondary surface because it is explicit, pinnable, and already fits the host’s native React/widget architecture.

**Load-bearing invariants.**
- Machine control does not mount as default chat-header chrome.
- Required machine-control interactions stay transcript-first.
- Any persistent machine-control affordance in the channel workspace should use the native widget system rather than bespoke header controls.
- `core/machine_control_native` is convenience UI only and must not export pinned-widget context into the prompt.

### Machine-control provider profiles are core-owned abstractions; SSH uses them first with no ambient fallback
**Decided 2026-04-24.** Reusable machine credentials/trust belong to the machine-control subsystem as provider-scoped profiles, not to ad hoc provider-global settings or a cross-integration credential vault.

**What changed.**
- Core machine-control summaries and admin APIs now expose provider profiles generically:
  - `supports_profiles`
  - `profile_fields`
  - `profiles`
  - `profile_count`
  - `/api/v1/admin/machines/providers/{provider_id}/profiles/*`
- `Admin > Machines` now owns profile CRUD for any provider that declares profile support.
- Integration pages no longer act as machine CRUD/setup shadows; they point back to the core machine center.
- `ssh` is the first provider to adopt this:
  - SSH targets now reference one explicit `profile_id`
  - named SSH profiles hold private key + `known_hosts`
  - the old provider-global `SSH_PRIVATE_KEY` / `SSH_KNOWN_HOSTS` runtime path is retired
  - no automatic fallback wraps or reuses those old top-level settings

**Why.**
- Multiple SSH targets need multiple independent identities/trust bundles, but solving that as an SSH-only hack would have leaked provider assumptions into core UX.
- A global cross-integration credential subsystem would be too broad and would violate the desired integration/app boundary in the other direction.
- The right abstraction is "provider-scoped machine-control profiles": core owns the UX and contract; providers own schema, validation, storage, and runtime resolution.

**Load-bearing invariants.**
- Profiles are machine-control-provider scoped, not a global credential vault.
- Core owns generic profile APIs and UI; providers own profile semantics and persistence.
- Profile-capable providers must require explicit target-to-profile binding rather than ambient provider-global credential fallback.
- Profile list/read surfaces may expose only safe summaries and secret-presence markers, never raw secret values.
- Integration pages may expose provider-wide settings, but machine profile lifecycle lives in `Admin > Machines`.

### Sub-agents are experimental readonly sidecars, not a default orchestration primitive
**Decided 2026-04-23.** `spawn_subagents` is no longer treated as a generally encouraged prompt-level tool.

**What changed.**
- Generic base-prompt and delegate-index nudges telling bots to use subagents were removed.
- Plan-mode subagent guidance remains separately gated and default-off.
- Built-in subagent presets were narrowed to readonly tools only.
- Subagent runtime now drops mutating, exec-capable, control-plane, unknown, and recursive delegation tools.
- Subagent runs no longer bypass tool policy.
- Each child run now records explicit `subagent_started` / `subagent_finished` trace events with tool/model metadata.

**Why.**
- The earlier contract encouraged models to use subagents casually before the orchestration pathway had been fully vetted.
- A readonly wrapper around exec-capable child work plus `skip_tool_policy=True` was an unsafe mismatch.
- The right first contract is bounded sidecar research, not arbitrary delegated execution hidden inside a tool call.

**Load-bearing invariants.**
- `spawn_subagents` is for bounded, parallel, readonly side work only.
- Subagents are never the default answer to "help me think."
- Prompt guidance must not encourage general subagent use unless a separate reviewed pathway explicitly enables it.
- Child runs must remain observable through persisted trace events.

### Skills-in-context is a canonical runtime residency set, not an accidental transcript side effect
**Decided 2026-04-23.** The runtime now treats "this skill is already in prompt context" as an explicit per-turn fact shared by prompt assembly, `get_skill`, and UI metadata.

**What changed.**
- Context assembly now derives a canonical `skills_in_context` set from the actual active assistant history that survives replay/pruning for the current turn.
- Each resident skill records:
  - `skill_id`
  - `skill_name`
  - `source` (`loaded` or `auto_injected`)
  - `messages_ago`
- The enrolled-skill index now marks resident skills as `[loaded]` and explicitly tells the model not to call `get_skill` again unless it intentionally wants a fresh copy.
- `get_skill()` now accepts `refresh: bool = false`.
- If the requested skill is already resident and `refresh` is not set, `get_skill()` returns a lightweight "already loaded" result instead of pasting the full skill body into context again.
- Existing `active_skills` metadata remains as a compatibility projection for UI paths that only understand manually loaded skills, but `skills_in_context` is now the canonical superset.

**Why.**
- The previous model had three conflicting realities:
  - sticky `get_skill` tool results often remained in replayed history,
  - prompt text still told the model to call `get_skill` "FIRST",
  - UI metadata tracked "active skills" separately from the real prompt window.
- That made duplicate skill fetches easy and hard to reason about. The model could already have the skill in context, but nothing in the runtime clearly told it so.
- A canonical residency model is also the right place to support deliberate refresh/reordering later without pretending every duplicate fetch is useful.

**Load-bearing invariants.**
- "Already loaded" means resident in the active prompt window for this turn, not merely present somewhere in persisted session history.
- Duplicate `get_skill()` calls must not reinsert the full skill body by default when the skill is already resident.
- Intentional reload is still allowed, but it must be explicit via `refresh=true`.
- Prompt guidance, runtime tool behavior, and UI metadata must all derive from the same residency computation; do not maintain separate "active skill" heuristics as the primary source of truth.
- Auto-injected skills and manually loaded skills share the same residency surface; they differ only by `source`.

### Plan mode state is a runtime capsule plus a Markdown artifact
**Decided 2026-04-23.** Session plan mode no longer treats the Markdown plan file as the only load-bearing state.

**What changed.**
- `Session.metadata_["plan_runtime"]` now stores the compact execution capsule: mode, current/next step ids, accepted/current revisions, next action, blockers, unresolved questions, replan metadata, pending/latest turn outcomes, and compaction watermark.
- `Session.metadata_["planning_state"]` stores visible durable planning notes: confirmed decisions, open questions, assumptions, constraints, non-goals, evidence, and preference changes.
- `Session.metadata_["plan_adherence"]` stores recent execution evidence, recent progress outcomes, semantic review history, and the current adherence status.
- Plan-state and plan endpoints return both `runtime` and deterministic `validation`.
- Approval rejects structurally incomplete plans instead of relying on prompt guidance.
- `request_plan_replan` is the explicit transition when execution proves the accepted plan is stale.
- `record_plan_progress` is the explicit per-turn execution outcome contract; turn-end supervision marks missing outcomes as pending and blocks further mutation until the outcome or replan is recorded.
- Semantic review is a separate on-demand pass over persisted turn evidence; it writes `semantic_status`/`latest_semantic_review` without replacing deterministic adherence.

**Why.**
- Markdown is readable but too fuzzy to be the only execution contract.
- Short planning/execution context windows and automatic compaction need a compact state capsule that can be injected every turn.
- Adherence cannot depend only on instructions; the runtime must block thin/unresolved plans and provide a typed replan path.

**Load-bearing invariants.**
- Markdown remains the canonical human-readable artifact.
- The runtime capsule is the canonical compact state summary for context injection and UI status.
- Planning-state is visible durable user/agent back-and-forth, not an invisible hidden plan.
- Adherence evidence and outcomes are compact supervision input, not proof that semantic step success has been fully verified.
- Protocol adherence and semantic adherence are separate surfaces and separate fields.
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

### Heartbeat execution policy is an enforced runtime layer
**Decided 2026-04-25.** Heartbeat `execution_policy` is not prompt guidance; it is a runtime policy layered on top of the restrictive `heartbeat` context profile.

**What changed.**
- `target_seconds` is an enforced soft elapsed-time budget. It triggers the same `heartbeat_budget_pressure` and in-loop pruning path as soft LLM-call and current-token budgets.
- `tool_surface` is enforced during context assembly:
  - `focused_escape` exposes retrieved tools, explicit tags, heartbeat-injected tools, and limited discovery escape hatches.
  - `strict` exposes retrieved/explicit/injected tools only.
  - `full` preserves broad chat-like pinned/discovery behavior.
- `provider_state` is reserved and normalizes back to `stateless` until the loop owns response-id retention, expiry, and replay semantics end to end.

**Load-bearing invariants.**
- Heartbeat policies must not expose fields that look active unless the runtime enforces them.
- Broad pinned tools must not leak into default heartbeat runs through a separate discovery or widget-handler path.
- `max_run_seconds` remains the outer hard timeout; soft budgets are pressure signals that ask the model to finish after pruning.

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

### Secondary channel-session panels are web-only unless made primary
**Decided 2026-04-24.** Channel split panels can mount historical/non-primary channel sessions as writable chat surfaces, but integration delivery remains attached only to the channel's primary session.

- Web clients targeting an explicit secondary channel session must send `external_delivery: "none"`; the backend rejects mirrored delivery for non-primary channel sessions.
- Session-scoped secondary turns still publish typed events on the parent channel bus tagged with `session_id`, so the split panel can stream them while the primary channel transcript ignores them.
- Queued secondary turns carry the same session-scoped execution flag so task-worker persistence suppresses outbox rows after the lock releases.
- Channel settings should make this explicit: dispatcher bindings mirror only the primary session; split sessions are web-only until promoted/switched primary.

Rationale:
- This keeps Slack/Discord/iMessage integrations from receiving replies from multiple visible web panels at once.
- The UI can evolve toward a canvas/split-screen model without inventing a second delivery system or weakening the existing `channel.active_session_id` contract.

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
- `plan_runtime` remains the compact execution state machine: accepted revision, current step, next action, blockers, replan, pending/latest turn outcomes, compaction watermark.
- `plan_adherence` records deterministic execution evidence plus explicit progress outcomes: progress, verification, step done, blocked, or no progress.
- `ask_plan_questions` answers are persisted both as a normal user message and as structured `planning_state` decisions.
- `publish_plan` validation warns if confirmed planning decisions are not visibly reflected in the draft.
- Tool dispatch gates mutating tools in planning mode and also blocks mutating execution when the accepted revision/current-step contract is invalid, blocked, or pending replan.
- Turn-end supervision marks executing/blocked turns without an explicit outcome as pending, and only `record_plan_progress` or `request_plan_replan` can clear the protocol block.
- Semantic review is user-triggered from the normal plan card, reconstructs persisted turn evidence by `correlation_id`, and writes `supported | weak_support | unsupported | needs_replan` without hard-blocking execution yet.

**Why.**
- Codex/Claude-style harnesses succeed by injecting the right small contract at the right time and gating side effects before they happen.
- Chat history and compaction summaries are too lossy to be the source of truth for multi-turn planning.
- The first reliable supervisor should be deterministic protocol enforcement plus evidence capture; semantic judging can come later as evals mature.

**Remaining gap.**
- Semantic review now exists, but it is still warning-only and judge-calibration/eval work is still needed before any sampled auto-review or hard gating.

### Integration runtime modules depend on the SDK bridge, not `app.*`
**Decided 2026-04-24.** Runtime integration code imports app-owned contracts through `integrations.sdk`. The only integration files allowed to import `app.*` directly are the infrastructure shims: `integrations/__init__.py`, `integrations/sdk.py`, and `integrations/utils.py`.

**What this means.**
- New integration routers, tools, renderers, config modules, and machine-control modules should not import `app.*` directly.
- If an integration needs an app-owned model, service, context var, dependency, or helper, expose it through `integrations.sdk` first.
- The static import-boundary test is now strict: there is no runtime-module allowlist for direct app imports.

**Why.**
- The SDK is the thin public interface for a deep integration module.
- Keeping app imports inside infrastructure shims makes dependency direction obvious and keeps future integration packaging work tractable.
- Tests should protect the boundary instead of documenting a growing debt list.

### Conversation-history admin views are current-session-first
**Decided 2026-04-25.** Runtime conversation history is session-scoped; admin Memory/History views must make that same boundary visible instead of flattening every archived section in the channel by default.

**Contract.**
- The current-session scope mirrors what the active chat can browse with `read_conversation_history`.
- All-sessions scope is an explicit admin inventory view. It may group and search across sessions, but copy must not imply the bot sees that flattened archive automatically.
- Section index preview is current-session-scoped because it previews prompt injection.
- Backfill/resume/re-chunk operate on the channel's current primary session, not every session attached to the channel.
- Section rows in cross-session views carry session metadata so users can see which chat produced each archive section.

**Why.**
- Primary, scratch, and previous channel sessions are equal transcript owners, but only one session is active for a single turn.
- Showing all archived sections as the default made a new primary session look like it already had 100+ sections and suggested the agent had access to a flattened channel memory it does not actually receive.
- Keeping inventory available behind an explicit scope preserves admin discoverability without lying about runtime context.

### Attention Items own attention state; Beacons are canvas rendering
**Decided 2026-04-26.** Human-visible warnings and structured system failures use one `WorkspaceAttentionItem` domain model. The Spatial Canvas renders active items as Attention Beacons, but spatial nodes do not own warning lifecycle.

**Contract.**
- `workspace_attention_items` owns source, target, severity, status, dedupe, occurrence count, evidence, response metadata, and assignment state.
- `workspace_spatial_nodes` remains the single source of truth for canvas positions only.
- Bot-authored beacons are created through policy-gated heartbeat/spatial tools and attach to existing channel/bot/widget/system targets.
- User-authored items are first-class Attention Items and can be created from the Attention Hub.
- Structured system failures are admin-only Attention Items; bot-authored and user-authored channel beacons remain visible to non-admin channel viewers.
- Reply status is distinct from resolution: a response marks `responded`, while humans or the source bot must still resolve the item.
- Assignment adds workflow state around the item rather than overloading item lifecycle. V1 assignment modes are `next_heartbeat` and `run_now`, both investigate/report only.
- The Spatial Canvas renders badges inside the target node or cluster shell with inverse scaling, so badges stay screen-sized but move with the bound object.
- The Attention Hub is the shared triage surface for lanes, manual intake, assignment, bot findings, and trace evidence.

**Why.**
- The same visual marker can represent a bot warning, a human-created item, an automatic trace failure, or investigate/report work without duplicating models.
- Keeping coordinates out of the attention table prevents a second spatial placement source of truth.
- Keeping assignment separate avoids painting a simple alert model into a command-queue corner too early.

### Harness host state is session metadata, not channel active state
**Decided 2026-04-26.** External harness runtime controls and host-side continuity state are bound to `Session.id`. `Channel.active_session_id` remains only the primary/default session and integration-mirroring pointer.

**What this means.**
- Harness model, effort, approval mode, native resume reset, and one-shot host hints live under `Session.metadata`.
- Web UI controls and slash commands must target the current component/querystring session id when present, falling back to `channel.active_session_id` only when no explicit session is supplied.
- Harness `/compact` resets the native resume boundary for that session and injects a continuity summary as a one-shot hint.
- Harness heartbeats enqueue host hints onto the channel primary session for now; scratch/split fanout requires an explicit future policy.

**Why.**
- Scratch, split, and primary panes are equal runtime sessions in the web app. Mutating the channel primary from another pane corrupts the wrong Claude/Codex native thread.
- A harness owns its native context, so host continuity needs a small explicit state contract instead of trying to reuse normal context sections/backfill.

### Bridged harness tools execute through Spindrel dispatch
**Decided 2026-04-26.** When a harness sees Spindrel tools, it sees adapter definitions only. Invocation routes back through `dispatch_tool_call`; runtimes do not call registry functions directly.

**What this means.**
- Tool definitions are resolved from the effective bot/channel tool set, including auto-injected tools and activated integration tools.
- Browser-client tools are excluded from server-side harness bridges.
- Policy checks, approval cards, trace/audit rows, secret redaction, result summarization, and stored tool-call rows remain centralized in the normal dispatcher.
- Claude Code uses the SDK's in-process MCP helper surface as the transport when available; other runtimes can map the same host adapter to their native tool mechanism.

**Why.**
- Direct runtime calls would bypass the security and observability properties users expect from Spindrel tools.
- A transport-specific adapter keeps Claude/Codex details out of core tool dispatch while still allowing harnesses to feel normal over time.
