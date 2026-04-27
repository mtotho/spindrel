# Changelog

All notable changes to Spindrel are recorded here. The format follows
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and Spindrel
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While Spindrel is in early access (`0.x`), minor releases may include breaking
changes to APIs, configuration formats, or database schemas. Breaking changes
are called out under the relevant release.

## [Unreleased]

### Added
- _Add new entries here as they land on `master`._

## [0.3.0] - 2026-04-27

**First public release.** Spindrel has been in daily use by the maintainer for months; v0.3.0 is the first version intended for outside self-hosters. Core surfaces — channels, skills, providers, workspaces, widgets, integrations, and the Claude Code harness — are stable and exercised every day. Some edge features are still rough and clearly labeled below; treat this as a confident early-access release, not a 1.0.

### Highlights

- **Self-hosted by design.** Runs on your own box (Docker Compose recommended). No telemetry, no phone-home, no required cloud account.
- **Bring any LLM provider.** OpenAI, Anthropic, Gemini, Ollama, OpenRouter, vLLM, or any OpenAI-compatible endpoint. ChatGPT Subscription works via OAuth device-code flow. Mix providers per bot, with retry + fallback.
- **External agent harnesses.** Run **Claude Code** (proven) and **Codex v1** (newly landed, fresher) as real Spindrel runtimes — persistent sessions, scheduled runs, channel-bound workspaces, in-browser terminal, resume on reload.
- **Skill-based expertise, auto-discovered.** Drop a markdown file into `skills/`; any bot can ground itself in it via RAG without per-bot wiring.
- **Workspace-driven memory.** Bots own a real on-disk workspace (`MEMORY.md`, daily logs, reference docs) — not opaque vector blobs. Indexed for retrieval.
- **Channels with continuity.** Per-channel file stores, automatic transcript archival into searchable sections, chat-state rehydration on reconnect, task runs as dedicated sub-sessions.
- **Task pipelines.** Multi-step automations with `exec` / `tool` / `agent` / `user_prompt` / `foreach` steps, conditions, approval gates, and cross-bot delegation.
- **Heartbeats + scheduled tasks.** Periodic autonomous check-ins with quiet hours; one-off and recurring tasks; bots can self-schedule.
- **Widget dashboards + HTML widgets.** Tool results render as live, pinnable widgets. Bots can author interactive HTML widgets with bot-scoped auth.
- **Spatial canvas.** `Ctrl+Shift+Space` toggles a workspace-scope infinite plane: channels as draggable tiles, the Now Well, semantic zoom, fisheye lens, scheduled work in orbit.
- **Programmatic tool calling.** `run_script` collapses ten-to-fifty tool dispatches into one batched in-turn step.
- **Pluggable integration framework.** Slack, GitHub, Discord, Frigate, Home Assistant, Excalidraw, Browser Live, Arr, Claude Code, Codex, BlueBubbles, Google Drive, Wyoming, Web Search, OpenWeather, Firecrawl, VS Code, and more — extend with your own YAML-declared integration.
- **Usage tracking + cost budgets.** Per-bot tokens and spend (best-effort, LiteLLM pricing data) with configurable limits.
- **PWA + push notifications.** Install the web app and let bots send explicit pushes to subscribed devices.
- **Custom tools + extensions.** Drop a `.py` into `tools/`, or load a personal extensions repo via `INTEGRATION_DIRS` with no boilerplate.

### Known rough edges

These ship but are not yet polished. File issues if you hit something:

- **Codex harness** is freshly landed (2026-04-27) — expect more issues than the Claude Code path until it sees broader use.
- **Spatial canvas** is feature-complete but performance under hundreds of channels has not been profiled.
- **Wyoming voice** ships scaffold + ESPHome + satellite paths; wake-word routing and streaming TTS are still in progress.
- **Google Workspace** integration is mid-migration to a community MCP server; only Drive folder + token refresh are live today.
- **Sub-agent system** is bounded and intentional but still labeled experimental — depth/rate limits exist; behavior under load is the open question.
- **Cost tracking** is best-effort against LiteLLM pricing data — verify against your provider's billing dashboard before trusting numbers.

