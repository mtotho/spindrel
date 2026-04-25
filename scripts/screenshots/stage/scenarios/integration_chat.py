"""Integration-chat scenario — captures of REAL bot tool calls.

Each capture drives the agent loop with a tightly-prompted user message and
asserts the named integration tool actually fires. The result widget (rendered
diagram, slide deck attachment, browser screenshot) is part of the captured
chat — no synthetic envelopes, no admin-page stand-ins.

Captures:

* ``chat-excalidraw.png`` — `mermaid_to_excalidraw` rendering a small system
  diagram in chat. Server-side puppeteer-core render; no external pairing.
* ``chat-marp.png`` — `create_marp_slides` (or legacy ``create_slides`` on
  older deployments) producing a slide-deck attachment widget. Server-side
  Marp via ``npx``.
* ``chat-browser-live.png`` — `browser_screenshot` driving a Playwright
  "extension simulator" paired over the WS bridge. The simulator is a thin
  Python proxy from the bridge's RPC verbs (goto/screenshot/...) onto a
  Playwright Page, so the bot really opens a browser and captures it.

Channel client_ids are stable (`screenshot:chat-<name>`) so reruns dedupe
through `ensure_channel`. Each channel scopes its own session so reset +
seed_turn produce a clean single-turn conversation.
"""
from __future__ import annotations

import logging
from typing import Any

from . import StagedState
from . import bots as bot_scenarios
from . import core_features as core
from ..client import SpindrelClient

logger = logging.getLogger(__name__)


CHAT_EXCALIDRAW_CHANNEL = "screenshot:chat-excalidraw"
CHAT_MARP_CHANNEL = "screenshot:chat-marp"
CHAT_BROWSER_LIVE_CHANNEL = "screenshot:chat-browser-live"


CHAT_INTEGRATION_CHANNELS: list[tuple[str, str, str]] = [
    (CHAT_EXCALIDRAW_CHANNEL,   "Excalidraw demo",   "Showcase"),
    (CHAT_MARP_CHANNEL,         "Marp slides demo",  "Showcase"),
    (CHAT_BROWSER_LIVE_CHANNEL, "Browser-live demo", "Showcase"),
]


# Tool prompts — name the tool and pass concrete inputs. Frontier models pick
# the right tool from intent alone; cheap models (Flash tier) need the
# function name + a worked example, otherwise they prose around it.
EXCALIDRAW_PROMPT = (
    "Use the mermaid_to_excalidraw tool to render this diagram. "
    "Mermaid input:\n\n"
    "graph LR\n"
    "  User -->|prompt| Bot\n"
    "  Bot -->|tool call| Server\n"
    "  Server -->|result| Bot\n"
    "  Bot -->|widget| User\n"
    "After it returns, say one short sentence about what the diagram shows."
)

# E2E instance may still be on the pre-rename `slides` integration. The
# resolver in seed_turn falls back to the legacy name if `create_marp_slides`
# is not in tool_calls. Spell out content; Flash tier won't invent a multi-
# slide deck without it.
MARP_PROMPT = (
    "Use the create_marp_slides tool (or create_slides if that's the only "
    "available name) to render this 3-slide deck. Use HTML format and "
    "filename 'spindrel-quickstart'. Markdown:\n\n"
    "---\n"
    "marp: true\n"
    "theme: default\n"
    "paginate: true\n"
    "---\n"
    "\n"
    "# Spindrel\n"
    "## A workspace, as a place\n"
    "\n"
    "---\n"
    "\n"
    "## Pin tool results as widgets\n"
    "\n"
    "- Live HTML widgets your bot writes\n"
    "- Per-channel dashboards from real tool runs\n"
    "- Pinnable to the spatial canvas\n"
    "\n"
    "---\n"
    "\n"
    "## Pipelines stream progress\n"
    "\n"
    "- Steps post into the chat as they run\n"
    "- Sub-sessions for each step\n"
    "- Webhooks + approvals for guarded actions\n"
    "\n"
    "After the tool returns, say one short sentence about the deck."
)

BROWSER_LIVE_PROMPT = (
    "First call browser_status to confirm a paired browser is available. "
    "If a connection is paired, then call browser_goto with url "
    "'https://example.com', then call browser_screenshot to capture it. "
    "Briefly describe what the page shows in 1-2 sentences."
)


# Tool-name preferences. The resolver hands the *first* match in this list to
# `expected_tool` so reruns succeed against either commit-tip code (where
# Marp is `create_marp_slides`) or the older `slides` integration on e2e
# (where the tool is `create_slides`).
EXCALIDRAW_EXPECTED_TOOLS = ("mermaid_to_excalidraw", "create_excalidraw")
MARP_EXPECTED_TOOLS = ("create_marp_slides", "create_slides")
BROWSER_LIVE_EXPECTED_TOOLS = ("browser_screenshot", "browser_status")


