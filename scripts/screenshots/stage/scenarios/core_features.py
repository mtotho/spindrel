"""Core-feature scenario — admin-page heroes + chat-content heroes.

Sub-pass 1 (admin-only):
  * ``webhooks-list.png``  — `/admin/webhooks` with 3 seeded endpoints
  * ``tools-library.png``  — `/admin/tools` (no staging)

Sub-pass 2a (KB inventory):
  * ``kb-detail.png``      — `/admin/learning#Knowledge` after seeding
    FilesystemChunk rows for ``screenshot-orchestrator``.

Sub-pass 2b (chat-content heroes — live agent loop driven):
  * ``chat-delegation.png`` — DelegationCard via ``delegate_to_agent`` to Vega

Each chat-content capture lives on its own dedicated channel so reruns reset
just that channel's session without nuking flagship's seeded
``screenshot:chat-main`` content. Channels are addressed by stable
``screenshot:chat-<name>`` client_ids and dedupe through ``ensure_channel``.

Model choice: the orchestrator is pinned to ``gemini-2.5-flash`` (provider
``gemini``) for these captures because the e2e instance routes that pair
through LiteLLM cheaply and Flash reliably calls the requested tool when
the user message names it explicitly. ``screenshot-researcher`` stays on
``gemini-2.5-flash-lite`` so the delegation child task is even cheaper.

All seeded webhook rows are keyed on stable ``name`` strings (the model has
no ``client_id``) so reruns dedupe and ``teardown_core_features`` cleans
exactly what was created. KB chunks key on (bot_id, file_path, chunk_index)
inside the server helper.
"""
from __future__ import annotations

import logging

from . import StagedState
from . import bots as bot_scenarios
from .._exec import run_server_helper
from ..client import SpindrelClient

logger = logging.getLogger(__name__)


# Stable webhook seeds. Keep names + URLs + event filters varied so the
# hero shows the visual range (multiple events per row, single-event rows,
# mixed lifecycle hooks).
WEBHOOK_SEEDS: list[dict] = [
    {
        "name": "GitHub Actions trigger",
        "url": "https://api.github.com/repos/example/agent-server/dispatches",
        "events": ["after_response", "after_task_complete"],
        "description": "Fires a repository_dispatch on every assistant turn so CI can react to a bot decision.",
    },
    {
        "name": "Datadog tool-call traces",
        "url": "https://collector.example.com/v1/traces",
        "events": [
            "before_tool_execution",
            "after_tool_call",
            "before_llm_call",
            "after_llm_call",
        ],
        "description": "Streams every tool + LLM call to the metrics pipeline.",
    },
    {
        "name": "Slack status pings",
        "url": "https://hooks.slack.com/services/T00000000/B00000000/screenshot-demo",
        "events": ["after_response"],
        "description": "Posts a one-line summary of the assistant turn back into #ai-ops.",
    },
]


# Bot we attach the KB seeds to. ensure_demo_bots() (re)creates the full
# screenshot-* trio idempotently — running --only core-features on a clean
# instance no longer requires --only flagship to have run first.
KB_BOT_ID = "screenshot-orchestrator"
DELEGATE_BOT_ID = "screenshot-researcher"

# Cheap, tool-call-capable model wired through LiteLLM on the e2e instance.
# Anthropic isn't configured there, so the bot's default ``claude-sonnet-4-6``
# 404s. Flash is reliable enough that the seed_turn assertion (must call the
# named tool) usually passes on the first run.
CHAT_PARENT_MODEL = ("gemini-2.5-flash", "gemini")
CHAT_CHILD_MODEL = ("gemini-2.5-flash-lite", "gemini")


# Per-capture channel layout. Each dedicated channel scopes its session so
# reset_channel + seed_turn produce a clean single-turn conversation that
# renders the target card without tail messages from prior runs leaking in.
CHAT_DELEGATION_CHANNEL = "screenshot:chat-delegation"
CHAT_CMD_EXEC_CHANNEL = "screenshot:chat-cmd-exec"
CHAT_PLAN_CHANNEL = "screenshot:chat-plan"
CHAT_SUBAGENTS_CHANNEL = "screenshot:chat-subagents"

CHAT_CONTENT_CHANNELS: list[tuple[str, str, str]] = [
    (CHAT_DELEGATION_CHANNEL, "Delegation demo", "Showcase"),
    (CHAT_CMD_EXEC_CHANNEL,   "Command execution demo", "Showcase"),
    (CHAT_PLAN_CHANNEL,       "Plan demo", "Showcase"),
    (CHAT_SUBAGENTS_CHANNEL,  "Subagents demo", "Showcase"),
]

