"""Orchestration tests for the canonical harness parity runner Module."""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import pytest

from scripts import agent_e2e_dev
from tests.e2e.harness import parity_presets, parity_runner


# ---------------------------------------------------------------------------
# Tier registry
# ---------------------------------------------------------------------------


def test_tier_order_is_strictly_increasing_from_core_to_replay():
    expected = [
        "core",
        "bridge",
        "terminal",
        "plan",
        "heartbeat",
        "automation",
        "writes",
        "context",
        "project",
        "memory",
        "skills",
        "replay",
    ]
    assert list(parity_runner.TIER_ORDER) == expected
    assert [parity_runner.TIER_ORDER[name] for name in expected] == list(range(12))


def test_tier_at_least_uses_canonical_rank():
    assert parity_runner.tier_at_least("terminal", "bridge")
    assert parity_runner.tier_at_least("replay", "core")
    assert not parity_runner.tier_at_least("core", "bridge")
    # unknown tier sinks to 0
    assert not parity_runner.tier_at_least("nonsense", "bridge")


# ---------------------------------------------------------------------------
# validate_tier_requirements
# ---------------------------------------------------------------------------


def test_validate_tier_requirements_flags_missing_session_route():
    missing = parity_runner.validate_tier_requirements("core", set())
    assert missing == [
        "/api/v1/channels/{channel_id}/sessions "
        "(or legacy /api/v1/channels/{channel_id}/reset)"
    ]


def test_validate_tier_requirements_accepts_legacy_reset_route():
    assert parity_runner.validate_tier_requirements(
        "core", {"/api/v1/channels/{channel_id}/reset"}
    ) == []


def test_validate_tier_requirements_requires_docker_stacks_at_terminal_tier():
    paths = {"/api/v1/channels/{channel_id}/sessions"}
    assert parity_runner.validate_tier_requirements("bridge", paths) == []
    assert parity_runner.validate_tier_requirements("terminal", paths) == [
        "/api/v1/admin/docker-stacks"
    ]


# ---------------------------------------------------------------------------
# validate_skips (JUnit)
# ---------------------------------------------------------------------------


_JUNIT_TEMPLATE = textwrap.dedent(
    """
    <?xml version="1.0" encoding="utf-8"?>
    <testsuite>
        <testcase classname="harness" name="passes"/>
        <testcase classname="harness" name="allowed_skip">
            <skipped message="{allowed}"/>
        </testcase>
        <testcase classname="harness" name="unexpected_skip">
            <skipped message="{unexpected}"/>
        </testcase>
    </testsuite>
    """
).strip()


def test_validate_skips_filters_allowed_regex(tmp_path):
    junit = tmp_path / "results.xml"
    junit.write_text(
        _JUNIT_TEMPLATE.format(
            allowed="Claude Code-specific behavior intentional",
            unexpected="Real failure path",
        )
    )

    result = parity_runner.validate_skips(junit)
    assert result == [("harness.unexpected_skip", "Real failure path")]


def test_validate_skips_returns_empty_when_no_skips(tmp_path):
    junit = tmp_path / "results.xml"
    junit.write_text(
        '<?xml version="1.0"?><testsuite>'
        '<testcase classname="h" name="x"/>'
        "</testsuite>"
    )
    assert parity_runner.validate_skips(junit) == []


# ---------------------------------------------------------------------------
# HarnessEnv strict-mode builder
# ---------------------------------------------------------------------------


def test_harness_env_fails_fast_when_e2e_port_unset():
    with pytest.raises(RuntimeError, match="E2E_PORT"):
        parity_runner.HarnessEnv.from_env({"E2E_API_KEY": "k"}, env_files=[])


def test_harness_env_resolves_from_process_env_overlay():
    env = {"E2E_PORT": "18123", "E2E_API_KEY": "secret", "E2E_HOST": "10.0.0.1"}
    he = parity_runner.HarnessEnv.from_env(env, env_files=[])
    assert he.e2e_port == 18123
    assert he.e2e_host == "10.0.0.1"
    assert he.e2e_api_key == "secret"


