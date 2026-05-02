"""Coverage for RuntimeCapabilities + the harness slash-policy intersection."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.agent_harnesses.base import (
    HarnessModelOption,
    HarnessSlashCommandPolicy,
    RuntimeCapabilities,
)
from app.services.agent_harnesses.capabilities import resolve_runtime_model_surface
from app.services.slash_commands import COMMANDS, _filter_specs_for_runtime


class _FakeRuntime:
    def __init__(self, allowed: frozenset[str]):
        self._caps = RuntimeCapabilities(
            display_name="Fake",
            slash_policy=HarnessSlashCommandPolicy(allowed_command_ids=allowed),
        )

    def capabilities(self) -> RuntimeCapabilities:
        return self._caps


def test_filter_passes_through_for_non_harness():
    specs = list(COMMANDS.values())
    out = _filter_specs_for_runtime(specs, runtime=None)
    assert [s.id for s in out] == [s.id for s in specs]


def test_filter_intersects_with_runtime_allowlist():
    specs = list(COMMANDS.values())
    runtime = _FakeRuntime(allowed=frozenset({"help", "stop", "clear"}))
    out = _filter_specs_for_runtime(specs, runtime=runtime)
    out_ids = {s.id for s in out}
    assert out_ids == {"help", "stop", "clear"}


def test_filter_preserves_registry_order():
    specs = list(COMMANDS.values())
    runtime = _FakeRuntime(allowed=frozenset({s.id for s in specs[:3]}))
    out = _filter_specs_for_runtime(specs, runtime=runtime)
    assert [s.id for s in out] == [s.id for s in specs[:3]]


def test_claude_capabilities_shape():
    """Pin the harness contract: runtime-owned models, effort, and slash policy."""
    pytest.importorskip("claude_agent_sdk")
    from integrations.claude_code.harness import ClaudeCodeRuntime

    caps = ClaudeCodeRuntime().capabilities()
    assert caps.display_name == "Claude Code"
    assert caps.model_is_freeform is True
    assert caps.supported_models
    assert caps.model_options
    assert caps.effort_values == ("low", "medium", "high", "xhigh", "max")
    assert caps.approval_modes == (
        "bypassPermissions", "acceptEdits", "default", "plan",
    )

    allowed = caps.slash_policy.allowed_command_ids
    # Must allow safe generics + /model (typed slash is a parallel write
    # path alongside the canonical header model pill):
    for cmd in (
        "help", "rename", "stop", "clear", "sessions", "scratch",
        "split", "focus", "model", "effort", "compact", "context",
        "project-init", "plan", "runtime",
    ):
        assert cmd in allowed, f"{cmd} should be in Claude allowlist"
    assert {cmd.id for cmd in caps.native_commands} >= {"auth", "version"}
    assert {cmd.id for cmd in caps.native_commands} >= {
        "skills", "plugins", "mcp", "agents", "hooks", "status", "doctor",
    }
    # Must NOT allow Spindrel-loop / runtime-conflicting commands:
    for cmd in ("find", "skills"):
        assert cmd not in allowed, f"{cmd} must NOT be in Claude allowlist"


def test_codex_capabilities_shape():
    """Pin the Codex runtime's static control surface."""
    from integrations.codex.harness import CodexRuntime

    caps = CodexRuntime().capabilities()
    assert caps.display_name == "Codex"
    assert caps.model_is_freeform is True
    # Fallbacks keep the UI useful when the binary/model-list probe is not
    # available; the capabilities endpoint replaces model_options with live
    # Codex model/list metadata when possible.
    assert caps.supported_models == ("gpt-5.5", "gpt-5.4", "gpt-5.4-mini")
    assert [opt.id for opt in caps.model_options] == ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]
    assert caps.effort_values == ("minimal", "low", "medium", "high", "xhigh")
    assert caps.approval_modes == (
        "bypassPermissions", "acceptEdits", "default", "plan",
    )
    assert "plan" in caps.slash_policy.allowed_command_ids
    assert "project-init" in caps.slash_policy.allowed_command_ids
    assert "runtime" in caps.slash_policy.allowed_command_ids
    assert {cmd.id for cmd in caps.native_commands} >= {
        "config", "mcp-status", "plugins", "skills", "features", "marketplace",
        "status", "diff", "undo", "branch", "resume", "review", "cloud",
        "agents", "hooks", "apps", "fs", "prompts", "approvals", "editor", "init",
    }
    aliases = {alias for cmd in caps.native_commands for alias in cmd.aliases}
    assert {"mcp", "plugin", "feature", "marketplaces", "agent", "app"} <= aliases
    by_id = {cmd.id: cmd for cmd in caps.native_commands}
    assert by_id["plugins"].mutability == "argument_sensitive"
    assert by_id["plugins"].readonly is False
    assert by_id["mcp-status"].mutability == "readonly"
    assert by_id["hooks"].mutability == "readonly"
    assert by_id["apps"].mutability == "readonly"
    assert by_id["fs"].mutability == "readonly"
    assert by_id["diff"].interaction_kind == "structured"
    assert by_id["review"].fallback_behavior == "terminal"
    assert by_id["undo"].mutability == "mutating"
    assert caps.native_compaction is True


