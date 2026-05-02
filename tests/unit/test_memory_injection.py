"""Unit tests for memory scheme injection in context_assembly.py.

Tests the memory-write nudge, loose file surfacing, and MEMORY.md injection
added as part of the memory system hardening (2026-04-13).
"""
import os
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agent.context_assembly import AssemblyLedger, _inject_memory_scheme
from app.agent.context_profiles import get_context_profile


def _make_bot(bot_id: str = "test-bot", ws_root: str = "/tmp"):
    """Create a minimal bot mock with workspace-files memory scheme."""
    bot = MagicMock()
    bot.id = bot_id
    bot.memory_scheme = "workspace-files"
    bot.shared_workspace_id = None
    bot.workspace = None
    return bot


async def _collect_events(bot, messages, ws_root):
    """Run _inject_memory_scheme and collect all yielded events."""
    injected_paths: set = set()
    ledger = AssemblyLedger()
    context_profile = get_context_profile("chat_rich")

    from unittest.mock import patch

    with patch("app.services.workspace.workspace_service") as mock_ws, \
         patch("app.services.memory_scheme.get_memory_root", return_value=os.path.join(ws_root, "memory")), \
         patch("app.services.memory_scheme.get_memory_index_prefix", return_value=f"bots/{bot.id}/memory"), \
         patch("app.services.memory_scheme.get_memory_rel_path", return_value="memory"):
        mock_ws.get_workspace_root.return_value = ws_root
        events = []
        async for event in _inject_memory_scheme(
            messages, bot, ledger, injected_paths, context_profile,
        ):
            events.append(event)
    return events, messages, injected_paths


async def _collect_events_with_profile(bot, messages, ws_root, profile_name: str):
    injected_paths: set = set()
    ledger = AssemblyLedger()
    context_profile = get_context_profile(profile_name)

    from unittest.mock import patch

    with patch("app.services.workspace.workspace_service") as mock_ws, \
         patch("app.services.memory_scheme.get_memory_root", return_value=os.path.join(ws_root, "memory")), \
         patch("app.services.memory_scheme.get_memory_index_prefix", return_value=f"bots/{bot.id}/memory"), \
         patch("app.services.memory_scheme.get_memory_rel_path", return_value="memory"):
        mock_ws.get_workspace_root.return_value = ws_root
        events = []
        async for event in _inject_memory_scheme(
            messages, bot, ledger, injected_paths, context_profile,
        ):
            events.append(event)
    return events, messages, injected_paths, ledger


@pytest.fixture
def mem_ws(tmp_path):
    """Create a workspace with memory/ directory structure."""
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "logs").mkdir()
    (mem / "reference").mkdir()
    (mem / "MEMORY.md").write_text("# Memory\n\n## Preferences\n- likes coffee\n")
    today = date.today().isoformat()
    (mem / "logs" / f"{today}.md").write_text("### 10:00 — started\n")
    return tmp_path


class TestLooseFileSurfacing:
    """Loose .md files in memory/ root should appear in context."""

    async def test_loose_files_listed(self, mem_ws):
        """Files in memory/ (besides MEMORY.md) appear in injected messages."""
        (mem_ws / "memory" / "todos.md").write_text("- buy milk\n")
        (mem_ws / "memory" / "plant-profiles.md").write_text("# Plants\n")

        bot = _make_bot(ws_root=str(mem_ws))
        messages: list[dict] = []
        events, messages, _ = await _collect_events(bot, messages, str(mem_ws))

        event_types = [e["type"] for e in events]
        assert "memory_scheme_loose_files" in event_types

        loose_event = next(e for e in events if e["type"] == "memory_scheme_loose_files")
        assert loose_event["count"] == 2

        # Check the message content mentions the files
        loose_msg = [m for m in messages if "Other files in" in m.get("content", "")]
        assert len(loose_msg) == 1
        assert "todos.md" in loose_msg[0]["content"]
        assert "plant-profiles.md" in loose_msg[0]["content"]

    async def test_no_loose_files_no_event(self, mem_ws):
        """No event when there are no loose files."""
        bot = _make_bot(ws_root=str(mem_ws))
        messages: list[dict] = []
        events, _, _ = await _collect_events(bot, messages, str(mem_ws))

        event_types = [e["type"] for e in events]
        assert "memory_scheme_loose_files" not in event_types

    async def test_loose_files_excludes_memory_md(self, mem_ws):
        """MEMORY.md itself is not listed as a loose file."""
        bot = _make_bot(ws_root=str(mem_ws))
        messages: list[dict] = []
        events, messages, _ = await _collect_events(bot, messages, str(mem_ws))

        for m in messages:
            content = m.get("content", "")
            if "Other files in" in content:
                assert "MEMORY.md" not in content

    async def test_loose_files_suggests_reference(self, mem_ws):
        """Loose file listing suggests moving to reference/."""
        (mem_ws / "memory" / "notes.md").write_text("stuff\n")

        bot = _make_bot(ws_root=str(mem_ws))
        messages: list[dict] = []
        events, messages, _ = await _collect_events(bot, messages, str(mem_ws))

        loose_msg = [m for m in messages if "Other files in" in m.get("content", "")]
        assert "reference/" in loose_msg[0]["content"]