def test_harness_env_reads_agent_state_dir_chain(tmp_path, monkeypatch):
    state_dir = tmp_path / "agent-e2e-18123"
    state_dir.mkdir()
    (state_dir / "native-api.env").write_text("DATABASE_URL=postgres://x\n")
    (state_dir / "harness-parity.env").write_text(
        "HARNESS_PARITY_CODEX_CHANNEL_ID=codex-1\n"
        "HARNESS_PARITY_CLAUDE_CHANNEL_ID=claude-1\n"
    )
    (tmp_path / ".env.agent-e2e").write_text(
        f"E2E_PORT=18123\nE2E_API_KEY=key\nSPINDREL_AGENT_E2E_STATE_DIR={state_dir}\n"
    )

    he = parity_runner.HarnessEnv.from_env(
        environ={
            "SPINDREL_AGENT_E2E_STATE_DIR": str(state_dir),
            "E2E_PORT": "18123",
            "E2E_API_KEY": "key",
        },
        repo_root=tmp_path,
    )
    assert he.codex_channel_id == "codex-1"
    assert he.claude_channel_id == "claude-1"


def test_harness_env_to_env_round_trips_required_fields():
    he = parity_runner.HarnessEnv.from_env(
        {"E2E_PORT": "18123", "E2E_API_KEY": "k", "HARNESS_PARITY_TIER": "bridge"},
        env_files=[],
    )
    out = he.to_env()
    assert out["E2E_PORT"] == "18123"
    assert out["E2E_API_KEY"] == "k"
    assert out["HARNESS_PARITY_TIER"] == "bridge"
    assert out["HARNESS_PARITY_FAIL_ON_SKIPS"] == "false"


# ---------------------------------------------------------------------------
# Preset slice expansion
# ---------------------------------------------------------------------------


def test_smoke_preset_runs_three_core_slices():
    smoke = parity_presets.PRESETS["smoke"]
    assert len(smoke) == 3
    assert all(slice_.tier == "core" for slice_ in smoke)


def test_all_preset_is_full_suite_replay():
    assert "all" in parity_presets.FULL_SUITE_PRESETS
    slices = parity_presets.PRESETS["all"]
    assert len(slices) == 1
    assert slices[0].tier == "replay"
    assert slices[0].selector == ""


def test_screenshot_filter_forces_off_for_workspace_writes():
    assert (
        parity_presets.screenshot_filter_for_selector("safe_workspace_write_read_delete")
        == "__off__"
    )


def test_screenshot_filter_returns_empty_for_unmapped_selector():
    assert parity_presets.screenshot_filter_for_selector("custom_selector") == ""


# ---------------------------------------------------------------------------
# run_tier — pytest invocation shape
# ---------------------------------------------------------------------------


def test_run_tier_builds_pytest_command_with_selector_and_junit(tmp_path):
    junit = tmp_path / "out" / "results.xml"
    captured: list[tuple[list[str], dict[str, str]]] = []

    def fake_runner(cmd, env):
        captured.append((cmd, env))
        return 0

    rc = parity_runner.run_tier(
        "bridge",
        selector="codex and bridge_tools",
        junit_xml=junit,
        pytest_bin="/usr/bin/pytest",
        runner=fake_runner,
    )

    assert rc == 0
    cmd, env = captured[0]
    assert cmd[0] == "/usr/bin/pytest"
    assert cmd[1] == "tests/e2e/scenarios/test_harness_live_parity.py"
    assert "-q" in cmd and "-rs" in cmd
    assert "--junitxml" in cmd
    assert str(junit) in cmd
    assert "-k" in cmd and "codex and bridge_tools" in cmd
    assert env["HARNESS_PARITY_TIER"] == "bridge"
    assert env["HARNESS_PARITY_PYTEST_JUNIT_XML"] == str(junit)
    assert junit.parent.exists()


