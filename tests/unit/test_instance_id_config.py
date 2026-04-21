"""Config tests for SPINDREL_INSTANCE_ID / AGENT_NETWORK_NAME derivation.

Part of the multi-instance stack collision fix. The instance id is what
namespaces integration docker stacks (project names, network aliases) so
that prod + e2e on the same Docker daemon don't fight over globally
unique names. The default must be auto-derived — users should never have
to set this manually on first deploy.
"""
from __future__ import annotations

from app.config import _default_instance_id, _default_agent_network


class TestDefaultInstanceId:
    def test_default_from_hostname_is_slugged(self, monkeypatch):
        import socket
        monkeypatch.setattr(socket, "gethostname", lambda: "AgentServer-Agent-Server-1")
        assert _default_instance_id() == "agentserver-agent-serv"[:20]

    def test_default_falls_back_when_hostname_blank(self, monkeypatch):
        import socket
        monkeypatch.setattr(socket, "gethostname", lambda: "")
        assert _default_instance_id() == "default"

    def test_default_strips_non_alnum(self, monkeypatch):
        import socket
        monkeypatch.setattr(socket, "gethostname", lambda: "host_name.example")
        got = _default_instance_id()
        # lowercase, non-alnum → hyphen, capped at 20
        assert got == "host-name-example"
        assert len(got) <= 20


class TestDefaultAgentNetwork:
    def test_default_derives_from_compose_project_name(self, monkeypatch):
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", "agent-server")
        assert _default_agent_network() == "agent-server_default"

    def test_introspects_docker_network_when_compose_env_missing(self, monkeypatch):
        import subprocess
        monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)

        class _Completed:
            returncode = 0
            stdout = '{"my-project_default": {}, "bridge": {}}'

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Completed())
        assert _default_agent_network() == "my-project_default"

    def test_empty_when_inspect_fails(self, monkeypatch):
        import subprocess
        monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)

        def _boom(*a, **kw):
            raise FileNotFoundError("docker not installed")

        monkeypatch.setattr(subprocess, "run", _boom)
        assert _default_agent_network() == ""
