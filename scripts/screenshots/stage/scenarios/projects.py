"""Project workspace screenshot scenario."""
from __future__ import annotations

import logging

from . import StagedState
from ..client import SpindrelClient

logger = logging.getLogger(__name__)

PROJECT_BOT_ID = "screenshot-projects"
PROJECT_CHANNEL_CLIENT_ID = "screenshot:project-workspace"
PROJECT_ATTACH_CLIENT_ID = "screenshot:project-workspace-attachable"
PROJECT_SLUG = "screenshot-project-workspace"
PROJECT_NAME = "Screenshot Project Workspace"
PROJECT_ROOT = "common/projects/spindrel-screenshot"
BLUEPRINT_SLUG = "screenshot-service-blueprint"
BLUEPRINT_NAME = "Screenshot Service Blueprint"
BLUEPRINT_PROJECT_SLUG = "screenshot-blueprint-project"
BLUEPRINT_PROJECT_NAME = "Screenshot Blueprint Project"
BLUEPRINT_PROJECT_ROOT = "common/projects/spindrel-blueprint"
BOUND_SECRET_NAME = "SCREENSHOT_PROJECT_GITHUB_TOKEN"


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
        state.dashboards["project_workspace_blueprint"] = "dry-run-blueprint"
        state.dashboards["project_workspace_blueprint_project"] = "dry-run-blueprint-project"
        return state

    workspaces = client.list_workspaces()
    if not workspaces:
        raise RuntimeError("project-workspace staging requires at least one workspace")
    workspace_id = str(workspaces[0]["id"])

    bot = client.ensure_bot(
        bot_id=PROJECT_BOT_ID,
        name="Project Screenshot Bot",
        model="llama3.2",
        model_provider_id="ollama",
        system_prompt=(
            "You are a screenshot fixture bot. When asked to use memory, call the "
            "host-provided memory tool exactly as requested and then answer briefly."
        ),
    )
    client.update_bot(
        str(bot["id"]),
        model="llama3.2",
        model_provider_id="ollama",
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

    existing_secret = next((s for s in client.list_secret_values() if s.get("name") == BOUND_SECRET_NAME), None)
    if existing_secret is None:
        existing_secret = client.create_secret_value(
            name=BOUND_SECRET_NAME,
            value="screenshot-token",
            description="Project Blueprint screenshot secret binding.",
        )
    blueprint = client.ensure_project_blueprint(
        name=BLUEPRINT_NAME,
        slug=BLUEPRINT_SLUG,
        default_root_path_pattern="common/projects/{slug}",
        description="Reusable screenshot recipe with files, knowledge, repo declarations, env defaults, and secret slots.",
        prompt="Use the Blueprint starter surface before making changes.",
        prompt_file_path=".spindrel/project-prompt.md",
        folders=[".spindrel", ".spindrel/knowledge-base", "docs", "src"],
        files={
            "README.md": "# Blueprint Project\n\nCreated from a Project Blueprint.\n",
            "docs/plan.md": "# Plan\n\nTrack the setup here.\n",
        },
        knowledge_files={"overview.md": "This Project was created from the screenshot Blueprint.\n"},
        repos=[{
            "name": "agent-server",
            "url": "https://github.com/example/agent-server.git",
            "path": "agent-server",
            "branch": "main",
        }],
        env={"NODE_ENV": "development", "PROJECT_KIND": "screenshot"},
        required_secrets=[BOUND_SECRET_NAME, "SCREENSHOT_PROJECT_NPM_TOKEN"],
    )
    blueprint_id = str(blueprint["id"])
    state.dashboards["project_workspace_blueprint"] = blueprint_id
    blueprint_project = client.create_project_from_blueprint(
        blueprint_id=blueprint_id,
        workspace_id=workspace_id,
        name=BLUEPRINT_PROJECT_NAME,
        slug=BLUEPRINT_PROJECT_SLUG,
        root_path=BLUEPRINT_PROJECT_ROOT,
        secret_bindings={BOUND_SECRET_NAME: str(existing_secret["id"])},
    )
    blueprint_project_id = str(blueprint_project["id"])
    state.dashboards["project_workspace_blueprint_project"] = blueprint_project_id
    client.update_project_secret_bindings(
        blueprint_project_id,
        {BOUND_SECRET_NAME: str(existing_secret["id"]), "SCREENSHOT_PROJECT_NPM_TOKEN": None},
    )

    channel = client.ensure_channel(
        client_id=PROJECT_CHANNEL_CLIENT_ID,
        bot_id=PROJECT_BOT_ID,
        name="Project workspace demo",
        category="Showcase",
    )
    channel_id = str(channel["id"])
    state.channels["project_workspace"] = channel_id

    client.ensure_channel(
        client_id=PROJECT_ATTACH_CLIENT_ID,
        bot_id=PROJECT_BOT_ID,
        name="Project workspace attach candidate",
        category="Showcase",
    )

    client.update_channel_settings(
        channel_id,
        project_id=project_id,
        chat_mode="terminal",
        tool_output_display="expanded",
    )
    client.write_workspace_file(
        workspace_id,
        f"{PROJECT_ROOT}/README.md",
        "# Screenshot Project Workspace\n\nThis file is rooted at the shared Project, not the channel workspace.\n",
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
        if ch.get("client_id") in {PROJECT_CHANNEL_CLIENT_ID, PROJECT_ATTACH_CLIENT_ID}:
            client.delete_channel(ch["id"])
