---
tags: [agent-server, plan, ui, tool-rendering, workspace-files]
status: draft
created: 2026-04-11
blocked-on: Track - Integration Delivery (Phase D minimum, Phase F for full capability wiring)
---
# Plan — Rich Tool Rendering & Pinned Workspace Panels

> **Status:** Draft. Not started. Do not begin implementation until [[Track - Integration Delivery]] Phase D has landed. See "Sequencing & conflicts" below. This plan was born from the UI Polish track item *"Investigate tool call rendering pattern"*.

## Motivation

Today, tool *results* are invisible to the user. `ui/src/components/chat/ToolBadges.tsx` surfaces tool names + arguments on click, but the actual result body (`tool_calls.result` column, `app/db/models.py:552`) is stored as flat `Text` and fed back only to the model. There is no rich-rendering surface for tool output — no markdown, no HTML widgets, no saveable artifacts, nothing like the Claude Desktop / Claude Code experience where a tool can produce a rendered artifact.

The long-term aspiration: **the agent builds user-facing features by writing files.** If a bot can save a dashboard, a report, or a dynamic HTML widget to the workspace and have it surface in the channel as a live panel, then the application gets minimal and the user gets customization for free — the bot authors the UI.

## Design — three separate mechanisms, one shared renderer

The core insight is that three ideas the user was conflating are actually distinct axes and should not share a flag:

### 1. Tool-result content type (per-result, ephemeral)
Tools return `{content_type, body}` and the UI picks a renderer keyed off mimetype. Default stays plain text; tools opt in.

- Schema addition to `ToolResultPart` (or equivalent) in `app/schemas/messages.py`: optional `content_type: str | None` and `display: Literal["inline", "panel", None]`.
- Dispatch-side change in `app/agent/tool_dispatch.py`: pass content_type through the result envelope to the event bus.
- Four UI renderers, keyed off mimetype:
  - `text/plain` — current badge behavior.
  - `text/markdown` — reuse existing `ui/src/components/chat/MarkdownContent.tsx`.
  - `application/json` — pretty tree (collapsible).
  - `text/html` — **sandboxed iframe**, strict CSP (`default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:`), no network, no same-origin. Spend a full session on the CSP and on attachment→blob-URL plumbing before shipping.
- `display` axis:
  - `None` (default) — current badge behavior, result body hidden.
  - `"inline"` — rendered in the chat stream under the tool call. Ephemeral, scrolls away with chat.
  - `"panel"` — opens in a transient side panel for this turn only. Not persisted.

### 2. Pinned workspace-file panels (per-channel, persistent)
A channel carries a list of pinned file paths. Writes to a pinned path refresh the panel. Unpinned writes are invisible regardless of how many happen.

- Storage: `channels.config.pinned_panels: list[{path: str, position: "right" | "bottom"}]`. No new table. JSONB mutation uses `copy.deepcopy()` + `flag_modified()` per the project gotcha.
- New bot tool (`app/tools/local/pin_panel.py` or folded into `file_ops.py`): `pin_panel(path, position="right")` / `unpin_panel(path)`. Tool policy: requires explicit bot enrollment, not auto-enrolled in the starter pack.
- User-facing: the workspace file browser UI gets a "Pin to channel" affordance on `.md`/`.html`/`.json`/`.txt` files. This is the non-bot entry point.
- Subscription: when a workspace file is written, emit a `PINNED_FILE_UPDATED` event on the `channel_events` bus (one event per channel that has the path pinned). The web UI subscribes and re-fetches the file content for the affected panel. **This is why Phase D must land first** — the bus is undergoing structural change for the integration-delivery outbox refactor and subscribing before it settles invites rebase pain.
- Renderer reuse: the side panel uses the **same mimetype-keyed renderers** as sub-piece 1. Mimetype is inferred from the file extension. One rendering code path, two entry points.

### 3. The split is the whole point

Do NOT merge these into one "`show_pinned_content=True`" param on file writes. They answer different questions:

- **"Is this file part of the channel's persistent view?"** → pin (channel-level, sticky, file-keyed, one-time subscription).
- **"Should the user see this particular result right now?"** → display hint (call-level, ephemeral, result-keyed, opt-in per tool call).

A bot should be able to silently update a pinned dashboard file without spamming chat every time it edits, *and* it should be able to occasionally surface an ephemeral widget that isn't pinned at all. One flag cannot serve both.

## Sequencing & conflicts

This plan is **blocked** on the in-flight refactors listed in the frontmatter. Conflict analysis:

| Sub-piece | Files touched | Conflict with Integration Delivery | Unblock condition |
|---|---|---|---|
| 1A. `content_type` schema | `app/schemas/messages.py`, `app/agent/tool_dispatch.py` | **HIGH.** Both files are in the dirty working tree for Integration Delivery Phase A + C1. | Phase D lands + working tree commits |
| 1B. `RICH_MARKDOWN`/`RICH_HTML` capabilities on `WebRenderer` | `app/integrations/core_renderers.py`, `Capability` enum | **HIGH.** The `Capability` enum won't stabilize until Phase F lands the SlackRenderer capability-aware downgrade. | Phase F lands |
| 1C. UI mimetype renderers | `ui/src/components/chat/ToolBadges.tsx`, new sibling components | LOW. UI-only. But useless without 1A feeding `content_type`. | Ships with 1A |
| 2. Pinned panels | `channels.config` JSONB, new tool, side-panel UI, `channel_events` subscription | LOW–MEDIUM. Separate code paths, but subscribes to the same bus the integration-delivery refactor is reshaping. | Phase D lands (bus structurally stable) |

