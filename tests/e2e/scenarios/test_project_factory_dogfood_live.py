"""Opt-in live dogfood proof for the conversational Project Factory path.

This is intentionally live-model gated. The deterministic Project Factory e2e
keeps CI stable; this scenario proves the exact user path where a Project-bound
harness chat turns a planning conversation into work packs, launches one, runs
real Project code, and finalizes review provenance.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from tests.e2e.harness.client import E2EClient


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.skip(
        reason=(
            "Phase 4BD.6 dropped the IssueWorkPack substrate. This live dogfood "
            "scenario will be rewritten against propose_run_packs + source_artifact "
            "in a follow-up slice (see docs/tracks/projects.md Phase 4BD)."
        )
    ),
]

ARTIFACT_PATH = Path("scratch/agent-e2e/project-factory-dogfood-live.json")


def _enabled() -> bool:
    return os.environ.get("PROJECT_FACTORY_DOGFOOD_LIVE", "").strip() == "1"


@pytest.mark.skipif(not _enabled(), reason="set PROJECT_FACTORY_DOGFOOD_LIVE=1 to run the live dogfood Project Factory flow")
async def test_live_project_factory_dogfood_plans_launches_runs_and_reviews(client: E2EClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    runtime = os.environ.get("PROJECT_FACTORY_DOGFOOD_RUNTIME", os.environ.get("PROJECT_FACTORY_RUNTIME", "codex"))
    harnesses = await client.list_harnesses()
    harness = next((item for item in harnesses if item.get("name") == runtime), None)
    assert harness and harness.get("ok"), f"{runtime} harness is not ready: {harness}"
    await client.get_runtime_capabilities(runtime)

    bot_id = f"factory-dogfood-{runtime}-{suffix}"
    await client.create_bot({
        "id": bot_id,
        "name": f"Factory Dogfood {runtime} {suffix}",
        "model": os.environ.get("PROJECT_FACTORY_MODEL", os.environ.get("E2E_DEFAULT_MODEL", "gpt-5.3-chat-latest")),
        "system_prompt": (
            "You are dogfooding Spindrel Project Factory. Follow the user's exact schema "
            "and use tools instead of only describing what you would do."
        ),
        "harness_runtime": runtime,
        "memory_scheme": "workspace-files",
        "local_tools": ["create_issue_work_packs", "publish_project_run_receipt"],
        "tool_retrieval": False,
        "tool_discovery": False,
    })

    blueprint = await client.create_project_blueprint({
        "name": f"Dogfood Factory {suffix}",
        "slug": f"dogfood-factory-{suffix}",
        "default_root_path_pattern": f"scratch/project-factory-dogfood/{suffix}",
        "files": {
            ".spindrel/factory-plan.md": (
                "# Dogfood Factory Plan\n\n"
                "- Code task: run the fixture smoke script, start the source app, verify the assigned URL, "
                "write docs/dogfood-screenshot-evidence.md, and publish a receipt.\n"
                "- Needs-info task: future visual polish ideas should stay out of launch until scoped.\n"
            ),
            "docker-compose.project.yml": """
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agent
      POSTGRES_DB: agentdb
    ports:
      - "0:5432"
""",
            "scripts/smoke.py": """
from __future__ import annotations

import os
from pathlib import Path

required = ["DATABASE_URL", "SPINDREL_DEV_APP_PORT", "SPINDREL_DEV_APP_URL"]
missing = [key for key in required if not os.environ.get(key)]
if missing:
    raise SystemExit(f"missing env: {', '.join(missing)}")
Path("dogfood-smoke.txt").write_text(
    "dogfood smoke passed\\n"
    f"dev={os.environ['SPINDREL_DEV_APP_URL']}\\n",
    encoding="utf-8",
)
print("DOGFOOD_SMOKE_OK")
""",
            "app.py": """
from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("SPINDREL_DEV_APP_PORT", "0") or "0")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            "<!doctype html><title>Dogfood Factory</title>"
            "<main><h1>Dogfood Factory</h1>"
            "<p id='status'>source server is running</p></main>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return

if __name__ == "__main__":
    if PORT <= 0:
        raise SystemExit("SPINDREL_DEV_APP_PORT is required")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
