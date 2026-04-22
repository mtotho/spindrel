# Architecture Decisions

## Guiding Principles
- **Product identity**: "Best self-hosted personal AI agent"
- **Target user**: Runs Ollama/local models, wants more than chat, values self-hosting
- **Design philosophy**: Reduce config surface, maximize auto-discovery
- **Integration isolation**: NO integration-specific code in `app/` — must live in `integrations/{name}/`

## Key Decisions

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
- **Legacy HTML Notes is compatibility-only.** Keep the old bundle on disk for existing pins/direct refs, but hide it from library discovery so new Notes placements use `notes_native`.

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

**Discoverability.** `scripts/entrypoint.sh` prepends `/opt/spindrel-pkg/usr/bin:/opt/spindrel-pkg/usr/local/bin:/opt/spindrel-pkg/usr/sbin` to `PATH` and `/opt/spindrel-pkg/usr/lib/x86_64-linux-gnu:/opt/spindrel-pkg/usr/lib` to `LD_LIBRARY_PATH` before `exec gosu spindrel uvicorn`, and forwards both across the gosu boundary via `env VAR=... VAR=...`. `shutil.which("chromium")` then returns `/opt/spindrel-pkg/usr/bin/chromium`, and the existing `_is_system_dep_available` check in `_check_system_deps` returns true → reinstall loop skipped entirely on rebuild.

**Idempotence.** Per-package file list written to `/opt/spindrel-pkg/.extracted-manifest/<pkg>.list` after a successful extraction. `_package_already_extracted()` is an O(1) file-exists check that makes repeat calls no-ops — this is what keeps the startup `ensure_integration_deps` loop silent on every rebuild after the first.

**Ownership.** Volume is chowned to `spindrel:spindrel` in the entrypoint so `dpkg -x` and the admin clear endpoint both run unprivileged. The `/etc/sudoers.d/spindrel-apt` rule stays narrow (apt-get only) — dpkg and rm don't need sudo.

**Sibling volumes** cover the rest: `spindrel-home:/home/spindrel` holds `~/.local/bin`, `~/.cache/{pip,huggingface,ms-playwright}`, `~/.npm`, `~/.claude`, any ad-hoc agent installs. `spindrel-apt-archives:/var/cache/apt/archives` keeps downloaded `.deb` files around as a source for dpkg-x on future installs (and lets apt-get update skip work via the persisted lists). Dockerfile drops `/etc/apt/apt.conf.d/docker-clean` and writes `Binary::apt::APT::Keep-Downloaded-Packages "true"` so those archives stop auto-wiping.

**Reset surface.** Admin-scoped `GET/POST /api/v1/admin/install-cache[/clear]` with `target: "pkg" | "home" | "apt" | "all"`. Each branch wipes contents only, never the mount point (would break the bind until restart). UI card on the Diagnostics page.

**Unrelated concerns intentionally kept out.** `/workspace-data` (agent-authored files) is a separate volume with its own lifecycle. Re-embedding skills/tools on rebuild is not a real problem — they're bind-mounted, embeddings live in `pgdata`, upserts are SHA256 content-hash-gated. Supersedes the "System deps lost on every Docker rebuild" Loose End (surfaced 2026-04-15, shipped 2026-04-21) and the earlier-same-day "archive-cache speedup" fix that missed the mark.