# The exact prompt we send for each capture. Keep these tightly directive
# — frontier models call the named tool reliably, but cheap models need
# the function name + key arg names spelled out, otherwise they'll prose
# their way around the request. The cmd-exec prompt also explicitly asks
# the model to quote raw stdout in a fenced block, so the hero shows the
# tool badge + a short narration + a real shell-output card instead of a
# summarized paraphrase.
CHAT_DELEGATION_PROMPT = (
    "Have Vega (screenshot-researcher) look up the current best practices "
    "for self-hosted vector search backends. Use the delegate_to_agent tool. "
    "Set notify_parent to false (fire-and-forget)."
)
CHAT_CMD_EXEC_PROMPT = (
    "Run \"python -c \\\"import sys, platform; print(sys.version.split()[0]); "
    "print(platform.system(), platform.release())\\\"\" via the exec_command "
    "tool. After it runs, briefly state the Python version and OS in 1-2 "
    "sentences AND quote the exact stdout in a fenced bash code block."
)
# Plan card hero. The bot fails on open-ended plan prompts at flash tier
# (it tries to ask clarifying questions and the schema-constrained
# publish_plan call never lands), so this prompt pre-fills the exact
# title/summary/scope/steps and instructs it to publish without any
# clarifying questions. Plan mode must be active before send — the seed
# helper enters plan mode first.
CHAT_PLAN_PROMPT = (
    "Publish this exact plan now using the publish_plan tool. Do not ask any "
    "clarifying questions.\n\n"
    "title: \"Nightly Postgres backup pipeline\"\n"
    "summary: \"Snapshot Postgres nightly, ship to S3-compatible storage, and "
    "verify weekly with a restore dry-run.\"\n"
    "scope: \"Spindrel server only. Excludes app-level dump scripts and Slack "
    "notifications.\"\n"
    "steps:\n"
    "  - label: \"Snapshot at 03:00 via pg_dump --format=custom\"\n"
    "  - label: \"Encrypt and upload to S3-compatible bucket via rclone\"\n"
    "  - label: \"Run weekly restore dry-run into a throwaway DB\"\n"
    "  - label: \"Alert ops via webhook on any failure\""
)
# Subagents prompt. Two narrowly-scoped read-only tasks so each child stays
# bounded; the synthesizer-style follow-up at the end keeps the parent's
# final assistant message non-trivial. Subagent turns inline-render WEB
# SEARCH / READ rows on the parent channel while still in flight, so the
# stager passes ``wait_subagents=True`` to let those finish before capture.
CHAT_SUBAGENTS_PROMPT = (
    "Run two bounded read-only sub-agents in parallel using spawn_subagents. "
    "Pass exactly this agents list:\n"
    "agents:\n"
    "  - preset: \"summarizer\"\n"
    "    prompt: \"In 2 bullets, summarize what HNSW means for vector search "
    "and when to prefer it over IVF-Flat.\"\n"
    "  - preset: \"researcher\"\n"
    "    prompt: \"List 3 widely-used open-source vector databases with one-"
    "line descriptions each.\"\n"
    "After the tool returns, give me a one-sentence synthesis."
)


def _ensure_chat_content_bots(client: SpindrelClient) -> None:
    """Pin the screenshot bots to a model the e2e instance can actually serve.

    ``ensure_demo_bots`` creates rows with the registry defaults
    (``claude-sonnet-4-6``); the e2e instance has no Anthropic provider so
    those 404 at chat time. PATCH each bot to the LiteLLM-routed Gemini pair
    that the e2e provider list actually exposes. Runs every stage so manual
    edits in the admin UI don't quietly break the next capture run.
    """
    bot_scenarios.ensure_demo_bots(client)

    parent_model, parent_provider = CHAT_PARENT_MODEL
    child_model, child_provider = CHAT_CHILD_MODEL
    client.update_bot(
        KB_BOT_ID,
        model=parent_model,
        model_provider_id=parent_provider,
        delegation_config={
            "delegate_bots": [DELEGATE_BOT_ID],
            "cross_workspace_access": False,
        },
    )
    client.update_bot(
        DELEGATE_BOT_ID,
        model=child_model,
        model_provider_id=child_provider,
    )


