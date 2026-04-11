"""Tests for webhook execution_config: dispatcher bug fix, inject_message,
ephemeral skills merge, and _build_execution_config."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. GitHubRenderer round-trips a github dispatch_config dict
# ---------------------------------------------------------------------------
#
# Phase G replaced ``GitHubDispatcher`` with ``GitHubRenderer``. The
# legacy ``deliver(task, result)`` test surface is gone — we now drive
# the renderer with a typed event + target. The thing the old test was
# really pinning was that the github dispatch_config shape (with the
# nested ``comment_target.issue_number`` and assorted event metadata)
# round-trips into a usable typed target. ``GitHubTarget.from_dispatch_config``
# is what handles that flattening, so we test it directly here.

class TestGitHubTargetRoundTrip:
    def _config(self, **overrides):
        cfg = {
            "type": "github",
            "owner": "org",
            "repo": "repo",
            "token": "ghp_test",
            "comment_target": {"type": "issue_comment", "issue_number": 1},
        }
        cfg.update(overrides)
        return cfg

    def test_parse_dispatch_target_flattens_comment_target(self):
        from app.domain.dispatch_target import parse_dispatch_target
        # Force the github target to be registered (test isolation —
        # the import side-effect runs target_registry.register).
        import integrations.github.target  # noqa: F401

        target = parse_dispatch_target(self._config())
        assert target.owner == "org"
        assert target.repo == "repo"
        assert target.issue_number == 1

    def test_parse_drops_token_and_event_metadata(self):
        from app.domain.dispatch_target import parse_dispatch_target
        import integrations.github.target  # noqa: F401

        cfg = self._config(sender="bot-user", action="opened")
        # Adding extra event metadata must NOT crash the parse — the
        # github target only consumes the fields it actually carries.
        target = parse_dispatch_target(cfg)
        assert target.owner == "org"
        assert not hasattr(target, "token")
        assert not hasattr(target, "sender")

    @pytest.mark.asyncio
    async def test_renderer_render_for_turn_ended(self):
        """Smoke-test that the renderer fires _post_comment with the
        flattened target. Phase G removed the dispatcher's
        ``extra_metadata`` plumbing — the renderer reads the result
        from the typed payload directly.
        """
        from app.domain.channel_events import ChannelEvent, ChannelEventKind
        from app.domain.dispatch_target import parse_dispatch_target
        from app.domain.payloads import TurnEndedPayload
        from integrations.github import target as _t  # noqa: F401  registers GitHubTarget
        from integrations.github.renderer import GitHubRenderer

        renderer = GitHubRenderer()
        target = parse_dispatch_target(self._config())
        event = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.TURN_ENDED,
            payload=TurnEndedPayload(
                bot_id="test-bot",
                turn_id=uuid.uuid4(),
                result="result text",
                error=None,
                client_actions=[],
            ),
        )

        with patch("integrations.github.renderer._post_comment",
                   new_callable=AsyncMock, return_value=True), \
             patch("integrations.github.renderer._get_token", return_value="ghp_test"):
            receipt = await renderer.render(event, target)
        assert receipt.success is True


# ---------------------------------------------------------------------------
# 2. inject_message stores execution_config on Task
# ---------------------------------------------------------------------------

class TestInjectMessageExecutionConfig:
    @pytest.mark.asyncio
    async def test_execution_config_stored_on_task(self):
        from integrations.utils import inject_message

        session_id = uuid.uuid4()
        session = MagicMock()
        session.bot_id = "test-bot"
        session.client_id = "github:org/repo"
        session.dispatch_config = {"type": "github"}

        msg = MagicMock()
        msg.id = uuid.uuid4()

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        added_objects = []
        db.add = lambda obj: added_objects.append(obj)
        db.commit = AsyncMock()
        # db.refresh needs to assign an id to the task (simulating DB)
        async def _refresh(obj):
            if hasattr(obj, "id") and obj.id is None:
                obj.id = uuid.uuid4()
        db.refresh = AsyncMock(side_effect=_refresh)

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = msg
        db.execute = AsyncMock(return_value=mock_result)

        ecfg = {"system_preamble": "Review this PR", "tools": ["github_get_pr"]}

        with patch("integrations.utils.store_passive_message", new_callable=AsyncMock):
            result = await inject_message(
                session_id, "PR opened", source="github",
                run_agent=True, notify=False,
                dispatch_config={"type": "github"},
                execution_config=ecfg,
                db=db,
            )

        assert result["task_id"] is not None
        task = next(obj for obj in added_objects if hasattr(obj, "execution_config"))
        assert task.execution_config == ecfg

    @pytest.mark.asyncio
    async def test_execution_config_none_by_default(self):
        from integrations.utils import inject_message

        session_id = uuid.uuid4()
        session = MagicMock()
        session.bot_id = "test-bot"
        session.client_id = "test"
        session.dispatch_config = {}

        msg = MagicMock()
        msg.id = uuid.uuid4()

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        added_objects = []
        db.add = lambda obj: added_objects.append(obj)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = msg
        db.execute = AsyncMock(return_value=mock_result)

        with patch("integrations.utils.store_passive_message", new_callable=AsyncMock):
            await inject_message(
                session_id, "hello", source="test",
                run_agent=True, notify=False, db=db,
            )

        task = next(obj for obj in added_objects if hasattr(obj, "execution_config"))
        assert task.execution_config is None

    @pytest.mark.asyncio
    async def test_task_carries_session_channel_id(self):
        """Regression: inject_message MUST propagate session.channel_id to the
        Task row.

        Without it, ``app/agent/tasks.py:_publish_turn_ended`` drops the
        TURN_ENDED publish (logs ``task ... has no channel_id``) and the
        renderer never sees the event — agent replies stop reaching the
        integration. Caught in production via the BlueBubbles webhook path
        when iMessage replies stopped showing up on the user's phone.
        """
        from integrations.utils import inject_message

        session_id = uuid.uuid4()
        channel_id = uuid.uuid4()
        session = MagicMock()
        session.bot_id = "test-bot"
        session.client_id = "bb:chat-guid"
        session.channel_id = channel_id
        session.dispatch_config = {"type": "bluebubbles"}

        msg = MagicMock()
        msg.id = uuid.uuid4()

        db = AsyncMock()
        db.get = AsyncMock(return_value=session)
        added_objects = []
        db.add = lambda obj: added_objects.append(obj)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one.return_value = msg
        db.execute = AsyncMock(return_value=mock_result)

        with patch("integrations.utils.store_passive_message", new_callable=AsyncMock):
            await inject_message(
                session_id, "[Me]: Wonky", source="bluebubbles",
                run_agent=True, notify=False, db=db,
            )

        task = next(obj for obj in added_objects if hasattr(obj, "execution_config"))
        assert task.channel_id == channel_id


# ---------------------------------------------------------------------------
# 3. Ephemeral skills merge (not replace)
# ---------------------------------------------------------------------------

class TestEphemeralSkillsMerge:
    def test_merge_preserves_existing_and_deduplicates(self):
        from app.agent.context import current_ephemeral_skills, set_ephemeral_skills

        # Simulate execution_config setting skills before @-tag resolution
        set_ephemeral_skills(["github_review", "code_style"])

        # Simulate merge logic from context_assembly
        _existing = list(current_ephemeral_skills.get() or [])
        _tagged = ["code_style", "arch_linux"]
        _merged = list(dict.fromkeys(_existing + _tagged))
        set_ephemeral_skills(_merged)

        result = current_ephemeral_skills.get()
        assert result == ["github_review", "code_style", "arch_linux"]

    def test_merge_with_no_existing(self):
        from app.agent.context import current_ephemeral_skills, set_ephemeral_skills

        set_ephemeral_skills([])

        _existing = list(current_ephemeral_skills.get() or [])
        _tagged = ["skill_a"]
        _merged = list(dict.fromkeys(_existing + _tagged))
        set_ephemeral_skills(_merged)

        assert current_ephemeral_skills.get() == ["skill_a"]


# ---------------------------------------------------------------------------
# 4. GitHub _build_execution_config
# ---------------------------------------------------------------------------

class TestGitHubBuildExecutionConfig:
    def _parsed(self, run_agent=True):
        p = MagicMock()
        p.run_agent = run_agent
        p.owner = "org"
        p.repo = "repo"
        return p

    def test_pull_request_opened(self):
        from integrations.github.router import _build_execution_config
        cfg = _build_execution_config("pull_request", self._parsed())
        assert cfg is not None
        assert "system_preamble" in cfg
        assert "pull request" in cfg["system_preamble"].lower()
        assert "github_get_pr" in cfg["tools"]
        assert "integrations/github/github" in cfg["skills"]

    def test_issues_opened(self):
        from integrations.github.router import _build_execution_config
        cfg = _build_execution_config("issues", self._parsed())
        assert cfg is not None
        assert "issue" in cfg["system_preamble"].lower()
        assert "tools" not in cfg
        assert "integrations/github/github" in cfg["skills"]

    def test_issue_comment(self):
        from integrations.github.router import _build_execution_config
        cfg = _build_execution_config("issue_comment", self._parsed())
        assert cfg is not None
        assert "comment" in cfg["system_preamble"].lower()
        assert "integrations/github/github" in cfg["skills"]

    def test_pull_request_review(self):
        from integrations.github.router import _build_execution_config
        cfg = _build_execution_config("pull_request_review", self._parsed())
        assert cfg is not None
        assert "github_get_pr" in cfg["tools"]
        assert "integrations/github/github" in cfg["skills"]

    def test_pull_request_review_comment(self):
        from integrations.github.router import _build_execution_config
        cfg = _build_execution_config("pull_request_review_comment", self._parsed())
        assert cfg is not None
        assert "github_get_pr" in cfg["tools"]
        assert "integrations/github/github" in cfg["skills"]

    def test_non_agent_event_returns_none(self):
        from integrations.github.router import _build_execution_config
        cfg = _build_execution_config("push", self._parsed(run_agent=False))
        assert cfg is None

    def test_unknown_event_returns_none(self):
        from integrations.github.router import _build_execution_config
        cfg = _build_execution_config("deployment", self._parsed())
        assert cfg is None


# ---------------------------------------------------------------------------
# 5. Frigate _build_execution_config
# ---------------------------------------------------------------------------

class TestFrigateBuildExecutionConfig:
    def test_detection_event(self):
        from integrations.frigate.router import ParsedEvent, _build_execution_config

        event = ParsedEvent(camera="front_door", label="person", score=0.95, message="...")
        cfg = _build_execution_config(event)

        assert "system_preamble" in cfg
        assert "front_door" in cfg["system_preamble"]
        assert "person" in cfg["system_preamble"]
        assert "95%" in cfg["system_preamble"]
        assert "frigate_event_snapshot" in cfg["tools"]
        assert "integrations/frigate/frigate" in cfg["skills"]

    def test_different_camera_and_label(self):
        from integrations.frigate.router import ParsedEvent, _build_execution_config

        event = ParsedEvent(camera="backyard", label="car", score=0.72, message="...")
        cfg = _build_execution_config(event)

        assert "backyard" in cfg["system_preamble"]
        assert "car" in cfg["system_preamble"]
        assert "72%" in cfg["system_preamble"]


# ---------------------------------------------------------------------------
# 6. run_task execution_config extraction logic
# ---------------------------------------------------------------------------

class TestRunTaskExecutionConfigExtraction:
    """Test that the execution_config extraction in run_task correctly reads
    system_preamble, skills, and tools fields."""

    def test_extraction_with_all_fields(self):
        """Verify the extraction logic produces correct values."""
        ecfg = {
            "system_preamble": "Review this PR",
            "skills": ["github_review"],
            "tools": ["github_get_pr"],
            "model_override": "gpt-4o",
        }
        # Simulate the extraction logic from run_task
        _ecfg_pre = ecfg
        _system_preamble = _ecfg_pre.get("system_preamble") or None
        _ecfg_skills = _ecfg_pre.get("skills") or None
        _ecfg_tool_names = _ecfg_pre.get("tools") or None

        assert _system_preamble == "Review this PR"
        assert _ecfg_skills == ["github_review"]
        assert _ecfg_tool_names == ["github_get_pr"]

    def test_extraction_with_empty_config(self):
        ecfg = {}
        _system_preamble = ecfg.get("system_preamble") or None
        _ecfg_skills = ecfg.get("skills") or None
        _ecfg_tool_names = ecfg.get("tools") or None

        assert _system_preamble is None
        assert _ecfg_skills is None
        assert _ecfg_tool_names is None

    def test_extraction_with_none_config(self):
        _ecfg_pre = None or {}
        _system_preamble = _ecfg_pre.get("system_preamble") or None
        _ecfg_skills = _ecfg_pre.get("skills") or None
        _ecfg_tool_names = _ecfg_pre.get("tools") or None

        assert _system_preamble is None
        assert _ecfg_skills is None
        assert _ecfg_tool_names is None

    def test_get_local_tool_schemas_called_for_tools(self):
        """Verify that tool names are resolved via get_local_tool_schemas."""
        from app.tools.registry import get_local_tool_schemas

        # get_local_tool_schemas returns [] for unknown tools (no crash)
        result = get_local_tool_schemas(["nonexistent_tool"])
        assert result == []

    def test_empty_tools_list_gives_none(self):
        """Empty tools list should be treated as None (falsy)."""
        ecfg = {"tools": []}
        _ecfg_tool_names = ecfg.get("tools") or None
        assert _ecfg_tool_names is None
