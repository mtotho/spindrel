from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.tools.local import machine_probes


def test_probe_catalog_has_small_progressive_set() -> None:
    probes = machine_probes._probe_catalog()
    ids = {probe["probe_id"] for probe in probes}

    assert {
        "network_basics",
        "dns_lookup",
        "tcp_port",
        "http_probe",
        "docker_summary",
        "compose_summary",
        "docker_logs_tail",
    } <= ids
    assert all(probe["requires_machine_lease"] is True for probe in probes)
    assert all("next_probe_ids" in probe for probe in probes)


def test_probe_argument_validation_rejects_shell_shaped_host() -> None:
    with pytest.raises(ValueError, match="host"):
        machine_probes._build_probe_command("dns_lookup", host="nas.local; rm -rf /")


def test_docker_log_probe_rejects_shell_shaped_container() -> None:
    with pytest.raises(ValueError, match="container"):
        machine_probes._build_probe_command("docker_logs_tail", container="plex && whoami")


@pytest.mark.asyncio
async def test_machine_run_probe_uses_fixed_provider_exec(monkeypatch) -> None:
    calls: list[tuple[str, str, str]] = []

    class Provider:
        async def exec_command(self, target_id: str, command: str, working_dir: str = ""):
            calls.append((target_id, command, working_dir))
            return {
                "stdout": "tcp_connect ok host=nas.local port=445 elapsed_ms=4\n",
                "stderr": "",
                "exit_code": 0,
                "duration_ms": 5,
                "truncated": False,
            }

    async def fake_policy(policy: str):
        return SimpleNamespace(
            allowed=True,
            lease={"provider_id": "ssh", "target_id": "nas"},
            reason=None,
        )

    monkeypatch.setattr(machine_probes, "validate_current_execution_policy", fake_policy)
    monkeypatch.setattr(machine_probes, "get_provider", lambda provider_id: Provider())

    payload = json.loads(await machine_probes.machine_run_probe("tcp_port", host="nas.local", port=445))

    assert payload["status"] == "ok"
    assert payload["status_color"] == "success"
    assert payload["target"] == "nas.local:445"
    assert payload["confidence"] == "high"
    assert payload["next_probe_ids"] == ["dns_lookup", "http_probe"]
    assert calls and calls[0][0] == "nas"
    assert "python3 -c" in calls[0][1]
    assert "nas.local" in calls[0][1]


@pytest.mark.asyncio
async def test_machine_run_probe_reports_missing_lease(monkeypatch) -> None:
    async def fake_policy(policy: str):
        return SimpleNamespace(allowed=False, lease=None, reason="grant a machine target")

    monkeypatch.setattr(machine_probes, "validate_current_execution_policy", fake_policy)

    payload = json.loads(await machine_probes.machine_run_probe("network_basics"))

    assert payload["status"] == "blocked"
    assert payload["status_color"] == "danger"
    assert payload["blocked_reason"] == "grant a machine target"
    assert payload["error"]["code"] == "local_control_required"
