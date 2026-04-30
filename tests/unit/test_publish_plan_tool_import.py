import json
import subprocess
import sys
from pathlib import Path


from app.tools.local.publish_plan import _tool_error_result


def test_plan_tools_register_during_tool_dispatch_import() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = """
import app.agent.tool_dispatch
from app.tools import registry
required = {'publish_plan', 'ask_plan_questions', 'request_plan_replan', 'record_plan_progress'}
raise SystemExit(0 if required.issubset(registry._tools) else 1)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_publish_plan_tool_errors_are_actionable() -> None:
    payload = json.loads(
        _tool_error_result(
            "Step '2' needs a concrete, outcome-oriented action label.",
            error_code="publish_plan_validation_failed",
            error_kind="validation",
            fallback="Revise the rejected fields, then call publish_plan again.",
        )
    )

    assert payload["success"] is False
    assert payload["error_kind"] == "validation"
    assert payload["retryable"] is False
    assert payload["fallback"].startswith("Revise the rejected fields")