@pytest.mark.asyncio
async def test_runtime_model_surface_uses_live_effort_projection():
    class Runtime:
        def capabilities(self):
            return RuntimeCapabilities(
                display_name="Live",
                supported_models=("fallback",),
                model_options=(
                    HarnessModelOption(
                        id="fallback",
                        effort_values=("minimal", "low", "medium"),
                    ),
                ),
                effort_values=("minimal", "low", "medium"),
            )

        async def list_model_options(self):
            return (
                HarnessModelOption(
                    id="live-a",
                    effort_values=("low", "medium"),
                    default_effort="medium",
                ),
                HarnessModelOption(
                    id="live-b",
                    effort_values=("high", "xhigh"),
                    default_effort="high",
                ),
            )

    surface = await resolve_runtime_model_surface(Runtime())

    assert [option.id for option in surface.model_options] == ["live-a", "live-b"]
    assert surface.available_models == ("live-a", "live-b")
    assert surface.effort_values == ("low", "medium", "high", "xhigh")


def test_claude_and_codex_have_distinct_display_names():
    pytest.importorskip("claude_agent_sdk")
    from integrations.claude_code.harness import ClaudeCodeRuntime
    from integrations.codex.harness import CodexRuntime

    assert ClaudeCodeRuntime().capabilities().display_name == "Claude Code"
    assert CodexRuntime().capabilities().display_name == "Codex"


@pytest.mark.asyncio
async def test_claude_native_plugin_install_returns_terminal_handoff():
    pytest.importorskip("claude_agent_sdk")
    from integrations.claude_code.harness import ClaudeCodeRuntime

    result = await ClaudeCodeRuntime().execute_native_command(
        command_id="plugins",
        args=("install", "fixture-plugin"),
        ctx=None,
    )

    assert result.status == "terminal_handoff"
    assert result.payload["suggested_command"] == "claude plugin install fixture-plugin"
    assert "plugin management changes runtime-owned configuration" in result.detail


@pytest.mark.asyncio
async def test_claude_native_mcp_login_returns_terminal_handoff():
    pytest.importorskip("claude_agent_sdk")
    from integrations.claude_code.harness import ClaudeCodeRuntime

    result = await ClaudeCodeRuntime().execute_native_command(
        command_id="mcp",
        args=("login", "fixture-server"),
        ctx=None,
    )

    assert result.status == "terminal_handoff"
    assert result.payload["suggested_command"] == "claude mcp login fixture-server"
    assert "MCP changes runtime-owned configuration" in result.detail


