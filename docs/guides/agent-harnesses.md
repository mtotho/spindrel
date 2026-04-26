# External Agent Harnesses

An **external agent harness** lets you run a coding-agent session from Spindrel's web UI without routing the turn through Spindrel's RAG loop. Claude Code is supported today; Codex is planned on the same runtime boundary.

The point: manage Claude Code sessions in your browser, alongside your Spindrel channels, with workspace access and persistence across restarts — without giving up Claude Code's own ecosystem (its skills, hooks, MCP servers, slash commands). Spindrel provides the remote UI, channel transcript, terminal drawer, workspace path, auth-status surface, and resume state. The external harness owns the reasoning loop, native tools, bash, file edits, permissions, and its own session id.

There is no Spindrel agent middleman in the turn. Internally the runtime is selected on a bot record so it can reuse channels, workspaces, and message persistence, but once a harness runtime is set, the normal Spindrel prompt, tools, skills, memory, and KB injection are bypassed for that turn. Harness model/effort controls are runtime-owned and stored per session under `Session.metadata["harness_settings"]`.

## Quick start

1. **Enable the integration that owns the runtime.** Each harness ships as part of an integration, not as a baked-in dep. For Claude Code: open `/admin/integrations`, find Claude Code, click Enable. The integration's `requirements.txt` (which pins `claude-agent-sdk`) installs on enable; the SDK bundles the `claude` CLI alongside it. **No SDK or CLI lives in the base Docker image** — nothing related to a harness ships with Spindrel itself.

2. **Authenticate the harness from the admin UI.** Open `/admin/harnesses`. Each enabled integration that provides a harness shows up as a card. If it's not authenticated, click the **Run `claude login`** button — a terminal drawer opens inside the Spindrel container with the command already running. Complete the OAuth flow in your browser, paste the code back into the drawer, close it. The card auto-refreshes to ✓ "Logged in via …".

    Under the hood the CLI writes credentials to `$CLAUDE_CONFIG_DIR/.credentials.json` (default `~/.claude/.credentials.json`). The Claude Agent SDK that the integration installed inherits these credentials — no API key needed. See [Admin Terminal](admin-terminal.md) for the terminal mechanics.

    *Old SSH workflow* (still works if you prefer): `docker exec -it spindrel claude login`.

3. **Workspaces — nothing new to mount.** A harness session reuses the bot's existing Spindrel workspace (the same `WORKSPACE_HOST_DIR` mount every other bot uses, default `~/.spindrel-workspaces/<bot_id>/`). No second mount, no parallel directory tree. The bot editor's *Workspace path (override)* field is for the rare case where you want to point the harness at a different directory — e.g. an existing repo on the host or a directory shared across multiple harness sessions.

