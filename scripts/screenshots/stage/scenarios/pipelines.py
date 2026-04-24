"""Mid-run pipeline stager.

Uses the HTTP admin API to create a normal 3-step pipeline, then invokes the
``seed_pipeline_step_states`` docker-exec helper to mutate runtime fields
(``step_states`` + ``status``) directly on the Task row. The API deliberately
does not expose those fields on create — see the revised plan for rationale.
"""
from __future__ import annotations

from ..client import SpindrelClient
from .._exec import run_server_helper

PIPELINE_TITLE_MARK = "screenshot:pipeline-demo"


def ensure_midrun_pipeline(
    client: SpindrelClient,
    *,
    bot_id: str,
    channel_id: str,
    ssh_alias: str,
    ssh_container: str,
    dry_run: bool = False,
) -> str:
    """Idempotent: return an existing screenshot-pipeline task_id or create one."""

    existing = [t for t in client.list_tasks(bot_id=bot_id) if t.get("title") == PIPELINE_TITLE_MARK]
    if existing:
        task_id = str(existing[0]["id"])
    else:
        created = client.create_pipeline(
            bot_id=bot_id,
            channel_id=channel_id,
            title=PIPELINE_TITLE_MARK,
            steps=[
                {"name": "Collect inputs",
                 "prompt": "Gather weather, calendar, and overnight alerts."},
                {"name": "Summarize overnight",
                 "prompt": "Write a one-paragraph overnight summary."},
                {"name": "Post to channel",
                 "prompt": "Post the summary to the morning briefing channel."},
            ],
        )
        task_id = str(created["id"])

    # Seed step_states = [done, done, running]; the UI renders from this.
    run_server_helper(
        ssh_alias=ssh_alias,
        container=ssh_container,
        helper_name="seed_pipeline_step_states",
        args=[task_id, "2"],
        dry_run=dry_run,
    )
    # Seed the sub-session + messages so PipelineRunLive mounts SessionChatView
    # instead of the "Spinning up the run session…" loader.
    run_server_helper(
        ssh_alias=ssh_alias,
        container=ssh_container,
        helper_name="seed_pipeline_run_session",
        args=[task_id],
        dry_run=dry_run,
    )
    return task_id


def teardown_midrun_pipelines(client: SpindrelClient, *, bot_id: str) -> None:
    for t in client.list_tasks(bot_id=bot_id):
        if t.get("title") == PIPELINE_TITLE_MARK:
            client.delete_task(str(t["id"]))
