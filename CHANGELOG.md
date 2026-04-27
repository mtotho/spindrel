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

[Unreleased]: https://github.com/mtotho/spindrel/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mtotho/spindrel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mtotho/spindrel/releases/tag/v0.1.0
