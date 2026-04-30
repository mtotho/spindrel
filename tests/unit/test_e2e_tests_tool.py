from __future__ import annotations

import json
import subprocess

import pytest

from app.tools.local import e2e_tests


def test_resolve_e2e_target_prefers_explicit_base_url():
    target = e2e_tests._resolve_e2e_target({
        "SPINDREL_E2E_URL": "https://e2e.example.invalid:18443/",
        "E2E_API_KEY": "secret",
    })

    assert target.base_url == "https://e2e.example.invalid:18443"
    assert target.host == "e2e.example.invalid"
    assert target.port == 18443
    assert target.api_key == "secret"
    assert target.source == "SPINDREL_E2E_URL"
    assert target.explicit is True


@pytest.mark.asyncio
async def test_status_probes_resolved_e2e_target(monkeypatch):
    import httpx

    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True}

    class FakeClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            calls.append((url, headers))
            return FakeResponse()

    monkeypatch.setenv("E2E_HOST", "10.10.30.208")
    monkeypatch.setenv("E2E_PORT", "18000")
    monkeypatch.setenv("E2E_API_KEY", "e2e-key")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    payload = json.loads(await e2e_tests._status())

    assert payload["running"] is True
    assert payload["target_base_url"] == "http://10.10.30.208:18000"
    assert calls == [("http://10.10.30.208:18000/health", {"Authorization": "Bearer e2e-key"})]


@pytest.mark.asyncio
async def test_run_passes_resolved_target_to_pytest(monkeypatch):
    captured = {}

    def fake_run(cmd, *, capture_output, text, timeout, env, cwd):
        captured.update({"cmd": cmd, "env": env, "cwd": cwd})
        return subprocess.CompletedProcess(cmd, 0, stdout="1 passed\n", stderr="")

    monkeypatch.setenv("E2E_HOST", "e2e.local")
    monkeypatch.setenv("E2E_PORT", "18000")
    monkeypatch.setenv("E2E_API_KEY", "target-key")
    monkeypatch.setattr(subprocess, "run", fake_run)

    payload = json.loads(await e2e_tests._run("project", keep_running=True, verbose=False))

    assert payload["passed"] is True
    assert payload["target_base_url"] == "http://e2e.local:18000"
    assert captured["env"]["E2E_MODE"] == "external"
    assert captured["env"]["E2E_HOST"] == "e2e.local"
    assert captured["env"]["E2E_PORT"] == "18000"
    assert captured["env"]["E2E_API_KEY"] == "target-key"
    assert captured["env"]["E2E_KEEP_RUNNING"] == "1"
