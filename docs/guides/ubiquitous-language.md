# Ubiquitous Language

This is the canonical glossary for Spindrel. If UI copy, code comments, track notes, or older guides disagree with this page on what a term means, this page wins.

Use it when:

- introducing a new concept in code or docs — check whether a term already exists before coining one
- reviewing a PR that renames or introduces domain vocabulary
- reading an older doc and unsure whether a term is still current
- writing a prompt, skill, or UI string that a human or a bot will read

Scope is the domain model — actors, rooms, conversations, discovery, integrations, widgets, context, planning, providers. Generic programming terms (function, endpoint, queue) are out of scope unless Spindrel gives them a specific meaning.

---

## Actors and auth

| Term | Definition | Aliases to avoid |
|---|---|---|
| **User** | An authentication identity in Spindrel. May be `admin` or a regular user. | account, login |
| **Admin** | A User with elevated privileges over integrations, providers, and server settings. | owner, root |
| **Bot** | An agent definition keyed by `model` + `system_prompt`. Runs turns, owns scopes, authenticates outbound widget calls as itself. | agent (overloaded), assistant |
| **Source bot** | The Bot that emitted a widget envelope. A standalone HTML widget authenticates as its source bot, not as the viewing User. | emitter |
| **Viewer** | The User currently viewing a widget in the UI. Viewer privileges are never lent to widget HTTP calls. | reader |
| **Workspace** | The single container environment every Bot is bootstrapped into. A Bot is not "in a workspace" — the workspace is the environment Bots live in. | bot group, tenant |

---

## Rooms and conversations

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Channel** | A persistent room that pairs zero or more Bots with a delivery surface (web, Slack, iMessage, voice). Has a `channel.config["layout_mode"]` and an implicit Widget Dashboard. | room, chat |
| **Session** (`ChatSession`) | The chat primitive anchored to a Channel. Holds history, plan state, and compaction watermarks. | conversation |
| **Sub-session** | A child Session spawned from a parent Message. Used for task pipeline runs, reply-in-thread forks, and scratch chat. Renders as a chat-native transcript and reuses the ChatSession primitive. | side-thread, branch |
| **Scratch session** | An ephemeral Sub-session opened from the Scratch FAB. First-class (titled, summarizable, renameable, promotable). | sandbox chat, draft chat |
| **Thread** | A single bidirectional conversation mirrored across web + an external platform (Slack thread, iMessage thread). Realized as a Sub-session with `integration_thread_refs`. | reply chain |
| **Turn** | One user message + the resulting agent response cycle. The unit `compaction_keep_turns` and context profiles count in. | round |
| **Iteration** | One LLM call inside a Turn. A single Turn may produce many Iterations when the model calls tools. | step, cycle |
| **Message** | A persisted row in the Channel transcript. May carry attachments, tool envelopes, and `metadata.hidden`/`metadata.pipeline_step`/`metadata.kind` markers that exclude it from replay. | entry, row |

## Attention and work intake

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Attention Item** | Persisted attention/work-intake state in `workspace_attention_items`: source, target, severity, lifecycle, dedupe, evidence, response, and future assignment metadata. | issue, alert row |
| **Attention Beacon** | The Spatial Canvas rendering of an active Attention Item. Map beacons render as target-owned severity signals; counts, evidence, and actions live in the Attention Hub. | issue marker, alert |
| **System Attention Item** | Admin-only Attention Item created by structured failure detectors such as failed ToolCalls, TraceEvents, or HeartbeatRuns. | log alert |

---

## Discovery and residency

These five states are distinct. Do not conflate them.

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Discoverable** | The runtime can suggest or retrieve the item but it is not in the bot's persistent working set. | available, searchable |
| **Enrolled** | Persistently part of the Bot's or Channel's working set / allowed set. A configuration fact. | installed, activated |
| **Loaded** | The Bot fetched the full content this run, usually via `get_skill()` or `get_tool_info()`. | pulled |
| **Resident** | The content is in the prompt window for the current Turn. A runtime fact. | in context, active |
| **Auto-injected** | The runtime preloaded the content without the Bot calling the fetch tool. | pushed |