4. **Create a harness-backed session owner and seed its workspace.** `/admin/bots` -> New bot. In the **Identity** group, set:

    - **Runtime:** `Claude Code`
    - **Workspace path (override):** leave blank — the bot uses its standard Spindrel workspace.

    Then click **Open shell** (drops you into the bot's workspace) and `git clone <url> .` your repo there. The harness sees that directory as its cwd — drop your `CLAUDE.md`, `AGENTS.md`, vault excerpts, sibling repos in there alongside the repo.

    System prompt, skills, tools, and memory fields are inert when a runtime is set — the harness owns them. Model/effort are exposed through the harness runtime capability contract, not the normal Spindrel provider override.

6. **Open a channel with the bot and chat.** Each turn opens a `ClaudeSDKClient` against your workspace dir, streams the assistant's text + tool calls into the channel, and persists the assistant message + the harness's session id for resume on the next turn.

## Docker / process boundary

If Spindrel runs in Docker (it does), the SDK process runs **inside the Spindrel container**. Two things have to be true:

- The credential file (`~/.claude/.credentials.json` or `$CLAUDE_CONFIG_DIR/.credentials.json`) is reachable from inside the container.
- The workspace directory you configure on the bot exists inside the container.

Two patterns:

### Bind-mount your host credentials and workspaces (recommended)

Add to `docker-compose.yml`:

```yaml
services:
  spindrel:
    # ...
    volumes:
      # Existing volumes here...
      - ${HOME}/.claude:/home/spindrel/.claude:rw
      - /data/harness:/data/harness:rw
```

Now `claude login` run on the *host* writes credentials that the container sees. Workspace dirs are shared — edit on the host (your IDE), see edits in the harness, and vice versa.

### Login inside the container

```sh
docker exec -it spindrel claude login
```

This writes credentials inside the container's filesystem only. They're lost on a `docker compose down -v` or container rebuild. Use this when you don't want host bind-mounts (multi-tenant, etc.).

## What harness sessions intentionally do *not* do

These are deliberate v1 boundaries, not oversights:

- **No Spindrel skills, KB, memory, or capability injection yet.** The harness reads its own skills from `~/.claude/skills/`, project `.claude/skills/`, etc. Spindrel's discovery layer is not bridged. Later bridge work should expose selected Spindrel tools/skills through the normal policy/approval/trace paths instead of direct runtime imports.
- **No widgets / no tool-result envelopes.** The harness emits plain text + tool-call breadcrumbs. No `emit_html_widget`, no standing orders, no dashboard pins.
- **Native harness tools are not Spindrel tools.** Harness approval modes can route native SDK permission prompts into Spindrel approval cards, but approved native calls still execute in the harness, not through Spindrel's `ToolCall` dispatcher.
- **No `/admin/usage` integration.** Cost and token usage are persisted on the assistant message under `metadata.harness.cost_usd`/`usage`, but not aggregated in the global cost dashboard yet.
- **No tool-call rehydration after page refresh.** The live stream shows tool calls; on reload, only the final assistant text comes back from the `Message` row.
- **No @-mention fanout.** A harness session owns its turn end-to-end; it doesn't trigger member-bot replies, supervisors, or context compaction.

If you need any of those, you want a normal Spindrel bot, not an external harness session.

Spindrel still applies its secret redactor at the harness host boundary, covering both registered secret values and common token/key patterns. Streamed assistant text, thinking blocks, tool arguments, tool-result summaries, and the persisted final assistant message are scrubbed before they enter the channel bus or transcript. This is defense-in-depth, not a substitute for rotating any token that a native harness command already printed.

## How session resume works

Every turn returns a `session_id` from the SDK's `ResultMessage`. Spindrel persists it on the assistant message under `metadata.harness.session_id`. The next turn for the same Spindrel `Session.id` reads the most recent harness metadata and passes that to the SDK as `ClaudeAgentOptions(resume=...)` so the harness re-enters the same conversation — no re-introduction, no lost state.

Cost is read from persisted assistant-message harness metadata (`metadata.harness.cost_usd` / `usage`) and surfaced in the UI; the old bot-level `harness_session_state` column is not the source of truth for current harness turns.

Harness settings are Spindrel-session scoped. In the web UI, a slash command or model/approval pill targets the current pane/session id from component state or the route querystring. `channel.active_session_id` is only the primary/default fallback and the integration-mirroring pointer; it must not be treated as the target for scratch, split, or thread panes.

## Runtime controls

Each runtime exposes a `RuntimeCapabilities` contract through `GET /api/v1/runtimes/{name}/capabilities`. The host uses it to render harness controls and filter slash commands:

- `supported_models` / `available_models` plus `model_is_freeform` drive the harness model picker.
- `effort_values` controls whether an effort pill or `/effort` value is available. Claude Code currently exposes no effort knob.
- `approval_modes` powers the per-session approval-mode pill.
- `slash_policy.allowed_command_ids` filters `/api/v1/slash-commands?bot_id=...` and `/help`.

Per-session values are read and patched via `GET/POST /api/v1/sessions/{id}/harness-settings`. Missing patch keys mean no change; JSON `null` clears a value.

## Adding context

Just put files in the workspace directory. The harness reads what's there:

- Want your dotfiles' `CLAUDE.md` in the bot's view? `git clone git@github.com:me/dotfiles /data/harness/my-project/.dotfiles` (or whatever layout makes sense — the harness sees a normal filesystem).
- Want your vault available? `git clone git@github.com:me/vault /data/harness/my-project/vault` and reference it from your project-level `CLAUDE.md`.
- Want a Spindrel skill loaded? Copy its markdown into `<workdir>/.claude/skills/<name>.md` and the harness will pick it up via its own skill loader. (No automatic sync — Spindrel doesn't know what Claude Code's skill format requires; some Spindrel-internal skills will reference tools the harness doesn't have.)

There is intentionally no UI for this in v1. The directory IS the contract.

## Operational notes

- **Single OAuth identity per host.** All harness sessions using `claude` ride the same `~/.claude/credentials.json`. There's no per-bot or per-channel auth scoping.
- **Workspace dir must exist before the first message.** The driver hard-fails if `harness_workdir` doesn't resolve to a directory. Create it (and seed it) up-front.
- **The bundled CLI comes from the integration, not the base image.** Enabling the `claude_code` integration installs `claude-agent-sdk`, which bundles the `claude` CLI binary. The base Spindrel image installs no harness CLIs. To upgrade the SDK + CLI, reinstall the integration's deps from `/admin/integrations`.
- **The SDK is alpha.** The integration pins a loose floor (`claude-agent-sdk>=0.1.0`) so each integration-deps reinstall picks up the latest. The bridge unit tests in `tests/unit/test_claude_code_runtime_bridge.py` import the live SDK dataclasses, so any rename of `ResultMessage.total_cost_usd` or content-block restructure surfaces as a CI failure, not a silent zero-cost / blank-text production turn.

## Adding a new harness runtime

Each runtime lives **inside its own integration**, never in `app/`. The pattern mirrors how integration tools register today.

1. Pick (or create) the integration: `integrations/<id>/`. Add `harness` to its `integration.yaml` `provides:` list. Pin the harness's Python package in `integrations/<id>/requirements.txt`.
2. Implement `HarnessRuntime` in `integrations/<id>/harness.py` — `start_turn()` translates the harness's streaming output into `ChannelEventEmitter` calls, `auth_status()` reports login state, `capabilities()` describes model/effort/slash controls, and approval classification methods describe which native tools are read-only or prompt-worthy. Import host contracts from `integrations.sdk`.
3. At the bottom of `harness.py`, call `register_runtime(name, RuntimeClass())` so the side effect fires on import.
4. Add the runtime label to the dropdown in `ui/app/(app)/admin/bots/[botId]/index.tsx` (the harness section in `IdentitySection`).

That's it. `discover_and_load_harnesses()` walks `integrations/*/harness.py` for active integrations on app startup; the dispatch branch in `app/services/turn_worker.py` and the persistence/event surface require no changes.

When the integration is disabled at `/admin/integrations`, its harness module isn't imported, so the runtime simply doesn't appear in the registry, the bot-editor dropdown, or `/admin/harnesses`.

## What's coming

- **Codex driver:** Implement Codex against the same `TurnContext`, approval, settings, and capability contracts.
- **Native compact/status:** Add harness-aware `/compact` semantics that summarize/reset the native resume state, and expose runtime context/window status in the chat chrome when available.
- **Tool and skill bridge:** Expose selected Spindrel tools/skills to harnesses through a bridge that preserves dispatch, policy, approval, trace, and result envelopes.
- **Heartbeat/memory integration:** Add a harness heartbeat path that can inject optional context hints, then layer read-only memory hints before allowing explicit writes through bridged tools.
