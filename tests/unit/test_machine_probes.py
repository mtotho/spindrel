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
        "docker_app_map",
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


def test_docker_app_map_uses_bounded_docker_formatters() -> None:
    target, command = machine_probes._build_probe_command("docker_app_map")

    assert target == "docker"
    assert "docker ps --format" in command
    assert "docker network ls --format" in command
    assert "docker compose ls --format" in command
    assert "docker inspect" not in command
    assert "Mounts" not in command
    assert "Env" not in command
    assert "{{.Labels}}" not in command


def test_parse_docker_app_map_extracts_safe_runtime_summary() -> None:
    stdout = "\n".join([
        "## app_map_containers",
        (
            "plex\tlscr.io/linuxserver/plex:latest\tUp 2 hours\t"
            "0.0.0.0:32400->32400/tcp, [::]:32400->32400/tcp\t"
            "media\tmedia\tplex"
        ),
        "redis\tredis:7\tUp 5 minutes\t6379/tcp\tbackend\t\t",
        "## app_map_networks",
        "media\tbridge\tlocal",
        "backend\tbridge\tlocal",
        "## app_map_compose",
        "media\trunning(1)",
    ])

    app_map = machine_probes._parse_docker_app_map(stdout)

    assert app_map["summary"] == {
        "containers": 2,
        "published_ports": 2,
        "networks": 2,
        "compose_projects": 1,
    }
    assert app_map["containers"][0] == {
        "name": "plex",
        "image": "lscr.io/linuxserver/plex:latest",
        "status": "Up 2 hours",
        "ports": "0.0.0.0:32400->32400/tcp, [::]:32400->32400/tcp",
        "networks": ["media"],
        "compose_project": "media",
        "compose_service": "plex",
    }
    assert app_map["published_ports"][0]["suggested_probe"] == {
        "probe_id": "tcp_port",
        "host": "127.0.0.1",
        "port": 32400,
    }
    assert app_map["published_ports"][1]["host_ip"] == "::"
    assert app_map["networks"][0] == {"name": "media", "driver": "bridge", "scope": "local"}
    assert app_map["compose_projects"] == [{"name": "media", "status": "running(1)"}]


def test_parse_docker_app_map_handles_empty_runtime() -> None:
    stdout = "\n".join([
        "## app_map_containers",
        "## app_map_networks",
        "bridge\tbridge\tlocal",
        "## app_map_compose",
    ])

    app_map = machine_probes._parse_docker_app_map(stdout)

    assert app_map["summary"] == {
        "containers": 0,
        "published_ports": 0,
        "networks": 1,
        "compose_projects": 0,
    }
    assert app_map["containers"] == []
    assert app_map["published_ports"] == []


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


@pytest.mark.asyncio
async def test_machine_run_probe_returns_structured_docker_app_map(monkeypatch) -> None:
    class Provider:
        async def exec_command(self, target_id: str, command: str, working_dir: str = ""):
            return {
                "stdout": "\n".join([
                    "## app_map_containers",
                    "plex\tplex:latest\tUp 1 hour\t0.0.0.0:32400->32400/tcp\tmedia\tmedia\tplex",
                    "## app_map_networks",
                    "media\tbridge\tlocal",
                    "## app_map_compose",
                    "media\trunning(1)",
                ]),
                "stderr": "",
                "exit_code": 0,
                "duration_ms": 7,
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

    payload = json.loads(await machine_probes.machine_run_probe("docker_app_map"))

    assert payload["status"] == "ok"
    assert payload["target"] == "docker"
    assert payload["app_map"]["summary"]["containers"] == 1
    assert payload["app_map"]["summary"]["published_ports"] == 1
    assert payload["app_map"]["published_ports"][0]["host_port"] == "32400"
    assert payload["evidence"][0].startswith("Docker app map: 1 containers")
