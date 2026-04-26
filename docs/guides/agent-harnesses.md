# Agent Harnesses

A **harness bot** is a Spindrel bot whose turn is driven by an external agent harness (Claude Code today, Codex later) instead of Spindrel's own RAG loop. The chat UI is Spindrel; the agent loop, tools, file edits, and bash are the harness's. You bring your own workspace and your own OAuth login.

The point: manage Claude Code sessions in your browser, alongside your Spindrel bots, with persistence across restarts — without giving up the harness's own ecosystem (its skills, hooks, MCP servers, slash commands).

## Quick start

1. **Enable the integration that owns the runtime.** Each harness ships as part of an integration, not as a baked-in dep. For Claude Code: open `/admin/integrations`, find Claude Code, click Enable. The integration's `requirements.txt` (which pins `claude-agent-sdk`) installs on enable; the SDK bundles the `claude` CLI alongside it. **No SDK or CLI lives in the base Docker image** — nothing related to a harness ships with Spindrel itself.

2. **Authenticate the harness from the admin UI.** Open `/admin/harnesses`. Each enabled integration that provides a harness shows up as a card. If it's not authenticated, click the **Run `claude login`** button — a terminal drawer opens inside the Spindrel container with the command already running. Complete the OAuth flow in your browser, paste the code back into the drawer, close it. The card auto-refreshes to ✓ "Logged in via …".

    Under the hood the CLI writes credentials to `$CLAUDE_CONFIG_DIR/.credentials.json` (default `~/.claude/.credentials.json`). The Claude Agent SDK that the integration installed inherits these credentials — no API key needed. See [Admin Terminal](admin-terminal.md) for the terminal mechanics.

    *Old SSH workflow* (still works if you prefer): `docker exec -it spindrel claude login`.

3. **Workspace root mount.** Per-bot workspaces live under one directory tree, by default `/data/harness/`. The harnesses page detects when this path isn't mounted and shows a banner with the docker-compose snippet to paste. Add it once and run `docker compose up -d`; the banner disappears.

4. **Create a harness bot and seed its workspace.** `/admin/bots` → New bot. In the **Identity** group, set:

    - **Runtime:** `Claude Code`
    - **Workspace path:** `/data/harness/my-project`

    Then click **Create workspace dir** (mkdir from the in-app terminal) and **Clone a repo** (opens a terminal in the workspace; type `git clone <url> .`). The harness sees that directory as its cwd — drop your `CLAUDE.md`, `AGENTS.md`, vault excerpts, sibling repos in there.

    Other fields (model, system prompt, skills, tools, memory) are inert when a runtime is set — the harness owns them.

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

## What harness bots intentionally do *not* do

These are deliberate v1 boundaries, not oversights:

- **No Spindrel skills, KB, or capability injection.** The harness reads its own skills from `~/.claude/skills/`, project `.claude/skills/`, etc. Spindrel's discovery layer is not bridged.
- **No widgets / no tool-result envelopes.** The harness emits plain text + tool-call breadcrumbs. No `emit_html_widget`, no standing orders, no dashboard pins.
- **No Spindrel approvals UI for tool calls.** The driver runs with `allowed_tools=["Read","Glob","Grep","Bash","Edit","Write","Task","WebFetch","WebSearch"]` and `permission_mode="acceptEdits"` — listed tools auto-approve, anything else hard-fails. To loosen, use `permission_mode="bypassPermissions"` (planned per-bot toggle in Phase 2).
- **No `/admin/usage` integration.** Cost and token usage are persisted on the assistant message under `metadata.harness.cost_usd`/`usage`, but not aggregated in the global cost dashboard yet.
- **No tool-call rehydration after page refresh.** The live stream shows tool calls; on reload, only the final assistant text comes back from the `Message` row.
- **No @-mention fanout.** A harness bot owns its turn end-to-end; it doesn't trigger member-bot replies, supervisors, or context compaction.

If you need any of those, you want a Spindrel bot, not a harness bot.

## How session resume works

