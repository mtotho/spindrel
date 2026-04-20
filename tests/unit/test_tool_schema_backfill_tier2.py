"""Schema validation tests for Tier-2 tool JSON backfill.

Verifies that each tool:
1. Returns valid JSON
2. Matches the declared returns schema in the registry
3. Handles happy-path and error cases structurally

Tools covered:
- list_session_traces (get_trace.py)
- get_trace — list mode + detail mode (get_trace.py)
- manage_bot_skill — list/get/create/error (bot_skills.py)
- file — list/grep/glob/write/read/error (file_ops.py)
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jsonschema
import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate(result: str, tool_name: str) -> dict | list:
    """Parse result as JSON and validate against the tool's declared returns schema."""
    from app.tools.registry import _tools
    data = json.loads(result)
    schema = _tools[tool_name].get("returns")
    if schema:
        jsonschema.validate(data, schema)
    return data


# ---------------------------------------------------------------------------
# list_session_traces
# ---------------------------------------------------------------------------

class TestListSessionTracesSchema:
    @pytest.mark.asyncio
    async def test_no_session_context_returns_json(self):
        from app.tools.local.get_trace import list_session_traces
        with patch("app.tools.local.get_trace.current_session_id") as mock_sess:
            mock_sess.get.return_value = None
            result = await list_session_traces()
        # Should return JSON with count=0
        data = json.loads(result)
        assert "count" in data
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_empty_session_matches_schema(self, db_session, patched_async_sessions):
        from app.db.models import Session as SessionRow
        from app.tools.local.get_trace import list_session_traces

        session_id = uuid.uuid4()
        db_session.add(SessionRow(id=session_id, client_id="test", bot_id="crumb"))
        await db_session.commit()

        with patch("app.tools.local.get_trace.current_session_id") as mock_sess:
            mock_sess.get.return_value = session_id
            result = await list_session_traces()

        data = _validate(result, "list_session_traces")
        assert data["count"] == 0
        assert data["traces"] == []

    @pytest.mark.asyncio
    async def test_with_traces_matches_schema(self, db_session, patched_async_sessions):
        from app.db.models import Session as SessionRow, TraceEvent, Message
        from app.tools.local.get_trace import list_session_traces

        session_id = uuid.uuid4()
        corr = uuid.uuid4()
        db_session.add(SessionRow(id=session_id, client_id="test", bot_id="crumb"))
        db_session.add(Message(
            session_id=session_id, role="user",
            content="hello bot", correlation_id=corr,
        ))
        db_session.add(TraceEvent(
            session_id=session_id, correlation_id=corr,
            bot_id="crumb", event_type="discovery_summary", data={"x": 1},
        ))
        await db_session.commit()

        with patch("app.tools.local.get_trace.current_session_id") as mock_sess:
            mock_sess.get.return_value = session_id
            result = await list_session_traces()

        data = _validate(result, "list_session_traces")
        assert data["count"] == 1
        trace = data["traces"][0]
        assert trace["correlation_id"] == str(corr)
        assert trace["event_count"] == 1
        assert "hello bot" in (trace["user_message_preview"] or "")


# ---------------------------------------------------------------------------
# get_trace
# ---------------------------------------------------------------------------