def test_claude_native_management_command_defaults_to_safe_list_forms():
    pytest.importorskip("claude_agent_sdk")
    from integrations.claude_code.harness import _claude_management_command

    def _portable(command_id: str, args: tuple[str, ...]) -> list[str]:
        command = _claude_management_command(command_id, args)
        return [Path(command[0]).name, *command[1:]]

    assert _portable("skills", ()) == ["claude", "skills", "list"]
    assert _portable("plugins", ()) == ["claude", "plugin", "list"]
    assert _portable("plugin", ("list",)) == ["claude", "plugin", "list"]
    assert _portable("mcp", ()) == ["claude", "mcp", "list"]
    assert _portable("agents", ()) == ["claude", "agents", "list"]
    assert _portable("hooks", ()) == ["claude", "hooks", "list"]
    assert _portable("status", ()) == ["claude", "status"]
    assert _portable("doctor", ("--json",)) == ["claude", "doctor", "--json"]


@pytest.mark.asyncio
async def test_claude_native_skills_lists_runtime_dirs_without_cli_spawn(monkeypatch, tmp_path):
    pytest.importorskip("claude_agent_sdk")

    from integrations.claude_code import harness as claude_harness
    from integrations.claude_code.harness import ClaudeCodeRuntime

    config_dir = tmp_path / ".claude"
    user_skill = config_dir / "skills" / "user-skill"
    project_skill = tmp_path / "project" / ".claude" / "skills" / "project-skill"
    user_skill.mkdir(parents=True)
    project_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text("# User skill\n")
    (project_skill / "SKILL.md").write_text("# Project skill\n")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    def _unexpected_run(*args, **kwargs):
        raise AssertionError("Bare Claude /skills should read native skill dirs directly")

    monkeypatch.setattr(claude_harness.subprocess, "run", _unexpected_run)

    ctx = SimpleNamespace(workdir=str(tmp_path / "project"))
    result = await ClaudeCodeRuntime().execute_native_command(
        command_id="skills",
        args=(),
        ctx=ctx,
    )

    assert result.status == "ok"
    assert "user-skill (user)" in result.detail
    assert "project-skill (project)" in result.detail
    assert result.payload["skills"] == [
        {"name": "user-skill", "source": "user", "path": str(user_skill / "SKILL.md")},
        {"name": "project-skill", "source": "project", "path": str(project_skill / "SKILL.md")},
    ]


def test_claude_cli_path_prefers_container_visible_installed_binary(monkeypatch, tmp_path):
    pytest.importorskip("claude_agent_sdk")
    from integrations.claude_code import harness as claude_harness

    explicit = tmp_path / "claude"
    explicit.write_text("#!/bin/sh\nexit 0\n")
    explicit.chmod(0o755)
    monkeypatch.setenv("CLAUDE_CODE_CLI_PATH", str(explicit))
    monkeypatch.setattr(claude_harness.shutil, "which", lambda _name: "/usr/bin/claude")

    assert claude_harness._resolve_claude_cli_path() == str(explicit)
    assert claude_harness._claude_cli_command("--version") == [str(explicit), "--version"]


def test_claude_auth_status_uses_native_auth_probe(monkeypatch, tmp_path):
    pytest.importorskip("claude_agent_sdk")
    from integrations.claude_code import harness as claude_harness
    from integrations.claude_code.harness import ClaudeCodeRuntime

    cred_dir = tmp_path / ".claude"
    cred_dir.mkdir()
    (cred_dir / ".credentials.json").write_text("{}")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cred_dir))
    monkeypatch.setattr(claude_harness, "_resolve_claude_cli_path", lambda: "/usr/bin/claude")
    monkeypatch.setattr(
        claude_harness,
        "_probe_claude_auth_status",
        lambda cli_path: (True, "Claude Code reports logged in via claude.ai."),
    )

    status = ClaudeCodeRuntime().auth_status()

    assert status.ok is True
    assert "CLI: /usr/bin/claude" in status.detail
    assert "Credentials:" in status.detail