def _ensure_channels(client: SpindrelClient) -> dict[str, str]:
    out: dict[str, str] = {}
    for client_id, name, category in CHAT_INTEGRATION_CHANNELS:
        ch = client.ensure_channel(
            client_id=client_id,
            bot_id=core.KB_BOT_ID,
            name=name,
            category=category,
        )
        out[client_id] = str(ch["id"])
    return out


def _seed_with_tool_fallback(
    client: SpindrelClient,
    *,
    channel_id: str,
    bot_id: str,
    prompt: str,
    expected_tools: tuple[str, ...],
    timeout_s: float = 240.0,
) -> dict[str, Any] | None:
    """Drive seed_turn, accepting any of ``expected_tools`` as a hit.

    `client.seed_turn` only takes a single ``expected_tool`` string, so we
    invoke it WITHOUT an assertion, then check ``tool_calls`` ourselves. This
    is what lets the same prompt work against both commit-tip code (new tool
    name) and the older e2e instance (legacy name) without branching.
    """
    client.reset_channel(channel_id)
    msg = client.seed_turn(
        channel_id=channel_id,
        bot_id=bot_id,
        message=prompt,
        expected_tool=None,
        timeout_s=timeout_s,
    )
    tool_calls = msg.get("tool_calls") or []
    names = []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        n = fn.get("name") or tc.get("name")
        if n:
            names.append(n)
    hit = next((n for n in expected_tools if n in names), None)
    if hit:
        logger.info("integration-chat: %s called %s", channel_id, hit)
        return msg
    logger.warning(
        "integration-chat: %s did not call any of %s (got %s)",
        channel_id, expected_tools, names,
    )
    return None


def stage_integration_chat(
    client: SpindrelClient,
    *,
    ssh_alias: str | None = None,
    ssh_container: str | None = None,
    dry_run: bool = False,
) -> StagedState:
    state = StagedState()
    if dry_run:
        return state

    # Reuse the orchestrator+vega pair from core_features so the bot is
    # pinned to a model that the e2e provider list actually serves.
    bot_scenarios.ensure_demo_bots(client)
    core._ensure_chat_content_bots(client)  # noqa: SLF001 — internal helper, intentional reuse

    # Pin the integration tools directly on the orchestrator so the agent
    # loop hits them without going through the multi-turn search_tools /
    # get_tool_info discovery dance. Both legacy + new tool names included
    # so the same scenario works against commit-tip code and older e2e
    # snapshots. Restored to ``[]`` in teardown.
    pinned = [
        "mermaid_to_excalidraw", "create_excalidraw",
        "create_marp_slides", "create_slides",
        "browser_status", "browser_goto", "browser_screenshot",
    ]
    try:
        client.update_bot(core.KB_BOT_ID, pinned_tools=pinned)
    except Exception:
        logger.exception(
            "failed to pin integration tools on %s; bot will fall back to "
            "discovery (and likely respond with search_tools / get_tool_info)",
            core.KB_BOT_ID,
        )

    state.channels.update(_ensure_channels(client))

    seeds: list[tuple[str, str, tuple[str, ...]]] = [
        (CHAT_EXCALIDRAW_CHANNEL,   EXCALIDRAW_PROMPT,   EXCALIDRAW_EXPECTED_TOOLS),
        (CHAT_MARP_CHANNEL,         MARP_PROMPT,         MARP_EXPECTED_TOOLS),
        (CHAT_BROWSER_LIVE_CHANNEL, BROWSER_LIVE_PROMPT, BROWSER_LIVE_EXPECTED_TOOLS),
    ]
    for client_id, prompt, expected in seeds:
        cid = state.channels.get(client_id)
        if not cid:
            continue
        try:
            _seed_with_tool_fallback(
                client,
                channel_id=cid,
                bot_id=core.KB_BOT_ID,
                prompt=prompt,
                expected_tools=expected,
            )
        except Exception:
            logger.exception(
                "integration-chat seed failed for %s; capture will likely show a "
                "tool-error or pre-tool message instead of the rendered widget",
                client_id,
            )

    # Resolve a "spatial_main" placeholder convention so capture specs that
    # need any of these channel UUIDs can substitute by client_id key.
    state.channels.setdefault("integration_chat_excalidraw", state.channels[CHAT_EXCALIDRAW_CHANNEL])
    state.channels.setdefault("integration_chat_marp", state.channels[CHAT_MARP_CHANNEL])
    state.channels.setdefault("integration_chat_browser_live", state.channels[CHAT_BROWSER_LIVE_CHANNEL])
    return state


def teardown_integration_chat(client: SpindrelClient) -> None:
    seeded = {client_id for client_id, _, _ in CHAT_INTEGRATION_CHANNELS}
    for ch in client.list_channels():
        if ch.get("client_id") in seeded:
            client.delete_channel(ch["id"])
    # Restore the orchestrator to its default (no pinned tools) so unrelated
    # captures don't run with a sticky integration-chat tool surface.
    try:
        client.update_bot(core.KB_BOT_ID, pinned_tools=[])
    except Exception:
        logger.exception("failed to clear pinned_tools on %s", core.KB_BOT_ID)
