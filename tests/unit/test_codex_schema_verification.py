from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations.codex import schema


def _write_schema(path: Path, properties: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"properties": {name: {} for name in properties}}))


def _write_client_request_schema(path: Path, methods: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"oneOf": [{"properties": {"method": {"enum": methods}}}]}))


def _write_required_client_request_schema(path: Path, *, extra: list[str] | None = None) -> None:
    methods = list(schema.REQUIRED_CLIENT_REQUEST_METHODS)
    methods.extend(extra or [])
    _write_client_request_schema(path, methods)


def test_verify_schema_against_binary_checks_required_fields(monkeypatch):
    def _fake_run(cmd, *, check, capture_output, text, timeout):
        out = Path(cmd[-1])
        _write_schema(out / "v2" / "ThreadStartParams.json", ["dynamicTools"])
        _write_schema(out / "v2" / "TurnStartParams.json", ["collaborationMode"])
        _write_schema(out / "ToolRequestUserInputResponse.json", ["answers"])
        _write_schema(out / "DynamicToolCallResponse.json", ["contentItems", "success"])
        _write_schema(out / "v2" / "ThreadTokenUsageUpdatedNotification.json", ["tokenUsage"])
        _write_required_client_request_schema(out / "ClientRequest.json")

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
        _write_required_client_request_schema(out / "ClientRequest.json")

    monkeypatch.setattr(schema.subprocess, "run", _fake_run)

    with pytest.raises(schema.CodexSchemaError, match="dynamicTools"):
        schema.verify_schema_against_binary("/bin/codex")


def test_verify_schema_against_binary_raises_on_method_drift(monkeypatch):
    def _fake_run(cmd, *, check, capture_output, text, timeout):
        out = Path(cmd[-1])
        _write_schema(out / "v2" / "ThreadStartParams.json", ["dynamicTools"])
        _write_schema(out / "v2" / "TurnStartParams.json", ["collaborationMode"])
        _write_schema(out / "ToolRequestUserInputResponse.json", ["answers"])
        _write_schema(out / "DynamicToolCallResponse.json", ["contentItems", "success"])
        _write_schema(out / "v2" / "ThreadTokenUsageUpdatedNotification.json", ["tokenUsage"])
        methods = [
            method for method in schema.REQUIRED_CLIENT_REQUEST_METHODS
            if method != schema.METHOD_APPS_LIST
        ]
        methods.append("apps/list")
        _write_client_request_schema(out / "ClientRequest.json", methods)

    monkeypatch.setattr(schema.subprocess, "run", _fake_run)

    with pytest.raises(schema.CodexSchemaError, match="app/list"):
        schema.verify_schema_against_binary("/bin/codex")


def test_verify_schema_against_binary_raises_on_untracked_method(monkeypatch):
    def _fake_run(cmd, *, check, capture_output, text, timeout):
        out = Path(cmd[-1])
        _write_schema(out / "v2" / "ThreadStartParams.json", ["dynamicTools"])
        _write_schema(out / "v2" / "TurnStartParams.json", ["collaborationMode"])
        _write_schema(out / "ToolRequestUserInputResponse.json", ["answers"])
        _write_schema(out / "DynamicToolCallResponse.json", ["contentItems", "success"])
        _write_schema(out / "v2" / "ThreadTokenUsageUpdatedNotification.json", ["tokenUsage"])
        _write_required_client_request_schema(
            out / "ClientRequest.json",
            extra=["thread/delete"],
        )

    monkeypatch.setattr(schema.subprocess, "run", _fake_run)

    with pytest.raises(schema.CodexSchemaError, match="untracked method"):
        schema.verify_schema_against_binary("/bin/codex")