def test_run_tier_omits_junit_and_selector_when_unset():
    captured: list[list[str]] = []
    parity_runner.run_tier(
        "core",
        pytest_bin="/usr/bin/pytest",
        runner=lambda cmd, env: captured.append(cmd) or 0,
    )
    cmd = captured[0]
    assert "--junitxml" not in cmd
    assert "-k" not in cmd


def test_main_live_forwards_unknown_pytest_args(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_tier(tier, *, pytest_args=(), **kwargs):
        captured["tier"] = tier
        captured["pytest_args"] = tuple(pytest_args)
        return 0

    monkeypatch.setattr(parity_runner, "run_tier", fake_run_tier)

    rc = parity_runner.main(
        ["live", "--tier", "core", "--maxfail=1", "--collect-only"]
    )

    assert rc == 0
    assert captured == {
        "tier": "core",
        "pytest_args": ("--maxfail=1", "--collect-only"),
    }


# ---------------------------------------------------------------------------
# Migrated orchestration tests for cmd_prepare
# (formerly in tests/unit/test_agent_e2e_dev.py — moved here because the body
# now lives in parity_runner.cmd_prepare; the agent_e2e_dev shim is too thin
# to test on its own.)
# ---------------------------------------------------------------------------


def test_prepare_harness_parity_skip_setup_starts_native_api_before_admin_calls(
    monkeypatch, tmp_path
):
    native_env = tmp_path / "native-api.env"
    native_env.write_text(
        "DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:19132/agentdb\n"
        "SEARXNG_URL=http://localhost:19133\n"
    )
    monkeypatch.setattr(agent_e2e_dev, "NATIVE_API_ENV", native_env)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SEARXNG_URL", raising=False)
    calls: list[str] = []

    def fake_start(api_url, api_key, env, *, startup_timeout):
        calls.append(f"start:{env['DATABASE_URL']}")
        return api_url

    def fake_set_enabled(api_url, api_key, integration_id):
        calls.append(f"enable:{integration_id}")

    monkeypatch.setattr(agent_e2e_dev, "_start_native_api", fake_start)
    monkeypatch.setattr(agent_e2e_dev, "_set_integration_enabled", fake_set_enabled)
    monkeypatch.setattr(
        agent_e2e_dev, "_install_integration_dependencies", lambda *a, **k: None
    )
    monkeypatch.setattr(
        agent_e2e_dev,
        "_restart_native_api",
        lambda api_url, api_key, env, *, timeout: api_url,
    )
    monkeypatch.setattr(
        agent_e2e_dev, "_ensure_project", lambda *a, **k: {"id": "project-id"}
    )
    monkeypatch.setattr(
        agent_e2e_dev, "_wait_for_harness_runtime", lambda *a, **k: {"ok": True}
    )
    monkeypatch.setattr(
        agent_e2e_dev, "_ensure_browser_automation_stack", lambda *a, **k: None
    )
    monkeypatch.setattr(agent_e2e_dev, "_validate_claude_live_auth_native", lambda: None)
    monkeypatch.setattr(agent_e2e_dev, "_ensure_harness_parity_bot", lambda *a, **k: None)
    monkeypatch.setattr(
        agent_e2e_dev, "_ensure_harness_parity_channel", lambda *a, **k: "channel-id"
    )
    monkeypatch.setattr(agent_e2e_dev, "_write_harness_parity_env", lambda *a, **k: None)

    args = argparse.Namespace(
        api_url="http://localhost:18000",
        api_key="key",
        runtime=["codex"],
        project_path="common/projects/harness-parity",
        skip_setup=True,
        no_build=False,
        skip_ui_build=False,
        docker_app=False,
        skip_live_auth_check=True,
        startup_timeout=1,
        runtime_timeout=1,
        allow_production=False,
    )

    assert parity_runner.cmd_prepare(args) == 0
    assert calls[:2] == [
        "start:postgresql+asyncpg://agent:agent@localhost:19132/agentdb",
        "enable:codex",
    ]


def test_prepare_harness_parity_sets_up_local_runtimes_channels_and_env(
    monkeypatch, tmp_path
):
    env_path = tmp_path / ".env.agent-e2e"
    override = tmp_path / "compose.auth.override.yml"
    harness_env = tmp_path / "harness-parity.env"
    env_path.write_text(
        "E2E_API_KEY=test-key\nE2E_LLM_BASE_URL=https://example.invalid/v1\n"
    )
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", override)
    monkeypatch.setattr(agent_e2e_dev, "HARNESS_PARITY_ENV", harness_env)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".claude").mkdir()
    monkeypatch.setattr(agent_e2e_dev.Path, "home", lambda: tmp_path)
    calls: list[tuple[str, str, dict | None]] = []
    channel_counter = 0

    def fake_request(method, url, *, api_key="", body=None, timeout=20):
        nonlocal channel_counter
        calls.append((method, url, body))
        if url.endswith("/api/v1/admin/harnesses"):
            return {
                "runtimes": [
                    {"name": "codex", "ok": True, "detail": "Logged in"},
                    {"name": "claude-code", "ok": True, "detail": "Logged in"},
                ]
            }
        if url.endswith("/api/v1/projects") and method == "GET":
            return []
        if url.endswith("/api/v1/projects") and method == "POST":
            return {
                "id": "project-1",
                "slug": "harness-parity-project",
                "root_path": body["root_path"],
            }
        if "/api/v1/admin/bots/" in url and method == "GET":
            raise RuntimeError(f"{method} {url} returned HTTP 404: missing")
        if url.endswith("/api/v1/channels") and method == "POST":
            channel_counter += 1
            return {"id": f"channel-{channel_counter}"}
        return {}

    monkeypatch.setattr(agent_e2e_dev, "_ensure_native_api", lambda **k: k["api_url"])
    monkeypatch.setattr(
        agent_e2e_dev,
        "_restart_native_api",
        lambda api_url, api_key, env, timeout: calls.append(("RESTART", api_url, None)),
    )
    monkeypatch.setattr(agent_e2e_dev, "_request_json", fake_request)
    monkeypatch.setattr(
        agent_e2e_dev, "_ensure_browser_automation_stack", lambda *a, **k: None
    )

    assert parity_runner.cmd_prepare(
        argparse.Namespace(
            api_url="http://localhost:18000",
            api_key="",
            runtime=None,
            project_path="common/projects",
            skip_setup=False,
            skip_live_auth_check=True,
            no_build=True,
            skip_ui_build=True,
            docker_app=False,
            startup_timeout=1,
            runtime_timeout=1,
            allow_production=False,
        )
    ) == 0

    assert not override.exists()
    assert ("RESTART", "http://localhost:18000", None) in calls
    assert (
        "PUT",
        "http://localhost:18000/api/v1/admin/integrations/codex/status",
        {"status": "enabled"},
    ) in calls
    assert (
        "PUT",
        "http://localhost:18000/api/v1/admin/integrations/claude_code/status",
        {"status": "enabled"},
    ) in calls
    bot_creates = [
        body for method, url, body in calls
        if method == "POST" and url.endswith("/api/v1/admin/bots")
    ]
    assert {body["id"] for body in bot_creates if body} == {
        "harness-parity-codex",
        "harness-parity-claude",
    }
    body = harness_env.read_text()
    assert "HARNESS_PARITY_LOCAL=1" in body
    assert "HARNESS_PARITY_NATIVE_APP=1" in body
    assert "HARNESS_PARITY_PROJECT_ID=project-1" in body
    assert "HARNESS_PARITY_CODEX_CHANNEL_ID=channel-1" in body
    assert "HARNESS_PARITY_CLAUDE_CHANNEL_ID=channel-2" in body