Entities that carry those states:

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Skill** | A markdown doc loadable with `get_skill(skill_id)`. Starter skills seed every new Bot; bot-authored skills may carry named stored scripts. | prompt template (distinct), snippet |
| **Starter skill** | A Skill id in `STARTER_SKILL_IDS`, enrolled into every Bot at startup via `backfill_missing_starter_skills()`. | default skill |
| **Tool** | A server-registered callable declared with `@register({...})`. May be pinned, enrolled, or discoverable; schema is fetched with `get_tool_info`. | function, action |
| **Pinned tool** | A Tool that must be available every Turn for a given Bot or Channel. The strongest availability signal. | required tool, always-on tool |
| **MCP server** | A Model Context Protocol server contributed by an integration or admin. Its tools participate in the same discovery / residency model as local tools. | MCP (ambiguous) |
| **Knowledge base** | An auto-created, auto-indexed folder searched with `search_channel_knowledge` or `search_bot_knowledge`. Per-channel at `channels/<id>/knowledge-base/`, per-bot at `knowledge-base/` or `bots/<bot_id>/knowledge-base/`. | KB (use in prose only), docs folder |

---

## Integrations

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Integration** | A folder at `integrations/<id>/` with an `integration.yaml`. Declares all extension points the app reads at startup. | plugin, connector |
| **The host** (`app/`) | The core application: context assembly, turn loop, dispatcher, delivery, bus, session/channel model, policy. Never branches on `integration_id`. | core, platform |
| **The tendril** (`integrations/<id>/`) | Everything integration-specific: platform clients, renderers, platform tools, config. Imports only through `integrations/sdk.py`. | adapter, driver |
| **Binding** | The per-Channel declaration of "which thing on the external platform does this Channel correspond to." Shape: `client_id_prefix`, `suggestions_endpoint`, `config_fields`. | channel config, connection |
| **Client ID** | The token stored on `ChannelIntegration.client_id` that identifies the external resource (e.g., `slack:C01ABC123`, `bb:iMessage;+;chat001`). Routing and renderer lookup key off its prefix. | channel id (ambiguous), external id |
| **Renderer** (`ChannelRenderer`) | The per-integration class that turns `ChannelEvent`s into outbound platform API calls. Declares a `frozenset[Capability]`. | sender, adapter |
| **Dispatcher** | The host-side service (`integration_dispatcher.py`) that reads `ChannelEvent`s and delegates to the Renderer by `integration_id`. | router (overloaded), broker |
| **Target** | A typed, frozen dispatch target the host addresses — auto-generated from `target:` in YAML, or custom via `target.py`. | destination |
| **Activation manifest** | The `activation:` YAML block listing the tools / skills / MCP servers a Channel gains when it enables this Integration. | capability bundle |
| **Capability** (renderer flag) | A member of `app/domain/capability.py::Capability`. Declares what a Renderer can render (`TEXT`, `RICH_TEXT`, `EPHEMERAL`, `MODALS`, `REACTIONS`, `APPROVAL_BUTTONS`, …). Gates event delivery. | feature flag (ambiguous), permission |
| **Capability gate** | The dispatcher-side check that silently skips events a Renderer's declared Capability set can't handle. | filter, shim |
| **Lifecycle hook** | A callback in `integrations/<id>/hooks.py` (e.g., `before_tool_execution`, `after_response`, override-capable `before_transcription`). | event handler (ambiguous), middleware |

---

## Widgets

Widget vocabulary separates three orthogonal axes. A confusion between them is the single biggest source of widget-system bugs.

### Definition kind — what is this widget, semantically?

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Tool widget** | A YAML-declared widget bound to one tool's output contract. Renders via `template:`, `html_template:`, or `view_key:`. | tool renderer, tool result template, tool template |
| **HTML widget** | A standalone iframe bundle using the Widget SDK. Owns its own runtime, fetches, and state. | custom widget, mini app |
| **Native widget** | A first-party host-rendered widget (Notes, Todo, Context Tracker, …). Core-only. | built-in, system widget |

