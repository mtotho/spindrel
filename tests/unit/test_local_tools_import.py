"""Every file in app/tools/local/ must import without error.

A top-level import of a module that itself imports the registry — most often
``from app.agent.tool_dispatch import ToolResultEnvelope`` — silently kills a
whole tool family at startup because ``_import_tool_file`` swallows the
ImportError. The loader logs and continues, so the only visible symptom is
"Tool 'foo' not found" several layers downstream. This test reproduces the
loader contract and fails loudly instead.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.tools.loader import _import_tool_file


_LOCAL_DIR = Path(__file__).resolve().parents[2] / "app" / "tools" / "local"


def test_every_local_tool_file_imports_cleanly(caplog):
    """Walk app/tools/local/*.py and assert no ImportError on load.

    Mirrors what ``app/tools/local/__init__.py`` does at startup.
    """
    files = sorted(p for p in _LOCAL_DIR.glob("*.py") if not p.name.startswith("_"))
    assert files, f"no tool files found under {_LOCAL_DIR}"

    with caplog.at_level(logging.ERROR, logger="app.tools.loader"):
        for py_file in files:
            _import_tool_file(py_file)

    failures = [
        rec for rec in caplog.records
        if rec.levelno >= logging.ERROR
        and "Failed to import tool file" in rec.getMessage()
    ]
    assert not failures, "tool file(s) failed to import: " + "; ".join(
        f"{rec.getMessage()} :: {rec.exc_info[1]!r}" if rec.exc_info else rec.getMessage()
        for rec in failures
    )


def test_machine_control_tools_register():
    """Regression: machine_control.py once had a top-level ToolResultEnvelope
    import that triggered a circular import, leaving all three tools
    unregistered at startup."""
    _import_tool_file(_LOCAL_DIR / "machine_control.py")
    from app.tools.registry import _tools
    for name in ("machine_status", "machine_inspect_command", "machine_exec_command"):
        assert name in _tools, f"{name} not registered after loading machine_control.py"