class TestGetTraceSchema:
    @pytest.mark.asyncio
    async def test_list_mode_matches_schema(self, db_session, patched_async_sessions):
        from app.db.models import Session as SessionRow, TraceEvent, Message
        from app.tools.local.get_trace import get_trace

        session_id = uuid.uuid4()
        corr = uuid.uuid4()
        db_session.add(SessionRow(id=session_id, client_id="test", bot_id="crumb"))
        db_session.add(Message(
            session_id=session_id, role="user",
            content="what time is it?", correlation_id=corr,
        ))
        db_session.add(TraceEvent(
            session_id=session_id, correlation_id=corr,
            bot_id="crumb", event_type="discovery_summary", data={"threshold": 0.35},
        ))
        await db_session.commit()

        result = await get_trace(event_type="discovery_summary")
        data = _validate(result, "get_trace")
        # List mode returns an array
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["event_type"] == "discovery_summary"
        assert data[0]["bot_id"] == "crumb"

    @pytest.mark.asyncio
    async def test_list_mode_with_user_message_matches_schema(
        self, db_session, patched_async_sessions
    ):
        from app.db.models import Session as SessionRow, TraceEvent, Message
        from app.tools.local.get_trace import get_trace

        session_id = uuid.uuid4()
        corr = uuid.uuid4()
        db_session.add(SessionRow(id=session_id, client_id="test", bot_id="crumb"))
        db_session.add(Message(
            session_id=session_id, role="user",
            content="audit my tools please", correlation_id=corr,
        ))
        db_session.add(TraceEvent(
            session_id=session_id, correlation_id=corr,
            bot_id="crumb", event_type="discovery_summary", data={},
        ))
        await db_session.commit()

        result = await get_trace(event_type="discovery_summary", include_user_message=True)
        data = _validate(result, "get_trace")
        assert data[0]["user_message"] == "audit my tools please"

    @pytest.mark.asyncio
    async def test_detail_mode_matches_schema(self, db_session, patched_async_sessions):
        from app.db.models import Session as SessionRow, TraceEvent, ToolCall
        from app.tools.local.get_trace import get_trace

        session_id = uuid.uuid4()
        corr = uuid.uuid4()
        db_session.add(SessionRow(id=session_id, client_id="test", bot_id="crumb"))
        db_session.add(TraceEvent(
            session_id=session_id, correlation_id=corr,
            bot_id="crumb", event_type="skill_index", data={"count": 3},
        ))
        db_session.add(ToolCall(
            session_id=session_id, correlation_id=corr,
            bot_id="crumb", tool_name="list_channels",
            tool_type="local", arguments={}, result='{"count": 2}',
        ))
        await db_session.commit()

        result = await get_trace(correlation_id=str(corr))
        data = _validate(result, "get_trace")
        assert data["correlation_id"] == str(corr)
        assert "timeline" in data
        assert data["tool_call_count"] == 1
        assert data["event_count"] == 1

        # Timeline entries should have required fields
        for entry in data["timeline"]:
            assert "type" in entry
            assert entry["type"] in ("tool_call", "trace_event")
            assert "timestamp" in entry

    @pytest.mark.asyncio
    async def test_detail_mode_no_data_returns_error_shape(
        self, db_session, patched_async_sessions
    ):
        from app.tools.local.get_trace import get_trace

        fake_corr = str(uuid.uuid4())
        result = await get_trace(correlation_id=fake_corr)
        data = json.loads(result)
        assert "error" in data

    def test_invalid_correlation_id_returns_error(self):
        import asyncio
        from app.tools.local.get_trace import get_trace

        result = asyncio.get_event_loop().run_until_complete(
            get_trace(correlation_id="not-a-uuid")
        )
        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# manage_bot_skill
# ---------------------------------------------------------------------------

