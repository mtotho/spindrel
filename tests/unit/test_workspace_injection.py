"""Tests that workspace skills and base prompt actually get injected into the right places."""
import hashlib
from unittest.mock import patch, AsyncMock, MagicMock
from types import SimpleNamespace

import pytest

from app.services.workspace_skills import WorkspaceSkill


# ---------------------------------------------------------------------------
# Helper: create WorkspaceSkill instances
# ---------------------------------------------------------------------------

def _skill(workspace_id: str, path: str, mode: str, content: str, bot_id: str | None = None):
    return WorkspaceSkill(
        workspace_id=workspace_id,
        source_path=path,
        mode=mode,
        skill_id=f"ws:test:{hashlib.sha256(path.encode()).hexdigest()[:12]}",
        bot_id=bot_id,
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        display_name=path.split("/")[-1].replace(".md", "").replace("-", " ").title(),
    )


# ---------------------------------------------------------------------------
# _inject_workspace_skills — pinned injection
# ---------------------------------------------------------------------------

class TestInjectWorkspaceSkillsPinned:
    @pytest.mark.asyncio
    @patch("app.services.workspace_skills.shared_workspace_service")
    async def test_pinned_skills_injected_as_system_message(self, mock_svc):
        """Pinned workspace skills should be appended as a system message with full content."""
        from app.agent.context_assembly import _inject_workspace_skills

        mock_svc.list_files.return_value = []
        mock_svc.read_file.return_value = {"content": "# Coding Standards\nUse strict mode."}

        pinned = _skill("ws-1", "common/skills/pinned/coding.md", "pinned", "# Coding Standards\nUse strict mode.")

        with patch("app.services.workspace_skills.discover_workspace_skills", return_value=[pinned]):
            messages = []
            inject_chars = {}
            events = []
            async for evt in _inject_workspace_skills(messages, "ws-1", "coder", "hello", inject_chars):
                events.append(evt)

            # Should have injected one system message
            assert len(messages) == 1
            assert messages[0]["role"] == "system"
            assert "Workspace pinned skills:" in messages[0]["content"]
            assert "Coding Standards" in messages[0]["content"]

            # Should have emitted a pinned event
            assert any(e["type"] == "ws_skill_pinned_context" for e in events)
            assert inject_chars.get("ws_skill_pinned", 0) > 0

    @pytest.mark.asyncio
    @patch("app.services.workspace_skills.shared_workspace_service")
    async def test_multiple_pinned_joined_with_separator(self, mock_svc):
        """Multiple pinned skills should be joined with separator."""
        from app.agent.context_assembly import _inject_workspace_skills

        mock_svc.list_files.return_value = []
        skills = [
            _skill("ws-1", "common/skills/pinned/a.md", "pinned", "Skill A content"),
            _skill("ws-1", "common/skills/pinned/b.md", "pinned", "Skill B content"),
        ]

        with patch("app.services.workspace_skills.discover_workspace_skills", return_value=skills):
            messages = []
            async for _ in _inject_workspace_skills(messages, "ws-1", "coder", "hello", {}):
                pass

            assert len(messages) == 1
            assert "Skill A content" in messages[0]["content"]
            assert "Skill B content" in messages[0]["content"]
            assert "---" in messages[0]["content"]


# ---------------------------------------------------------------------------
# _inject_workspace_skills — RAG injection
# ---------------------------------------------------------------------------