@pytest.mark.asyncio
async def test_claude_native_tty_management_commands_return_immediate_terminal_handoff(monkeypatch):
    pytest.importorskip("claude_agent_sdk")

    from integrations.claude_code import harness as claude_harness
    from integrations.claude_code.harness import ClaudeCodeRuntime

    def _unexpected_run(*args, **kwargs):
        raise AssertionError("TTY-only Claude native commands should not spawn in chat")

    monkeypatch.setattr(claude_harness.subprocess, "run", _unexpected_run)

    for command_id in ("hooks", "status", "doctor"):
        result = await ClaudeCodeRuntime().execute_native_command(
            command_id=command_id,
            args=(),
            ctx=None,
        )

        assert result.status == "terminal_handoff"
        suggested = str(result.payload["suggested_command"])
        assert suggested.endswith(f"claude {command_id}") or suggested.endswith(f"claude {command_id} list")
        assert "without waiting for a chat-side subprocess timeout" in result.detail


@pytest.mark.asyncio
async def test_claude_native_management_timeout_still_returns_terminal_handoff(monkeypatch):
    pytest.importorskip("claude_agent_sdk")
    import subprocess

    from integrations.claude_code import harness as claude_harness
    from integrations.claude_code.harness import ClaudeCodeRuntime

    def _timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["claude", "agents", "list"], timeout=20)

    monkeypatch.setattr(claude_harness.subprocess, "run", _timeout_run)

    result = await ClaudeCodeRuntime().execute_native_command(
        command_id="agents",
        args=(),
        ctx=None,
    )

    assert result.status == "terminal_handoff"
    suggested = str(result.payload["suggested_command"])
    assert suggested.endswith("claude agents list")
    assert "within the chat timeout" in result.detail


@pytest.mark.asyncio
async def test_codex_native_mutating_args_return_canonical_terminal_command():
    from integrations.codex.harness import CodexRuntime

    mcp = await CodexRuntime().execute_native_command(
        command_id="mcp-status",
        args=("add", "fixture-server"),
        ctx=None,
    )

    assert mcp.status == "terminal_handoff"
    assert mcp.payload["suggested_command"] == "codex mcp add fixture-server"


@pytest.mark.asyncio
async def test_codex_native_unknown_app_server_method_returns_terminal_handoff(monkeypatch):
    from integrations.codex import harness as codex_harness
    from integrations.codex.app_server import CodexAppServerError
    from integrations.codex.harness import CodexRuntime

    class _FakeClient:
        async def initialize(self):
            return {}

        async def request(self, method, params, *, timeout=60.0):
            raise CodexAppServerError(
                -32600,
                f"Invalid request: unknown variant `{method}`",
            )

    @asynccontextmanager
    async def _fake_spawn(*, extra_env=None):
        yield _FakeClient()

    monkeypatch.setattr(codex_harness.CodexAppServer, "spawn", _fake_spawn)

    result = await CodexRuntime().execute_native_command(
        command_id="cloud",
        args=("subscription",),
        ctx=SimpleNamespace(env={}, workdir="/tmp/project"),
    )

    assert result.status == "terminal_handoff"
    assert result.payload["method"] == "user/limits/subscription"
    assert result.payload["suggested_command"] == "codex cloud subscription"


@pytest.mark.asyncio
async def test_codex_native_apps_hooks_and_fs_route_to_current_app_server_methods(monkeypatch):
    from integrations.codex import harness as codex_harness
    from integrations.codex.harness import CodexRuntime

    calls: list[tuple[str, dict]] = []

    class _FakeClient:
        async def initialize(self):
            return {}

        async def request(self, method, params, *, timeout=60.0):
            calls.append((method, params))
            return {"ok": True}

    @asynccontextmanager
    async def _fake_spawn(*, extra_env=None):
        yield _FakeClient()

    monkeypatch.setattr(codex_harness.CodexAppServer, "spawn", _fake_spawn)
    ctx = SimpleNamespace(env={}, workdir="/tmp/project")

    await CodexRuntime().execute_native_command(command_id="apps", args=(), ctx=ctx)
    await CodexRuntime().execute_native_command(command_id="hooks", args=(), ctx=ctx)
    await CodexRuntime().execute_native_command(command_id="fs", args=("read", "README.md"), ctx=ctx)
    await CodexRuntime().execute_native_command(command_id="approvals", args=(), ctx=ctx)

    assert calls == [
        ("app/list", {}),
        ("hooks/list", {"cwds": ["/tmp/project"]}),
        ("fs/readFile", {"path": "/tmp/project/README.md"}),
        ("configRequirements/read", {}),
    ]


