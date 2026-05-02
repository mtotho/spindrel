from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import urllib.error

import pytest

from scripts import agent_e2e_dev


def test_agent_e2e_dev_direct_invocation_finds_repo_imports_without_pythonpath():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, "scripts/agent_e2e_dev.py", "--help"],
        cwd=agent_e2e_dev.REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )

    assert proc.returncode == 0, proc.stderr
    assert "prepare-harness-parity" in proc.stdout


def test_project_run_guard_blocks_repo_dev_bootstrap(monkeypatch):
    monkeypatch.setenv("SPINDREL_PROJECT_RUN_GUARD", "1")

    with pytest.raises(SystemExit, match="Refusing to run repo-dev e2e bootstrap"):
        agent_e2e_dev._reject_project_run_bootstrap("prepare-harness-parity")


def test_project_run_guard_allows_explicit_infrastructure_override(monkeypatch):
    monkeypatch.setenv("SPINDREL_PROJECT_RUN_GUARD", "1")
    monkeypatch.setenv("SPINDREL_ALLOW_REPO_DEV_BOOTSTRAP", "1")

    agent_e2e_dev._reject_project_run_bootstrap("prepare-harness-parity")


def test_resolve_scratch_dir_isolates_non_default_port():
    path = agent_e2e_dev._resolve_scratch_dir({"E2E_PORT": "18100"})

    assert path == agent_e2e_dev.REPO_ROOT / "scratch" / "agent-e2e-18100"


def test_resolve_scratch_dir_prefers_explicit_state_dir():
    path = agent_e2e_dev._resolve_scratch_dir({
        "E2E_PORT": "18100",
        "SPINDREL_AGENT_E2E_STATE_DIR": "scratch/custom-e2e-state",
    })

    assert path == agent_e2e_dev.REPO_ROOT / "scratch" / "custom-e2e-state"


def test_write_env_redacts_nothing_but_writes_gitignored_local_env(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)

    args = argparse.Namespace(
        host="localhost",
        port="19000",
        api_key="test-key",
        base_url="",
        llm_base_url="https://example.invalid/v1",
        llm_api_key="secret-key",
        model="gpt-test",
        provider="openai-compatible",
        force=False,
        allow_production=False,
    )

    assert agent_e2e_dev.cmd_write_env(args) == 0
    body = env_path.read_text()
    assert "E2E_MODE=external" in body
    assert "E2E_PORT=19000" in body
    assert "E2E_IMAGE=spindrel:e2e" in body
    assert "E2E_LLM_API_KEY=secret-key" in body
    assert "ENCRYPTION_KEY=" in body
    assert "JWT_SECRET=" in body
    assert env_path.stat().st_mode & 0o777 == 0o600


def test_write_env_auto_leases_agent_owned_port(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "_pick_available_port", lambda preferred: 19123)

    args = argparse.Namespace(
        host="localhost",
        port="auto",
        api_key="test-key",
        base_url="",
        llm_base_url="https://example.invalid/v1",
        llm_api_key="secret-key",
        model="gpt-test",
        provider="openai-compatible",
        force=False,
        allow_production=False,
    )

    assert agent_e2e_dev.cmd_write_env(args) == 0
    body = env_path.read_text()
    assert "E2E_PORT=19123" in body
    assert "SPINDREL_E2E_URL=http://localhost:19123" in body
    assert "SPINDREL_AGENT_E2E_STATE_DIR=scratch/agent-e2e-19123" in body


