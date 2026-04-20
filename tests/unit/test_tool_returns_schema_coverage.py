"""Lint pin: every registered readonly tool must declare a returns schema,
unless explicitly excluded below.

This test prevents silent regressions where a tool gets registered without a
returns schema, which breaks `run_script` composition and `list_tool_signatures`.

Exclusion list categories:
  _TEXT_OUTPUT_TOOLS  — intentionally return raw text (file content, CLI output)
                        these are not composable by design
  _PENDING_BACKFILL   — return JSON but have un-normalized bare-string error paths;
                        tracked here so new tools don't silently join them
"""
from __future__ import annotations

import importlib
import pkgutil

import pytest

# ---------------------------------------------------------------------------
# Exclusion lists
# ---------------------------------------------------------------------------

# Intentionally text output — not composable JSON
_TEXT_OUTPUT_TOOLS: frozenset[str] = frozenset({
    "read_conversation_history",   # returns formatted history text
    "read_sub_session",            # returns session file content
    "github_get_file",             # returns raw repo file content
    "github_list_branches",        # returns plain text branch list
    "github_compare",              # returns rich diff text
    "gws",                         # raw Google Workspace CLI stdout
    "fetch_url",                   # raw webpage content
    "run_claude_code",             # Claude Code CLI output
    "load_experiment_template",    # returns raw YAML template text
})

# Pending normalization — have partial bare-string returns, tracked as debt
_PENDING_BACKFILL: frozenset[str] = frozenset({
    # Local tools needing normalization
    "prune_enrolled_skills",        # mixed JSON/bare-string returns
    "list_sub_sessions",            # bare-string returns throughout
})

_EXCLUDED: frozenset[str] = _TEXT_OUTPUT_TOOLS | _PENDING_BACKFILL


# ---------------------------------------------------------------------------
# Import all tool modules so @reg.register decorators run
# ---------------------------------------------------------------------------

def _import_all_tools() -> None:
    import app.tools.local as local_pkg
    for _, module_name, _ in pkgutil.walk_packages(
        local_pkg.__path__, prefix="app.tools.local."
    ):
        try:
            importlib.import_module(module_name)
        except Exception:
            pass

    try:
        import integrations
        for _, module_name, _ in pkgutil.walk_packages(
            integrations.__path__, prefix="integrations."
        ):
            if ".tools." in module_name:
                try:
                    importlib.import_module(module_name)
                except Exception:
                    pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def test_readonly_tools_have_returns_schema() -> None:
    """All non-excluded readonly tools must declare a returns schema."""
    _import_all_tools()

    from app.tools.registry import _tools

    missing = [
        name
        for name, spec in _tools.items()
        if spec.get("safety_tier") == "readonly"
        and not spec.get("returns")
        and name not in _EXCLUDED
    ]

    assert not missing, (
        f"The following readonly tools are missing a 'returns' schema:\n"
        + "\n".join(f"  - {name}" for name in sorted(missing))
        + "\n\nAdd returns={{...}} to their @reg.register() call, "
        "or add the tool to _PENDING_BACKFILL in this test file if normalization "
        "is deferred."
    )