@pytest.mark.asyncio
async def test_codex_native_apps_forbidden_returns_terminal_handoff(monkeypatch):
    from integrations.codex import harness as codex_harness
    from integrations.codex.app_server import CodexAppServerError
    from integrations.codex.harness import CodexRuntime

    class _FakeClient:
        async def initialize(self):
            return {}

        async def request(self, method, params, *, timeout=60.0):
            raise CodexAppServerError(
                -32603,
                "failed to list apps: Request failed with status 403 Forbidden",
            )

    @asynccontextmanager
    async def _fake_spawn(*, extra_env=None):
        yield _FakeClient()

    monkeypatch.setattr(codex_harness.CodexAppServer, "spawn", _fake_spawn)

    result = await CodexRuntime().execute_native_command(
        command_id="apps",
        args=(),
        ctx=SimpleNamespace(env={}, workdir="/tmp/project"),
    )

    assert result.status == "terminal_handoff"
    assert result.payload["method"] == "app/list"
    assert result.payload["suggested_command"] == "codex app"


def test_codex_native_mutating_args_require_approval():
    from integrations.codex.harness import CodexRuntime

    runtime = CodexRuntime()
    assert runtime.native_command_requires_approval(
        command_id="plugins", args=("install", "fixture-plugin")
    )
    assert not runtime.native_command_requires_approval(
        command_id="plugins", args=("read", "fixture-plugin")
    )
    assert runtime.native_command_requires_approval(command_id="undo", args=())
    assert runtime.native_command_requires_approval(command_id="branch", args=("feature-x",))
    assert runtime.native_command_requires_approval(command_id="resume", args=("rollback",))
    assert runtime.native_command_requires_approval(command_id="resume", args=("archive", "thread-1"))
    assert runtime.native_command_requires_approval(command_id="review", args=("worktree",))
    assert not runtime.native_command_requires_approval(command_id="resume", args=("show", "thread-1"))


@pytest.mark.asyncio
async def test_codex_auth_status_blocks_unsupported_cli_version(monkeypatch):
    from integrations.codex import harness as codex_harness

    monkeypatch.setattr(codex_harness, "_codex_cli_version", lambda: "0.125.0")

    status = await codex_harness._check_auth_status()

    assert status.ok is False
    assert "0.125.0" in status.detail
    assert "0.128.0+" in status.detail
    assert status.suggested_command == "npm --prefix /home/spindrel/.local install -g @openai/codex@latest"


@pytest.mark.asyncio
async def test_codex_auth_status_includes_supported_cli_version(monkeypatch):
    from integrations.codex import harness as codex_harness

    class _FakeClient:
        async def initialize(self):
            return {}

        async def request(self, method, params, *, timeout=60.0):
            return {"account": {"email": "codex@example.test"}}

    @asynccontextmanager
    async def _fake_spawn(*, extra_env=None):
        yield _FakeClient()

    monkeypatch.setattr(codex_harness, "_codex_cli_version", lambda: "0.128.0")
    monkeypatch.setattr(codex_harness.CodexAppServer, "spawn", _fake_spawn)

    status = await codex_harness._check_auth_status()

    assert status.ok is True
    assert status.detail == "Logged in as codex@example.test (codex-cli 0.128.0)"


@pytest.mark.asyncio
async def test_codex_sync_auth_status_runs_from_existing_event_loop(monkeypatch):
    from integrations.codex import harness as codex_harness
    from app.services.agent_harnesses.base import AuthStatus

    async def _fake_check():
        return AuthStatus(ok=True, detail="threaded auth ok")

    monkeypatch.setattr(codex_harness, "_check_auth_status", _fake_check)

    status = codex_harness._run_auth_status_check_sync()

    assert status.ok is True
    assert status.detail == "threaded auth ok"
