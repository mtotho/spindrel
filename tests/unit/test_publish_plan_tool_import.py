import subprocess
import sys
from pathlib import Path


def test_plan_tools_register_during_tool_dispatch_import() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = """
import app.agent.tool_dispatch
from app.tools import registry
required = {'publish_plan', 'ask_plan_questions', 'request_plan_replan'}
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
