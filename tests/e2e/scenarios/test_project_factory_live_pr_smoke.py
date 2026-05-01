"""Opt-in local e2e smoke for a real Project coding-run PR handoff."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from tests.e2e.harness.client import E2EClient


pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

SECRET_NAME = "PROJECT_FACTORY_SMOKE_GITHUB_TOKEN"
ARTIFACT_PATH = Path("scratch/agent-e2e/project-factory-live-pr-smoke.json")


def _enabled() -> bool:
    return os.environ.get("PROJECT_FACTORY_LIVE_PR", "").strip() == "1"


@pytest.mark.skipif(not _enabled(), reason="set PROJECT_FACTORY_LIVE_PR=1 to open a real draft PR")
async def test_local_e2e_project_coding_run_opens_draft_pr(client: E2EClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    repo_full_name = os.environ.get("PROJECT_FACTORY_GITHUB_REPO", "mtotho/vault")
    base_branch = os.environ.get("PROJECT_FACTORY_BASE_BRANCH", "master")
    secret_name = os.environ.get("PROJECT_FACTORY_GITHUB_SECRET", SECRET_NAME)

    harnesses = await client.list_harnesses()
    codex = next((item for item in harnesses if item.get("name") == "codex"), None)
    assert codex and codex.get("ok"), f"codex harness is not ready: {codex}"
    await client.get_runtime_capabilities("codex")

    secrets = await client.list_secret_values()
    github_secret = next((item for item in secrets if item.get("name") == secret_name), None)
    assert github_secret is not None, (
        f"missing local e2e secret {secret_name!r}; run "
        "`python scripts/agent_e2e_dev.py prepare-project-factory-smoke "
        "--runtime codex --github-repo mtotho/vault --base-branch master --seed-github-token-from-gh`"
    )

    bot_id = f"factory-codex-{suffix}"
    bot = await client.create_bot({
        "id": bot_id,
        "name": f"Factory Codex {suffix}",
        "model": os.environ.get("PROJECT_FACTORY_MODEL", os.environ.get("E2E_DEFAULT_MODEL", "gpt-5.3-chat-latest")),
        "system_prompt": "You are a Project coding-run smoke agent. Follow the task exactly.",
        "harness_runtime": "codex",
        "memory_scheme": "workspace-files",
        "tool_retrieval": False,
        "tool_discovery": False,
    })
    assert bot["id"] == bot_id

    blueprint = await client.create_project_blueprint({
        "name": f"Vault PR Smoke {suffix}",
        "slug": f"vault-pr-smoke-{suffix}",
        "default_root_path_pattern": f"scratch/project-factory-live-pr/{suffix}",
        "repos": [{
            "name": "vault",
            "url": f"https://github.com/{repo_full_name}.git",
            "path": "repo",
            "branch": base_branch,
        }],
        "required_secrets": ["GITHUB_TOKEN"],
        "metadata_": {"scenario": "project_factory_live_pr_smoke"},
    })
    project = await client.create_project_from_blueprint({
        "blueprint_id": blueprint["id"],
        "name": f"Vault PR Smoke {suffix}",
        "slug": f"vault-pr-smoke-{suffix}",
        "secret_bindings": {"GITHUB_TOKEN": github_secret["id"]},
    })
    channel = await client.create_channel({
        "name": f"Vault PR Smoke {suffix}",
        "client_id": client.new_client_id("factory-pr-smoke"),
        "bot_id": bot_id,
        "project_id": project["id"],
        "private": True,
    })

    setup = await client.run_project_setup(project["id"])
    assert setup["status"] == "succeeded", setup
    assert setup["result"]["repos"][0]["status"] in {"cloned", "already_present"}

    marker_path = f"spindrel-smoke/project-factory-pr-smoke-{suffix}.md"
    request = (
        "Local e2e Project Factory PR smoke. Work only inside the repo at `repo`. "
        f"Create `{marker_path}` containing one sentence that names this marker: {suffix}. "
        "Run `git status --short` and `git diff --stat`. Commit the change with message "
        f"`Project factory PR smoke {suffix}`. Then call prepare_project_run_handoff with "
        "action `open_pr`, draft true, and a PR title beginning `Project Factory PR Smoke`. "
        "Finally call publish_project_run_receipt with status `needs_review`, the branch, "
        "base branch, changed file path, test/check commands, and the PR URL."
    )
    launched = await client.create_project_coding_run(project["id"], {
        "channel_id": channel["id"],
        "request": request,
    })
    task_id = launched["task"]["id"]
    finished = await client.wait_task_terminal(
        task_id,
        timeout=float(os.environ.get("PROJECT_FACTORY_LIVE_PR_TIMEOUT", "900")),
    )
    assert finished["status"] == "complete", finished

    runs = await client.list_project_coding_runs(project["id"])
    smoke_runs = [
        run for run in runs
        if run["task"]["id"] == task_id
    ]
    assert smoke_runs, runs
    run_with_pr = next((run for run in smoke_runs if (run.get("receipt") or {}).get("handoff_url")), None)
    assert run_with_pr is not None, smoke_runs
    receipt = run_with_pr["receipt"]
    assert receipt["handoff_url"].startswith(f"https://github.com/{repo_full_name}/pull/")
    changed_paths = {
        item.get("path") if isinstance(item, dict) else item
        for item in receipt.get("changed_files") or []
    }
    assert marker_path in changed_paths
    if receipt.get("handoff_type"):
        assert receipt["handoff_type"] in {"github_pr", "pull_request"}
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(
        json.dumps(
            {
                "project_id": project["id"],
                "channel_id": channel["id"],
                "task_id": task_id,
                "project_run_id": run_with_pr["id"],
                "repo": repo_full_name,
                "base_branch": base_branch,
                "marker_path": marker_path,
                "pr_url": receipt["handoff_url"],
                "receipt": receipt,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