Every turn returns a `session_id` from the SDK's `ResultMessage`. We persist it in `bots.harness_session_state.session_id`. The next turn passes that to the SDK as `ClaudeAgentOptions(resume=...)` so the harness re-enters the same conversation — no re-introduction, no lost state.

Cost accumulates in `harness_session_state.cost_total` (sum of `total_cost_usd` reported by each `ResultMessage`).

## Adding context

Just put files in the workspace directory. The harness reads what's there:

- Want your dotfiles' `CLAUDE.md` in the bot's view? `git clone git@github.com:me/dotfiles /data/harness/my-project/.dotfiles` (or whatever layout makes sense — the harness sees a normal filesystem).
- Want your vault available? `git clone git@github.com:me/vault /data/harness/my-project/vault` and reference it from your project-level `CLAUDE.md`.
- Want a Spindrel skill loaded? Copy its markdown into `<workdir>/.claude/skills/<name>.md` and the harness will pick it up via its own skill loader. (No automatic sync — Spindrel doesn't know what Claude Code's skill format requires; some Spindrel-internal skills will reference tools the harness doesn't have.)

There is intentionally no UI for this in v1. The directory IS the contract.

## Operational notes

- **Single OAuth identity per host.** All harness channels using `claude` ride the same `~/.claude/credentials.json`. There's no per-bot or per-channel auth scoping.
- **Workspace dir must exist before the first message.** The driver hard-fails if `harness_workdir` doesn't resolve to a directory. Create it (and seed it) up-front.
- **The bundled CLI comes from the integration, not the base image.** Enabling the `claude_code` integration installs `claude-agent-sdk`, which bundles the `claude` CLI binary. The base Spindrel image installs no harness CLIs. To upgrade the SDK + CLI, reinstall the integration's deps from `/admin/integrations`.
- **The SDK is alpha.** The integration pins a loose floor (`claude-agent-sdk>=0.1.0`) so each integration-deps reinstall picks up the latest. The bridge unit tests in `tests/unit/test_claude_code_runtime_bridge.py` import the live SDK dataclasses, so any rename of `ResultMessage.total_cost_usd` or content-block restructure surfaces as a CI failure, not a silent zero-cost / blank-text production turn.

## Adding a new harness runtime

Each runtime lives **inside its own integration**, never in `app/`. The pattern mirrors how integration tools register today.

1. Pick (or create) the integration: `integrations/<id>/`. Add `harness` to its `integration.yaml` `provides:` list. Pin the harness's Python package in `integrations/<id>/requirements.txt`.
2. Implement `HarnessRuntime` in `integrations/<id>/harness.py` — one `start_turn()` method that translates the harness's streaming output into `ChannelEventEmitter` calls, plus an `auth_status()` method. Import from `app.services.agent_harnesses.base`, never reach into `app/services/agent_harnesses/__init__.py` for runtime classes.
3. At the bottom of `harness.py`, call `register_runtime(name, RuntimeClass())` so the side effect fires on import.
4. Add the runtime label to the dropdown in `ui/app/(app)/admin/bots/[botId]/index.tsx` (the harness section in `IdentitySection`).

That's it. `discover_and_load_harnesses()` walks `integrations/*/harness.py` for active integrations on app startup; the dispatch branch in `app/services/turn_worker.py` and the persistence/event surface require no changes.

When the integration is disabled at `/admin/integrations`, its harness module isn't imported, so the runtime simply doesn't appear in the registry, the bot-editor dropdown, or `/admin/harnesses`.

## What's coming

- **Phase 2:** Workspace list on `/admin/harnesses` (per-bot last session id + cost), "open in shell" hint, bot-editor "Create workspace dir" button.
- **Phase 3:** Per-channel plan-mode toggle (`permission_mode="plan"`); permission-request routing into Spindrel's approvals UI via the SDK's `can_use_tool` callback.
- **Phase 4:** Codex driver. Either via the `codex-app-server-sdk` Python package once it lands on PyPI, or via subprocess to the `codex` CLI sooner — the protocol accepts both.