""",
        },
        "dependency_stack": {
            "source_path": "docker-compose.project.yml",
            "env": {
                "DATABASE_URL": "postgresql://agent:agent@${postgres.host}:${postgres.5432}/agentdb",
            },
            "commands": {
                "postgres-ready": "pg_isready -U agent -d agentdb",
            },
        },
        "metadata_": {
            "scenario": "project_factory_dogfood_live",
            "dev_targets": [{
                "key": "app",
                "label": "Dogfood app",
                "port_env": "SPINDREL_DEV_APP_PORT",
                "url_env": "SPINDREL_DEV_APP_URL",
                "port_range": [31390, 31440],
            }],
        },
    })
    project = await client.create_project_from_blueprint({
        "blueprint_id": blueprint["id"],
        "name": f"Dogfood Factory {suffix}",
        "slug": f"dogfood-factory-{suffix}",
    })
    channel = await client.create_channel({
        "name": f"Dogfood Factory {suffix}",
        "client_id": client.new_client_id("factory-dogfood"),
        "bot_id": bot_id,
        "project_id": project["id"],
        "private": True,
    })
    session_id = await client.create_channel_session(channel["id"])

    launch_prompt = (
        "Dogfood Project Factory coding run. Work in this Project root. Do not run Spindrel e2e bootstrap helpers. "
        "Confirm DATABASE_URL, SPINDREL_DEV_APP_PORT, and SPINDREL_DEV_APP_URL are present without printing secret values. "
        "Run `python scripts/smoke.py`. Start the app with `nohup python app.py > dogfood-server.log 2>&1 &`. "
        "Verify the assigned app URL with `python - <<'PY'\\nimport os, urllib.request\\n"
        "print(urllib.request.urlopen(os.environ['SPINDREL_DEV_APP_URL'], timeout=10).status)\\nPY`. "
        "Write `docs/dogfood-screenshot-evidence.md` describing the Dogfood Factory page marker. "
        "Finish by calling publish_project_run_receipt with status `needs_review`, changed files, command results, "
        "the assigned dev target URL/status, dependency stack env-key evidence, and screenshot/evidence path."
    )
    planning_prompt = (
        "Use @file:.spindrel/factory-plan.md and @project:dependencies as context. "
        "Create exactly two proposed work packs by calling create_issue_work_packs once. "
        "Use project_id "
        f"{project['id']} for the call. The first pack must be category code_bug, confidence high, "
        f"title 'Dogfood code pack {suffix}', and launch_prompt exactly: {launch_prompt!r}. "
        "The second pack must be category needs_info, confidence medium, "
        f"title 'Dogfood needs info pack {suffix}', and explain that future visual polish needs scope. "
        "Include a triage_receipt with summary, grouping_rationale, launch_readiness, follow_up_questions, and excluded_items. "
        "After the tool call, reply with DOGFOOD_WORK_PACKS_CREATED."
    )
    planning = await client.chat_session_stream(
        planning_prompt,
        session_id=session_id,
        channel_id=channel["id"],
        bot_id=bot_id,
        timeout=float(os.environ.get("PROJECT_FACTORY_DOGFOOD_PLAN_TIMEOUT", "600")),
    )
    assert "create_issue_work_packs" in planning.tools_used, planning.response_text

    packs = await client.list_issue_work_packs()
    code_pack = next(pack for pack in packs if pack["title"] == f"Dogfood code pack {suffix}")
    needs_info_pack = next(pack for pack in packs if pack["title"] == f"Dogfood needs info pack {suffix}")
    assert code_pack["status"] == "proposed"
    assert code_pack["category"] == "code_bug"
    assert code_pack["project_id"] == project["id"]
    assert code_pack["channel_id"] == channel["id"]
    assert "scripts/smoke.py" in code_pack["launch_prompt"]
    assert needs_info_pack["status"] == "needs_info"
    assert needs_info_pack["triage_receipt_id"].startswith("issue-triage-receipt:")
    assert needs_info_pack["source_item_ids"]

    launched = await client.batch_launch_issue_work_packs_project_runs(
        work_pack_ids=[code_pack["id"]],
        project_id=project["id"],
        channel_id=channel["id"],
        note="Dogfood live flow launches the model-created code pack.",
    )
    assert launched["count"] == 1
    run = launched["runs"][0]
    task_id = run["task"]["id"]

    finished = await client.wait_task_terminal(
        task_id,
        timeout=float(os.environ.get("PROJECT_FACTORY_DOGFOOD_RUN_TIMEOUT", "900")),
    )
    assert finished["status"] == "complete", finished

    runs = await client.list_project_coding_runs(project["id"])
    project_run = next(item for item in runs if item["task"]["id"] == task_id)
    receipt = project_run.get("receipt") or {}
    assert receipt.get("status") in {"needs_review", "complete", "completed"}
    assert any("scripts/smoke.py" in str(item) for item in (receipt.get("tests") or []))
    assert any("dogfood-screenshot-evidence" in str(item) for item in (receipt.get("screenshots") or []))
    assert (project_run.get("dependency_stack_preflight") or {}).get("status") == "running"
    assert project_run.get("dev_targets"), project_run

    review = await client.create_project_review_session(project["id"], {
        "channel_id": channel["id"],
        "task_ids": [task_id],
        "prompt": "Review the selected dogfood run. Accept without merging if receipt evidence is present.",
        "merge_method": "squash",
    })
    review_context = await client.get_project_review_context(project["id"], review["id"])
    assert review_context["ok"] is True
    assert review_context["readiness"]["ready"] is True
    assert review_context["selected_runs"][0]["receipt"]["id"] == receipt["id"]

    finalized = await client.finalize_project_review(project["id"], {
        "review_task_id": review["id"],
        "run_task_id": task_id,
        "outcome": "accepted",
        "summary": "Dogfood live review accepted the Project Factory run.",
        "details": {"scenario": "project_factory_dogfood_live"},
        "merge": False,
        "merge_method": "squash",
    })
    assert finalized["ok"] is True
    assert finalized["status"] == "reviewed"

    reviewed_packs = await client.list_issue_work_packs(status="launched")
    reviewed_code_pack = next(pack for pack in reviewed_packs if pack["id"] == code_pack["id"])
    assert reviewed_code_pack["latest_review_action"]["action"] == "reviewed"
    assert reviewed_code_pack["latest_review_action"]["review_task_id"] == review["id"]

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(
        json.dumps(
            {
                "runtime": runtime,
                "project_id": project["id"],
                "channel_id": channel["id"],
                "planning_session_id": session_id,
                "planning_tools_used": planning.tools_used,
                "code_pack_id": code_pack["id"],
                "needs_info_pack_id": needs_info_pack["id"],
                "launch_batch_id": launched["launch_batch_id"],
                "task_id": task_id,
                "review_task_id": review["id"],
                "receipt": receipt,
                "dev_targets": project_run.get("dev_targets") or [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