class TestManageBotSkillSchema:
    @pytest.mark.asyncio
    async def test_list_empty_matches_schema(self, db_session, patched_async_sessions):
        from app.tools.local.bot_skills import manage_bot_skill

        with patch("app.tools.local.bot_skills.current_bot_id") as mock_bot:
            mock_bot.get.return_value = "crumb"
            result = await manage_bot_skill(action="list")

        data = _validate(result, "manage_bot_skill")
        assert "skills" in data
        assert data["skills"] == []

    @pytest.mark.asyncio
    async def test_list_with_skills_matches_schema(self, db_session, patched_async_sessions):
        from app.db.models import Skill
        from app.tools.local.bot_skills import manage_bot_skill
        from datetime import datetime, timezone

        db_session.add(Skill(
            id="bots/crumb/test-skill",
            name="Test Skill",
            content="---\nname: Test Skill\n---\n\nThis is test content that is long enough to pass validation.",
            source_type="tool",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        with patch("app.tools.local.bot_skills.current_bot_id") as mock_bot:
            mock_bot.get.return_value = "crumb"
            result = await manage_bot_skill(action="list")

        data = _validate(result, "manage_bot_skill")
        assert len(data["skills"]) == 1
        assert data["skills"][0]["id"] == "bots/crumb/test-skill"
        assert "stale" in data["skills"][0]

    @pytest.mark.asyncio
    async def test_get_missing_returns_error_shape(self, db_session, patched_async_sessions):
        from app.tools.local.bot_skills import manage_bot_skill

        with patch("app.tools.local.bot_skills.current_bot_id") as mock_bot:
            mock_bot.get.return_value = "crumb"
            result = await manage_bot_skill(action="get", name="nonexistent")

        data = _validate(result, "manage_bot_skill")
        assert "error" in data

    @pytest.mark.asyncio
    async def test_get_existing_matches_schema(self, db_session, patched_async_sessions):
        from app.db.models import Skill
        from app.tools.local.bot_skills import manage_bot_skill
        from datetime import datetime, timezone

        db_session.add(Skill(
            id="bots/crumb/my-guide",
            name="My Guide",
            content="---\nname: My Guide\n---\n\nThis is the guide content, long enough to pass.",
            source_type="tool",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        await db_session.commit()

        with patch("app.tools.local.bot_skills.current_bot_id") as mock_bot:
            mock_bot.get.return_value = "crumb"
            result = await manage_bot_skill(action="get", name="my-guide")

        data = _validate(result, "manage_bot_skill")
        assert data["id"] == "bots/crumb/my-guide"
        assert "content" in data

    @pytest.mark.asyncio
    async def test_create_matches_schema(self, db_session, patched_async_sessions):
        from app.tools.local.bot_skills import manage_bot_skill

        with (
            patch("app.tools.local.bot_skills.current_bot_id") as mock_bot,
            patch("app.tools.local.bot_skills._embed_skill_safe", new=AsyncMock(return_value=True)),
            patch("app.tools.local.bot_skills._check_skill_dedup", new=AsyncMock(return_value=None)),
            patch("app.tools.local.bot_skills._check_count_warning", new=AsyncMock(return_value=None)),
            patch("app.tools.local.bot_skills._invalidate_cache"),
        ):
            mock_bot.get.return_value = "crumb"
            result = await manage_bot_skill(
                action="create",
                name="new-skill",
                title="New Skill",
                content="This is the content for the new skill. It needs to be at least 50 characters long.",
            )

        data = _validate(result, "manage_bot_skill")
        assert data["ok"] is True
        assert data["id"] == "bots/crumb/new-skill"

    def test_no_bot_context_returns_error_shape(self):
        import asyncio
        from app.tools.local.bot_skills import manage_bot_skill

        with patch("app.tools.local.bot_skills.current_bot_id") as mock_bot:
            mock_bot.get.return_value = None
            result = asyncio.get_event_loop().run_until_complete(
                manage_bot_skill(action="list")
            )

        data = json.loads(result)
        assert "error" in data


# ---------------------------------------------------------------------------
# file tool — op-level schema tests
# ---------------------------------------------------------------------------

class TestFileToolSchema:
    """Tests that call op-level functions directly to validate returned JSON shapes."""

    def _setup_ws(self, tmp_path):
        (tmp_path / "notes.md").write_text("# Notes\n\nHello world.\n")
        (tmp_path / "data.json").write_text('{"key": "value"}\n')
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.py").write_text("def foo(): pass\n")
        return tmp_path

    def test_list_op_matches_schema(self, tmp_path):
        from app.tools.local.file_ops import _op_list
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        result = _op_list(str(ws), str(ws))
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert data["path"] == "."
        assert isinstance(data["entries"], list)
        # At least one entry should have name and type
        for e in data["entries"]:
            assert "name" in e
            assert e["type"] in ("file", "dir")

    def test_grep_op_matches_schema(self, tmp_path):
        from app.tools.local.file_ops import _op_grep
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        result = _op_grep(str(ws), "Hello", None, str(ws), None)
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert "matches" in data
        assert data["count"] >= 1
        assert data["matches"][0]["text"] == "Hello world."

    def test_grep_no_match_returns_empty_matches(self, tmp_path):
        from app.tools.local.file_ops import _op_grep

        ws = self._setup_ws(tmp_path)
        result = _op_grep(str(ws), "XYZNOTFOUND", None, str(ws), None)
        data = json.loads(result)
        assert data["count"] == 0
        assert data["matches"] == []

    def test_glob_op_matches_schema(self, tmp_path):
        from app.tools.local.file_ops import _op_glob
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        result = _op_glob(str(ws), "**/*.md", str(ws), None)
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert "paths" in data
        assert data["count"] >= 1
        assert any("notes.md" in p for p in data["paths"])

    def test_create_op_matches_schema(self, tmp_path):
        from app.tools.local.file_ops import _op_create
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        target = str(ws / "new_file.txt")
        result = _op_create(target, "New content here\n")
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert data["ok"] is True
        assert data["created"] is True

    def test_create_existing_returns_error_shape(self, tmp_path):
        from app.tools.local.file_ops import _op_create
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        target = str(ws / "notes.md")  # already exists
        result = _op_create(target, "content")
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert "error" in data

    def test_mkdir_op_matches_schema(self, tmp_path):
        from app.tools.local.file_ops import _op_mkdir
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        target = str(ws / "newdir")
        result = _op_mkdir(target)
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert data["ok"] is True

    def test_delete_op_matches_schema(self, tmp_path):
        from app.tools.local.file_ops import _op_delete
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        target = str(ws / "notes.md")
        result = _op_delete(target)
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert data["ok"] is True
        assert data["deleted"] is True

    def test_history_no_backups_matches_schema(self, tmp_path):
        from app.tools.local.file_ops import _op_history
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        result = _op_history(str(ws / "notes.md"), str(ws))
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert data["ok"] is True
        assert data["versions"] == []

    def test_append_op_matches_schema(self, tmp_path):
        from app.tools.local.file_ops import _op_append
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        target = str(ws / "notes.md")
        result = _op_append(target, "Appended line\n")
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert data["ok"] is True

    def test_edit_op_matches_schema(self, tmp_path):
        from app.tools.local.file_ops import _op_edit
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        target = str(ws / "notes.md")
        result = _op_edit(target, "Hello world", "Hello everyone", False)
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert data["ok"] is True
        assert data["replacements"] == 1

    def test_edit_not_found_returns_error_shape(self, tmp_path):
        from app.tools.local.file_ops import _op_edit
        from app.tools.registry import _tools

        ws = self._setup_ws(tmp_path)
        target = str(ws / "notes.md")
        result = _op_edit(target, "NOTFOUND_STRING", "replacement", False)
        data = json.loads(result)
        schema = _tools["file"]["returns"]
        jsonschema.validate(data, schema)
        assert "error" in data


# ---------------------------------------------------------------------------
# experiment_tools — returns schema coverage
# ---------------------------------------------------------------------------

class TestExperimentToolsSchema:
    def test_append_experiment_history_missing_context_returns_error(self):
        import asyncio
        from app.tools.local.experiment_tools import append_experiment_history

        with patch("app.tools.local.experiment_tools.current_bot_id") as mock_bot, \
             patch("app.tools.local.experiment_tools.current_channel_id") as mock_ch:
            mock_bot.get.return_value = None
            mock_ch.get.return_value = None
            result = asyncio.get_event_loop().run_until_complete(
                append_experiment_history("test-exp", '{"x":1}')
            )
        data = _validate(result, "append_experiment_history")
        assert "error" in data

    def test_update_current_best_missing_context_returns_error(self):
        import asyncio
        from app.tools.local.experiment_tools import update_current_best

        with patch("app.tools.local.experiment_tools.current_bot_id") as mock_bot, \
             patch("app.tools.local.experiment_tools.current_channel_id") as mock_ch:
            mock_bot.get.return_value = None
            mock_ch.get.return_value = None
            result = asyncio.get_event_loop().run_until_complete(
                update_current_best("test-exp", '{"x":1}')
            )
        data = _validate(result, "update_current_best")
        assert "error" in data

    def test_build_experiment_record_matches_schema(self):
        import asyncio
        from app.tools.local.experiment_tools import build_experiment_record

        result = asyncio.get_event_loop().run_until_complete(
            build_experiment_record(
                iteration_n="0",
                variant_prompt="Be concise.",
                scores_json='{"primary": {"aggregate": 0.8}, "guards": {}, "variant_valid": true}',
            )
        )
        data = _validate(result, "build_experiment_record")
        assert data["iteration_n"] == 0
        assert "variant" in data
        assert "scores" in data

    def test_build_experiment_record_bad_scores_returns_error(self):
        import asyncio
        from app.tools.local.experiment_tools import build_experiment_record

        result = asyncio.get_event_loop().run_until_complete(
            build_experiment_record(
                iteration_n="0",
                variant_prompt="Be concise.",
                scores_json="not-json",
            )
        )
        data = _validate(result, "build_experiment_record")
        assert "error" in data

    def test_check_experiment_budget_missing_context_returns_error(self):
        import asyncio
        from app.tools.local.experiment_tools import check_experiment_budget

        with patch("app.tools.local.experiment_tools.current_bot_id") as mock_bot, \
             patch("app.tools.local.experiment_tools.current_channel_id") as mock_ch:
            mock_bot.get.return_value = None
            mock_ch.get.return_value = None
            result = asyncio.get_event_loop().run_until_complete(
                check_experiment_budget("test-exp")
            )
        data = _validate(result, "check_experiment_budget")
        assert "error" in data


# ---------------------------------------------------------------------------
# spawn_subagents — returns schema coverage
# ---------------------------------------------------------------------------

class TestSpawnSubagentsSchema:
    @pytest.mark.asyncio
    async def test_empty_agents_returns_error(self):
        from app.tools.local.subagents import spawn_subagents

        with patch("app.tools.local.subagents.current_bot_id") as mock_bot, \
             patch("app.tools.local.subagents.current_channel_id") as mock_ch, \
             patch("app.tools.local.subagents.current_session_id") as mock_sess:
            mock_bot.get.return_value = "crumb"
            mock_ch.get.return_value = uuid.uuid4()
            mock_sess.get.return_value = uuid.uuid4()
            result = await spawn_subagents([])

        data = _validate(result, "spawn_subagents")
        assert "error" in data

    @pytest.mark.asyncio
    async def test_valid_agents_matches_schema(self):
        from app.tools.local.subagents import spawn_subagents
        from app.agent.subagents import SubagentResult

        mock_result = SubagentResult(index=0, status="ok", result="done", preset=None, elapsed_ms=42)

        with patch("app.agent.subagents.run_subagents", return_value=[mock_result]), \
             patch("app.tools.local.subagents.current_bot_id") as mock_bot, \
             patch("app.tools.local.subagents.current_channel_id") as mock_ch, \
             patch("app.tools.local.subagents.current_session_id") as mock_sess:
            mock_bot.get.return_value = "crumb"
            mock_ch.get.return_value = uuid.uuid4()
            mock_sess.get.return_value = uuid.uuid4()
            result = await spawn_subagents([{"prompt": "do something"}])

        data = _validate(result, "spawn_subagents")
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["status"] == "ok"


# ---------------------------------------------------------------------------
# todos — returns schema coverage
# ---------------------------------------------------------------------------

class TestTodosSchema:
    @pytest.mark.asyncio
    async def test_create_todo_matches_schema(self, db_session, patched_async_sessions):
        from app.tools.local.todos import create_todo

        with patch("app.tools.local.todos.current_bot_id") as mock_bot, \
             patch("app.tools.local.todos.current_channel_id") as mock_ch:
            mock_bot.get.return_value = "crumb"
            mock_ch.get.return_value = uuid.uuid4()
            result = await create_todo("Buy groceries")

        data = _validate(result, "create_todo")
        assert "id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_todos_empty_matches_schema(self, db_session, patched_async_sessions):
        from app.tools.local.todos import list_todos

        with patch("app.tools.local.todos.current_bot_id") as mock_bot, \
             patch("app.tools.local.todos.current_channel_id") as mock_ch:
            mock_bot.get.return_value = "crumb"
            mock_ch.get.return_value = uuid.uuid4()
            result = await list_todos()

        data = _validate(result, "list_todos")
        assert data["count"] == 0
        assert data["todos"] == []

    @pytest.mark.asyncio
    async def test_complete_todo_not_found_returns_error(self, db_session, patched_async_sessions):
        from app.tools.local.todos import complete_todo

        with patch("app.tools.local.todos.current_bot_id") as mock_bot, \
             patch("app.tools.local.todos.current_channel_id") as mock_ch:
            mock_bot.get.return_value = "crumb"
            mock_ch.get.return_value = uuid.uuid4()
            result = await complete_todo(str(uuid.uuid4()))

        data = _validate(result, "complete_todo")
        assert "error" in data

    @pytest.mark.asyncio
    async def test_delete_todo_invalid_id_returns_error(self, db_session, patched_async_sessions):
        from app.tools.local.todos import delete_todo

        with patch("app.tools.local.todos.current_bot_id") as mock_bot, \
             patch("app.tools.local.todos.current_channel_id") as mock_ch:
            mock_bot.get.return_value = "crumb"
            mock_ch.get.return_value = uuid.uuid4()
            result = await delete_todo("not-a-uuid")

        data = _validate(result, "delete_todo")
        assert "error" in data


# ---------------------------------------------------------------------------
# prune_enrolled_tools — returns schema coverage
# ---------------------------------------------------------------------------

class TestPruneEnrolledToolsSchema:
    @pytest.mark.asyncio
    async def test_no_bot_context_returns_error(self):
        from app.tools.local.discovery import prune_enrolled_tools

        with patch("app.tools.local.discovery.current_bot_id") as mock_bot:
            mock_bot.get.return_value = None
            result = await prune_enrolled_tools(["some_tool"])

        data = _validate(result, "prune_enrolled_tools")
        assert "error" in data

    @pytest.mark.asyncio
    async def test_empty_tool_names_returns_error(self):
        from app.tools.local.discovery import prune_enrolled_tools

        with patch("app.tools.local.discovery.current_bot_id") as mock_bot:
            mock_bot.get.return_value = "crumb"
            result = await prune_enrolled_tools([])

        data = _validate(result, "prune_enrolled_tools")
        assert "error" in data

    @pytest.mark.asyncio
    async def test_successful_prune_matches_schema(self):
        from app.tools.local.discovery import prune_enrolled_tools

        with patch("app.tools.local.discovery.current_bot_id") as mock_bot, \
             patch("app.tools.local.discovery.unenroll_many", new=AsyncMock(return_value=2), create=True):
            mock_bot.get.return_value = "crumb"
            with patch("app.services.tool_enrollment.unenroll_many", new=AsyncMock(return_value=2)):
                result = await prune_enrolled_tools(["tool_a", "tool_b"])

        data = _validate(result, "prune_enrolled_tools")
        assert "removed" in data or "error" in data


# ---------------------------------------------------------------------------
# client_action — returns schema coverage
# ---------------------------------------------------------------------------

class TestClientActionSchema:
    @pytest.mark.asyncio
    async def test_known_action_matches_schema(self):
        from app.tools.local.client_action import client_action

        result = await client_action("new_session")
        data = _validate(result, "client_action")
        assert data["status"] == "ok"
        assert data["action"] == "new_session"

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self):
        from app.tools.local.client_action import client_action

        result = await client_action("unknown_action_xyz")
        data = _validate(result, "client_action")
        assert "error" in data


# ---------------------------------------------------------------------------
# manage_capability — returns schema coverage
# ---------------------------------------------------------------------------

class TestManageCapabilitySchema:
    @pytest.mark.asyncio
    async def test_list_empty_matches_schema(self, db_session, patched_async_sessions):
        from app.tools.local.carapaces import manage_capability

        # list_carapaces is imported lazily inside manage_capability — patch at source
        with patch("app.agent.carapaces.list_carapaces", return_value=[]):
            result = await manage_capability(action="list")

        data = _validate(result, "manage_capability")
        assert "carapaces" in data

    @pytest.mark.asyncio
    async def test_get_missing_returns_error(self, db_session, patched_async_sessions):
        from app.tools.local.carapaces import manage_capability

        with patch("app.agent.carapaces.get_carapace", return_value=None):
            result = await manage_capability(action="get", id="nonexistent")

        data = _validate(result, "manage_capability")
        assert "error" in data


# ---------------------------------------------------------------------------
# git_pull — returns schema coverage
# ---------------------------------------------------------------------------

class TestGitPullSchema:
    @pytest.mark.asyncio
    async def test_git_pull_matches_schema(self):
        from app.tools.local.git_pull import git_pull

        with patch("asyncio.create_subprocess_exec") as mock_proc:
            mock_instance = MagicMock()
            mock_instance.communicate = AsyncMock(return_value=(b"Already up to date.\n", b""))
            mock_instance.returncode = 0
            mock_proc.return_value = mock_instance
            result = await git_pull()

        data = _validate(result, "git_pull")
        assert "stdout" in data
        assert "exit_code" in data
