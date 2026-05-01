"""Opt-in live Project Factory feedback-loop proof.

This proves the generic Project contract rather than Spindrel's own e2e suite:
a real harness agent receives injected dependency/dev-target env, runs the
fixture Project's own scripts, starts a native dev server, records screenshot
evidence, and publishes a Project run receipt.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from tests.e2e.harness.client import E2EClient


pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

ARTIFACT_PATH = Path("scratch/agent-e2e/project-factory-generic-live-loop.json")


def _enabled() -> bool:
    return os.environ.get("PROJECT_FACTORY_GENERIC_LOOP", "").strip() == "1"


@pytest.mark.skipif(not _enabled(), reason="set PROJECT_FACTORY_GENERIC_LOOP=1 to run a live harness Project Factory loop")
async def test_live_project_factory_agent_runs_project_tests_server_and_receipt(client: E2EClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    runtime = os.environ.get("PROJECT_FACTORY_RUNTIME", "codex")
    harnesses = await client.list_harnesses()
    harness = next((item for item in harnesses if item.get("name") == runtime), None)
    assert harness and harness.get("ok"), f"{runtime} harness is not ready: {harness}"
    await client.get_runtime_capabilities(runtime)

    bot_id = f"factory-loop-{runtime}-{suffix}"
    await client.create_bot({
        "id": bot_id,
        "name": f"Factory Loop {runtime} {suffix}",
        "model": os.environ.get("PROJECT_FACTORY_MODEL", "gpt-5.4-mini"),
        "system_prompt": "You are validating a generic Project Factory run. Follow the task exactly.",
        "harness_runtime": runtime,
        "memory_scheme": "workspace-files",
        "tool_retrieval": False,
        "tool_discovery": False,
    })

    blueprint = await client.create_project_blueprint({
        "name": f"Generic Factory Loop {suffix}",
        "slug": f"generic-factory-loop-{suffix}",
        "default_root_path_pattern": f"scratch/project-factory-generic-loop/{suffix}",
        "files": {
            "README.md": "# Generic Factory Loop\n",
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
Path("factory-loop-smoke.txt").write_text(
    "generic factory loop smoke passed\\n"
    f"dev={os.environ['SPINDREL_DEV_APP_URL']}\\n",
    encoding="utf-8",
)
print("SMOKE_OK")
""",
            "app.py": """
from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("SPINDREL_DEV_APP_PORT", "0") or "0")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            "<!doctype html><title>Generic Factory Loop</title>"
            "<main><h1>Generic Factory Loop</h1>"
            "<p id='status'>server is running</p></main>"
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
            "scenario": "project_factory_generic_live_loop",
            "dev_targets": [{
                "key": "app",
                "label": "Fixture app",
                "port_env": "SPINDREL_DEV_APP_PORT",
                "url_env": "SPINDREL_DEV_APP_URL",
                "port_range": [31320, 31380],
            }],
        },
    })
    project = await client.create_project_from_blueprint({
        "blueprint_id": blueprint["id"],
        "name": f"Generic Factory Loop {suffix}",
        "slug": f"generic-factory-loop-{suffix}",
    })
    channel = await client.create_channel({
        "name": f"Generic Factory Loop {suffix}",
        "client_id": client.new_client_id("factory-loop"),
        "bot_id": bot_id,
        "project_id": project["id"],
        "private": True,
    })

    request = (
        "Generic Project Factory live loop. Work in this Project root. "
        "Do not run Spindrel e2e bootstrap helpers such as scripts/agent_e2e_dev.py prepare, start-api, or prepare-harness-parity; the host test server is already running. "
        "First confirm DATABASE_URL, SPINDREL_DEV_APP_PORT, and SPINDREL_DEV_APP_URL are present without printing secret values. "
        "Run `python scripts/smoke.py`. Start the app with "
        "`nohup python app.py > factory-loop-server.log 2>&1 &`. Then verify the assigned app URL with "
        "`python - <<'PY'\\nimport os, urllib.request\\nprint(urllib.request.urlopen(os.environ['SPINDREL_DEV_APP_URL'], timeout=10).status)\\nPY`. "
        "Create a screenshot/evidence file at `docs/factory-loop-screenshot-evidence.md` describing the app page marker. "
        "Finally call publish_project_run_receipt with status `needs_review`, changed files, command results, the assigned dev target URL/status, dependency stack env-key evidence, and screenshot/evidence path."
    )
    launched = await client.create_project_coding_run(project["id"], {
        "channel_id": channel["id"],
        "request": request,
    })
    template_task_id = launched["task"]["id"]
    concrete = await client.run_task_now(template_task_id)
    concrete_task_id = concrete["id"]
    finished = await client.wait_task_terminal(
        concrete_task_id,
        timeout=float(os.environ.get("PROJECT_FACTORY_GENERIC_LOOP_TIMEOUT", "900")),
    )
    assert finished["status"] == "complete", finished

    runs = await client.list_project_coding_runs(project["id"])
    run = next((
        item for item in runs
        if item["task"]["id"] in {template_task_id, concrete_task_id}
        or item.get("task", {}).get("parent_task_id") == template_task_id
    ), None)
    assert run is not None, runs
    receipt = run.get("receipt") or {}
    assert receipt.get("status") in {"needs_review", "complete", "completed"}
    test_commands = {item.get("command") for item in receipt.get("tests") or [] if isinstance(item, dict)}
    assert any(command and "scripts/smoke.py" in command for command in test_commands)
    screenshots = receipt.get("screenshots") or []
    assert any("factory-loop-screenshot-evidence" in str(item) for item in screenshots)
    assert (run.get("dependency_stack_preflight") or {}).get("status") == "running"
    assert run.get("dev_targets"), run

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(
        json.dumps(
            {
                "project_id": project["id"],
                "channel_id": channel["id"],
                "template_task_id": template_task_id,
                "task_id": concrete_task_id,
                "project_run_id": run["id"],
                "receipt": receipt,
                "dev_targets": run.get("dev_targets") or [],
                "dependency_stack": run.get("dependency_stack") or {},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
