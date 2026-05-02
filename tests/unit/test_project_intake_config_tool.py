"""Phase 4BD.2 - tool wrapper for update_project_intake_config.

Tool is intentionally thin: it validates the kind, persists three columns,
and returns the resolved intake_config. The validation contract is what
matters for unit coverage; the persistence path needs a real DB session
and is covered by the DB-backed projects/factory-state tests.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.tools.local.project_intake_config import update_project_intake_config_tool


@pytest.mark.asyncio
async def test_update_project_intake_config_rejects_unknown_kind():
    """Bad kind short-circuits before any DB work and returns ok=False."""
    raw = await update_project_intake_config_tool(
        kind="github_issues",
        target="https://example.com",
        project_id=str(uuid.uuid4()),
    )
    payload = json.loads(raw)
    assert payload["ok"] is False
    assert "intake_kind must be one of" in payload["error"]


@pytest.mark.asyncio
async def test_update_project_intake_config_rejects_non_string_kind():
    """Numeric kinds are rejected at the validation step, not at the DB layer."""
    raw = await update_project_intake_config_tool(
        kind=42,  # type: ignore[arg-type]
        project_id=str(uuid.uuid4()),
    )
    payload = json.loads(raw)
    assert payload["ok"] is False
    assert payload["error"]


def test_update_project_intake_config_tool_schema_matches_enum():
    """Tool's JSON Schema enum stays in sync with PROJECT_INTAKE_KINDS."""
    # Importing the package walks the auto-loader and registers every local tool.
    import app.tools.local  # noqa: F401
    from app.services.projects import PROJECT_INTAKE_KINDS
    from app.tools.registry import _tools

    entry = _tools.get("update_project_intake_config")
    assert entry is not None, "update_project_intake_config tool must be registered"
    enum_values = entry["schema"]["function"]["parameters"]["properties"]["kind"]["enum"]
    assert set(enum_values) == set(PROJECT_INTAKE_KINDS), (
        "Tool schema enum must match PROJECT_INTAKE_KINDS; update both sides if changing."
    )


def test_setup_init_skill_documents_intake_prompt_step():
    """Phase 4BD.2 - setup/init must walk the user through the intake prompt."""
    from pathlib import Path

    skill_path = Path(__file__).resolve().parents[2] / "skills/project/setup/init.md"
    text = skill_path.read_text()
    assert "update_project_intake_config" in text, (
        "project/setup/init must reference the new tool so agents persist the convention."
    )
    assert "intake_config" in text or "intake_kind" in text, (
        "project/setup/init must instruct the agent to read intake_config from factory-state."
    )
    assert "reconfigure intake" in text.lower(), (
        "project/setup/init must explain when to re-prompt (only on explicit reconfigure request)."
    )
