"""Slash-command harness branches.

Pins the Phase 4 contract:

- harness ``/effort low`` does NOT mutate ``channel.config['effort_override']``
  (test gate from the v2 plan review)
- harness ``/model X`` writes per-session ``harness_settings.model``
- non-harness ``/model X`` writes ``channel.model_override``
- harness ``/help`` lists only the runtime-allowlisted commands
- catalog endpoint with ``?bot_id=`` returns the intersected list
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.db.models import Bot as BotRow, Channel as ChannelRow, Message, Session as SessionRow
from app.services.agent_harnesses import HARNESS_REGISTRY, register_runtime, unregister_runtime
from app.services.agent_harnesses.base import (
    HarnessRuntimeCommandResult,
    HarnessRuntimeCommandSpec,
    HarnessSlashCommandPolicy,
    RuntimeCapabilities,
)
from app.services.agent_harnesses.settings import (
    HARNESS_SETTINGS_KEY,
    load_session_settings,
)
from app.services.agent_harnesses.approvals import load_session_mode
from app.services.session_plan_mode import get_session_plan_mode
from app.services.slash_commands import (
    execute_slash_command,
    list_supported_slash_commands,
)
from tests.factories import build_bot, build_channel

pytestmark = pytest.mark.asyncio

_RUNTIME_NAME = "test-harness-phase4"


class _StubRuntime:
    """A harness runtime with a tiny allowlist + no effort knob."""

    name = _RUNTIME_NAME
    approval_checks: list[dict] = []

    def readonly_tools(self):
        return frozenset()

    def prompts_in_accept_edits(self, tool_name: str) -> bool:
        return True

    def autoapprove_in_plan(self, tool_name: str) -> bool:
        return False

    def native_command_requires_approval(
        self,
        *,
        command_id: str,
        args: tuple[str, ...],
        args_text: str | None = None,
    ) -> bool:
        self.approval_checks.append({
            "command_id": command_id,
            "args": args,
            "args_text": args_text,
        })
        return command_id == "mutate"

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            display_name="Test Harness",
            supported_models=(),
            model_is_freeform=True,
            effort_values=(),  # No effort — friendly no-op path
            slash_policy=HarnessSlashCommandPolicy(
                allowed_command_ids=frozenset({"help", "stop", "rename", "model", "runtime"}),
            ),
            native_commands=(
                HarnessRuntimeCommandSpec(
                    id="status",
                    label="status",
                    description="Show test harness status.",
                    aliases=("health",),
                ),
                HarnessRuntimeCommandSpec(
                    id="context",
                    label="context",
                    description="Show test harness native context.",
                ),
                HarnessRuntimeCommandSpec(
                    id="mutate",
                    label="mutate",
                    description="Mutating test command.",
                    readonly=False,
                    mutability="mutating",
                ),
            ),
        )

    async def execute_native_command(self, *, command_id: str, args: tuple[str, ...], ctx):
        return HarnessRuntimeCommandResult(
            command_id=command_id,
            title="Stub runtime status",
            detail=f"session={ctx.spindrel_session_id}; args={','.join(args)}",
            payload={"workdir": ctx.workdir},
        )

    async def context_status(self, *, ctx):
        return HarnessRuntimeCommandResult(
            command_id="context",
            title="Stub native context",
            detail="native context from runtime",
            payload={
                "usage": {
                    "input_tokens": 26,
                    "iterations": {"count": 2},
                }
            },
        )


@pytest.fixture(autouse=True)
def _register_stub_runtime():
    _StubRuntime.approval_checks = []
    register_runtime(_RUNTIME_NAME, _StubRuntime())
    yield
    unregister_runtime(_RUNTIME_NAME)


async def _make_harness_setup(db_session):
    bot = build_bot(id="harness-slash-bot", name="HS Bot", model="x")
    bot.harness_runtime = _RUNTIME_NAME
    db_session.add(bot)
    channel = build_channel(bot_id=bot.id)
    db_session.add(channel)
    session = SessionRow(
        id=uuid.uuid4(),
        client_id="hs-client",
        bot_id=bot.id,
        channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(session)
    # Channel has an active session so channel-surface /model can resolve it.
    channel.active_session_id = session.id
    await db_session.commit()
    return bot, channel, session


async def _make_normal_setup(db_session):
    bot = build_bot(id="normal-bot", name="Normal Bot", model="x")
    db_session.add(bot)
    channel = build_channel(bot_id=bot.id)
    db_session.add(channel)
    session = SessionRow(
        id=uuid.uuid4(),
        client_id="norm-client",
        bot_id=bot.id,
        channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.commit()
    return bot, channel, session


# ---------------------------------------------------------------------------
# /effort — harness with no effort_values must NOT touch channel.config
# ---------------------------------------------------------------------------


async def test_harness_effort_does_not_mutate_channel_config(db_session):
    """v2 review test gate: friendly no-op never writes effort_override."""
    bot, channel, session = await _make_harness_setup(db_session)
    initial_config = dict(channel.config or {})

    result = await execute_slash_command(
        command_id="effort",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["low"],
    )

    assert result.command_id == "effort"
    # Friendly no-op message — runtime declares no effort knob.
    assert "does not expose" in result.payload["detail"].lower()
    # Critical: channel.config must be unchanged.
    await db_session.refresh(channel)
    assert (channel.config or {}) == initial_config
    assert "effort_override" not in (channel.config or {})


async def test_harness_effort_session_surface_does_not_mutate_channel_config(db_session):
    bot, channel, session = await _make_harness_setup(db_session)
    initial_config = dict(channel.config or {})

    result = await execute_slash_command(
        command_id="effort",
        channel_id=None,
        session_id=session.id,
        db=db_session,
        args=["low"],
    )

    assert result.command_id == "effort"
    assert result.payload["scope_kind"] == "session"
    assert "does not expose" in result.payload["detail"].lower()
    await db_session.refresh(channel)
    assert (channel.config or {}) == initial_config


# ---------------------------------------------------------------------------
# /model — harness writes harness_settings; non-harness writes channel
# ---------------------------------------------------------------------------


async def test_harness_model_writes_harness_settings(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    result = await execute_slash_command(
        command_id="model",
        channel_id=None,
        session_id=session.id,
        db=db_session,
        args=["claude-sonnet-4-6"],
    )
    assert result.command_id == "model"

    fresh = await load_session_settings(db_session, session.id)
    assert fresh.model == "claude-sonnet-4-6"
    # Channel override must NOT be touched for harness bots.
    await db_session.refresh(channel)
    assert channel.model_override is None


async def test_harness_model_from_channel_surface_resolves_active_session(db_session):
    """Composer fires /model with channel_id only — handler must fall back
    to channel.active_session_id rather than rejecting. Without this, typed
    /model in a harness channel is unreachable."""
    bot, channel, session = await _make_harness_setup(db_session)

    result = await execute_slash_command(
        command_id="model",
        channel_id=channel.id,    # surface = channel
        session_id=None,           # NOT supplied — handler must resolve
        db=db_session,
        args=["claude-opus-4-7"],
    )
    assert result.command_id == "model"

    # Settings landed on the channel's active session.
    fresh = await load_session_settings(db_session, session.id)
    assert fresh.model == "claude-opus-4-7"
    # Channel override still untouched (harness path).
    await db_session.refresh(channel)
    assert channel.model_override is None


async def test_harness_model_from_channel_surface_uses_current_session_id(db_session):
    """Channel surface commands must target the UI-current session, not the
    channel primary. ``active_session_id`` only supplies the default primary
    when no current session is provided."""
    bot, channel, primary = await _make_harness_setup(db_session)
    scratch = SessionRow(
        id=uuid.uuid4(),
        client_id="hs-client",
        bot_id=bot.id,
        channel_id=None,
        parent_channel_id=channel.id,
        session_type="scratch",
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(scratch)
    await db_session.commit()

    result = await execute_slash_command(
        command_id="model",
        channel_id=channel.id,
        session_id=None,
        current_session_id=scratch.id,
        db=db_session,
        args=["claude-haiku-4-5"],
    )
    assert result.command_id == "model"

    scratch_settings = await load_session_settings(db_session, scratch.id)
    primary_settings = await load_session_settings(db_session, primary.id)
    assert scratch_settings.model == "claude-haiku-4-5"
    assert primary_settings.model is None


async def test_harness_model_without_arg_returns_picker_status(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    result = await execute_slash_command(
        command_id="model",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=[],
    )

    assert result.result_type == "harness_model_effort_picker"
    assert result.payload["session_id"] == str(session.id)
    assert result.payload["runtime"] == _RUNTIME_NAME
    assert "runtime default" in result.fallback_text


async def test_harness_model_clear_removes_session_model_setting(db_session):
    bot, channel, session = await _make_harness_setup(db_session)
    await execute_slash_command(
        command_id="model",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["claude-opus-4-7"],
    )

    result = await execute_slash_command(
        command_id="model",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["clear"],
    )

    assert result.payload["scope_kind"] == "session"
    assert "cleared" in result.payload["detail"].lower()
    settings = await load_session_settings(db_session, session.id)
    assert settings.model is None
    await db_session.refresh(channel)
    assert channel.model_override is None


async def test_channel_surface_rejects_current_session_from_other_channel(db_session):
    bot, channel, primary = await _make_harness_setup(db_session)
    other_channel = build_channel(bot_id=bot.id)
    db_session.add(other_channel)
    other_session = SessionRow(
        id=uuid.uuid4(),
        client_id="hs-client",
        bot_id=bot.id,
        channel_id=other_channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(other_session)
    await db_session.commit()

    with pytest.raises(ValueError, match="does not belong"):
        await execute_slash_command(
            command_id="model",
            channel_id=channel.id,
            session_id=None,
            current_session_id=other_session.id,
            db=db_session,
            args=["claude-haiku-4-5"],
        )


async def test_normal_model_writes_channel_override(db_session):
    bot, channel, session = await _make_normal_setup(db_session)

    result = await execute_slash_command(
        command_id="model",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["gpt-4o"],
    )
    assert result.command_id == "model"

    await db_session.refresh(channel)
    assert channel.model_override == "gpt-4o"
    # Harness settings must NOT be touched for non-harness bots.
    fresh = await load_session_settings(db_session, session.id)
    assert fresh.model is None


async def test_normal_model_without_arg_returns_channel_status(db_session):
    bot, channel, session = await _make_normal_setup(db_session)

    result = await execute_slash_command(
        command_id="model",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=[],
    )

    assert result.payload["scope_kind"] == "channel"
    assert "bot default" in result.payload["detail"].lower()


async def test_normal_model_clear_removes_channel_override(db_session):
    bot, channel, session = await _make_normal_setup(db_session)
    channel.model_override = "gpt-4o"
    channel.model_provider_id_override = "provider-a"
    await db_session.commit()

    result = await execute_slash_command(
        command_id="model",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["clear"],
    )

    assert result.payload["scope_kind"] == "channel"
    assert "cleared" in result.payload["detail"].lower()
    await db_session.refresh(channel)
    assert channel.model_override is None
    assert channel.model_provider_id_override is None


async def test_harness_plan_sets_session_plan_mode_not_approval_mode(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    result = await execute_slash_command(
        command_id="plan",
        channel_id=None,
        session_id=session.id,
        db=db_session,
        args=[],
    )

    assert result.command_id == "plan"
    await db_session.refresh(session)
    assert get_session_plan_mode(session) == "planning"
    assert await load_session_mode(db_session, session.id) == "bypassPermissions"


async def test_harness_context_routes_to_native_runtime_without_host_summary(db_session, monkeypatch):
    bot, channel, session = await _make_harness_setup(db_session)

    async def fake_resolve_harness_paths(db, *, channel_id, bot):
        return type("Paths", (), {
            "workdir": "/effective/project",
            "bot_workspace_dir": "/bot/workspace",
            "project_dir": None,
            "work_surface": None,
        })()

    monkeypatch.setattr(
        "app.services.agent_harnesses.project.resolve_harness_paths",
        fake_resolve_harness_paths,
    )

    result = await execute_slash_command(
        command_id="context",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=[],
    )

    assert result.result_type == "harness_runtime_command"
    assert result.payload["runtime"] == _RUNTIME_NAME
    assert result.payload["command"] == "context"
    assert result.payload["status"] == "ok"
    assert result.payload["title"] == "Stub native context"
    assert result.payload["detail"] == "native context from runtime"
    assert result.payload["data"]["usage"]["iterations"] == {"count": 2}
    assert "host_context" not in result.payload
    assert "native_context" not in result.payload
    assert "native context from runtime" in result.fallback_text
    assert "Spindrel bridge tools" not in result.fallback_text


async def test_harness_model_rejects_oversized(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    with pytest.raises(ValueError, match="exceeds"):
        await execute_slash_command(
            command_id="model",
            channel_id=None,
            session_id=session.id,
            db=db_session,
            args=["x" * 257],
        )


# ---------------------------------------------------------------------------
# /help filtered by runtime allowlist
# ---------------------------------------------------------------------------


async def test_harness_help_lists_only_allowed_commands(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    result = await execute_slash_command(
        command_id="help",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=[],
    )
    labels = {c["label"] for c in result.payload["top_categories"]}
    # Allowlist for stub plus runtime-native command aliases.
    assert labels == {"/help", "/stop", "/rename", "/model", "/runtime", "/status", "/health", "/mutate"}


async def test_normal_help_lists_full_surface(db_session):
    bot, channel, session = await _make_normal_setup(db_session)

    result = await execute_slash_command(
        command_id="help",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=[],
    )
    labels = {c["label"] for c in result.payload["top_categories"]}
    # Spot-check that several non-allowlisted commands appear for a normal bot.
    assert "/find" in labels
    assert "/effort" in labels
    assert "/compact" in labels


# ---------------------------------------------------------------------------
# Catalog endpoint with bot_id intersects
# ---------------------------------------------------------------------------


async def test_catalog_with_bot_id_intersects(db_session):
    bot, _channel, _session = await _make_harness_setup(db_session)

    catalog = await list_supported_slash_commands(db=db_session, bot_id=bot.id)
    ids = {c["id"] for c in catalog}
    assert ids == {"help", "stop", "rename", "model", "runtime", "status", "health", "mutate"}
    mutate = next(item for item in catalog if item["id"] == "mutate")
    assert mutate["runtime_command_mutability"] == "mutating"


async def test_catalog_with_session_id_adds_runtime_reported_native_slashes(db_session):
    bot, _channel, session = await _make_harness_setup(db_session)
    db_session.add(Message(
        session_id=session.id,
        role="assistant",
        content="initialized",
        metadata_={
            "harness": {
                "claude_native_slash_commands": [
                    {
                        "name": "project-fixture",
                        "description": "Project-local fixture skill.",
                    },
                    {
                        "name": "status",
                        "description": "Duplicate static native command.",
                    },
                ]
            }
        },
        created_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    catalog = await list_supported_slash_commands(
        db=db_session,
        bot_id=bot.id,
        session_id=session.id,
    )

    by_id = {item["id"]: item for item in catalog}
    assert "project-fixture" in by_id
    assert by_id["project-fixture"]["runtime_command_interaction_kind"] == "native_session"
    assert by_id["project-fixture"]["description"] == "Project-local fixture skill."
    assert sum(1 for item in catalog if item["id"] == "status") == 1


async def test_harness_runtime_command_dispatches_to_whitelisted_runtime(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    result = await execute_slash_command(
        command_id="runtime",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["status", "extra"],
    )

    assert result.result_type == "harness_runtime_command"
    assert result.payload["runtime"] == _RUNTIME_NAME
    assert result.payload["command"] == "status"
    assert result.payload["status"] == "ok"
    assert "args=extra" in result.payload["detail"]


async def test_harness_native_command_dispatches_by_direct_slash_name(db_session, monkeypatch):
    bot, channel, session = await _make_harness_setup(db_session)

    async def fake_resolve_harness_paths(db, *, channel_id, bot):
        return type("Paths", (), {
            "workdir": "/effective/project",
            "bot_workspace_dir": "/bot/workspace",
            "project_dir": None,
            "work_surface": None,
        })()

    monkeypatch.setattr(
        "app.services.agent_harnesses.project.resolve_harness_paths",
        fake_resolve_harness_paths,
    )
    result = await execute_slash_command(
        command_id="status",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["extra"],
    )

    assert result.command_id == "status"
    assert result.result_type == "harness_runtime_command"
    assert result.payload["runtime"] == _RUNTIME_NAME
    assert result.payload["command"] == "status"
    assert "args=extra" in result.payload["detail"]
    assert result.payload["data"]["workdir"] == "/effective/project"


async def test_harness_native_command_dispatches_by_alias(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    result = await execute_slash_command(
        command_id="health",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=[],
    )

    assert result.command_id == "health"
    assert result.payload["command"] == "status"


async def test_mutating_harness_native_command_requires_approval(db_session, monkeypatch):
    bot, channel, session = await _make_harness_setup(db_session)

    async def _deny(**kwargs):
        from app.services.agent_harnesses.approvals import AllowDeny

        _deny.calls.append(kwargs)
        return AllowDeny.deny("blocked by test")

    _deny.calls = []

    monkeypatch.setattr(
        "app.services.agent_harnesses.approvals.request_harness_approval",
        _deny,
    )

    result = await execute_slash_command(
        command_id="mutate",
        channel_id=channel.id,
        session_id=None,
        db=db_session,
        args=["install", "fixture plugin"],
        args_text='install "fixture plugin"',
    )

    assert result.command_id == "mutate"
    assert result.payload["status"] == "denied"
    assert result.payload["command"] == "mutate"
    assert "blocked by test" in result.fallback_text
    assert _StubRuntime.approval_checks[-1]["args_text"] == 'install "fixture plugin"'
    assert _deny.calls[-1]["tool_input"]["args_text"] == 'install "fixture plugin"'


async def test_harness_runtime_command_rejects_unlisted_runtime_command(db_session):
    bot, channel, session = await _make_harness_setup(db_session)

    with pytest.raises(ValueError, match="not available"):
        await execute_slash_command(
            command_id="runtime",
            channel_id=channel.id,
            session_id=None,
            db=db_session,
            args=["shell"],
        )


async def test_catalog_without_bot_id_returns_full(db_session):
    catalog = await list_supported_slash_commands()
    ids = {c["id"] for c in catalog}
    # Sanity: full catalog has more than the stub allowlist.
    assert len(ids) > 4
    assert {"help", "stop", "rename", "find", "effort", "model"} <= ids
