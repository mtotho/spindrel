"""Core-feature scenario — admin-page heroes for guides without images.

Sub-pass 1 (admin-only):

  * ``webhooks-list.png``  — `/admin/webhooks` with 3 seeded endpoints
  * ``tools-library.png``  — `/admin/tools` (no staging)

Sub-pass 2 adds:

  * ``kb-detail.png``      — `/admin/learning#Knowledge` with seeded
    FilesystemChunk rows for ``screenshot-orchestrator``'s knowledge-base/
    folder so the inventory page shows real file/chunk counts and a
    ``last_indexed_at`` timestamp.

The chat-content captures (delegation / command-execution / plan-card /
subagents) remain queued — each needs distinct ``message.metadata`` shape
synthesis (assistant_turn_body + tool_calls + tool_results triples), best
done one at a time with visual verification.

All seeded webhook rows are keyed on stable ``name`` strings (the model has
no ``client_id``) so reruns dedupe and ``teardown_core_features`` cleans
exactly what was created. KB chunks are keyed on (bot_id, file_path,
chunk_index) inside the server helper.
"""
from __future__ import annotations

from . import StagedState
from . import bots as bot_scenarios
from .._exec import run_server_helper
from ..client import SpindrelClient


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


def stage_core_features(
    client: SpindrelClient,
    *,
    ssh_alias: str | None = None,
    ssh_container: str | None = None,
    dry_run: bool = False,
) -> StagedState:
    """Idempotent seed for the core-features admin captures.

    HTTP-only steps (webhook rows) always run. KB chunk seeding is gated on
    ``ssh_alias``/``ssh_container`` being supplied because the server helper
    pipes a script through ``docker exec``; without those there is no path
    to insert FilesystemChunk rows. In dry-run mode both HTTP and SSH paths
    log without mutating.
    """
    state = StagedState()
    if dry_run:
        return state

    for seed in WEBHOOK_SEEDS:
        client.ensure_webhook(**seed)

    if ssh_alias and ssh_container:
        bot_scenarios.ensure_demo_bots(client)
        run_server_helper(
            ssh_alias=ssh_alias,
            container=ssh_container,
            helper_name="seed_bot_knowledge_chunks",
            args=[KB_BOT_ID],
            dry_run=dry_run,
        )

    return state


def teardown_core_features(
    client: SpindrelClient,
    *,
    ssh_alias: str | None = None,
    ssh_container: str | None = None,
) -> None:
    """Remove seeded webhook rows + KB chunks.

    Bot rows themselves are intentionally left alone — flagship and
    docs-repair stagers may rely on them. ``ensure_demo_bots`` is
    idempotent, so re-running another scenario after this teardown
    re-creates anything that was removed.
    """
    seeded_names = {seed["name"] for seed in WEBHOOK_SEEDS}
    for hook in client.list_webhooks():
        if hook.get("name") in seeded_names:
            client.delete_webhook(hook["id"])

    if ssh_alias and ssh_container:
        run_server_helper(
            ssh_alias=ssh_alias,
            container=ssh_container,
            helper_name="clear_bot_knowledge_chunks",
            args=[KB_BOT_ID],
        )