class TestMemoryPolicyCaps:
    async def test_lean_profile_caps_memory_bootstrap_and_skips_logs(self, mem_ws):
        (mem_ws / "memory" / "MEMORY.md").write_text("x" * 5000)

        bot = _make_bot(ws_root=str(mem_ws))
        messages: list[dict] = []
        events, messages, _, ledger = await _collect_events_with_profile(
            bot,
            messages,
            str(mem_ws),
            "chat_lean",
        )

        event_types = [e["type"] for e in events]
        assert "memory_scheme_bootstrap" in event_types
        assert "memory_scheme_today_log" not in event_types
        bootstrap_msg = next(m for m in messages if "Your persistent memory" in m.get("content", ""))
        assert "Truncated to 4000 chars" in bootstrap_msg["content"]
        assert ledger.inject_decisions["memory_today_log"] == "skipped_by_profile"


class TestMemoryWriteNudge:
    """Bot should be nudged when no memory writes detected in recent turns."""

    async def test_nudge_fires_after_threshold(self, mem_ws):
        """Nudge appears when 5+ user turns pass without a memory write."""
        bot = _make_bot(ws_root=str(mem_ws))
        messages: list[dict] = []
        # Simulate 6 user turns with no memory writes
        for i in range(6):
            messages.append({"role": "user", "content": f"message {i}"})
            messages.append({"role": "assistant", "content": f"response {i}"})

        events, messages, _ = await _collect_events(bot, messages, str(mem_ws))

        event_types = [e["type"] for e in events]
        assert "memory_scheme_nudge" in event_types

        nudge_msgs = [m for m in messages if "Memory reminder" in m.get("content", "")]
        assert len(nudge_msgs) == 1

    async def test_no_nudge_with_recent_memory_write(self, mem_ws):
        """No nudge when a recent file tool call wrote to memory/."""
        bot = _make_bot(ws_root=str(mem_ws))
        messages: list[dict] = []
        # Simulate turns with a memory write in the middle
        for i in range(3):
            messages.append({"role": "user", "content": f"message {i}"})
            messages.append({"role": "assistant", "content": f"response {i}"})
        # Memory write tool result
        messages.append({
            "role": "tool",
            "content": '{"ok": true, "bytes": 100, "path": "memory/MEMORY.md"}',
        })
        # A few more turns
        messages.append({"role": "user", "content": "another message"})
        messages.append({"role": "assistant", "content": "another response"})

        events, messages, _ = await _collect_events(bot, messages, str(mem_ws))

        event_types = [e["type"] for e in events]
        assert "memory_scheme_nudge" not in event_types

    async def test_no_nudge_with_few_turns(self, mem_ws):
        """No nudge when fewer than threshold turns have passed."""
        bot = _make_bot(ws_root=str(mem_ws))
        messages: list[dict] = []
        # Only 3 user turns
        for i in range(3):
            messages.append({"role": "user", "content": f"message {i}"})
            messages.append({"role": "assistant", "content": f"response {i}"})

        events, messages, _ = await _collect_events(bot, messages, str(mem_ws))

        event_types = [e["type"] for e in events]
        assert "memory_scheme_nudge" not in event_types

    async def test_nudge_detects_assistant_tool_calls(self, mem_ws):
        """Memory write detected in assistant message tool_calls."""
        bot = _make_bot(ws_root=str(mem_ws))
        messages: list[dict] = []
        for i in range(3):
            messages.append({"role": "user", "content": f"message {i}"})
            messages.append({"role": "assistant", "content": f"response {i}"})
        # Assistant with a file tool call to memory/
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "tc1",
                "function": {
                    "name": "file",
                    "arguments": '{"operation":"append","path":"memory/logs/2026-04-13.md","content":"entry"}',
                },
            }],
        })
        for i in range(3):
            messages.append({"role": "user", "content": f"later {i}"})
            messages.append({"role": "assistant", "content": f"reply {i}"})

        events, messages, _ = await _collect_events(bot, messages, str(mem_ws))

        event_types = [e["type"] for e in events]
        # Only 3 turns since the write — should NOT nudge
        assert "memory_scheme_nudge" not in event_types