### Instantiation kind — how did this concrete instance get into the world?

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Direct tool call** | A Tool widget rendered from a normal tool result. | ad-hoc render |
| **Preset** | A guided binding flow that instantiates a Tool widget (entity picker, device picker, mailbox picker, …). Not a fourth Definition kind. | widget preset (ambiguous), recipe |
| **Library pin** | A standalone HTML widget pinned from the widget library. | bundle pin |
| **Runtime emit** | A standalone HTML widget emitted at runtime via `emit_html_widget`. | ad-hoc HTML, bot-emitted widget |
| **Native catalog** | A Native widget placed from the built-in catalog. | core placement |

### Presentation and placement

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Presentation family** | Authored rendering intent — `card`, `chip`, or `panel`. Answers "what kind of host surface was this authored for?" | widget type, variant |
| **Placement zone** | The host surface a pin lives in — `rail`, `header`, `dock`, `grid`. Derived per-read by `channel_chat_zones.classify_pin`. | slot, region |
| **Widget contract** | The normalized public inspection object on a widget (`definition_kind`, `binding_kind`, `instantiation_kind`, `auth_model`, `state_model`, `refresh_model`, `theme_model`, `actions`). | widget metadata |
| **Widget origin** | Canonical provenance on a Pin — tracks which instantiation kind created it. | source, pin type |
| **Resolved host policy** | The final rendering decision for one placement, combining zone + presentation + chrome + per-pin overrides. | render config |
| **Pin** | A placed widget row on a Channel's Dashboard. Caches render envelopes; may carry `widget_contract_snapshot` and `widget_presentation_snapshot`. | instance (ambiguous), placement |
| **Dashboard** | The implicit widget board on every Channel at slug `channel:<uuid>`, lazy-created and cascade-deleted. | channel board, layout |
| **OmniPanel** | A scaled mini-view of a Dashboard's left half; layout round-trips with the dashboard. | preview panel |
| **Widget envelope** | The serialized payload a Renderer or runtime hands the frontend to render a widget. | widget payload |

### Widget config surfaces (four things, often confused)

| Term | Definition | Aliases to avoid |
|---|---|---|
| `widget_config` | The canonical runtime config name on a Tool widget or preset-backed Tool widget. | `config` (legacy alias) |
| `binding_schema` | Preset-only. Guided user inputs to instantiate a Preset. | preset config |
| `default_config` | A widget's default runtime config — seeds per-instance `widget_config`. | defaults |
| `config_schema` | The editable runtime config contract for a placed widget instance. | editor schema |

---

## Context, memory, and knowledge

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Base context** | System prompt + persona + mode contract. Always kept, never compacted. | preamble |
| **Live history** | Recent user / assistant / tool replay in the prompt. Subject to compaction and token guards. | recent messages |
| **Static injection** | Optional prompt blocks — workspace files, memory logs, section index, pinned-widget text, discovery hints. Admission-controlled per profile. | additions, extras |
| **Tool schema** | Callable tool definitions supplied to the model. Sized via retrieval, not compaction. | function list |
| **Output reserve** | Prompt-window headroom reserved for assistant output. | response budget |
| **Context profile** | One of `chat`, `planning`, `executing`, `task_recent`, `task_none`, `heartbeat`. Gates live-history depth and static-injection admission. Profile gating happens before budget gating. | mode (overloaded) |
| **Compaction** | Replacing older Live history with a summary or section archive while preserving continuity. Triggered by interval, live-history ratio, or total utilization. | trimming |
| **Watermark** | The persisted boundary between compacted history and the kept live window. Summary windows never overlap the live window. | cutoff |
| **Keep turns** (`compaction_keep_turns`) | Minimum verbatim-Turn floor after compaction. A continuity knob, not a budget guarantee. | floor turns |
| **History mode** | The archival strategy — `file` (section index + on-demand read), `structured` (executive summary, legacy), `summary` (rolling flat summary, legacy). | storage mode |
| **MEMORY.md** | The one unconditional workspace-files memory file, admitted under every Context profile (when the Bot uses `workspace-files`). | memory note |
| **Workspace file** | A file under a Bot's working directory. Durable, editable by tools, searchable via workspace RAG. | user file |
| **Workspace RAG** | Semantic search across Workspace files. Admission-controlled per profile. | file search |
| **Channel knowledge base** | Reference material scoped to one Channel — facts, runbooks, glossaries. | channel docs |
| **Bot knowledge base** | Reference material that travels with a Bot across Channels. | bot docs |
| **Pinned widget context** | The textual capsule injected when a widget is pinned and the Context profile allows it. | widget prose |