### Breaking changes

None for new installs. Operators upgrading from a `0.2.x` deployment should run `alembic upgrade head` on first boot and double-check `pyproject.toml` / `ui/package.json` are aligned to `0.3.0` in any custom build pipelines.

## [0.2.0] - 2026-04-27

### Added
- **Codex agent harness** — `codex app-server` integration with native plan
  mode, per-turn sandbox/approval policy, dynamic-tool bridging, model listing
  (`gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`), and live schema-drift checks.
- **Claude Code harness polish** — streaming permission hook, harness-question
  cards rendered as durable read-only transcript rows, native compaction with
  context-window telemetry.
- **Spatial canvas + Attention Hub** — workspace-scope infinite plane with
  draggable channel/widget tiles, edge beacons, the Now Well, and an
  assignment-first Attention Hub.
- **Notifications + unread state** — durable per-user/per-session unread
  high-watermarks, cross-session UI badges and toasts, reusable notification
  targets, unread reminder worker.
- **Memory Observatory** — surfaces memory-hygiene findings and approvals.
- **Pinned widget full-route** — `/widgets/pins/:pinId` page, mobile
  tap-to-full, and a collapse-to-space handoff between dashboards and the
  spatial canvas.
- **Programmatic tool calling** — `run_script` for batched in-turn tool
  orchestration; `register(returns=...)` + `list_tool_signatures`.
- **Standing orders** — native widget + cron seam, `spawn_standing_order` tool,
  tick engine + strategies.
- **Image generation** — first-class `generate_image` for any bot, with
  Gemini multimodal edit and Responses-API routing.
- **Scheduled harness runs** — heartbeats and tasks now execute real
  `_run_harness_turn` calls with per-run model/effort overrides.

### Changed
- Harness usage telemetry normalized into generic context-window fields so
  `/context` and the chat HUD work uniformly across providers.
- Channel binding model — capabilities live on the binding set returned by
  `resolve_targets(channel)`, not on `Channel.client_id`.
- Dashboard pin retrieval, widget pin page, and chat composer interactions
  reworked for consistency across mobile + desktop.

### Fixed
- Codex `item/tool/requestUserInput` schema — replies now use the app-server
  shape (answers keyed by question id) instead of the Claude SDK shape.
- Codex stdio crash/EOF no longer leaves turns hanging — pending RPCs fail
  cleanly and the channel returns to idle.
- Plan-mode split-brain — Spindrel `planning` state propagates to
  `TurnContext` and reaches Codex on resumed native threads.
- Multiple turn-worker / harness-context regressions caught by new unit tests.

## [0.1.0] - 2026-04-27

Initial tagged release. Establishes the public surface as Spindrel:

- Self-hosted FastAPI agent server with persistent channels, skill-based
  expertise, workspace-driven file memory, task pipelines, and interactive
  widgets.
- Pluggable integration framework (Slack, GitHub, Discord, Frigate, Home
  Assistant, Excalidraw, Browser Live, Arr, BlueBubbles, Google Drive,
  Wyoming, Web Search, OpenWeather, Firecrawl, VS Code, and more).
- Provider catalog covering OpenAI, Anthropic, Gemini, Ollama, OpenRouter,
  vLLM, and OpenAI-compatible endpoints, including the ChatGPT
  Subscription OAuth device-code provider.
- Channel widget dashboards, the OmniPanel rail, HTML-widget authoring,
  and the dev panel at `/widgets/dev`.
- PWA + push notifications, scoped API keys, secret vault with automatic
  redaction, Docker-sandbox command execution, and local-machine-control
  leases.

[Unreleased]: https://github.com/mtotho/spindrel/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/mtotho/spindrel/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/mtotho/spindrel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mtotho/spindrel/releases/tag/v0.1.0