### Thread-session outbox enqueue is transactional with message persist
**Decided 2026-04-20.** The thread branch of `persist_turn` (`app/services/sessions.py`) enqueues outbox rows *before* `db.commit()`, inside the same transaction that inserts the assistant `Message`. Previously it committed the message first and then called a helper (`enqueue_new_message_for_thread_session`) that opened its own session and swallowed failures — a dispatch-side problem would silently leave a persisted message with no outbound delivery. The new shape matches the channel branch exactly: `resolve_targets(channel_row)` + `apply_session_thread_refs(session_row, targets)` + per-record `outbox.enqueue(db, bus_ch, event, targets)`, all before `db.commit()`. Delivery is now all-or-nothing with persistence, same durability contract the channel path has always had. `enqueue_new_message_for_thread_session` deleted from `outbox_publish.py` — `persist_turn` was its only caller. Triggered by Codex adversarial review of Phase 7. See [[Track - Task Sub-Sessions#Phase 7 hardening — atomic thread outbox + race-safe external thread resolution (shipped 2026-04-20)]].

### External-thread refs are uniqueness-enforced at the DB level
**Decided 2026-04-20.** Migration 231 replaces migration 230's non-unique `ix_sessions_slack_thread_lookup` with a **partial unique index** on `(integration_thread_refs->'slack'->>'channel', integration_thread_refs->'slack'->>'thread_ts')` scoped to `session_type='thread' AND thread_ts IS NOT NULL`. App-side, `resolve_or_spawn_external_thread_session` (`app/services/sub_sessions.py`) now wraps the spawn in `db.begin_nested()` + `db.flush()`; on `IntegrityError` it re-runs the lookup and returns the winner, rolling back only the savepoint (outer transaction — `persist_turn`, inbound router — stays intact). Chose a partial unique index + SAVEPOINT retry over a Postgres advisory lock because the index is declarative (no code has to remember to acquire it) and the SAVEPOINT pattern is SQLAlchemy-idiomatic for "spawn if not exists" flows. SQLite doesn't enforce the partial clause at index-creation time (tests run there), so the app-level retry branch is what the unit suite exercises; Postgres enforces it in production. Discord / future thread-mirroring integrations add their own sibling partial unique index per-ref-shape — not globalized because each integration's ref dict has different keys. Triggered by Codex adversarial review of Phase 7. See [[Track - Task Sub-Sessions#Phase 7 hardening — atomic thread outbox + race-safe external thread resolution (shipped 2026-04-20)]].

### Configurator skill + `propose_config_change` replaces featured audit pipelines
**Decided 2026-04-20.** The ambient "fix my config" UX is now an organic chat-driven path, not a launchpad of structured audit pipelines. Six featured `analyze_*` / `full_scan` pipelines accumulated noise because "audit everything in one pass" can't meet the ≥2-correlation_id evidence contract; only `analyze_discovery` produced apply-worthy proposals. The replacement:

- **Skill**: new folder layout `skills/configurator/{index,bot,channel,integration}.md`. `index.md` teaches a per-scope decision table + evidence rule; sub-skills `bot.md` / `channel.md` / `integration.md` carry the scope-specific investigate-and-propose playbook + field allowlists. Loadable via `get_skill("configurator/bot")` etc.
- **Tool**: new `app/tools/local/propose_config_change.py`. `safety_tier="mutating"` so the existing tool-policy approval gate fires (`TOOL_POLICY_DEFAULT_ACTION=require_approval` default). Per-scope allowlists mirror the pipeline PATCH whitelists — bot: 7 fields, channel: `pipeline_mode / layout_mode / config.<whitelist>`, integration: `enabled / config.<key>`. On approve, the tool PATCHes via direct SQLAlchemy / `set_status` / `update_settings`. Evidence is a required argument (≥1 signal string; skill enforces ≥2 correlation_ids).
- **Pipeline surface**: five YAMLs flipped to `featured: false`. They stay on disk for Library-drawer use; only `analyze_discovery` remains featured.

**Why this shape.** Narrow tool with validation + per-scope allowlist beats bespoke pipelines (one multi-step audit per knob) beats a giant `call_api` that mutates anything. Tool-policy approval gate is already wired; a structured `InlineApprovalReview`-style widget is a follow-up but not required for v1. Skill folder layout is a pre-req that also unblocks Widget Library Phase 3's planned `skills/widgets/` reorg — same loader change, no duplicated work.

**Load-bearing implementation choices.**
- **Skill loader walks folders.** `app/services/file_sync.py::_walk_skill_files` + `app/agent/skills.py::list_available_skills` recognize `skills/<name>/index.md` (or `README.md`) as the folder entry; `skills/<name>/<sub>.md` registers as `<name>/<sub>`. Flat `skills/<name>.md` still works. Both layouts coexist.
- **Tool is `mutating`, not a bespoke "proposal" type.** Every call routes through the standard approval gate; the approval UI shows args. No new DB table, no new endpoint, no new renderer required for v1. A nicer widget-based review is deferred to when it's clear the plain approval prompt is insufficient.
- **Per-scope PATCH is done directly, not via HTTP.** Bot: setattr + commit. Channel: deepcopy config JSONB + set key + `flag_modified`. Integration: `set_status` or `update_settings`. No internal HTTP → no auth token plumbing.

Plan: `~/.claude/plans/scalable-prancing-music.md`. Superseded: [[Track - Task Sub-Sessions#Phase 4 — Orchestrator "Home" redesign: settings lattice + ubiquitous ephemeral chat (PARKED 2026-04-20)]] (parked; the skill answers the same ask at a fraction of the scope).

### Mobile hamburger on channel routes opens a tabbed drawer; desktop keeps plain palette
**Decided 2026-04-20.** On the channel chat screen, the mobile hamburger no longer opens the global CommandPalette — it opens a new `MobileChannelDrawer` (`ui/app/(app)/channels/[channelId]/MobileChannelDrawer.tsx`) with three tabs: `[Widgets (N)] [Files] [Jump]`. Default tab = Jump, which embeds `CommandPaletteContent variant="modal"` inline so muscle memory for the palette keeps working. Widgets tab shows every channel-dashboard pin grouped by zone (Header / Rail / Dock / Grid) so mobile users see full dashboard contents regardless of the chat-screen layout mode. Files tab = existing `FilesTabPanel`. Desktop ⌘K and mobile non-channel hamburger still open the plain CommandPalette — no tab-strip chrome there.

**Why.** Mobile had three surfaces doing overlapping jobs — hamburger (palette/nav), bottom sheet (channel OmniPanel), peek tabs (collapsed docks). Folding widget + file + nav access into one drawer removed the surface count without taking away any functionality. Desktop has OmniPanel in the rail already, so adding channel tabs to desktop ⌘K would duplicate chrome users don't need. `MobileOmniSheet.tsx` is deleted; `fileExplorerOpen` now drives the drawer open-state on mobile (same state key, same triggers).

### Chat-screen zones are gated by `channel.config["layout_mode"]`
**Decided 2026-04-20.** A channel may now pick how its dashboard zones surface on the chat screen via a four-value `layout_mode` stored in `Channel.config` JSONB:

| Mode                 | Rail | Header chips | Dock | Chat |
|----------------------|------|--------------|------|------|
| `full` (default)     |  ✓   |     ✓        |  ✓   |  ✓   |
| `rail-header-chat`   |  ✓   |     ✓        |  —   |  ✓   |
| `rail-chat`          |  ✓   |     —        |  —   |  ✓   |
| `dashboard-only`     |  —   |     —        |  —   |  redirect card → `/widgets/channel/:id` |

**Why.** The full chat-screen layout (rail + header + dock + chat) is great for active conversation channels but wrong for channels that are really widget dashboards (a Frigate wall, a Home Control panel, etc.). Letting the owner pick the mode per channel avoids a one-size-fits-all compromise. Grid pins always persist on the dashboard regardless of mode — `layout_mode` only affects what surfaces on the chat screen. Mobile drawer always shows every zone regardless, so the setting is purely a chat-screen chrome knob.

**Load-bearing implementation choices.**
- **No schema migration.** Layout mode rides on the existing `channels.config` JSONB, same pattern as `pipeline_mode`. `"full"` is serialized as a missing key to keep defaults lean.
- **UI lives in `/channels/:id/settings` under a new "Layout" section.** Not in the dashboard edit bar — discoverability matters more than proximity to the editor.
- **Unknown values default to `"full"`** on the client (graceful) but are rejected with 422 on the API (strict) — typos can't silently no-op.

### Dashboard editor is desktop-only by design on mobile
**Decided 2026-04-20.** `/widgets/channel/:id` on viewports < 768px renders a `MobileEditorGate` card pointing users at the chat screen + offering a "Copy desktop link" affordance instead of the multi-canvas editor. The editor's hardcoded rail (300px) + dock (320px) widths don't translate to portrait phones, and DnD gestures aren't usable on touch. Mobile users see their channel's widgets via `MobileChannelDrawer`'s Widgets tab (all zones listed) — no duplicate rendering path.

**Why.** Making the multi-canvas editor responsive would be a large piece of work with marginal payoff — the typical author workflow is keyboard + mouse. The drawer already surfaces every pin on mobile; mobile authoring would just be a convenience for a tiny use case. Scoping explicitly to desktop keeps both the editor's architecture and the polish surface contained.

### Interactive-HTML widget pins carry an auth-scope choice (user vs bot)
**Decided 2026-04-20.** A pin's `source_bot_id` is now the single discriminator for iframe auth scope, chosen explicitly at pin time from the catalog:
- **`source_bot_id = null` → user scope.** `InteractiveHtmlRenderer` skips `/widget-auth/mint` and bakes the viewer's own bearer into `state.token`. Endpoints accept it via `verify_auth_or_user`. Each viewer sees data through their own account.
- **`source_bot_id = <uuid>` → bot scope.** Existing mint flow. Every viewer sees the same data through the bot's scoped API key (lets a shared widget expose state no individual viewer could read).

**Why.** The Widget SDK Phase B.6 suite work established "dashboard slug IS the scope" for the shared-SQLite DB — but left iframe auth untouched, which still assumed every interactive-HTML widget was bot-emitted. User-pinned suites (MC Kanban / Timeline / Tasks, HTML-widget catalog pins) had no natural bot, so they silently shipped with `source_bot_id = null`, `shouldMint = false`, no token, and `sp.db.query()` hung forever waiting for a bearer that never arrived. The catalog could have defaulted to a channel's bot, but that's a hack that hides the actual choice: *whose credentials is this widget running under?*

**Load-bearing implementation choices.**
- **No schema change.** The existing nullable `widget_dashboard_pins.source_bot_id` column already encodes both states.
- **`AddFromChannelSheet` exposes the choice explicitly.** Scope picker on HTML Widgets + Suites tabs with two labels: "You — each viewer sees data through their own account" vs "A bot — every viewer sees the same data through the bot's credentials." Default: user. Pre-existing paths (Recent calls, From channel) don't show the picker — those envelopes already carry an emitting `source_bot_id` from the tool call.
- **Suite pin defaults to whole-suite scope.** One scope setting applies to all members of a suite at pin time; per-pin override happens later via the pin drawer (existing rename/config flow).
- **`create_suite_pins` now stamps `source_kind` + `source_integration_id`.** Inferred from `SuiteManifest.source_path` — built-in suites get `"builtin"`, integration suites get `"integration"` + the integration id. Without this the iframe defaulted to `"channel"` and fetched built-in HTML from the wrong endpoint.
- **Scope chip renders for both modes.** Bottom-left pill on every interactive-HTML tile reads `@botname` or `as you` with a tooltip explaining whose permissions are in effect — the security posture stays visible to viewers.
- **Pin-implicit channel auth still composes.** A user-scoped pin on a `channel:<uuid>` dashboard can still hit channel-scoped reads via the session-14 pattern: `ApiKeyAuth.pin_id` check remains the same, and user JWTs with dashboard membership are accepted independently.

### Widget-JWT pins grant implicit channel-scoped read access
**Decided 2026-04-20.** `app/dependencies.py::ApiKeyAuth` now carries an optional `pin_id` captured from the widget JWT (`kind: "widget"` tokens minted by `POST /api/v1/widget-auth/mint`). Channel-scoped read endpoints that opt into the pattern — starting with `/channels/{id}/context-budget` and `/context-breakdown` — accept the call when the caller's `pin_id` resolves to a dashboard with slug `channel:<channel_id>` matching the request path, **regardless of scope**. The UI renderer (`InteractiveHtmlRenderer.tsx`) now posts `pin_id` alongside `source_bot_id` at mint time, keyed on both so different pins mint different tokens.

**Why.** Widgets authenticate as the emitting bot via a JWT inheriting that bot's API-key scopes. Requiring every widget-emitting bot to carry `channels:read` just so pinned widgets can render their host channel's context is overreach — the pin itself is already the authorization (the pin exists because an admin-ish operation placed it there). Forcing the scope push instead pushed users toward either (a) granting broader scopes than they wanted or (b) shipping 403-ing widgets. Architecturally: the pin proves the relationship; scope gating is redundant for widget reads scoped to their own host channel.

**Load-bearing implementation choices.**
- **Only channel-bound dashboards count.** The slug comparison `dashboard_key == f"channel:{channel_id}"` means widgets on a user/global dashboard *don't* get implicit access to any channel — they still need scope. The pattern applies exclusively to channel dashboards.
- **Helper, not a dependency.** `_auth_channel_context(channel_id, auth, db)` in `app/routers/api_v1_channels.py` is a hand-rolled check invoked inside the endpoint after `verify_auth_or_user`. Not a reusable FastAPI `Depends(...)` wrapper — the helper needs the parsed `channel_id` path parameter and a DB session, which the dependency graph can't provide cleanly. Keep it narrow: each new channel-scoped widget-readable endpoint opts in explicitly by calling the helper.
- **Scope gate still works.** Users with `channels:read` (or admin) still pass the same check via `has_scope()`; the pin path is an additional pass, not a replacement.

### Channel-scoped context endpoints are public, not admin-only
**Decided 2026-04-20.** Moved `GET /channels/{id}/context-budget` and `GET /channels/{id}/context-breakdown` out of the `admin/` prefix into the public `/api/v1/channels/` router, gated by `channels:read`. The admin-prefixed routes remain as thin aliases so the existing admin UI keeps working. Shared helper `fetch_latest_context_budget(channel_id, db)` lives in `app/services/context_breakdown.py` — both admin and public paths call it so they cannot drift.

**Why.** The data is channel-scoped, not administratively privileged. Putting it under `admin/` meant bot-authenticated HTML widgets (e.g. Context Tracker) couldn't render a steady-state snapshot — they had to either subscribe purely to the event bus (blank until a turn fires) or require the bot to carry `admin` scope (overreach). The endpoints don't expose anything a bot with `channels:read` shouldn't already be able to derive from `/channels/{id}/state` + `/sessions/{id}/context`.

**Load-bearing implementation choices.**
- **Bot scope requirement is explicit.** Widgets need `channels:read` on their bot's API key; on 403 they degrade to a clear warning panel pointing at Admin → Bots → Permissions, not a silent failure. Default bot scopes unchanged — that's a separate policy call.
- **No new service code.** Public routes reuse `compute_context_breakdown()` verbatim and the same trace-event query (now extracted as `fetch_latest_context_budget`).

### New bots auto-mint a read-only widget key
**Decided 2026-04-21.** `POST /api/v1/admin/bots` now creates a scoped API key for every new bot immediately, with the minimal read-only bundle `attachments:read` + `channels:read`. Before this, new bots had no key at all, so any interactive HTML widget they emitted failed `/api/v1/widget-auth/mint` until an admin manually visited the bot's Permissions tab.

**Why this shape.** Interactive widgets execute on behalf of the emitting bot, not the viewing user. A zero-scope/default-null bot looked fine at creation time but broke as soon as it emitted a widget that called `loadAttachment()` or read channel/workspace-backed assets. The fix needed to make new bots widget-ready by default without sneaking in broad write access.

**Load-bearing implementation choices.**
- **Read-only only.** `attachments:read` covers attachment fetches; `channels:read` covers channel-bound dashboard reads and channel-workspace asset/file reads. No write or chat scope is granted by default.
- **Create-time mint, not lazy-on-first-widget.** The bot always has a stable scoped identity from day one, so widget auth, dashboard validation, and permissions UI all see the same model.
- **Permissions tab remains the widening point.** Any bot that needs mutation scopes, chat-scoped helpers, or direct API/tool access still gets that explicitly under Admin → Bots → Permissions; creation only handles the safe baseline.

### `WidgetScope.dashboard` carries optional `channelId`
**Decided 2026-04-20.** The TypeScript discriminator on `ui/src/types/api.ts` `WidgetScope` now allows `{kind:"dashboard", channelId?: string}` instead of the earlier channel-less `{kind:"dashboard"}`. Channel dashboards (`slug: channel:<uuid>`) plumb their channelId through `ChannelDashboardMultiCanvas` into every pin's scope so `window.spindrel.channelId` resolves correctly inside pinned HTML widgets across all four canvases (rail / dock / header / grid). Also deleted the `envelope.source_channel_id` fallback in `InteractiveHtmlRenderer` — the scope prop is authoritative now; the fallback was papering over the plumbing gap.

**Why.** The original `{kind:"dashboard"}` modelled "dashboard-scope has no channel" — wrong. A channel dashboard IS channel-bound; throwing away that information at the scope boundary broke every HTML widget that needed `sp.channelId` when pinned to anything other than the chat rail (which had its own `{kind:"channel", channelId}` path). Catalog-synthesized `emit_html_widget` envelopes for HTML widgets didn't carry `source_channel_id`, so the envelope fallback worked for some pins and not others — classic silent plumbing bug. The fix is to stop treating the scope as channel-less when it isn't.

**Load-bearing implementation choices.**
- **User dashboards keep `channelId` optional.** Non-channel dashboards (`default`, user-created slugs) omit the field, and widgets pinned there render the "bind to a channel" empty state — correct behavior for widgets that need a channel.
- **`HeaderCanvas.tileScope` no longer reads `p.source_channel_id`.** On a channel dashboard, the enclosing `channelId` is authoritative; per-pin `source_channel_id` was always either identical or irrelevant for chip rendering.

### Mission Control and generic Plan tables retired; widgets replace tasks/plans/timelines
**Decided 2026-04-20.** Removed the entire `integrations/mission_control/` tree (router + Vite dashboard + SQLite DB + 6 tools + 5 skills + 18 channel-prompt seed templates + `mission-control` carapace) and, in the same sweep, the core `plans` / `plan_items` tables plus `app/tools/local/plans.py` and the `/sessions/{id}/plans` + admin channel-plans endpoints. The `plans.md` stall-detection block in `context_assembly.py` went with them. Migration 228 drops the two Postgres tables. `mission_control:read|write` scopes and the `Mission Control` scope bundle left `api_keys.py` at the same time.

**Why.** MC was frozen since 2026-04-07 ("make what's there work, don't extend") and had sat incomplete. The Widget SDK (Phases A + B.0–B.4) — per-pin SQLite, `@on_cron`, `@on_event`, bot-scoped auth, chat-zone placement, multi-canvas dashboards — now covers everything MC's kanban/timeline/plans tried to be, with better ergonomics and zero parallel data model. Keeping MC alongside the SDK meant carrying two dashboards, two data-model languages, and a Roadmap tech-debt line ("two parallel plans systems"). The generic `Plan`/`PlanItem` tables were a mostly-unused mirror of MC's plan executor and had drifted out of the product entirely — sessions.py routes, one admin endpoint, no active UI.

**Load-bearing implementation choices.**
- **No data migration** from MC → widgets. Single-user deployment, freeze policy. Users re-author kanban / plans / timelines as widgets if and when they need them.
- **Tool names not preserved.** `draft_plan` / `update_plan_step` / `create_task_card` are gone. Replacement widgets get fresh verb names that fit their actual storage model (per-pin SQLite, not workspace markdown).
- **`channel_prompt` (core column) stays.** Orthogonal to MC. The 18 MC channel-prompt seed templates under `integrations/mission_control/prompts/` were already unwired by migration 134; their deletion is a tree cleanup, not a behavioral change.
- **Cross-integration MC references pruned.** `integrations/arr/integration.yaml` dropped `includes: [mission_control]`; `integrations/gmail/carapaces/gmail-feeds.yaml` dropped `includes: mission-control` and its MC tool mentions; `carapaces/orchestrator/carapace.yaml` dropped `includes: mission-control`; `integrations/gmail/agent_client.write_workspace_file` switched from `/integrations/mission_control/channels/.../files/content` to the core `PUT /api/v1/channels/.../workspace/files/content`.
- **Future widgets on their own tracks.** Kanban / plans / timeline widgets queued as separate track stubs, not in this commit.

**Non-goals** (explicitly not done): porting any MC logic into widgets, preserving MC content for any existing user, building replacement widgets in the same change.

### Knowledge-base convention replaces manual segment UI as the default
**Decided 2026-04-19.** Users had ≥4 overlapping knobs to teach a bot about files (`bot.workspace.indexing.segments`, `channel.index_segments`, legacy `bot.filesystem_indexes`, and auto-injected channel workspace files). All routed to the same backend; the surface was the mess. Replaced the defaults with a single convention: every channel has `channels/<id>/knowledge-base/`, every bot has `knowledge-base/` (standalone) or `bots/<id>/knowledge-base/` (shared-workspace). Both are auto-created on provisioning, auto-indexed under the default `**/*.md` patterns, auto-retrieved by the existing `_inject_workspace_rag` + `_inject_channel_workspace` paths, and have a narrow search tool each (`search_bot_knowledge`, `search_channel_knowledge`) that scopes `hybrid_memory_search` to the KB prefix.

**Why the distinction matters.** Our own principle — "if the user has to choose, we failed" — was being violated every time someone opened ChannelWorkspaceTab and saw a path-prefix / pattern / top-k / threshold editor for what should be "drop a file in this folder and the bot will know." The convention ships zero-config; the editor stays as an Advanced disclosure for real power cases (external repos, per-prefix embedding models).

**Load-bearing implementation choices.**
- **No new DB table, no new schema.** KB files flow through the existing `filesystem_chunks` table via the existing default patterns. The convention is a filesystem convention + a retrieval-side implicit segment in `_inject_channel_workspace`, not a new indexer.
- **Channel KB needs an extra retrieval.** Channel workspace chunks live under the `channel:{id}` sentinel `bot_id`. The bot's regular workspace RAG filters on `bot_id == bot.id OR NULL`, so channel KB content won't show up there — context_assembly always fires a second retrieval targeted at `channels/{id}/knowledge-base/` via `retrieve_filesystem_context`, whether or not `channel.index_segments` is configured.
- **Subfolders are organizational only.** `knowledge-base/recipes/pasta.md` is indexed the same as `knowledge-base/pasta.md`. No `scope:` parameter on the search tools — reintroducing that would bring back the "pick a bucket" problem we're trying to kill.
- **Existing segment configuration is untouched.** Custom segments compose with the implicit KB segment; explicit `path_prefix: "knowledge-base"` is deduplicated against the implicit one.

Bot-facing skill at `skills/knowledge_bases.md` teaches the two tools + the write-where heuristic (memory.md for short behavioral notes; knowledge-base/ for browsable reference).

### Tool Renderers vs HTML Widgets: Two Kinds, Not One
**Decided 2026-04-19** (P3-1 — HTML widget catalog). The product has two "widget" concepts that answer different questions, and UI wording must not conflate them.

- **Tool renderers** — YAML packages in `app/tools/**/*.widgets.yaml` and `integrations/*/tool_widgets.yaml`, seeded into `widget_template_packages`. They render a specific tool's output. Always tool-bound. Pinned indirectly (the user runs the tool, its envelope carries the rendered widget, they pin from "Recent calls"). Authoring audience: integration / template developers.
- **HTML widgets** — bot/user-authored `.html` files in the widget library, addressed as `widget://bot/<name>/` (private) or `widget://workspace/<name>/` (shared) via the `file` tool; `widget://core/<name>/` covers read-only in-repo bundles. Standalone dashboard control surfaces. Emitted via `emit_html_widget(library_ref="<name>")`; pinned directly — no intermediate tool call needed. Authoring audience: bots running `emit_html_widget`, or users editing via the workspace file browser.

**Why the distinction matters.** Before this decision the word "templates" was used for both, and `/widgets/dev#library` listed only tool renderers under that label — which made end-users think "templates" meant "things I can add to my dashboard." They aren't. Tool renderers are format definitions; HTML widgets are instances. Mixing them in any end-user picker routes the user to confusing UIs (pinning a tool renderer requires a tool call; pinning an HTML widget needs a file path).

**Rules going forward.**
- **Tool renderers never appear in end-user "Add widget" flows** — only via "Recent calls" after the underlying tool has run. They're an authoring artifact, not a catalog item.
- **HTML widgets get their own surface**: a dedicated "HTML widgets" tab in `AddFromChannelSheet` (channel-scoped) and a labeled section in `/widgets/dev#library`. Neither surface conflates the two kinds.
- **The dev-panel Library banner** must explain the distinction in one paragraph. If a future redesign collapses the two, revisit this decision first.

**Storage asymmetry.** Tool renderers earn DB rows (seeded from immutable repo files, carry user-forked copies and `is_active` flags). HTML widgets ship as registry-only (live scan of the workspace, parsed frontmatter, mtime cache). Adding DB persistence for HTML widgets is a separate decision that requires a feature driver (favorites, cross-channel search, version-bump-notify) — don't introduce it just to symmetrize.

**Frontmatter convention** (HTML widgets): leading HTML comment with a YAML block (`name`, `description`, `version`, `author`, `tags`, `icon`). Only `name` is required. Source of truth: `app/services/html_widget_scanner.py` parser + `skills/html_widgets.md` authoring guide.

**Signals this decision is load-bearing.** If you catch yourself writing a "Templates" filter that mixes both kinds, or adding "HTML widget" metadata to `widget_template_packages`, stop — you're collapsing the boundary that made the UX legible.

---

### Widget Pin Identity: Write-Once at Create, Never Mutated by Refresh
**Decided 2026-04-19** (session 13, after ~10 recurring shapes of the "dashboard widget mints 400" bug).

`WidgetDashboardPin.source_bot_id` / `source_channel_id` are set once at create time and are authoritative for the lifetime of the pin. The refreshed envelope's copy of those fields is a cache, not a writer — refresh force-overwrites them from the pin row before persisting.

**Why.** The prior design had `refresh_widget_state` read the pin's stored `source_bot_id`, pass it into `_do_state_poll` (which sets `current_bot_id` ContextVar from that value and stamps the re-polled envelope with it), and then `update_pin_envelope` overwrite `pin.envelope` unconditionally. Any pin that ever held a bad bot id — from any past UI write-path bug, race, or legacy data — re-stamped itself on every refresh and re-persisted the badness. Self-amplifying loop: no opportunity to self-correct. Channel-chat widget renders worked correctly because they used the live envelope from the agent's tool-call frame (ContextVar set from the authoritative emitting bot); dashboard refreshes were running a different code path with different assumptions. Different mechanisms for the same widget — which is exactly the asymmetry that let this bug recur in ~10 different shapes across sessions. Same anti-pattern as the **Channel binding model** (Slack Depth P3 cost): treating a stored identity column as authoritative without revalidating against the canonical source.

**Rules.**
- **Create-time is the only write site for pin identity.** `create_pin` (`app/services/dashboard_pins.py`) derives `source_bot_id` from `envelope["source_bot_id"]` (authoritative — stamped from `current_bot_id` ContextVar at emission) in preference to a body-provided value; logs WARNING on mismatch. Validates Bot row exists; for interactive-HTML pins also validates active ApiKey. Unknown-bot or keyless-HTML-pin → `HTTP 400` with the bot id cited. NULL remains allowed for pins without iframe-auth needs.
- **Refresh cannot mutate identity.** `refresh_widget_state` (`app/routers/api_v1_widget_actions.py`) force-overwrites `env_dict["source_bot_id"]` / `source_channel_id` from the pin row (or strips the keys if the pin's column is NULL) before calling `update_pin_envelope`.
- **Mint errors are structured.** `/widget-auth/mint` returns `detail={message, reason, bot_id, pin_id}` on 400 so the UI can surface which specific pin is broken.

**Anti-patterns to avoid going forward.**
- Don't add new write sites for `pin.source_bot_id` beyond `create_pin`. If you need to re-parent a pin, that's explicit user action, not a refresh side-effect.
- Don't let the envelope act as authority for pin identity in any persisted context. The envelope is a render-time projection, not a data source for the pin row.

**Signals this decision is load-bearing.** If you find yourself writing code that reads a stored identity column to reconstruct context that then gets re-persisted, stop — that's the shape of this bug. Validate against the canonical source (Bot registry, channel membership) instead of trusting the stored copy forever.

---

### ChatGPT Subscription OAuth — Codex Device-Code Flow, Responses-API-Only
**Decided 2026-04-19** (session 7). A new `openai-subscription` provider type authenticates against OpenAI's Codex Responses API using a ChatGPT OAuth Bearer token, instead of an API key.

**Shape.**
- Driver: `app/services/provider_drivers/openai_subscription_driver.py` — declares `requires_api_key=False`, `requires_base_url=False`, a hardcoded model allowlist (`gpt-5-codex`, `gpt-5`, `gpt-5-mini`, `o4-mini`), and a reused Codex CLI client_id (`app_EMoamEEZ73f0CkXaXp7hrann`).
- Adapter: `app/services/openai_responses_adapter.py` — drop-in `AsyncOpenAI` facade that translates `chat.completions.create` ↔ `POST /responses` at `https://chatgpt.com/backend-api/codex`. Mirrors the AnthropicOpenAIAdapter pattern.
- OAuth: device-code flow at `https://auth.openai.com/deviceauth/{usercode,token}` + standard `/oauth/token` grant. Tokens persisted encrypted at `ProviderConfig.config.oauth.{access_token,refresh_token}`; `account_id`/email/plan stay plaintext for UI display.
- Refresh: `_REFRESH_LEEWAY_SECONDS = 600` — every `chat.completions.create` re-reads tokens via `tokens_source_for_provider`; any that expire within 10min trigger a refresh behind a per-provider asyncio.Lock.
- Admin: `/api/v1/admin/providers/openai-oauth/{start,poll,disconnect,status}/{provider_id}` + an inline Connect-ChatGPT-Account card on the provider edit page.

**Why device-code, not PKCE.** Self-hosted installs sit behind localhost/LAN/tunnels where a stable HTTP callback URL is awkward. Device-code needs only an outbound POST from the server and a browser on any device. Matches Codex CLI's `--device-auth` flag.

**Why the Codex CLI client_id.** There is no public "Sign in with ChatGPT" OAuth-app program for third parties. OpenAI's Responses API via Codex-issued tokens is gated by a specific client_id hardcoded in the official CLI and reused by every community plugin (opencode-openai-codex-auth, openai-oauth). Baking the same client_id in is the only way this works at all; alternative would be forcing every user to dig up a client_id by hand.

**Why Responses API only, not Chat Completions.** ChatGPT-subscription OAuth tokens do NOT work against `api.openai.com/v1/chat/completions`. They are scoped to `/v1/responses` on the Codex backend. The adapter absorbs that asymmetry so the agent loop still sees a uniform `chat.completions` interface.

**ToS-aware framing.** Admin UI shows a subtle amber disclaimer: this is for personal self-hosted use; OpenAI recommends API keys for programmatic workflows. Rate limits are the user's ChatGPT plan limits, not API limits.

**Billing wiring.** Creating an `openai-subscription` provider in the UI pre-fills `billing_type=plan`, `plan_cost=20`, `plan_period=monthly` — overridable. Existing plan-billed code path (`_plan_billed_models` + `_resolve_event_cost()` → $0 per-call) handles cost reporting unchanged.

**Tests.** 45 new tests (25 adapter + 13 OAuth service + 7 admin integration). Adapter covers message/tool/tool_choice translation, response parsing, streaming SSE → chat.completions chunks, exception translation (401 → AuthenticationError, 429 → RateLimitError, etc.). OAuth tests cover claim parsing, device start/poll lifecycle, refresh-window timing, encryption round-trip. Admin tests exercise the full router lifecycle against a real FastAPI + SQLite + mocked OpenAI endpoints.

---

### Integration Ingest Contract: Clean Content, Metadata-Driven Attribution
**Decided 2026-04-19** (session 5, cascading fix from the Slack prefix leak into the web chat UI).

Integrations MUST emit the raw human-authored text into `Message.content` and put all routing, identity, threading, and platform-native tokens in `msg_metadata`. The assembly layer (`app/routers/chat/_context.py::_apply_user_attribution` + `_inject_thread_context_blocks`) composes the LLM-facing attribution line (`[Name]:` or `[Name (<@U…>)]:`) and injects `thread_context` as an adjacent system message. Integrations never format for the LLM at ingest.

**Canonical metadata shape** lives at `app/routers/chat/_schemas.py::IngestMessageMetadata` (source / sender_id / sender_display_name / sender_type required; channel_external_id, mention_token, thread_context, is_from_me, passive, trigger_rag, recipient_id optional). Composers live in `app/agent/message_formatting.py`. Authoritative doc for integration authors: `docs/integrations/message-ingest-contract.md`; SDK contract docstring reiterates it on `integrations/sdk.py`.

**Why the previous shape was wrong.** Slack baked `[Slack channel:C… user:Name (<@U…>)]` into content. Discord baked `[Discord channel:… user:Name]`. BlueBubbles baked `[Name]:` (6+ call sites). Three consequences:
1. `Message.content` diverged from "what the human typed" — the DB stored formatting instead of data.
2. The UI needed one bespoke regex per integration to peel the prefix off for display. When Slack tweaked `sender_mention` to include `(<@U…>)` (a space-bearing parenthesized form), the UI regex (`\S+` after `user:`) broke silently. Discord had no stripper at all — every Discord message rendered its raw prefix in the web UI for weeks.
3. Double attribution reached the LLM. `_apply_user_attribution` prepended `[Name]: ` from metadata, but the skip guard only fired on exact `[<name>]:` match — so the baked-in `[Slack channel:…` prefix stacked on top, yielding `[Olivia]: [Slack channel:… user:Olivia (<@U…>)] text`.

**Load-bearing preservation.** Slack `chat.postMessage` only resolves mentions when the agent sends `<@U123>` verbatim — plain `@Alice` does not notify. The mention token must survive to the LLM so the agent can tag users back. Relocated from content to `metadata.mention_token`; `compose_attribution_prefix` includes it as `[Name (<@U123>)]:` when present. Round-trip verified.

**Scope of the refactor (one commit):**
- Ingest: `integrations/slack/{message_handlers,slash_commands}.py`, `integrations/discord/{message_handlers,slash_commands}.py`, `integrations/bluebubbles/{router,bb_client}.py` — all now emit clean content + enriched metadata.
- Assembly: `_apply_user_attribution` switches to `compose_attribution_prefix`; new `_inject_thread_context_blocks` extracts `thread_context` out of metadata and inserts it as a system block immediately before the owning user turn.
- UI: `ui/src/components/chat/messageUtils.ts` — deleted `parseSlackPrefix` / `stripBBPrefix`; replaced by one generic `stripLegacyIngestPrefix(content, source)` helper (transitional, flagged for removal after 2026-Q3) for historic rows. `MessageBubble.tsx` reads `metadata.sender_display_name` + `metadata.source` and renders content verbatim.
- No data migration. Historic rows keep their prefixes; the transitional stripper covers display.

**Tests:** `tests/unit/test_apply_user_attribution.py` locks in composer + injection behavior (name-only prefix, mention-token prefix, idempotency, multimodal-skip, thread-block placement, multi-turn independence). Slack renderer echo-prevention tests retargeted at metadata-based detection, no longer dependent on the in-content prefix.

**Canonical reference for future integration work:** any new integration receiving user-authored messages must pass raw text in `content` and populate `IngestMessageMetadata` fields. If the platform has a native @-tag token, populate `mention_token`. If it delivers thread context, put the LLM-ready summary in `thread_context`. No per-integration regex goes in the UI.

### Interactive HTML Widgets Authenticate as the Emitting Bot
**Decided 2026-04-19.** `emit_html_widget` output renders in a sandboxed iframe with `allow-scripts allow-same-origin`. Its JS cannot borrow the viewing user's `Authorization: Bearer <user-jwt>` — that credential is in localStorage, accessible only to the host document. Even if the iframe could read it, **it shouldn't**: a malicious widget would then run with whatever scopes the viewer has (admin, in the developer's case), promoting any bot into full system access via rendered output. The decision: mint a **short-lived (15 min) HS256 JWT** scoped to the *emitting bot's* API key at render time and inject it into `window.spindrel.api()`. Token payload: `{kind: "widget", bot_id, scopes, api_key_id, pin_id?, iat, exp}`. `verify_auth_or_user` has a dedicated widget-kind branch that returns `ApiKeyAuth(scopes=payload.scopes, name="widget:<bot>")` without a DB lookup — the scopes list is authoritative in the JWT itself.

**Trade-offs chosen:**
- **Scopes captured at mint time, not re-checked per request.** Revoking the bot's key leaves in-flight widget tokens valid until their own 15-min expiry. Accepted for verifier simplicity; 15 min is short enough that screenshots leaking a token expire before they're useful.
- **No cookie-based auth.** Considered, rejected — would require a parallel auth path on every scoped endpoint and leak the user's session into the iframe anyway. Bearer injection into `window.spindrel` is orthogonal.
- **Mint requires caller ownership of the bot.** `bot.user_id == user.id` or admin. This prevents a member user from minting a widget token for a more-privileged bot by guessing its id.
- **Bots without API keys can't emit functional widgets.** The mint endpoint 400s with an actionable message; the renderer shows a "Widget auth failed" banner. Alternative (silently degrade to no-auth) was rejected because the failure is better surfaced than hidden.

**Load-bearing invariant:** `source_bot_id` must be stamped on every interactive HTML envelope at emit time and persisted on every `WidgetDashboardPin` for pinned widgets. Without it, the renderer has no bot identity to mint against, and the widget regresses to a 422-every-request state. The envelope field + `_build_envelope_from_optin` + `compact_dict` must stay in sync. Code path: `app/tools/local/emit_html_widget.py` → `app/agent/tool_dispatch.py` → `app/services/dashboard_pins.py::create_pin(source_bot_id=...)`.

**UX cue:** widget card renders a subtle bottom-left chip `<BotIcon> @<botname>` so the viewing user always knows the widget is acting with that bot's permissions, not theirs. This is the user-facing half of the decision — the security model only holds if the user understands it. See `skills/html_widgets.md` for the bot-author-facing version.

See also: Fix Log entry 2026-04-19 for the symptom trail (422 on `/channels/<uuid>` with a valid UUID turned out to be missing `Authorization` header, not UUID validation).

### Integration Docker Stacks Are Namespaced by `SPINDREL_INSTANCE_ID`
**Decided 2026-04-18.** Integration-declared `docker_compose:` stacks (web_search, wyoming today) are **per-instance**, not global. Their compose `project_name` and in-network DNS aliases interpolate `${SPINDREL_INSTANCE_ID}` (default: slug of the container hostname, zero-config). Hard-coded `container_name:` is forbidden in integration compose files — it's globally unique on the Docker daemon and guarantees collision when two instances share a host. Per-service DNS comes from `docker network connect --alias <service>-<instance>` on the agent-server's own network, declared in `integration.yaml` as `network_aliases: {service: "<name>-${SPINDREL_INSTANCE_ID}"}`. Integration `config.py` resolves service hostnames the same way.

**Why:** prod + e2e on the same Docker daemon used to collide on `container_name: spindrel-searxng` / `project_name: spindrel-web-search`; whichever started first owned the container, the second silently no-opped, and its DB row stayed `status=running` so subsequent startup syncs skipped the retry. Cost: web_search was broken on prod for an unknown window until a user hit it. The namespacing is generic (no integration-specific code in `app/`), interpolation happens in Python at discovery time for integration.yaml fields and by compose CLI itself for `${VAR}` inside compose YAML. Two defensive hardeners ride alongside: pre-start collision detection in `stack_service.start()` fails loud if a foreign compose project claims one of our declared `container_name:` values, and `reconcile_running()` now treats `created`/`exited`/`dead`/`paused` as not-running so stuck states can't permanently shadow the DB into believing a stack is live.

**Canonical reference for future integration work:** any integration adding a `docker_compose:` block must (a) omit `container_name:` in the compose file, (b) interpolate `${SPINDREL_INSTANCE_ID}` into `project_name:` in `integration.yaml`, (c) declare `network_aliases:` for every service the agent-server needs to reach, (d) resolve service URLs from `settings.SPINDREL_INSTANCE_ID` in its `config.py`. Host `ports:` are orthogonal — only publish if a human needs to hit the service from the host; prefer network-alias-only access.

### Channel Binding Model — Capabilities Live on the Binding, Not the Channel
**Decided 2026-04-17** (session 11, correcting the Slack-Depth Phase 3/4 regression shipped earlier the same day).

Channels are Spindrel's primary object. Every channel has ONE or MANY integration bindings stored as `ChannelIntegration` rows. The canonical resolver is `app/services/dispatch_resolution.py:resolve_targets(channel) → list[(integration_id, DispatchTarget)]`. The legacy `Channel.client_id` / `Channel.integration` fields are 1:1 holdovers and **must not** be treated as authoritative for capability decisions.

Three contracts fall out of this:

1. **Ephemeral is strict-deliver**, never broadcast. `deliver_ephemeral` picks the single bound integration whose renderer has `Capability.EPHEMERAL` and whose integration-native user-id format matches `recipient_user_id`; publishes `EPHEMERAL_MESSAGE` with `target_integration_id` set; the dispatcher filters it out of every other renderer. If no bound integration can honor the request, `respond_privately` returns `unsupported`. Earlier the code would re-publish the "private" text as a `NEW_MESSAGE` with a `🔒` marker on every binding — a privacy violation.
2. **Modals target the origin binding.** `open_modal` picks the MODALS-capable binding whose `integration_id` matches the triggering user message's `metadata["source"]` (fallback: first MODALS-capable binding). The "Open form" button is enqueued via `outbox_publish.enqueue_new_message_for_target` — one outbox row, one binding. Other bindings never see a button they cannot action.
3. **Tool exposure is capability-gated, declaratively.** `@register` accepts `required_capabilities` (e.g. `respond_privately` → `{EPHEMERAL}`, `open_modal` → `{MODALS}`) and `required_integrations` (e.g. `slack_pin_message` / `slack_add_bookmark` / `slack_schedule_message` → `{"slack"}`). `app/agent/capability_gate.py:build_view` unions renderer capabilities across `resolve_targets(channel)` and the assembly filter at `context_assembly.py:1765` drops any tool whose requirements aren't ⊆ the channel's view.

**Why:** phase 3/4 of the Slack Depth track shipped `ephemeral_dispatch._resolve_integration_id` and `forms.open_modal` both deriving a single integration from `Channel.client_id.split(":",1)[0]`. On a real multi-bound channel (web + slack is the default) that yielded random behavior depending on which legacy field was set — plus the broadcast fallback that leaked private replies. The three contracts above make the single-binding shortcut structurally impossible to reintroduce: the gate filters unsafe tools at assembly time, the outbox column scopes delivery per binding, and the dispatcher filter defends against future mis-scoped publishes.

**Canonical reference for future integration work:** any code branching on "what can this channel do" must go through `resolve_targets` + `renderer.capabilities`, never `Channel.client_id` prefix parsing.

### Pipeline-User-Interaction Over Widget-Pin Proposals
**Decided 2026-04-17.** The orchestrator channel's configuration-review flow could have been built as a bespoke "pin an approval widget" mechanism layered on top of the existing pin machinery. Rejected. Instead, a first-class `user_prompt` step type pauses the pipeline, emits the widget envelope via the anchor-message `MESSAGE_UPDATED` stream already used by tool-result widgets, stores a response schema in `step_states[i]`, and resumes via `POST /api/v1/admin/tasks/{id}/steps/{index}/resolve`.

**Why:** centralized state (one row, one anchor message, one stream instead of three), broad reuse (closes the approval-gates gap in [[Track - Automations]] for every pipeline — not just orchestrator), and avoids fracturing "what is this task waiting on?" across pipeline step_states + widget-pin records + UI caches. The `foreach` step added in the same session reuses the same pipeline primitives to close the batch-operations gap.

### Tools-Scoped Discovery Proposals are Advisory-Only
**Decided 2026-04-17** (session 18). The `orchestrator.analyze_discovery` pipeline can emit proposals targeting tools (e.g. `summarize_channel`, `homeassistant-GetLiveContext`), but there is no `PATCH /api/v1/admin/tools/{id}` — tool descriptions live in integration packages / system code, not the DB. Rather than add a description-override table (violates freeze) or filter the analyzer's output, the review UI (`InlineApprovalReview.tsx`) marks any proposal with `scope.target_kind === "tools"` as **Advisory**: Approve is disabled, an amber pill explains why, and the footer counter has a third "advisory" bucket. The insight stays visible; the broken apply path is gone. Revisit if/when a tool-description persistence layer exists.

### Bespoke Apply-Patch Tools Rejected; `call_api` + Existing PATCH Endpoints Instead
**Decided 2026-04-17.** The orchestrator pipelines apply accepted configuration changes by a `foreach` step whose sub-step calls the existing `call_api` tool (`app/tools/local/api_access.py`) against the same validated `PATCH /api/v1/admin/bots/{id}` etc. endpoints a human admin would hit. Considered and rejected: domain-specific `apply_bot_patch` / `apply_skill_patch` tools.

**Why:** the PATCH endpoints already field-validate, already scope-check via `api_permissions`, and already live at the admin-auth boundary. A bespoke wrapper duplicates every piece of that surface and adds a new invariant to keep in sync on every schema change. Determinism at apply time is preserved: the `tool` sub-step substitutes literal args from `{{item.target_method}}` / `{{item.target_path}}` / `{{item.patch_body}}` with zero LLM invocation — the agent step emits the proposals, the human gates them, the pipeline applies them.

**Follow-up noted**: per-item gating inside the `foreach` — current `when: output_contains: "approve"` is step-level, so if any proposal is approved every iteration fires. Richer `when:` expression (drill into `{{steps.review.result[item.id]}}`) is a v2 primitive enhancement.

### Temporal Context Block Fires Unconditionally
**Decided 2026-04-17** — with a flag.

The enhanced "Current time" block at `app/agent/context_assembly.py:1770` (`build_current_time_block` + Layer-2 resolved-references scan) is not gated on `task_mode` or job type. Every code path that reaches `assemble_context` gets the block.

**Coverage table (recorded so the assumption is revisitable):**

| Context | Entry point | Fires? | Stance |
|---|---|---|---|
| User chat | `turn_worker.run_stream` → `loop.run_stream` | ✅ | Wanted — core case |
| Heartbeats | `heartbeat.py:606` → `loop.run` (task_mode=True) | ✅ | Wanted — bot woken by schedule must know user-gap |
| Scheduled tasks / pipelines | `tasks.py:999` → `loop.run` (task_mode=True) | ✅ | Conditional — see caveat |
| Sub-agents (delegation) | `delegation.py:56` → `run_stream` | ✅ | Wanted — same as chat |
| Compaction / memory flush | `compaction.py:266` → `loop.run` (task_mode=True) | ✅ | Noise — summarization LLM doesn't need it, but also doesn't suffer |
| Memory hygiene / skill review | scheduled → task pipeline → `tasks.py` | ✅ (indirect) | Noise — curating files, temporal cue unused |

**Caveat — contextless task toggle**: when the open "tasks should be able to run without channel context" toggle (see [[Loose Ends#Channel-targeted tasks don't show output in channel]]) gets implemented, the temporal block MUST be gated under it. The block's Layer-2 bullets are derived from recent channel messages — that's channel context by another name. A task a user explicitly marked contextless should not receive "'overnight' has now passed" bullets pulled from the channel history.

**Why not gate up-front**: user (Michael) flagged unease with "opinionated context hints creeping in everywhere". Noted — the current choice trades a ~100–500 char unconditional hint for implementation simplicity. Revisit if:
- Compaction/hygiene summaries start echoing temporal commentary,
- Users report feeling like the bot is being "told what to think" about time,
- The contextless-task toggle lands (mandatory gate at that point).

A `skip_temporal_block: bool = False` parameter on `assemble_context` is the trivial escape hatch; adding it is ~2 lines once there's a concrete caller that needs it.

### Integration Lifecycle Lives on IntegrationSetting, Not IntegrationManifest
YAML seeds the *catalog* (what exists); the DB owns *adoption* (what the user opted in to). Lifecycle is a `_status` row (`available | enabled`) on `integration_settings`, not a column on `integration_manifests`. Two states only — "needs setup" is NOT a lifecycle state, it's a derived readiness flag surfaced from `is_configured` as a UI badge. Lifecycle reflects user intent; readiness reflects config completeness; they're orthogonal. Process auto-start and sidebar visibility gate on `is_active = enabled AND is_configured`. Moving to `available` tears down (stop process, unregister tools, drop embeddings) but preserves settings rows so re-adding is instant. Decided 2026-04-17. **Revised same day**: the initial implementation had a three-state model (`available | needs_setup | enabled`) with auto-promote/auto-demote in settings writes. It broke for env-var-backed integrations (e.g., Slack with tokens in env) because the migration only read DB rows so it seeded `needs_setup` even when `is_configured()` at runtime returned true; auto-promote only fires on settings writes, leaving the integration stuck with no explicit Enable button. Collapsed to two states: explicit user intent, derived readiness.

### Tools as Deterministic Boundary
Platform features shouldn't depend on LLM compliance. The LLM decides *what* to do (probabilistic), but tool execution is platform-controlled (deterministic). Integration tools write to DB, not markdown files. If bot doesn't call tools, worst case is "nothing happens" rather than "corrupted state."

### Auto-Discovery Over Manual Config
Bots should find the right tools and skills without explicit configuration. Skill auto-enrollment + tool discovery + capability RAG make this work. The only manual config remaining is `model`, `system_prompt`, and optionally `capabilities`.

### Pinning Is a Hard Guarantee, Not an Ordering Hint
If a tool is in `bot.pinned_tools`, the backend must load its schema and include it in the authorized tool list regardless of whether it also appears in `local_tools`/`mcp_servers`/`client_tools`. The UI labels pinning as "always available every turn" — the runtime must match that contract even when the invariant `pinned ⊆ declared` drifts (UI bugs, YAML seeds, direct DB edits). Schema loading lives in `app/agent/message_utils.py:_all_tool_schemas_by_name`; the function consults pins across all three registries and pulls in undeclared MCP servers when a pin resolves there. Startup `validate_pinned_tools()` is informational only. (2026-04-18)

### Prior Assistant Refusals Are Treated as Stale by Default
Tool availability changes turn-to-turn (retrieval, carapace activation, channel overrides). Assistant messages from earlier turns that said "I don't have tool X" are treated as stale context — when a refusal is detected in the last 5 assistant turns, `app/services/tool_refusal_guard.py` late-injects a corrective system message (named if the refused tool is now authorized, generic otherwise). Counters the history-poisoning failure mode where models pattern-match on their own prior refusals even after the tool becomes authorized. Lives in the late, cache-safe band. (2026-04-18)

### `search_tools` Is Discovery-Mode Only
When `bot.tool_discovery=True`, the LLM gets a `search_tools(query)` tool that semantically searches the full pool. When discovery is off, all of the bot's tools are already declared and `search_tools` would be noise — it's not injected. UI reflects this in `autoInjectedTools` on the bot edit screen. Threshold is loose (0.2) so weak models still surface candidates. Does not activate tools; the LLM still follows up with `get_tool_info`. (2026-04-18)

### Templates Demoted, Not Killed
Channel workspace schema templates still exist but are hidden behind "Advanced" in UI. The channel creation wizard no longer has a template step. Integration capabilities teach file organization directly.

### Auto-Generated Endpoint Catalog
Static endpoint catalogs drift. Instead, `endpoint_catalog.py` introspects all FastAPI routes at startup, extracts scope from `require_scopes()` closures, and builds the catalog dynamically. Every route uses `require_scopes()` (replacing `verify_auth_or_user`/`verify_admin_auth`), so the catalog is always in sync. `test_endpoint_catalog.py` validates >90% scope coverage.

### Capability Approval as Trust Boundary
Pinned capabilities are pre-approved. Everything auto-discovered needs user consent before activation. This prevents the system from autonomously escalating its own permissions.

### DB-Backed Integrations with Write-Through Markdown
Mission Control stores data in its own SQLite DB, then renders .md files into the workspace for context injection. This gives deterministic storage + compatibility with the existing workspace file injection system.

### Single Workspace (deferred)
Plan: auto-create one workspace at boot, every bot belongs to it. Multi-workspace support exists but nobody uses it. NOT ready for multi-tenancy.

### Chat scroll: `column-reverse` on outer container, normal flow inside (2026-04-10)
**Decision**: the web chat scroll container uses `flex-direction: column-reverse` on the OUTER scroll container, with the message list wrapped in a normal-flow inner `<div>`. No imperative JS scroll anchoring.

**Why**: Pin-to-bottom is a *browser-native* behavior for `column-reverse` scroll containers — `scrollTop === 0` always maps to the visual bottom, new messages stay pinned without any effect, older-page prepend extends the scroll range upward with no jump, and late-loading images don't shift visible content. The canonical chat scroll pattern, shipping in production chat apps for a decade. A previous session tried to fix a text-selection bug by replacing `column-reverse` with imperative `el.scrollTop = el.scrollHeight` effects and a snapshot/delta pagination adjustment; the result was a race condition against image loads (chat "starts scrolled up, then jumps down") and a corrupted at-bottom flag on chain-load (chat "stays stuck up"). That was the wrong trade — text selection is fixable without sacrificing the canonical pattern.

**How it works**: the outer scroll container is `column-reverse` → DOM-first child is visual bottom, DOM-last child is visual top. Indicators (DOM first) sit at the visual bottom; a `sentinelRef` div (DOM last) sits at the visual top for IntersectionObserver-driven older-page loading; messages sit between them **inside a normal-flow inner `<div>`**. Because the inner div is not reversed, its children are in chronological DOM order == chronological visual order, so native text selection, copy, and find-in-page work perfectly.

**What this means for future work**: NEVER reintroduce imperative `scrollTop` manipulation in `ChatMessageArea.tsx`. If a new behavior seems to need it, there is almost certainly a CSS-native way to do it. File: `ui/app/(app)/channels/[channelId]/ChatMessageArea.tsx`, stylesheet: `ui/global.css` (`.chat-scroll-web`).

**Broader meta-lesson** — recorded in `Loose Ends` under *"Don't band-aid — keep the broader vision"*: when the user reports a single symptom, don't narrow the fix so much that you rip out a canonical pattern to make the symptom go away. The fix was a 10-line CSS/JSX tweak (wrap messages in a normal-flow inner div), not a re-architecture.

### Channel Events Bus is the Source of Truth for Live Messages (in progress 2026-04-10)
**Decision**: the in-memory channel-events bus (`app/services/channel_events.py`) is the single delivery mechanism for live chat events — including the sender's own stream. Persistence is coupled to publishing: every persisted Message row is published as a `new_message` event carrying the row, with a per-channel monotonic sequence number. Clients are dumb subscribers that bootstrap history once via REST and append live messages from the bus. There is no separate POST-stream-back-to-the-sender path.

**Why**: the original design used POST /chat as a long-poll with a private SSE response channel, and added the channel-events bus later as a "notification only — go refetch from DB" mechanism for cross-tab observation. This produces seven cascading symptoms (dual-write at `_routes.py:763-766`, `isLocalStream` suppression in `useChannelEvents.ts`, synthetic-message preservation hack, invalidation storms, two cache layers fighting, no reconnect/replay, business-logic-tangled-with-transport in 850-line `_routes.py`). All seven descend from one missed call: trust the bus.

**Phased rollout**: Phase 1 makes the bus carry data (events ship Message rows + seq numbers + replay buffer) without changing the client. Phase 2 collapses the two delivery paths and POST /chat returns 202. Phases 3-5 split the UI cache, separate domain from transport, and add backpressure + transactional outbox. See [[Track - Streaming Architecture]].

**Constraints during transition**: web UI and Slack must remain functional throughout. CLI/voice/other paths are not actively tested and any breakage there is noted as a follow-up rather than a blocker.

### Multi-Bot Shared Session Model
All bots in a channel share one Session. Each bot's messages are tagged with `_metadata.sender_id` for attribution. History rewriting converts other bots' messages so the LLM doesn't confuse identities.

**Critical invariants**:
- After any routing change, the system prompt in `messages[0]` MUST be rebuilt for the bot that's about to run
- Routed non-primary bots MUST get a `system_preamble` (injected right before user message by `assemble_context`) — the system prompt at `messages[0]` alone is insufficient because channel workspace files and conversation history from the primary bot drown it out
- Snapshots for member bots MUST be captured before `_rewrite_history_for_member_bot` and `strip_metadata_keys` run — the `messages` list is mutated in place for the primary bot, so any snapshot taken after mutation is "poisoned" for member bots (wrong rewrite, missing `_metadata`)
- The raw snapshot (`_raw_messages_for_members`) must also include the current user message, since `assemble_context` appends it later than snapshot capture time

See [[Track - Multi-Bot Channels]].

### Bot system_prompt Reinforcement (Position is Load-Bearing) — 2026-04-10
**Decision**: `assemble_context` appends `bot.system_prompt` as a dedicated final system message AFTER the "Everything above is context" marker, immediately before the user message. The reinforcement is in addition to (not a replacement for) the system prompt at `messages[0]`.

**Why**: On Gemini 2.5 Flash, `messages[0]` is ~12KB (`GLOBAL_BASE_PROMPT` + `bot.system_prompt` + `DEFAULT_MEMORY_SCHEME_PROMPT`) and the bot's tiny ~150-char system prompt gets drowned out — the model defaults to generic "I'm a large language model" responses regardless of the persona it was given. Direct Gemini API tests showed reinforcement BEFORE the marker still fails; only AFTER works (recency bias). Verified against the four `test_multibot` failures (Sparrow / Pelican / Parrot / Cockatoo) and committed `c4bfc308`. Regression test: `tests/integration/test_context_assembly.py::TestMessageOrdering::test_bot_system_prompt_reinforced_at_end`.

**How to apply**: Any future change to context assembly that touches the position of system messages must preserve the post-marker reinforcement. Ordering invariant: `[messages[0] system] → ...context blocks... → [marker] → [post-marker bot.system_prompt reinforcement] → [user message]`.

### Memory Scheme Trusts Conversation History First — 2026-04-10
**Decision**: `DEFAULT_MEMORY_SCHEME_PROMPT` Promotion Rule leads with "Trust the current conversation first. If the user mentioned something earlier in THIS conversation (it's already in your context as a prior turn), use that directly. Do NOT call `search_memory` for information the user just told you." Memory search is scoped to "facts NOT visible in the current conversation".

**Why**: Earlier framing was "Before answering about past work or context: search_memory first." Gemini Flash took this literally — `test_context_persists` (turn 1: "my favorite color is purple", turn 2: "what's my favorite color?") would call `search_memory` and reply "I don't have your favorite color stored." The prompt was teaching the bot to distrust its own context window.

**How to apply**: Memory scheme prompt edits must preserve the conversation-first ordering. `search_memory` is for cross-session / cross-channel recall, not for round-tripping facts the user just stated.

### Per-Bot Persistent Skill Working Set — 2026-04-10
**Decision**: Bots have a per-bot persistent enrollment (`bot_skill_enrollment` table) that replaces per-turn ephemeral auto-enrollment. New bots get a starter pack (`STARTER_SKILL_IDS` in `app/config.py`); successful `get_skill()` calls promote into the working set; the hygiene loop prunes unused enrollments via `prune_enrolled_skills`. Semantic discovery layer surfaces *unenrolled* skills as fetchable suggestions in a separate system message labeled distinctly from the working-set flat list.

**Why**: The previous design rebuilt `bot.skills` from core + integration + bot-authored on every turn. This had three problems: (1) silent semantic-filter failure dropped relevant skills below the 0.35 similarity threshold, (2) no durable bot identity ("the skills I usually use"), (3) 47% of catalog skills had NULL descriptions, sinking both flat-list and filter approaches. The working set is always visible (no filter failure), accretes through use (durable), and operates on content embeddings (descriptions only matter for the small enrolled set).

**How to apply**: New skill-discovery features must layer on top of the working set, not replace it. Channel-level skill overrides (`skills_extra` / `skills_disabled`) are deprecated — per-bot enrollment is the canonical assignment surface. See [[Track - Skill Simplification - Phase 3 Working Set Design]].

### Enrolled Skill Relevance Ranking + Auto-Inject — 2026-04-14
**Decision**: Enrolled skills are now semantically ranked per-turn against the user message (via `rank_enrolled_skills()` in `rag.py`). The flat list is replaced with a two-tier format: skills above the relevance threshold (default 0.40) are marked with `↑` and labeled "relevant to this message — load them before responding." The highest-confidence match (above 0.55 similarity) has its full content auto-injected into context, eliminating the `get_skill()` round-trip.

**Why**: Phase 3 gave enrolled skills always-visible flat listing, fixing silent-filter failures. But bots weren't actually using their skills — 18 items with equal weight gave the LLM no signal about which to load. All three existing skill nudges (correction, repeated lookup, iteration) were about *creating* skills, not *using* them. The system needed a *usage* nudge, and the most effective nudge is relevance annotation + auto-injection.

**Key distinction from the old RAG approach (removed 2026-04-10)**: The old system used RAG as a *filter* — below-threshold skills were hidden, causing silent relevance failures. The new system uses RAG as a *ranker* — all enrolled skills remain visible (Phase 3 invariant preserved), similarity only controls ordering and annotation.

**Tracking**: Auto-injects are tracked separately from `get_skill` calls via `auto_inject_count`/`last_auto_injected_at` on `BotSkillEnrollment`. Global `surface_count` is NOT incremented for auto-injects — it remains a measure of intentional bot behavior. Hygiene prompt and admin Learning UI show both counters for evaluation.

**How to apply**: The `SKILL_ENROLLED_*` settings in `config.py` control thresholds. Monitor the ratio of `fetch_count` to `auto_inject_count` per enrollment — high auto-inject + zero fetch may indicate noise (threshold too low or skill not relevant).

### Auto-Inject Persistence via Synthetic Tool Calls — 2026-04-14
**Decision**: Auto-injected skill content persists across turns by recording the intent in `AssemblyResult.auto_inject_skills` and injecting synthetic `get_skill()` tool call/result message pairs into the conversation. These pairs carry `_no_prune` metadata so they survive tool-result pruning and session reload.

**Why**: Auto-inject content was originally ephemeral (system messages filtered at persist time). This meant auto-injected skills vanished on session reload — the bot would forget expertise it had just demonstrated. Synthetic tool call pairs are the natural format because `get_skill()` results already have `_no_prune` protection via `STICKY_TOOL_NAMES`.

**Budget accounting**: `_budget_can_afford(skill, remaining_budget)` checks skill content size against remaining context budget before injection. `_budget_consume` deducts from the budget. Prevents large skills from overflowing the context window when `AUTO_INJECT_MAX > 1`.

**Dedup**: History-scan at assembly time checks for existing `get_skill()` results in conversation context and skips skills already present. Trace events record `skills_in_history`, `skipped_in_history`, `skipped_budget` for observability.

**How to apply**: Any new mechanism that auto-injects content into context should follow this pattern (synthetic tool call pairs with `_no_prune`) rather than using system messages that don't persist.

### Channel Snapshots in Memory Hygiene — 2026-04-14
**Decision**: Memory hygiene now generates a markdown snapshot of the bot's channels with last activity times, user message counts over the past week, and enrolled skill usage data. This snapshot is included in the hygiene task prompt.

**Why**: The hygiene bot had no awareness of channel activity patterns — it couldn't distinguish a dead channel from an active one, or know which skills were actually being used where. Channel snapshots give the hygiene prompt the context needed for better curation decisions (e.g., don't prune skills actively used in busy channels).

**How to apply**: When extending hygiene prompts with new data, include it in the channel snapshot format rather than adding separate system messages.

### Conditional Auto-Enrollment on Workspace Join — 2026-04-10
**Decision**: When a bot is added to a shared workspace, `add_bot_to_workspace` calls `enroll_many(bot_id, ["workspace_member","channel_workspaces","docker_stacks"], source="auto")`. New `source="auto"` enrollment value extends the existing `Literal["starter","fetched","manual","migration","authored"]`.

**Why**: This is the architectural replacement for the dropped `SharedWorkspace.skills` JSONB column (Phase 4 workspace half). Operator-driven workspace-wide skill assignment was a structural twin of channel `skills_extra` and bypassed the per-bot working-set discipline. The conditional auto-enrollment achieves the same goal — workspace-relevant skills land on workspace bots — without giving operators a knob to bloat working sets.

**How to apply**: Future "every bot needs skill X in context Y" requirements should follow this pattern (conditional `enroll_many` at the join/activation point) rather than adding a new operator-facing assignment surface.

### Tool-Result Pruning with Retrieval Pointers — 2026-04-10
**Decision**: Tool results are aggressively pruned at two layers — turn-boundary (`prune_tool_results` in `assemble_context`) and in-loop (`prune_in_loop_tool_results` at the start of each loop iteration past the first). Pruned messages get a short marker that embeds `read_conversation_history(section='tool:<tool_record_id>')` so the bot can fetch the full output on demand. Full output is stored in the `tool_calls` table at dispatch time with a UUID `tool_record_id` persisted on the message metadata. Hard cap (`TOOL_RESULT_HARD_CAP`, default 50000 chars) truncates oversized outputs at dispatch time before they hit context. Skill content survives via `STICKY_TOOL_NAMES = {"get_skill", "get_skill_list"}` + `_no_prune` flag, persisted in `metadata_["no_prune"]` so it survives session reload.

**Why**: A `haos-bot` channel hit 470k+ tokens per turn (~$1/turn) because tool results accumulated across iterations. The original `keep_full_turns=10` heuristic protected ALL recent tool messages from pruning, which was wrong: `prune_tool_results` only touches tool messages (never user/assistant text), so it can't break conversation continuity (that's compaction's job). Tool results are *consumable* — the bot reads them, replies based on them, the reply carries the meaning forward. The setting was added to DB but never surfaced in UI or documented — users had no way to discover/configure it. Removing it produced the structural fix.

**How to apply**: When adding a new long-output tool, decide if it's "sticky" (skill / runbook content the bot should carry across turns) or normal (data the bot consumes once). Sticky tools go in `STICKY_TOOL_NAMES`. Normal tools rely on the retrieval pointer for replay. Never add a "keep N turns of tool results" knob — the pattern is per-tool stickiness, not per-turn count.

**Critical invariants**:
- `IN_LOOP_PRUNING_KEEP_ITERATIONS` is clamped to ≥1 internally — pruning the just-produced tool results would break the next LLM call
- Internal `_`-prefixed message keys (like `_tool_record_id`, `_no_prune`) MUST be stripped by `_prepare_call_params` in `llm.py` before any LLM API call — providers reject unknown fields

### Integration Delivery: Bus + Outbox + Renderer Abstraction — 2026-04-11
**Decision**: Every integration is a `ChannelRenderer` subscribed to the in-memory channel-events bus. The agent loop publishes typed `ChannelEvent`s exactly once per turn. Durability comes from a transactional outbox table written in the same DB transaction as `persist_turn`; a background drainer hands rows to renderers via the same `render(event, target)` interface used by the in-memory subscriber path. POST `/chat` returns 202 immediately and the browser consumes the bus over SSE — there is no synchronous chat response anywhere.

**Why**: Slack delivery was unreliable because Slack had two mutually exclusive outbound paths (subprocess long-poll path with in-process `chat.update` storms, and main-process `SlackDispatcher.deliver` queued path). The two paths produced different rendering, different rate-limit behavior, and were race-gated on session lock state. The deeper problem: there was no real standard for integration delivery — `Dispatcher` Protocol was three methods plus duck-typed `notify_start` / `request_approval` extras, ~20 sites in `app/` invoked `dispatchers.get(x).something()` with subtly different expectations, and web-UI vs integration-origin messages took totally different code paths gated on `if not req.dispatch_config`. No improvement to one integration could propagate to others.

**Architecture**:
```
POST /chat → 202 → start_turn(...) → background turn worker
                                              │
                                              ▼
                                    publish ChannelEvent
                                              │
                          ┌───────────────────┼───────────────────┐
                          │                   │                   │
                          ▼                   ▼                   ▼
                    Web SSE sub          outbox row          renderer task
                    (browsers)           (durable)           subscribe_all()
                                              │                   │
                                              └──────┬────────────┘
                                                     ▼
                                            ChannelRenderer.render(event, target)
                                                     │
                                                     ▼
                                           (integration API)
```

**Key invariants**:
- **Single publish path.** No `if not req.dispatch_config` gate. Web-origin and Slack-origin take the same path.
- **Renderers run in the main process.** Slack/Discord subprocesses only handle inbound; they POST `/chat` and return immediately.
- **Outbox is durability.** Per-target rows written inside the same transaction as `persist_turn`. Crash → drainer redelivers on restart via `reset_stale_in_flight` (resets IN_FLIGHT → PENDING without incrementing `attempts`, since the prior attempt never reached a renderer receipt).
- **Per-target capability declarations.** Renderers declare `frozenset[Capability]` (TEXT, RICH_TEXT, THREADING, REACTIONS, INLINE_BUTTONS, ATTACHMENTS, IMAGE_UPLOAD, FILE_UPLOAD, FILE_DELETE, STREAMING_EDIT, APPROVAL_BUTTONS, DISPLAY_NAMES, MENTIONS). Events requiring an unsupported capability are silently skipped at the dispatcher boundary.
- **Target boundary is enforced.** `DispatchTarget` is a type alias for `_BaseTarget`; integration-specific targets live in `integrations/{name}/target.py` and self-register via the target_registry, mirroring the renderer_registry. Adding a new integration target is **zero changes to `app/`**.
- **Discovery loop auto-imports `target.py` + `renderer.py`** from every integration during `_load_single_integration`. `app/main.py` does not need explicit imports.
- **`turn_id: uuid.UUID`** is the demux key on every typed `TurnStream*` payload. Multi-bot channels publish one `TURN_STARTED → (TURN_STREAM_*)* → TURN_ENDED` sequence per concurrent bot, all on the same channel bus.
- **Slack rate-limit via 0.8s coalesce window.** `SlackRenderer._do_flush` queues the latest accumulated text in `pending_text` if a token arrives while a flush is in flight, fires one final `chat.update` after the in-flight call completes. Single shared `SlackRateLimiter` (per-method async token bucket; on 429, `record_429` pushes next-allowed time forward by `Retry-After`).

**Critical load-bearing facts** (for anyone touching this code):
1. **Slack subprocess and main process share `dispatch_config` via JSONB column.** Any field added subprocess-side must also exist on the typed target class — `parse_dispatch_target` will throw on unknown kwargs and silently fall through to `NoneTarget`. Symptom: complete delivery loss to that integration. Catch with round-trip tests that feed the exact dict the subprocess writes through `parse_dispatch_target`.
2. **NEW_MESSAGE is delivered via TWO paths today** (outbox drainer + `subscribe_all()` global subscriber), so renderers must dedupe on `msg.id`. Architectural fix is to make the outbox the sole NEW_MESSAGE path; tracked in [[Loose Ends]].
3. **`_persist_and_publish_user_message` builds `DomainMessage` manually** without going through `from_orm`, so the actor.id retains the integration prefix (`slack:U06STGBF4Q0`). The Slack echo filter depends on this — any refactor that strips prefixes or migrates to `from_orm` silently breaks the filter. Threading `metadata` through and detecting origin via `metadata["source"]` is the right fix; tracked in [[Loose Ends]].
4. **`run_stream` tool-call args are JSON strings** (`app/agent/loop.py:919`), not dicts. `_coerce_tool_arguments` in `app/services/turn_event_emit.py` is the only thing standing between that and a `ValueError` cascade. Don't bypass it.

**How to apply**: Any new integration writes a `target.py` (typed `DispatchTarget` subclass + `_register()` call) and a `renderer.py` (`ChannelRenderer` subclass declaring capabilities). Both auto-register at module import via the discovery loop. Zero `app/` changes. Inbound side POSTs `/chat` and returns 202. The renderer drives all outbound delivery from the bus.

See [[Track - Integration Delivery]] for active polish + Phase H acceptance test status.

### Self-Improvement Awareness in Base Prompt — 2026-04-10
**Decision**: `DEFAULT_GLOBAL_BASE_PROMPT` includes a "Self-Improvement" section that explains `manage_bot_skill` and the skill-vs-reference-file distinction in ~6 lines. `skill_authoring` is in `STARTER_SKILL_IDS` so every new bot gets the full reference doc in its working set.

**Why**: The `manage_bot_skill` tool was pinned and always-visible in `MEMORY_SCHEME_TOOLS`, but the global base prompt never mentioned it. The three reactive nudges (correction regex, repeated lookups, post-N-iterations) only fired on specific triggers. Bots that didn't trip them never discovered they could author skills. Auto-pinning a tool is necessary but not sufficient — the model needs the system prompt to TELL it when to use the tool. Cost: ~140 tokens fleet-wide for the highest-leverage change in the skill-content review.

### Bot-Authored Skills Can Carry Named `run_script` Snippets — 2026-04-21
**Decision**: Bot-authored skills now have a structured `scripts` payload (`skills.scripts` JSONB). `manage_bot_skill` exposes dedicated script CRUD (`get_script`, `add_script`, `update_script`, `delete_script`), while `run_script` can execute either ad-hoc inline source or a stored named script via `skill_name + script_name`.

**Why**: Some durable learnings are executable workflows, not just prose. Before this change, bots could write the explanation into a skill, but the working tool-orchestration code either got lost, duplicated in future turns, or buried inside markdown where it was neither validated nor directly runnable. Separating discoverable prose from reusable code keeps the RAG surface clean while making the workflow directly reusable.

**How to apply**: Keep semantic discovery anchored on the skill's prose (`name`, `description`, `triggers`, `content`), not raw script bodies. Store reusable multi-step tool workflows as attached named scripts, and maintain them with dedicated script CRUD rather than patching code blobs inside the markdown body.

**How to apply**: When a tool is structurally critical to a workflow but not used despite being available, fix it in the base prompt, not by adding more reactive nudges.

### Session-Local Plan Mode Uses a Canonical Markdown Artifact — 2026-04-21
**Decision**: Plan mode is session-local, not a separate planner session or DB-backed plan table. The source of truth is a single strict-template Markdown file under the channel workspace at `channels/<channel-id>/.sessions/<session-id>/plans/<task-slug>.md`, plus lightweight `sessions.metadata` keys for current mode/path/revision.

**Why**: We explicitly retired the old generic `plans` / `plan_items` tables on 2026-04-20. Re-introducing a new plans table one day later would recreate the same parallel product surface we just removed. The actual UX need is narrower: users want a Codex/Claude-style "plan first, then execute" loop inside the same conversation, especially for widget work. A strict Markdown artifact keeps the implementation cheap, inspectable, and bot-friendly, while session metadata gives us the runtime contract we need (planning vs executing, accepted revision, active file path).

**How to apply**:
- Entering plan mode flips a session-level mode flag and injects mode-specific system context on every turn.
- Planning mode may read/search normally but may only mutate the canonical plan file.
- Approval binds execution to the accepted revision; the executor advances one step at a time against that same Markdown file.
- Progress stays inline in the file; no shadow DB row or second execution artifact in v1.

### Return-Capable Tool Hooks (pending) — 2026-04-12
**Decision (pending)**: Current `after_tool_call` hooks are fire-and-forget (observe only). For integration-specific MCP result rendering, we'd want hooks that can *modify* the envelope (e.g., Firecrawl crawl results → link list, HA state queries → properties component).

**Options**: (a) make `after_tool_call` return-capable (short-circuit on first non-None, like `before_transcription`), or (b) add a purpose-built `envelope_transformer` registry keyed by MCP server name. Option (b) is simpler and scoped.

**Context**: Smart content-type detection (markdown/JSON auto-promote) shipped 2026-04-12 as a zero-config baseline, reducing the urgency.

### Task Pipelines as Automation Primitive — 2026-04-15
**Decision**: Task pipelines (inline steps on the Task model) are the automation system going forward. The standalone workflow system (Workflow + WorkflowRun models, 22 UI components, YAML definitions) is deprecated and hidden from the admin nav. Workflow backend code and 186+ tests are preserved but dormant.

**Why**: Two systems existed for multi-step execution. Workflows created a parallel object model — separate Workflow objects, WorkflowRun tracking, YAML definitions, dedicated UI — that duplicated what tasks already do. A workflow step ultimately creates a task, making the abstraction layer cost more than it pays. Task pipelines skip the indirection: steps live on the task, triggers live on the task, bot assignment lives on the task. One object to understand.

The workflow system was well-built (full state machine, approval gates, session modes, recovery logic, 186 unit tests) but never used in practice. The UI was confusing and over-featured. Task pipelines align with the Home Assistant automation model (trigger → condition → actions) without ceremony.

**What's preserved**: Shared pure functions (`evaluate_condition`, `render_prompt`, `build_condition_context`) were extracted from workflow_executor into step_executor and are imported by both. Workflow tests still pass. YAML workflow definitions stay in `workflows/` as potential seed material for a future template library.

**Known gaps in task pipelines** (tracked in [[Track - Automations]]):
1. Run history — pipeline executions overwrite step_states, no per-run records
2. Approval gates — `requires_approval` exists in workflows but not pipelines; UX design needed
3. Channel presence — no in-channel visibility of active pipeline runs
4. Reusable templates — no "define once, trigger with params" pattern

**How to apply**: New automation features build on task pipelines. Do not extend the workflow system. If a gap requires a feature that workflows had, port the concept to step_executor, don't resurrect the workflow UI.

## Technical Debt
- User-facing name is "Capabilities", internal code uses "carapace" — accepted debt, don't rename internals
- Config references LiteLLM but works with any OpenAI-compatible endpoint — historical
- Knowledge system (BotKnowledge, KnowledgePin, etc.) is fully superseded by skills + filesystem indexing but code is still active — tracked in [[Loose Ends]]

## What's Wrong Today
1. Concept overload: 12+ concepts before productive
2. No guided first-run / onboarding experience
3. 12 channel tabs overwhelming (should be 7 + Advanced)
4. 34 admin pages with no progressive disclosure
5. Integration depth is shallow — architecture is solid, individual integrations need polish
