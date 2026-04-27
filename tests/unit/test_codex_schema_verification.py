from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations.codex import schema


def _write_schema(path: Path, properties: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"properties": {name: {} for name in properties}}))


def test_verify_schema_against_binary_checks_required_fields(monkeypatch):
    def _fake_run(cmd, *, check, capture_output, text, timeout):
        out = Path(cmd[-1])
        _write_schema(out / "v2" / "ThreadStartParams.json", ["dynamicTools"])
        _write_schema(out / "v2" / "TurnStartParams.json", ["collaborationMode"])
        _write_schema(out / "ToolRequestUserInputResponse.json", ["answers"])
        _write_schema(out / "DynamicToolCallResponse.json", ["contentItems", "success"])
        _write_schema(out / "v2" / "ThreadTokenUsageUpdatedNotification.json", ["tokenUsage"])

    monkeypatch.setattr(schema.subprocess, "run", _fake_run)

    schema.verify_schema_against_binary("/bin/codex")


def test_verify_schema_against_binary_raises_on_drift(monkeypatch):
    def _fake_run(cmd, *, check, capture_output, text, timeout):
        out = Path(cmd[-1])
        _write_schema(out / "v2" / "ThreadStartParams.json", [])
        _write_schema(out / "v2" / "TurnStartParams.json", ["collaborationMode"])
        _write_schema(out / "ToolRequestUserInputResponse.json", ["answers"])
        _write_schema(out / "DynamicToolCallResponse.json", ["contentItems", "success"])
        _write_schema(out / "v2" / "ThreadTokenUsageUpdatedNotification.json", ["tokenUsage"])

    monkeypatch.setattr(schema.subprocess, "run", _fake_run)

    with pytest.raises(schema.CodexSchemaError, match="dynamicTools"):
        schema.verify_schema_against_binary("/bin/codex")