class TestInjectWorkspaceSkillsRag:
    @pytest.mark.asyncio
    @patch("app.agent.rag.retrieve_context", new_callable=AsyncMock)
    @patch("app.services.workspace_skills.shared_workspace_service")
    async def test_rag_skills_retrieved_and_injected(self, mock_svc, mock_retrieve):
        """RAG workspace skills should query retrieve_context and inject results."""
        from app.agent.context_assembly import _inject_workspace_skills

        mock_svc.list_files.return_value = []
        rag = _skill("ws-1", "common/skills/rag/api.md", "rag", "API reference content")
        mock_retrieve.return_value = ([("Retrieved chunk about API", "ws_skill:ws-1:common/skills/rag/api.md")], 0.85)

        with patch("app.services.workspace_skills.discover_workspace_skills", return_value=[rag]):
            messages = []
            inject_chars = {}
            events = []
            async for evt in _inject_workspace_skills(messages, "ws-1", "coder", "how does the API work?", inject_chars):
                events.append(evt)

            # Should have called retrieve_context with sources filter
            mock_retrieve.assert_called_once()
            call_kwargs = mock_retrieve.call_args
            assert "sources" in call_kwargs.kwargs or len(call_kwargs.args) > 1

            # Should inject retrieved content
            assert len(messages) == 1
            assert "Relevant workspace skills:" in messages[0]["content"]
            assert "Retrieved chunk about API" in messages[0]["content"]
            assert any(e["type"] == "ws_skill_rag_context" for e in events)

    @pytest.mark.asyncio
    @patch("app.agent.rag.retrieve_context", new_callable=AsyncMock)
    @patch("app.services.workspace_skills.shared_workspace_service")
    async def test_rag_no_results_no_message(self, mock_svc, mock_retrieve):
        """If RAG retrieval returns no chunks, no message should be injected."""
        from app.agent.context_assembly import _inject_workspace_skills

        mock_svc.list_files.return_value = []
        rag = _skill("ws-1", "common/skills/rag/api.md", "rag", "API reference content")
        mock_retrieve.return_value = ([], 0.0)

        with patch("app.services.workspace_skills.discover_workspace_skills", return_value=[rag]):
            messages = []
            events = []
            async for evt in _inject_workspace_skills(messages, "ws-1", "coder", "unrelated query", {}):
                events.append(evt)

            assert len(messages) == 0
            assert not any(e.get("type") == "ws_skill_rag_context" for e in events)


# ---------------------------------------------------------------------------
# _inject_workspace_skills — on-demand injection
# ---------------------------------------------------------------------------

class TestInjectWorkspaceSkillsOnDemand:
    @pytest.mark.asyncio
    @patch("app.services.workspace_skills.shared_workspace_service")
    async def test_on_demand_skills_inject_index(self, mock_svc):
        """On-demand workspace skills should inject a skill index referencing get_workspace_skill."""
        from app.agent.context_assembly import _inject_workspace_skills

        mock_svc.list_files.return_value = []
        od = _skill("ws-1", "common/skills/on-demand/reference.md", "on_demand", "Detailed reference")

        with patch("app.services.workspace_skills.discover_workspace_skills", return_value=[od]):
            messages = []
            events = []
            async for evt in _inject_workspace_skills(messages, "ws-1", "coder", "hello", {}):
                events.append(evt)

            assert len(messages) == 1
            assert "Available workspace skills" in messages[0]["content"]
            assert "get_workspace_skill" in messages[0]["content"]
            assert od.skill_id in messages[0]["content"]
            assert od.display_name in messages[0]["content"]
            assert any(e["type"] == "ws_skill_index" for e in events)


# ---------------------------------------------------------------------------
# _inject_workspace_skills — mixed modes
# ---------------------------------------------------------------------------

class TestInjectWorkspaceSkillsMixed:
    @pytest.mark.asyncio
    @patch("app.agent.rag.retrieve_context", new_callable=AsyncMock)
    @patch("app.services.workspace_skills.shared_workspace_service")
    async def test_all_three_modes_injected(self, mock_svc, mock_retrieve):
        """When all three modes are present, all three should produce messages."""
        from app.agent.context_assembly import _inject_workspace_skills

        mock_svc.list_files.return_value = []
        mock_retrieve.return_value = ([("RAG chunk", "ws_skill:ws-1:common/skills/rag/b.md")], 0.9)

        skills = [
            _skill("ws-1", "common/skills/pinned/a.md", "pinned", "Pinned content"),
            _skill("ws-1", "common/skills/rag/b.md", "rag", "RAG content"),
            _skill("ws-1", "common/skills/on-demand/c.md", "on_demand", "OD content"),
        ]

        with patch("app.services.workspace_skills.discover_workspace_skills", return_value=skills):
            messages = []
            inject_chars = {}
            events = []
            async for evt in _inject_workspace_skills(messages, "ws-1", "coder", "test query", inject_chars):
                events.append(evt)

            # Should have 3 system messages (pinned + rag + on-demand index)
            assert len(messages) == 3
            assert "Workspace pinned skills:" in messages[0]["content"]
            assert "Relevant workspace skills:" in messages[1]["content"]
            assert "Available workspace skills" in messages[2]["content"]

            event_types = [e["type"] for e in events]
            assert "ws_skill_pinned_context" in event_types
            assert "ws_skill_rag_context" in event_types
            assert "ws_skill_index" in event_types

    @pytest.mark.asyncio
    @patch("app.services.workspace_skills.shared_workspace_service")
    async def test_empty_skills_no_messages(self, mock_svc):
        """When no skills exist, no messages should be injected."""
        from app.agent.context_assembly import _inject_workspace_skills

        mock_svc.list_files.side_effect = Exception("not found")

        with patch("app.services.workspace_skills.discover_workspace_skills", return_value=[]):
            messages = []
            events = []
            async for evt in _inject_workspace_skills(messages, "ws-1", "coder", "hello", {}):
                events.append(evt)

            assert len(messages) == 0
            assert len(events) == 0