def _ensure_chat_content_channels(client: SpindrelClient) -> dict[str, str]:
    """Create the dedicated chat-content channels and return a label→id map."""
    out: dict[str, str] = {}
    for client_id, name, category in CHAT_CONTENT_CHANNELS:
        ch = client.ensure_channel(
            client_id=client_id,
            bot_id=KB_BOT_ID,
            name=name,
            category=category,
        )
        out[client_id] = str(ch["id"])
    return out


def stage_core_features(
    client: SpindrelClient,
    *,
    ssh_alias: str | None = None,
    ssh_container: str | None = None,
    dry_run: bool = False,
) -> StagedState:
    """Idempotent seed for the core-features captures.

    Layered so partial environments still work: HTTP-only steps (webhooks,
    bots, channels, model patches) always run; KB chunk seeding requires
    ``ssh_alias``/``ssh_container`` because the helper pipes through
    ``docker exec``; ``seed_turn`` requires a working LLM provider on the
    target instance and is skipped silently when the parent bot's provider
    fails so the rest of the captures still ship.
    """
    state = StagedState()
    if dry_run:
        return state

    for seed in WEBHOOK_SEEDS:
        client.ensure_webhook(**seed)

    _ensure_chat_content_bots(client)
    state.channels.update(_ensure_chat_content_channels(client))

    if ssh_alias and ssh_container:
        run_server_helper(
            ssh_alias=ssh_alias,
            container=ssh_container,
            helper_name="seed_bot_knowledge_chunks",
            args=[KB_BOT_ID],
            dry_run=dry_run,
        )

    # (channel_id, prompt, expected_tool, plan_mode, wait_subagents) —
    # plan_mode toggles a POST /sessions/{sid}/plan/start before sending so
    # publish_plan is accepted; wait_subagents waits for spawn_subagents'
    # ephemeral child turns to finish their inline WEB SEARCH / READ rows.
    chat_seeds: list[tuple[str, str, str, bool, bool]] = [
        (CHAT_DELEGATION_CHANNEL, CHAT_DELEGATION_PROMPT, "delegate_to_agent", False, False),
        (CHAT_CMD_EXEC_CHANNEL,   CHAT_CMD_EXEC_PROMPT,   "exec_command",      False, False),
        (CHAT_PLAN_CHANNEL,       CHAT_PLAN_PROMPT,       "publish_plan",      True,  False),
        (CHAT_SUBAGENTS_CHANNEL,  CHAT_SUBAGENTS_PROMPT,  "spawn_subagents",   False, True),
    ]
    for client_id, prompt, expected_tool, plan_mode, wait_sub in chat_seeds:
        cid = state.channels.get(client_id)
        if not cid:
            continue
        try:
            client.reset_channel(cid)
            if plan_mode:
                sid = client.get_active_session_id(cid)
                if sid:
                    client.start_session_plan_mode(sid)
            client.seed_turn(
                channel_id=cid,
                bot_id=KB_BOT_ID,
                message=prompt,
                expected_tool=expected_tool,
                timeout_s=180.0,
                wait_subagents=wait_sub,
            )
        except Exception:
            # Seeding flake (provider 404, model picked the wrong tool, etc.)
            # is loud-logged but doesn't sink the rest of the pass — the
            # admin / KB captures still ship and a rerun is cheap.
            logger.exception(
                "chat-content seed failed for %s; capture will likely 404 the predicate",
                client_id,
            )

    return state


def teardown_core_features(
    client: SpindrelClient,
    *,
    ssh_alias: str | None = None,
    ssh_container: str | None = None,
) -> None:
    """Remove seeded webhook rows + KB chunks + dedicated chat-content channels.

    Bot rows themselves are intentionally left alone — flagship and
    docs-repair stagers may rely on them. ``ensure_demo_bots`` is idempotent,
    so re-running another scenario after this teardown re-creates anything
    that was removed. Reverting the orchestrator's model PATCH is also
    skipped: ``ensure_demo_bots`` would just re-pin Gemini on the next run.
    """
    seeded_names = {seed["name"] for seed in WEBHOOK_SEEDS}
    for hook in client.list_webhooks():
        if hook.get("name") in seeded_names:
            client.delete_webhook(hook["id"])

    seeded_chat_clients = {client_id for client_id, _, _ in CHAT_CONTENT_CHANNELS}
    for ch in client.list_channels():
        if ch.get("client_id") in seeded_chat_clients:
            client.delete_channel(ch["id"])

    if ssh_alias and ssh_container:
        run_server_helper(
            ssh_alias=ssh_alias,
            container=ssh_container,
            helper_name="clear_bot_knowledge_chunks",
            args=[KB_BOT_ID],
        )