---

## Sessions, modes, and planning

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Plan mode** | A Session state with values `planning`, `executing`, `blocked`, `done`. Tightens write policy and swaps the Context profile. | planning mode only (narrower) |
| **Active plan artifact** | The canonical Markdown plan file that survives across `planning` / `executing` Turns as load-bearing context. | plan file |
| **planning_state** | Metadata capsule holding visible back-and-forth planning notes before the full plan artifact exists. | plan draft |
| **plan_runtime** | Metadata capsule holding compact execution state — current step, next action, blockers, replan requests, last outcome. | run state |
| **plan_adherence** | Metadata capsule holding recent execution evidence and explicit progress outcomes. | progress |
| **Terminal chat mode** | A per-Channel setting that renders the feed and composer in a command-first Codex/Claude-style surface. Does not change approvals or tool plumbing. | CLI mode |
| **Default chat mode** | The conversational feed layout. Contrast with Terminal chat mode. | chat mode (ambiguous) |

---

## Automations and scheduled work

Five distinct execution models live here. They share the `tasks` table but are not interchangeable. Pick the precise term; bare "Task" is internal vocabulary only.

| Term | Definition | Aliases to avoid |
|---|---|---|
| **Automation** | The user-facing umbrella for any work the system performs without a human typing each turn. Covers Scheduled prompts and Pipelines. The admin nav category and the route `/admin/automations/` use this word. | task (internal-only), workflow (deprecated) |
| **Scheduled prompt** | A single-prompt agent run with optional `scheduled_at` / `recurrence` / `trigger_config`. Internally a `Task` row with `task_type='scheduled'`. Created by the `schedule_prompt` tool. | one-shot task, scheduled task |
| **Pipeline** | A declarative multi-step automation: each step is `exec` / `tool` / `agent` / `user_prompt` / `foreach`. Slug-addressable, reusable, runs as a Sub-session. Internally a `Task` row with `task_type='pipeline'`. Created by `define_pipeline`; invoked by `run_pipeline`. | task pipeline (internal alias), workflow, flow |
| **Run** | One concrete execution of an Automation. For Pipelines, a Run renders as a chat-native Sub-session; for Scheduled prompts, a Run is a single Turn dispatched to the target Channel. | invocation, instance |
| **Delegation** | A parent Bot handing async work to a different child Bot via the `delegate_to_agent` tool. Materializes as a `Task` row with delegation source/metadata; result auto-posts to the originating Channel when complete. | hand-off, sub-task |
| **Sub-agent** | A bounded, parallel, **readonly** sidecar spawned inline via `spawn_subagents`. Returns its result to the parent Turn; never posts to a Channel; cannot mutate, exec, or recurse. Distinct from Delegation. | mini-agent, worker |
| **Heartbeat run** | A narrow-profile agent run (no live chat replay, no ambient injections) that fires without a human turn. Distinct from a Scheduled prompt — heartbeats live on `channel_heartbeats`, not on `tasks`. | cron run, tick |
| **Standing order** | A first-party native widget that ticks on a schedule (poll / timer) without an LLM call per tick, then pings the Channel when a completion strategy fires. Lives on `widget_instances`, not on `tasks`. Created by `spawn_standing_order`. | standing task, watcher |
| **Background worker** | A long-lived asyncio task spawned at server startup (`safe_create_task(...)`): outbox drainer, catalog refresh, heartbeat loop. Invisible to Bots. Not user-facing. | background task, daemon |

---

## Providers