## Recommended start order (after unblock)

1. **Sub-piece 2 first.** Pinned panels reuse the settled bus and have the lowest collision risk. They also deliver the "agent builds features by writing files" vision most directly. Ship read-only first: pin → panel displays file → writes trigger refresh. Editing/state/reactive behavior comes later (maybe never — files are enough).
2. **Sub-piece 1A + 1C together.** Once Phase F lands and the `Capability` enum is stable, add `content_type` to the tool result schema, wire through dispatch, and land the four UI renderers in one PR. Default to `text/plain` so existing tools are byte-identical.
3. **Sub-piece 1B** is a small follow-up: declare the new capabilities on `WebRenderer`, and make sure Slack/webhook renderers downgrade gracefully (Slack gets the plain-text `body`, web UI gets the rich renderer).

## What NOT to build

- **No "render_result_panel" per-tool hook.** That pushes UI code into every tool and creates 40 bespoke renderers. Mimetypes are a proven abstraction; use them.
- **No new "widgets" or "saved results" table.** You have files. Files have history (git/workspace). Files have sharing (workspaces). Files have versioning. The file *is* the widget.
- **No "terminal mode" in channels.** The underlying need is "run commands, see rich output inline." That's `exec_command` + a streaming plaintext renderer for its results (sub-piece 1). A modal shell is over-commitment.
- **No coupling to the integration delivery refactor beyond the `Capability` declaration.** Let integration delivery finish. This plan sits on top of it.
- **No ambient "show important writes" heuristic.** Display intent must be explicit — either pinned (persistent) or display-hinted (ephemeral). Heuristics here will be wrong most of the time.

## Open questions to resolve before starting

- **HTML iframe CSP details.** The user-facing risk is a bot writing malicious HTML (or being prompt-injected into writing it). The sandbox has to be airtight. Review `ui/global.css` CSP, nail down the allowlist, prototype an XSS attempt before trusting it.
- **Where does `display="inline"` render exactly?** Below the tool badge? Inline with the assistant message body? Collapsed by default, expand on click? Pick a rule before writing the component.
- **Pin scope.** Does a pin live on a channel, or on a workspace? Channel-level is simpler (user's channel = user's panels). Workspace-level is more sharable but bleeds panels across channels. Lean channel-level for v1.
- **Unpin on file delete.** If the pinned file is deleted from the workspace, does the pin auto-remove or become a 404 placeholder? Placeholder is more honest ("this was pinned, it's gone").
- **Who can pin?** Bot via tool *or* user via file browser? v1 can be user-only; bot-side pin is a follow-up after we see whether bots use it responsibly.

## Files that will be touched (forecast)

Backend:
- `app/schemas/messages.py` — `content_type`, `display` fields on tool result
- `app/agent/tool_dispatch.py` — thread content_type through result envelope
- `app/integrations/core_renderers.py` — `RICH_MARKDOWN`/`RICH_HTML` on `WebRenderer`
- `app/integrations/renderer.py` — new `Capability` variants
- `app/services/channel_events.py` — `PINNED_FILE_UPDATED` event type
- `app/tools/local/pin_panel.py` (new) or `file_ops.py` (extended)
- `app/services/workspace_files.py` or equivalent — emit `PINNED_FILE_UPDATED` on write if path is pinned in any channel
- `app/db/models.py` — **none.** Pins live in `channels.config` JSONB.

Frontend:
- `ui/src/components/chat/ToolBadges.tsx` — mimetype-based result rendering
- `ui/src/components/chat/MarkdownContent.tsx` — already exists, reused
- `ui/src/components/chat/renderers/JsonTree.tsx` (new)
- `ui/src/components/chat/renderers/SandboxedHtml.tsx` (new)
- `ui/src/components/channels/PinnedPanels.tsx` (new) — side-panel container
- `ui/src/components/workspace/FileBrowser.tsx` — pin affordance
- `ui/app/(app)/channels/[channelId]/index.tsx` — mount `PinnedPanels`

Tests:
- Unit tests for each renderer component
- Backend test for pin subscription + event emission
- Sandboxed HTML XSS test
- E2E test: bot writes `dashboard.md` → user pins it → bot edits → panel refreshes

## Cross-references

- [[Track - UI Polish]] — origin of the "Investigate tool call rendering pattern" item. When this plan is executed, mark that item done and link here.
- [[Track - Integration Delivery]] — blocker. `Capability` enum evolution happens there first.
- [[Architecture Decisions]] — the "one mechanism, two entry points" decision about shared renderers is worth an entry once this ships.
- [[Loose Ends]] — no entries yet; any discoveries during implementation land there.