# ---------------------------------------------------------------------------
# _effective_system_prompt — workspace base prompt injection
# ---------------------------------------------------------------------------

class TestBasePromptInjection:
    """Verify that _effective_system_prompt actually swaps in the workspace base prompt."""

    @patch("app.agent.base_prompt.resolve_workspace_base_prompt")
    @patch("app.agent.base_prompt.render_base_prompt")
    def test_workspace_base_prompt_replaces_global_in_system_prompt(self, mock_render, mock_resolve):
        """The full system prompt should contain workspace base, not global base."""
        from app.services.sessions import _effective_system_prompt

        mock_render.return_value = "You are a helpful global assistant."
        mock_resolve.return_value = "You are a workspace-specific assistant."

        bot = SimpleNamespace(
            id="coder", name="Coder",
            system_prompt="Do coding tasks.",
            base_prompt=True, skills=None,
            memory=SimpleNamespace(enabled=False, prompt=None),
            knowledge=SimpleNamespace(enabled=False),
            delegate_bots=[], shared_workspace_id="ws-123",
        )

        result = _effective_system_prompt(bot, workspace_base_prompt_enabled=True)

        # Workspace prompt should be present, global should not
        assert "workspace-specific assistant" in result
        assert "global assistant" not in result
        # Bot system_prompt should still be there
        assert "coding tasks" in result

    @patch("app.agent.base_prompt.resolve_workspace_base_prompt")
    @patch("app.agent.base_prompt.render_base_prompt")
    def test_workspace_base_prompt_disabled_keeps_global(self, mock_render, mock_resolve):
        """When disabled, global base prompt should be used, not workspace."""
        from app.services.sessions import _effective_system_prompt

        mock_render.return_value = "You are a helpful global assistant."
        mock_resolve.return_value = "You are a workspace-specific assistant."

        bot = SimpleNamespace(
            id="coder", name="Coder",
            system_prompt="Do coding tasks.",
            base_prompt=True, skills=None,
            memory=SimpleNamespace(enabled=False, prompt=None),
            knowledge=SimpleNamespace(enabled=False),
            delegate_bots=[], shared_workspace_id="ws-123",
        )

        result = _effective_system_prompt(bot, workspace_base_prompt_enabled=False)

        assert "global assistant" in result
        assert "workspace-specific assistant" not in result

    @patch("app.agent.base_prompt.resolve_workspace_base_prompt")
    @patch("app.agent.base_prompt.render_base_prompt")
    def test_workspace_base_prompt_none_falls_back_to_global(self, mock_render, mock_resolve):
        """When workspace prompt file doesn't exist (returns None), global is used."""
        from app.services.sessions import _effective_system_prompt

        mock_render.return_value = "Global base."
        mock_resolve.return_value = None

        bot = SimpleNamespace(
            id="coder", name="Coder",
            system_prompt="Sys prompt.",
            base_prompt=True, skills=None,
            memory=SimpleNamespace(enabled=False, prompt=None),
            knowledge=SimpleNamespace(enabled=False),
            delegate_bots=[], shared_workspace_id="ws-123",
        )

        result = _effective_system_prompt(bot, workspace_base_prompt_enabled=True)
        assert "Global base." in result