| Term | Definition | Aliases to avoid |
|---|---|---|
| **LLM provider** | An entry in `ProviderModel`: `openai`, `anthropic`, `ollama`, `openai-subscription`, etc. Carries a `prompt_style` capability flag (markdown / xml / structured). | model vendor |
| **Machine-control provider** | A driver for local/remote machine targets under `app/services/machine_control/*`. `local_companion` and `ssh` are the first shipped providers. Targets are addressed as `(provider_id, target_id)`. | device provider, agent |
| **reasoning_effort** / **effort** | The unified reasoning knob — `off` / `low` / `medium` / `high`. Set via `/effort` slash command. | thinking level |

---

## Flagged ambiguities

These are terms that have bitten Spindrel work before. Call them out explicitly in new docs, prompts, and UI copy.

- **"Capability" is overloaded.** Two unrelated meanings are both live: (1) the Renderer Capability flag (`Capability.EPHEMERAL`, `Capability.MODALS`, …) which gates event delivery at the dispatcher; (2) the vestigial "Capabilities" UI label that once named the composition-pipeline construct called `carapace`. The carapace / `activate_capability` / capability-approval pipeline has been removed. Skills replace it. When writing new prompts, skill docs, or tool results, never mention "capabilities," "carapace," or "activate_capability" in the composition sense. When writing integration code, `Capability.*` is the renderer flag and is canonical.
- **"Capabilities" (UI copy)** is accepted debt for the removed carapace concept. Do not reintroduce it in new surfaces. The code concept it named no longer exists.
- **"Provider" is disambiguated by context.** LLM provider (OpenAI, Anthropic, Ollama, …) and Machine-control provider (`local_companion`, SSH, …) are unrelated. Always qualify in docs: "LLM provider" or "machine-control provider." `ProviderModel` is the LLM one.
- **"Memory" is not the `memories` table.** The `memories` and `bot_knowledge` DB tables are deprecated. `memory_scheme: "workspace-files"` is the only active option — durable memory is `MEMORY.md` plus other workspace files. "Memory" as a concept means the workspace-files layer.
- **"Task" is overloaded — use a precise term.** The bare word "Task" is internal vocabulary for a row in the `tasks` table, which carries multiple shapes via `task_type`. In user-facing copy, prompts, skill docs, and tool names, write the precise term instead: **Automation** (the umbrella), **Scheduled prompt** (`task_type='scheduled'`), **Pipeline** (`task_type='pipeline'`), **Delegation** (`delegate_to_agent`), **Standing order** (widget-backed; not on `tasks`), **Heartbeat run** (`channel_heartbeats`; not on `tasks`), **Background worker** (asyncio startup task; invisible). The `Task` SQLAlchemy class name stays — it is internal.
- **"Pipeline" is the user-facing word for a multi-step automation definition.** "Task pipeline" is an internal synonym; "Workflow" is deprecated (UI hidden, backend dormant). Do not use "workflow" in new code or docs.
- **Sub-agent ≠ Delegation.** A Sub-agent is a bounded readonly inline sidecar (`spawn_subagents`) that returns a value to the parent Turn. A Delegation is an async hand-off to a different Bot (`delegate_to_agent`) that posts back to the originating Channel. They are not interchangeable; the readonly boundary on Sub-agents is enforced in code at `app/agent/subagents.py`.
- **"Tool widget" is canonical.** "Tool renderer" and "tool result template" are stale. A YAML widget using `html_template:` is still a Tool widget; it is not an HTML widget. `widget_config` is canonical; bare `config` is a legacy alias.
- **"Workspace" is the container environment, not a property of a Bot.** Every Bot is a permanent member of the default Workspace via `ensure_all_bots_enrolled`. There is no such thing as a "non-workspace bot." The `POST` / `DELETE` workspace-bot endpoints are 410'd; membership is owned by bootstrap.
- **"Session" vs "Sub-session" vs "Thread"** all ride the same `ChatSession` primitive. A Thread is a Sub-session that is mirrored to an external platform via `integration_thread_refs`. A Scratch session is a Sub-session opened from the FAB.
- **Enrolled ≠ Resident.** Enrolled is persistent configuration; Resident is a runtime fact about the current prompt. A Skill can be Enrolled without being Resident; a Tool can be Discoverable without its schema being Loaded.
- **Four widget config shapes are not interchangeable.** `binding_schema` (preset setup), `default_config` (seeds `widget_config`), `widget_config` (runtime per-instance), `config_schema` (editor contract). Write the exact one; do not reach for "config."
- **"Pin" is a dashboard placement, not a synonym for "instance."** Native widgets have an authoritative `widget_instances` row separate from the Pin that caches its envelope. Deleting a Pin is not the same as deleting the widget instance.
- **Placement zone vs Presentation family.** `rail` / `header` / `dock` / `grid` are zones (where it lives). `card` / `chip` / `panel` are families (what it was authored for). `header` is a zone; `chip` is a family. They are often confused; any widget may be placed in any zone, but only a matching family is guaranteed to fit cleanly.

