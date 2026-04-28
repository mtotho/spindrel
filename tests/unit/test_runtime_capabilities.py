"""Coverage for RuntimeCapabilities + the harness slash-policy intersection."""
from __future__ import annotations

import pytest

from app.services.agent_harnesses.base import (
    HarnessSlashCommandPolicy,
    RuntimeCapabilities,
)
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
        "plan", "runtime",
    ):
        assert cmd in allowed, f"{cmd} should be in Claude allowlist"
    assert {cmd.id for cmd in caps.native_commands} >= {"auth", "version"}
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
    assert "runtime" in caps.slash_policy.allowed_command_ids
    assert {cmd.id for cmd in caps.native_commands} >= {
        "config", "mcp-status", "plugins", "skills", "features",
    }
    assert caps.native_compaction is True


def test_claude_and_codex_have_distinct_display_names():
    pytest.importorskip("claude_agent_sdk")
    from integrations.claude_code.harness import ClaudeCodeRuntime
    from integrations.codex.harness import CodexRuntime

    assert ClaudeCodeRuntime().capabilities().display_name == "Claude Code"
    assert CodexRuntime().capabilities().display_name == "Codex"
