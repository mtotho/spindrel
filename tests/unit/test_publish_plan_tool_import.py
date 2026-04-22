import subprocess
import sys
from pathlib import Path


def test_publish_plan_registers_during_tool_dispatch_import() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = """
import app.agent.tool_dispatch
from app.tools import registry
raise SystemExit(0 if 'publish_plan' in registry._tools else 1)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