---

## Relationships

- A **Channel** has zero or more **Bots** as participants, one **Dashboard**, and zero or one active **Binding** per **Integration**. Member Bots can receive active turns through routing such as @-mention, and can also absorb passive channel context for memory/dreaming according to passive-memory and bot learning settings.
- A **Session** belongs to exactly one **Channel**; **Sub-sessions** point to a parent **Message** on that Session.
- A **Turn** produces one or more **Iterations**; each Iteration may load **Skills** (becoming **Resident**) and call **Tools** (whose schemas may be **Loaded**).
- A **Pin** references a **Widget definition** and carries a **Widget origin** describing its **Instantiation kind**; the host combines that with a **Placement zone** to produce a **Resolved host policy**.
- An **Integration** declares **Capability flags** on its **Renderer**; the **Dispatcher** uses those flags to gate which **ChannelEvents** are delivered.
- A **Bot** is a permanent member of the **Workspace**; Workspace is the environment, not a Bot attribute.

---

## Example dialogue

> **Dev:** "A **Bot** called `emit_html_widget` in a Slack **Channel**. Why did the widget render for me in the web UI but not appear in Slack?"
>
> **Domain expert:** "Because it's an **HTML widget** — a **Runtime emit** instantiation. The Slack **Renderer** declares `Capability.TEXT` and `Capability.RICH_TEXT` but not a generic 'arbitrary HTML' flag. The **Dispatcher** skips the envelope for Slack and delivers it only to the web Channel view."
>
> **Dev:** "Got it. So if I want that same thing to show up everywhere, I should make it a **Tool widget** with a `view_key`?"
>
> **Domain expert:** "Yes, if one **Tool** owns the truth. The Tool widget renders as rich text on Slack via the fallback template and as a component on web. If it needs a guided bind — say, pick a Slack channel to show stats for — add a **Preset** on top. The **Definition kind** is still `tool_widget`; the Preset is an **Instantiation kind**, not a fourth widget kind."
>
> **Dev:** "And if I want the user to be able to **Pin** it to the **Dashboard**?"
>
> **Domain expert:** "Pinning is downstream. The authored **Presentation family** (`card` / `chip` / `panel`) plus the **Placement zone** the user drops it into (`rail` / `header` / `dock` / `grid`) produce the **Resolved host policy**. The underlying `tool_widget` doesn't change across placements — the host policy does."

---

## Maintenance

This glossary was extracted from the five sibling canonical guides (`context-management.md`, `discovery-and-enrollment.md`, `widget-system.md`, `ui-design.md`, `integrations.md`), the `Capability` enum in `app/domain/capability.py`, and the project **CLAUDE.md** and **Roadmap.md**. It is the terminology ledger — other guides own their mechanisms and policies.

Re-run the **[ubiquitous-language skill](https://raw.githubusercontent.com/mattpocock/skills/refs/heads/main/ubiquitous-language/SKILL.md)** against this file when:

- a canonical guide is added, split, or renames a first-class concept
- a new user-facing term lands in the UI (check against the "Aliases to avoid" columns)
- a new ambiguity surfaces in review ("I thought X meant Y")
- a removal like `chat_hud` / carapace happens — move the term from active tables to Flagged ambiguities with a "removed" note

When re-running, read this file first, incorporate new terms, sharpen definitions, and refresh the example dialogue so the newest ambiguities get airtime. Do not duplicate terms across tables — each term lives in exactly one group.