def test_write_env_refuses_production_like_base_url(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", tmp_path / ".env.agent-e2e")
    args = argparse.Namespace(
        host="localhost",
        port="18000",
        api_key="test-key",
        base_url="http://127.0.0.1:8000",
        llm_base_url="",
        llm_api_key="",
        model="gpt-test",
        provider="openai-compatible",
        force=False,
        allow_production=False,
    )

    with pytest.raises(SystemExit, match="refusing production-like target"):
        agent_e2e_dev.cmd_write_env(args)


def test_merge_previous_native_api_env_preserves_alternate_dependency_ports(monkeypatch, tmp_path):
    native_env = tmp_path / "native-api.env"
    native_env.write_text(
        "\n".join(
            [
                "E2E_PORT=19001",
                "DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:19132/agentdb",
                "SEARXNG_URL=http://localhost:19133",
            ]
        )
        + "\n"
    )
    monkeypatch.setattr(agent_e2e_dev, "NATIVE_API_ENV", native_env)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.setenv("E2E_PORT", "18001")

    merged = agent_e2e_dev._merge_previous_native_api_env({"E2E_PORT": "18000"})

    assert merged["E2E_PORT"] == "18000"
    assert merged["DATABASE_URL"] == "postgresql+asyncpg://agent:agent@localhost:19132/agentdb"
    assert merged["SEARXNG_URL"] == "http://localhost:19133"


def test_write_auth_override_mounts_existing_auth_dirs(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    scratch = repo / "scratch" / "agent-e2e"
    override = scratch / "compose.auth.override.yml"
    codex_home = tmp_path / ".codex"
    claude_home = tmp_path / ".claude"
    codex_home.mkdir()
    claude_home.mkdir()
    monkeypatch.setattr(agent_e2e_dev, "REPO_ROOT", repo)
    monkeypatch.setattr(agent_e2e_dev, "SCRATCH_DIR", scratch)
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", override)

    args = argparse.Namespace(
        codex_home=str(codex_home),
        claude_home=str(claude_home),
        force=False,
    )

    assert agent_e2e_dev.cmd_write_auth_override(args) == 0
    body = override.read_text()
    assert "spindrel:" in body
    assert f"{codex_home}:/home/spindrel/.codex:rw" in body
    assert f"{claude_home}:/home/spindrel/.claude:rw" in body


def test_merged_env_does_not_add_app_container_auth_override(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    override = tmp_path / "compose.auth.override.yml"
    env_path.write_text("E2E_API_KEY=test-key\n")
    override.write_text("services: {}\n")
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", override)
    monkeypatch.delenv("E2E_COMPOSE_OVERRIDES", raising=False)

    env = agent_e2e_dev._merged_env()

    assert "E2E_COMPOSE_OVERRIDES" not in env


def test_compose_overrides_adds_auth_override_only_for_app_container(monkeypatch, tmp_path):
    override = tmp_path / "compose.auth.override.yml"
    override.write_text("services: {}\n")
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", override)

    assert agent_e2e_dev._compose_overrides({}, include_auth_override=False) == []
    assert agent_e2e_dev._compose_overrides({}, include_auth_override=True) == [override]


def test_compose_env_persists_missing_local_secrets(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "_generate_fernet_key", lambda: "stable-fernet-key")

    env = {"E2E_IMAGE": "spindrel:test"}
    compose_env = agent_e2e_dev._compose_env(
        env,
        api_url="http://localhost:19000",
        api_key="test-key",
    )

    assert compose_env["ENCRYPTION_KEY"] == "stable-fernet-key"
    assert len(compose_env["JWT_SECRET"]) == 64
    body = env_path.read_text()
    assert "ENCRYPTION_KEY=stable-fernet-key" in body
    assert "JWT_SECRET=" in body
    assert env_path.stat().st_mode & 0o777 == 0o600


def test_compose_file_has_safe_dummy_llm_default_for_dependency_commands():
    compose_body = agent_e2e_dev.COMPOSE_FILE.read_text()

    assert "E2E_LLM_BASE_URL:-http://127.0.0.1:9/v1" in compose_body
    assert "E2E_LLM_BASE_URL:?" not in compose_body


def test_write_env_subscription_mode_uses_placeholder_until_oauth(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)

    args = argparse.Namespace(
        host="localhost",
        port="18000",
        api_key="test-key",
        base_url="",
        llm_base_url="",
        llm_api_key="ignored-key",
        model="",
        provider="subscription",
        force=False,
        allow_production=False,
    )

    assert agent_e2e_dev.cmd_write_env(args) == 0
    body = env_path.read_text()
    assert f"E2E_LLM_BASE_URL={agent_e2e_dev.SUBSCRIPTION_DUMMY_BASE_URL}" in body
    assert "E2E_LLM_API_KEY=" in body
    assert f"E2E_DEFAULT_MODEL={agent_e2e_dev.SUBSCRIPTION_DEFAULT_MODEL}" in body
    assert "SPINDREL_AGENT_E2E_PROVIDER=subscription" in body
    assert "SPINDREL_PROVIDER=chatgpt-subscription" in body
    assert "subscription mode" in capsys.readouterr().out


def test_attachment_vision_e2e_defaults_to_subscription_mini_model():
    body = (agent_e2e_dev.REPO_ROOT / "tests/e2e/scenarios/test_attachment_vision_routing.py").read_text()

    assert 'VISION_MODEL = os.environ.get("E2E_VISION_MODEL", "gpt-5.4-mini")' in body
    assert 'VISION_MODEL = os.environ.get("E2E_VISION_MODEL", "gpt-5.4")' not in body


def test_doctor_redacts_api_keys(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text(
        "\n".join([
            "SPINDREL_E2E_URL=http://localhost:18000",
            "E2E_API_KEY=abcdef123456",
            "E2E_LLM_API_KEY=llmsecret123456",
        ])
    )
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "SCREENSHOT_ENV", tmp_path / "missing")
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", tmp_path / "missing-override.yml")
    monkeypatch.setattr(agent_e2e_dev, "_check_url", lambda url, key: (True, "{}"))

    args = argparse.Namespace(allow_production=False, provider_id="chatgpt-subscription")

    assert agent_e2e_dev.cmd_doctor(args) == 0
    out = capsys.readouterr().out
    assert "abcdef123456" not in out
    assert "llmsecret123456" not in out
    assert "abcd...3456" in out
    assert "llms...3456" in out


def test_doctor_reports_subscription_bootstrap_pending(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text(
        "\n".join([
            "SPINDREL_E2E_URL=http://localhost:18000",
            "E2E_API_KEY=abcdef123456",
            "SPINDREL_AGENT_E2E_PROVIDER=subscription",
            f"E2E_LLM_BASE_URL={agent_e2e_dev.SUBSCRIPTION_DUMMY_BASE_URL}",
        ])
    )
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "SCREENSHOT_ENV", tmp_path / "missing")
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", tmp_path / "missing-override.yml")
    monkeypatch.setattr(agent_e2e_dev, "_check_url", lambda url, key: (True, "{}"))

    assert agent_e2e_dev.cmd_doctor(
        argparse.Namespace(allow_production=False, provider_id="chatgpt-subscription")
    ) == 0
    out = capsys.readouterr().out
    assert "provider mode: subscription" in out
    assert "subscription bootstrap: pending" in out


def test_commands_prints_subscription_handoff_when_configured(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text("SPINDREL_AGENT_E2E_PROVIDER=subscription\n")
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", tmp_path / "missing-override.yml")

    assert agent_e2e_dev.cmd_commands(argparse.Namespace(env_file=".env.agent-e2e")) == 0
    out = capsys.readouterr().out
    assert "python scripts/agent_e2e_dev.py prepare" in out
    assert "native-api.env" in out
    assert "E2E_KEEP_RUNNING=1 pytest tests/e2e/ -k \"test_health\"" in out
    assert "E2E_COMPOSE_OVERRIDES" not in out
    assert "subscription handoff:" in out
    assert "bootstrap-subscription" in out
    assert "prepare-project-factory-smoke" in out


def test_prepare_builds_recreates_stack_and_waits_for_health(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text(
        "\n".join([
            "E2E_API_KEY=test-key",
            "E2E_LLM_BASE_URL=https://example.invalid/v1",
            "E2E_LLM_API_KEY=llm-key",
            "E2E_DEFAULT_MODEL=gpt-test",
        ])
    )
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev.shutil, "which", lambda name: "/usr/bin/docker")
    calls: list[list[str]] = []
    best_effort_calls: list[list[str]] = []

    def fake_run(cmd, *, env=None, timeout=600):
        calls.append(cmd)

    monkeypatch.setattr(agent_e2e_dev, "_run", fake_run)
    monkeypatch.setattr(agent_e2e_dev, "_compose_container_status_lines", lambda *, project=None: [])
    monkeypatch.setattr(
        agent_e2e_dev,
        "_run_best_effort",
        lambda cmd, *, env=None, timeout=120: best_effort_calls.append(cmd),
    )
    removed_services: list[tuple[str, str]] = []

    def fake_remove_service(service: str, *, project: str = agent_e2e_dev.APP_COMPOSE_PROJECT):
        removed_services.append((service, project))

    monkeypatch.setattr(agent_e2e_dev, "_remove_compose_service_containers", fake_remove_service)
    monkeypatch.setattr(agent_e2e_dev, "_check_url", lambda url, key: (True, '{"status":"ok"}'))

    assert agent_e2e_dev.cmd_prepare(
        argparse.Namespace(
            api_url="http://localhost:19000",
            api_key="",
            no_build=False,
            startup_timeout=1,
            allow_production=False,
        )
    ) == 0

    assert calls[0][:4] == ["docker", "build", "-t", "spindrel:e2e"]
    assert calls[1][-3:] == ["--remove-orphans", "postgres", "searxng"]
    assert "--wait" in calls[1]
    assert "--wait-timeout" in calls[1]
    assert best_effort_calls[0][-2:] == ["stop", "spindrel"]
    assert best_effort_calls[1][-3:] == ["rm", "-f", "spindrel"]
    assert removed_services == [("spindrel", agent_e2e_dev.APP_COMPOSE_PROJECT)]
    assert calls[2][-3:] == ["-d", "--no-deps", "spindrel"]
    assert "-p" in calls[1]
    assert agent_e2e_dev.APP_COMPOSE_PROJECT in calls[1]


def test_prepare_deps_starts_only_dependency_services(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text(
        "\n".join([
            "E2E_API_KEY=test-key",
            "E2E_POSTGRES_PORT=16432",
            "E2E_SEARXNG_PORT=19080",
        ])
    )
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev.shutil, "which", lambda name: "/usr/bin/docker")
    calls: list[list[str]] = []

    def fake_run(cmd, *, env=None, timeout=600):
        calls.append(cmd)

    monkeypatch.setattr(agent_e2e_dev, "_run", fake_run)
    monkeypatch.setattr(agent_e2e_dev, "_compose_container_status_lines", lambda *, project=None: [])

    assert agent_e2e_dev.cmd_prepare_deps(
        argparse.Namespace(
            api_url="http://localhost:19000",
            api_key="",
            allow_production=False,
        )
    ) == 0

    assert len(calls) == 1
    assert calls[0][-3:] == ["--remove-orphans", "postgres", "searxng"]
    assert "--wait" in calls[0]
    assert "--wait-timeout" in calls[0]
    assert "spindrel" not in calls[0]
    assert agent_e2e_dev.DEPENDENCY_COMPOSE_PROJECT in calls[0]
    out = capsys.readouterr().out
    assert "DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:16432/agentdb" in out
    assert "SEARXNG_URL=http://localhost:19080" in out
    assert "own unused port" in out


def test_prepare_deps_retries_marked_for_removal_containers(monkeypatch):
    calls: list[list[str]] = []
    removed: list[tuple[str, str]] = []
    sleeps: list[int] = []

    def fake_run(cmd, *, env=None, timeout=600):
        calls.append(cmd)
        if len(calls) == 1:
            raise SystemExit("Error response from daemon: container is marked for removal and cannot be started")

    monkeypatch.setattr(agent_e2e_dev, "_run", fake_run)
    monkeypatch.setattr(agent_e2e_dev, "_compose_container_status_lines", lambda *, project=None: [])
    def fake_remove_service(service: str, *, project: str = agent_e2e_dev.APP_COMPOSE_PROJECT):
        removed.append((service, project))

    monkeypatch.setattr(agent_e2e_dev, "_remove_compose_service_containers", fake_remove_service)
    monkeypatch.setattr(agent_e2e_dev.time, "sleep", sleeps.append)

    agent_e2e_dev._start_dependency_services({}, [])

    assert len(calls) == 2
    assert removed == [
        ("postgres", agent_e2e_dev.DEPENDENCY_COMPOSE_PROJECT),
        ("searxng", agent_e2e_dev.DEPENDENCY_COMPOSE_PROJECT),
    ]
    assert sleeps == [2]


def test_prepare_deps_reports_docker_daemon_removal_state(monkeypatch):
    def fake_run(cmd, *, env=None, timeout=600):
        raise SystemExit("Error response from daemon: container is marked for removal and cannot be started")

    monkeypatch.setattr(agent_e2e_dev, "_run", fake_run)
    monkeypatch.setattr(agent_e2e_dev, "_remove_compose_service_containers", lambda service, *, project=None: None)
    monkeypatch.setattr(agent_e2e_dev.time, "sleep", lambda seconds: None)
    status_calls = 0

    def fake_status(*, project=None):
        nonlocal status_calls
        status_calls += 1
        if status_calls == 1:
            return []
        return ["abc123 spindrel-local-e2e-runtime-deps-postgres-1 Dead"]

    monkeypatch.setattr(agent_e2e_dev, "_compose_container_status_lines", fake_status)

    with pytest.raises(SystemExit) as exc_info:
        agent_e2e_dev._start_dependency_services({}, [])

    message = str(exc_info.value)
    assert "stuck in Docker removal state" in message
    assert "Do not switch to a private compose project" in message
    assert agent_e2e_dev.DEPENDENCY_COMPOSE_PROJECT in message
    assert "abc123 spindrel-local-e2e-runtime-deps-postgres-1 Dead" in message


def test_prepare_deps_fails_fast_on_dead_compose_containers(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(agent_e2e_dev, "_run", lambda cmd, *, env=None, timeout=600: calls.append(cmd))
    monkeypatch.setattr(
        agent_e2e_dev,
        "_compose_container_status_lines",
        lambda *, project=None: ["abc123 spindrel-local-e2e-runtime-deps-searxng-1 Dead"],
    )

    with pytest.raises(SystemExit) as exc_info:
        agent_e2e_dev._start_dependency_services({}, [])

    message = str(exc_info.value)
    assert "has Docker containers in Dead state" in message
    assert "Restart Docker" in message
    assert "abc123 spindrel-local-e2e-runtime-deps-searxng-1 Dead" in message
    assert calls == []


def test_native_api_process_env_uses_host_dependency_urls(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "SCRATCH_DIR", tmp_path / "scratch")
    monkeypatch.setattr(agent_e2e_dev, "_generate_fernet_key", lambda: "stable-fernet-key")

    env = {
        "E2E_POSTGRES_PORT": "16432",
        "E2E_SEARXNG_PORT": "19080",
        "E2E_LLM_BASE_URL": "https://example.invalid/v1",
        "E2E_LLM_API_KEY": "llm-key",
        "E2E_DEFAULT_MODEL": "gpt-test",
    }

    native_env = agent_e2e_dev._native_api_process_env(
        env,
        api_url="http://localhost:19000",
        api_key="test-key",
    )

    assert native_env["API_KEY"] == "test-key"
    assert native_env["SPINDREL_E2E_URL"] == "http://localhost:19000"
    assert native_env["SPINDREL_UI_URL"] == "http://localhost:19000"
    assert native_env["DATABASE_URL"] == "postgresql+asyncpg://agent:agent@localhost:16432/agentdb"
    assert native_env["SEARXNG_URL"] == "http://localhost:19080"
    assert native_env["DOCKER_STACKS_ENABLED"] == "false"
    assert native_env["CONFIG_STATE_FILE"] == ""
    assert native_env["LITELLM_BASE_URL"] == "https://example.invalid/v1"
    assert native_env["LITELLM_API_KEY"] == "llm-key"
    assert native_env["DEFAULT_MODEL"] == "gpt-test"
    assert "ENCRYPTION_KEY=stable-fernet-key" in env_path.read_text()


def test_start_api_prepares_deps_and_starts_native_server(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    native_env_path = tmp_path / "native-api.env"
    env_path.write_text("E2E_API_KEY=test-key\n")
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "NATIVE_API_ENV", native_env_path)

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_e2e_dev,
        "_ensure_native_api",
        lambda *, api_url, api_key, env, startup_timeout: calls.append((api_url, api_key)) or "http://localhost:19000",
    )

    assert agent_e2e_dev.cmd_start_api(
        argparse.Namespace(
            api_url="http://localhost:19000",
            api_key="",
            build_ui=False,
            startup_timeout=1,
            allow_production=False,
        )
    ) == 0

    assert calls == [("http://localhost:19000", "test-key")]


def test_prepare_project_factory_smoke_enables_runtime_installs_gh_and_seeds_secret(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    override = tmp_path / "compose.auth.override.yml"
    env_path.write_text("E2E_API_KEY=test-key\nE2E_LLM_BASE_URL=https://example.invalid/v1\n")
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", override)
    (tmp_path / ".codex").mkdir()
    monkeypatch.setattr(agent_e2e_dev.Path, "home", lambda: tmp_path)
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method: str, url: str, *, api_key: str = "", body: dict | None = None, timeout: int = 20):
        calls.append((method, url, body))
        if url.endswith("/api/v1/admin/secret-values/") and method == "GET":
            return []
        if url.endswith("/api/v1/admin/harnesses"):
            return {"runtimes": [{"name": "codex", "ok": True, "detail": "Logged in"}]}
        return {}

    monkeypatch.setattr(agent_e2e_dev, "_prepare_stack", lambda **kwargs: calls.append(("PREPARE", kwargs["api_url"], None)))
    monkeypatch.setattr(agent_e2e_dev, "_request_json", fake_request)
    monkeypatch.setattr(agent_e2e_dev, "_host_command_output", lambda args: "ghp_test_token")

    assert agent_e2e_dev.cmd_prepare_project_factory_smoke(
        argparse.Namespace(
            api_url="http://localhost:18000",
            api_key="",
            runtime="codex",
            github_repo="mtotho/vault",
            base_branch="master",
            github_secret_name="PROJECT_FACTORY_SMOKE_GITHUB_TOKEN",
            seed_github_token_from_gh=True,
            skip_setup=False,
            no_build=True,
            startup_timeout=1,
            allow_production=False,
        )
    ) == 0

    assert override.exists()
    assert ("PUT", "http://localhost:18000/api/v1/admin/integrations/codex/status", {"status": "enabled"}) in calls
    assert (
        "POST",
        "http://localhost:18000/api/v1/admin/integrations/codex/install-system-deps",
        {"apt_package": "gh"},
    ) in calls
    assert (
        "POST",
        "http://localhost:18000/api/v1/admin/secret-values/",
        {
            "name": "PROJECT_FACTORY_SMOKE_GITHUB_TOKEN",
            "value": "ghp_test_token",
            "description": "Local e2e Project Factory smoke GitHub token seeded from host gh auth.",
        },
    ) in calls


def test_harness_parity_env_preserves_runtime_ids_when_preparing_subset(monkeypatch, tmp_path):
    harness_env = tmp_path / "harness-parity.env"
    harness_env.write_text(
        "\n".join([
            "HARNESS_PARITY_CODEX_CHANNEL_ID=existing-codex-channel",
            "HARNESS_PARITY_CODEX_BOT_ID=harness-parity-codex",
            "",
        ])
    )
    monkeypatch.setattr(agent_e2e_dev, "HARNESS_PARITY_ENV", harness_env)

    agent_e2e_dev._write_harness_parity_env(
        api_url="http://localhost:18000",
        api_key="test-key",
        channel_ids_by_runtime={"claude-code": "new-claude-channel"},
        project_id="project-1",
        project_path="common/projects",
        native_app=True,
    )

    body = harness_env.read_text()
    assert "HARNESS_PARITY_CODEX_CHANNEL_ID=existing-codex-channel" in body
    assert "HARNESS_PARITY_CLAUDE_CHANNEL_ID=new-claude-channel" in body


def test_claude_live_auth_validation_reports_exact_login_command(monkeypatch):
    monkeypatch.setattr(agent_e2e_dev.shutil, "which", lambda name: "/usr/bin/docker" if name == "docker" else None)

    class Result:
        returncode = 1
        stdout = ""
        stderr = "Invalid authentication credentials"

    monkeypatch.setattr(agent_e2e_dev.subprocess, "run", lambda *args, **kwargs: Result())

    with pytest.raises(SystemExit) as exc:
        agent_e2e_dev._validate_claude_live_auth("spindrel-local-e2e-spindrel-1")

    message = str(exc.value)
    assert "docker exec -it -u spindrel spindrel-local-e2e-spindrel-1 claude auth login" in message
    assert "Invalid authentication credentials" in message


def test_doctor_reports_connected_subscription(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text(
        "\n".join([
            "SPINDREL_E2E_URL=http://localhost:18000",
            "E2E_API_KEY=abcdef123456",
            "SPINDREL_AGENT_E2E_PROVIDER=subscription",
        ])
    )
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "SCREENSHOT_ENV", tmp_path / "missing")
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", tmp_path / "missing-override.yml")
    monkeypatch.setattr(agent_e2e_dev, "_check_url", lambda url, key: (True, "{}"))
    monkeypatch.setattr(
        agent_e2e_dev,
        "_subscription_status",
        lambda url, key, provider_id: {"connected": True, "email": "user@example.invalid"},
    )

    assert agent_e2e_dev.cmd_doctor(
        argparse.Namespace(allow_production=False, provider_id="chatgpt-subscription")
    ) == 0

    assert "subscription bootstrap: connected (user@example.invalid)" in capsys.readouterr().out


def test_wipe_db_requires_explicit_yes(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", tmp_path / ".env.agent-e2e")

    with pytest.raises(SystemExit, match="without --yes"):
        agent_e2e_dev.cmd_wipe_db(
            argparse.Namespace(
                api_url="http://localhost:18000",
                api_key="",
                yes=False,
                allow_production=False,
            )
        )


def test_wipe_db_runs_compose_down_with_volume_only_when_explicit(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text("E2E_API_KEY=test-key\n")
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(agent_e2e_dev, "_run", lambda cmd, *, env=None, timeout=600: calls.append(cmd))

    assert agent_e2e_dev.cmd_wipe_db(
        argparse.Namespace(
            api_url="http://localhost:18000",
            api_key="",
            yes=True,
            allow_production=False,
        )
    ) == 0

    assert calls[0][-3:] == ["down", "-v", "--remove-orphans"]


def test_bootstrap_subscription_prepares_stack_before_oauth(monkeypatch, tmp_path):
    calls: list[str] = []
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text("E2E_API_KEY=key\n")
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)

    monkeypatch.setattr(agent_e2e_dev, "_prepare_stack", lambda **kwargs: calls.append("prepare"))
    monkeypatch.setattr(agent_e2e_dev, "_ensure_provider", lambda api_url, api_key, provider_id: calls.append("provider"))

    def fake_request(method: str, url: str, *, api_key: str = "", body: dict | None = None, timeout: int = 20):
        if url.endswith("/start/chatgpt-subscription"):
            calls.append("start")
            return {"verification_uri": "https://example.invalid/device", "user_code": "ABCD", "interval": 1, "expires_in": 20}
        if url.endswith("/poll/chatgpt-subscription"):
            calls.append("poll")
            return {"status": "success"}
        return {}

    monkeypatch.setattr(agent_e2e_dev, "_request_json", fake_request)
    monkeypatch.setattr(agent_e2e_dev.time, "sleep", lambda _: None)

    assert agent_e2e_dev.cmd_bootstrap_subscription(
        argparse.Namespace(
            api_url="http://localhost:18000",
            api_key="key",
            provider_id="chatgpt-subscription",
            model="gpt-5.4-mini",
            bot=[],
            skip_setup=False,
            no_build=False,
            startup_timeout=1,
            allow_production=False,
        )
    ) == 0

    assert calls[:3] == ["prepare", "provider", "start"]


def test_bootstrap_subscription_sequences_provider_oauth_and_bot_patch(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method: str, url: str, *, api_key: str = "", body: dict | None = None, timeout: int = 20):
        calls.append((method, url, body))
        if url.endswith("/api/v1/admin/providers/chatgpt-subscription") and method == "GET":
            return {"id": "chatgpt-subscription"}
        if url.endswith("/start/chatgpt-subscription"):
            return {
                "verification_uri": "https://example.invalid/device",
                "user_code": "ABCD",
                "interval": 1,
                "expires_in": 20,
            }
        if url.endswith("/poll/chatgpt-subscription"):
            return {"status": "success", "email": "user@example.invalid", "plan": "Plus"}
        return {}

    monkeypatch.setattr(agent_e2e_dev, "_request_json", fake_request)
    monkeypatch.setattr(agent_e2e_dev.time, "sleep", lambda _: None)
    args = argparse.Namespace(
        api_url="http://localhost:18000",
        api_key="key",
        provider_id="chatgpt-subscription",
        model="gpt-5.4-mini",
        bot=["e2e"],
        skip_setup=True,
        no_build=False,
        startup_timeout=1,
        allow_production=False,
    )

    assert agent_e2e_dev.cmd_bootstrap_subscription(args) == 0
    assert (
        "PATCH",
        "http://localhost:18000/api/v1/admin/bots/e2e",
        {"model_provider_id": "chatgpt-subscription", "model": "gpt-5.4-mini"},
    ) in calls


def test_bootstrap_subscription_skips_oauth_when_already_connected(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method: str, url: str, *, api_key: str = "", body: dict | None = None, timeout: int = 20):
        calls.append((method, url, body))
        if url.endswith("/api/v1/admin/providers/chatgpt-subscription") and method == "GET":
            return {"id": "chatgpt-subscription"}
        if url.endswith("/status/chatgpt-subscription"):
            return {"connected": True, "email": "user@example.invalid"}
        if url.endswith("/start/chatgpt-subscription"):
            raise AssertionError("OAuth should not restart for an already-connected provider")
        return {}

    monkeypatch.setattr(agent_e2e_dev, "_request_json", fake_request)
    args = argparse.Namespace(
        api_url="http://localhost:18000",
        api_key="key",
        provider_id="chatgpt-subscription",
        model="gpt-5.4-mini",
        bot=["e2e"],
        skip_setup=True,
        no_build=False,
        startup_timeout=1,
        allow_production=False,
    )

    assert agent_e2e_dev.cmd_bootstrap_subscription(args) == 0
    assert (
        "PATCH",
        "http://localhost:18000/api/v1/admin/bots/e2e",
        {"model_provider_id": "chatgpt-subscription", "model": "gpt-5.4-mini"},
    ) in calls


def test_request_json_includes_http_error_body(monkeypatch):
    class FakeHTTPError(urllib.error.HTTPError):
        def read(self):
            return b'{"detail":"bad payload"}'

    def fake_urlopen(req, timeout):
        raise FakeHTTPError(req.full_url, 422, "Unprocessable Entity", {}, None)

    monkeypatch.setattr(agent_e2e_dev.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match='HTTP 422: {"detail":"bad payload"}'):
        agent_e2e_dev._request_json("POST", "http://localhost:18000/test")


def test_bootstrap_subscription_explains_stale_image_for_missing_provider_type(monkeypatch):
    def fake_ensure_provider(api_url, api_key, provider_id):
        raise RuntimeError(
            "POST /providers returned HTTP 422: "
            "{\"detail\":\"Invalid provider_type. Must be one of: ['openai-compatible']\"}"
        )

    monkeypatch.setattr(agent_e2e_dev, "_ensure_provider", fake_ensure_provider)
    args = argparse.Namespace(
        api_url="http://localhost:18000",
        api_key="key",
        provider_id="chatgpt-subscription",
        model="gpt-5.4-mini",
        bot=["e2e"],
        skip_setup=True,
        no_build=False,
        startup_timeout=1,
        allow_production=False,
    )

    with pytest.raises(SystemExit, match="without --skip-setup"):
        agent_e2e_dev.cmd_bootstrap_subscription(args)
