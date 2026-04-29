"""Project workspace screenshot scenario."""
from __future__ import annotations

import logging

from . import StagedState
from ..client import SpindrelClient

logger = logging.getLogger(__name__)

PROJECT_BOT_ID = "screenshot-projects"
PROJECT_CHANNEL_CLIENT_ID = "screenshot:project-workspace"
PROJECT_SLUG = "screenshot-project-workspace"
PROJECT_NAME = "Screenshot Project Workspace"
PROJECT_ROOT = "common/projects/spindrel-screenshot"


def stage_project_workspace(
    client: SpindrelClient,
    *,
    dry_run: bool = False,
) -> StagedState:
    state = StagedState()
    if dry_run:
        state.channels["project_workspace"] = "dry-run-channel"
        state.bots["project_bot"] = PROJECT_BOT_ID
        state.dashboards["project_workspace_project"] = "dry-run-project"
        return state

    workspaces = client.list_workspaces()
    if not workspaces:
        raise RuntimeError("project-workspace staging requires at least one workspace")
    workspace_id = str(workspaces[0]["id"])

    bot = client.ensure_bot(
        bot_id=PROJECT_BOT_ID,
        name="Project Screenshot Bot",
        model="gemini-2.5-flash",
        model_provider_id="gemini",
        system_prompt=(
            "You are a screenshot fixture bot. When asked to use memory, call the "
            "host-provided memory tool exactly as requested and then answer briefly."
        ),
    )
    client.update_bot(
        str(bot["id"]),
        model="gemini-2.5-flash",
        model_provider_id="gemini",
        memory_scheme="workspace-files",
    )
    state.bots["project_bot"] = PROJECT_BOT_ID

    project = client.ensure_project(
        workspace_id=workspace_id,
        name=PROJECT_NAME,
        slug=PROJECT_SLUG,
        root_path=PROJECT_ROOT,
        description="Shared Project root used by the screenshot Project workspace bundle.",
        prompt="Use this Project as the default working root for files, terminal, search, and harness turns.",
    )
    project_id = str(project["id"])
    state.dashboards["project_workspace_project"] = project_id

    channel = client.ensure_channel(
        client_id=PROJECT_CHANNEL_CLIENT_ID,
        bot_id=PROJECT_BOT_ID,
        name="Project workspace demo",
        category="Showcase",
    )
    channel_id = str(channel["id"])
    state.channels["project_workspace"] = channel_id

    client.update_channel_settings(
        channel_id,
        project_id=project_id,
        chat_mode="terminal",
        tool_output_display="expanded",
    )
    client.write_channel_workspace_file(
        channel_id,
        "README.md",
        "# Screenshot Project Workspace\n\nThis file is rooted at the shared Project, not the channel workspace.\n",
    )

    try:
        client.reset_channel(channel_id)
        client.seed_turn(
            channel_id=channel_id,
            bot_id=PROJECT_BOT_ID,
            message=(
                "Call the host-provided memory tool exactly once with this JSON object as arguments: "
                '{"operation":"replace_section","path":"MEMORY.md","heading":"Screenshot Project Workspace",'
                '"content":"Project workspace screenshot memory fact."} '
                "Do not use shell commands. After the tool call, reply with one short sentence saying the memory was updated."
            ),
            expected_tool="memory",
            timeout_s=180.0,
        )
    except Exception:
        logger.exception("project-workspace memory turn seed failed; capture will show the channel if transcript is missing")

    return state


def teardown_project_workspace(client: SpindrelClient) -> None:
    for ch in client.list_channels():
        if ch.get("client_id") == PROJECT_CHANNEL_CLIENT_ID:
            client.delete_channel(ch["id"])
