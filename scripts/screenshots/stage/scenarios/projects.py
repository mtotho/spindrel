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
SECOND_BOUND_SECRET_NAME = "SCREENSHOT_PROJECT_NPM_TOKEN"
CODING_RUN_REQUEST = "Prepare the Project workspace screenshot receipt and handoff evidence."


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
        model="gemini-2.5-flash-lite",
        model_provider_id="gemini",
        system_prompt=(
            "You are a screenshot fixture bot. When asked to use memory, call the "
            "host-provided memory tool exactly as requested and then answer briefly."
        ),
    )
    client.update_bot(
        str(bot["id"]),
        model="gemini-2.5-flash-lite",
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

    existing_secret = next((s for s in client.list_secret_values() if s.get("name") == BOUND_SECRET_NAME), None)
    if existing_secret is None:
        existing_secret = client.create_secret_value(
            name=BOUND_SECRET_NAME,
            value="screenshot-token",
            description="Project Blueprint screenshot secret binding.",
        )
    existing_secret_two = next((s for s in client.list_secret_values() if s.get("name") == SECOND_BOUND_SECRET_NAME), None)
    if existing_secret_two is None:
        existing_secret_two = client.create_secret_value(
            name=SECOND_BOUND_SECRET_NAME,
            value="screenshot-token-two",
            description="Second Project Blueprint screenshot secret binding.",
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
            "name": "spindrel",
            "url": "https://github.com/mtotho/spindrel.git",
            "path": "spindrel",
            "branch": "development",
        }],
        setup_commands=[{
            "name": "Verify Blueprint runtime",
            "command": "printf 'Project kind: %s\\n' \"$PROJECT_KIND\"",
            "cwd": "",
            "timeout_seconds": 30,
        }],
        env={"NODE_ENV": "development", "PROJECT_KIND": "screenshot"},
        required_secrets=[BOUND_SECRET_NAME, SECOND_BOUND_SECRET_NAME],
    )
    blueprint_id = str(blueprint["id"])
    state.dashboards["project_workspace_blueprint"] = blueprint_id
    blueprint_project = client.create_project_from_blueprint(
        blueprint_id=blueprint_id,
        workspace_id=workspace_id,
        name=BLUEPRINT_PROJECT_NAME,
        slug=BLUEPRINT_PROJECT_SLUG,
        root_path=BLUEPRINT_PROJECT_ROOT,
        secret_bindings={BOUND_SECRET_NAME: str(existing_secret["id"]), SECOND_BOUND_SECRET_NAME: str(existing_secret_two["id"])},
    )
    blueprint_project_id = str(blueprint_project["id"])
    blueprint_project = client.update_project(
        blueprint_project_id,
        metadata_={
            **(blueprint_project.get("metadata_") or {}),
            "blueprint": {
                "id": blueprint_id,
                "name": blueprint["name"],
                "slug": blueprint["slug"],
            },
            "blueprint_snapshot": {
                "folders": blueprint.get("folders") or [],
                "files": blueprint.get("files") or {},
                "knowledge_files": blueprint.get("knowledge_files") or {},
                "repos": blueprint.get("repos") or [],
                "setup_commands": blueprint.get("setup_commands") or [],
                "env": blueprint.get("env") or {},
                "required_secrets": blueprint.get("required_secrets") or [],
            },
        },
    )
    state.dashboards["project_workspace_blueprint_project"] = blueprint_project_id
    client.update_project_secret_bindings(
        blueprint_project_id,
        {BOUND_SECRET_NAME: str(existing_secret["id"]), SECOND_BOUND_SECRET_NAME: str(existing_secret_two["id"])},
    )
    setup = client.get_project_setup(blueprint_project_id)
    if not any(run.get("status") == "succeeded" for run in (setup.get("runs") or [])):
        client.run_project_setup(blueprint_project_id)
    client.create_project_instance(blueprint_project_id)

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
    existing_runs = client.list_project_coding_runs(project_id)
    coding_run = next((run for run in existing_runs if run.get("request") == CODING_RUN_REQUEST), None)
    if coding_run is None:
        coding_run = client.create_project_coding_run(
            project_id,
            channel_id=channel_id,
            request=CODING_RUN_REQUEST,
        )
    task_id = (coding_run.get("task") or {}).get("id")
    client.create_project_run_receipt(
        project_id,
        {
            "idempotency_key": "screenshot:project-coding-run",
            "task_id": task_id,
            "status": "completed",
            "summary": "Screenshot Project coding run receipt",
            "bot_id": PROJECT_BOT_ID,
            "changed_files": [
                "app/services/projects.py",
                "ui/app/(app)/admin/projects/[projectId]/ProjectRunsSection.tsx",
            ],
            "tests": [
                {"command": "pytest tests/unit/test_projects_service.py", "status": "passed"},
                {"command": "cd ui && npx tsc --noEmit", "status": "passed"},
            ],
            "screenshots": [
                {"path": "docs/images/project-workspace-runs.png", "status": "captured"},
            ],
            "handoff_type": "branch",
            "handoff_url": "https://example.invalid/spindrel/project-run",
            "branch": "screenshot/project-coding-run",
            "base_branch": "development",
        },
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
