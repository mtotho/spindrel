"""Unit tests for workflow condition evaluator, prompt rendering, param validation,
chat message posting, and the workflow service (create_workflow)."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import Workflow
from app.services.workflows import create_workflow
from app.services import workflows as _workflows_mod

from app.services.workflow_executor import (
    evaluate_condition,
    render_prompt,
    validate_params,
    validate_secrets,
    _post_workflow_chat_message,
)


# ---------------------------------------------------------------------------
# evaluate_condition
# ---------------------------------------------------------------------------

class TestEvaluateCondition:
    """Tests for the pure condition evaluator."""

    def test_none_condition_returns_true(self):
        assert evaluate_condition(None, {}) is True

    def test_empty_dict_returns_true(self):
        assert evaluate_condition({}, {}) is True

    def test_step_status_match(self):
        ctx = {"steps": {"search": {"status": "done", "result": "found it"}}, "params": {}}
        assert evaluate_condition({"step": "search", "status": "done"}, ctx) is True

    def test_step_status_mismatch(self):
        ctx = {"steps": {"search": {"status": "failed"}}, "params": {}}
        assert evaluate_condition({"step": "search", "status": "done"}, ctx) is False

    def test_step_missing(self):
        ctx = {"steps": {}, "params": {}}
        assert evaluate_condition({"step": "search", "status": "done"}, ctx) is False

    def test_step_output_contains(self):
        ctx = {"steps": {"search": {"status": "done", "result": '{"found": false}'}}, "params": {}}
        assert evaluate_condition(
            {"step": "search", "status": "done", "output_contains": '"found": false'},
            ctx,
        ) is True

    def test_step_output_contains_case_insensitive(self):
        ctx = {"steps": {"search": {"status": "done", "result": "Found It"}}, "params": {}}
        assert evaluate_condition(
            {"step": "search", "status": "done", "output_contains": "found it"},
            ctx,
        ) is True

    def test_step_output_contains_missing(self):
        ctx = {"steps": {"search": {"status": "done", "result": "nothing here"}}, "params": {}}
        assert evaluate_condition(
            {"step": "search", "status": "done", "output_contains": "found"},
            ctx,
        ) is False

    def test_step_output_not_contains(self):
        ctx = {"steps": {"search": {"status": "done", "result": "success"}}, "params": {}}
        assert evaluate_condition(
            {"step": "search", "output_not_contains": "error"},
            ctx,
        ) is True

    def test_step_output_not_contains_fails(self):
        ctx = {"steps": {"search": {"status": "done", "result": "error occurred"}}, "params": {}}
        assert evaluate_condition(
            {"step": "search", "output_not_contains": "error"},
            ctx,
        ) is False

    def test_step_null_result_output_contains(self):
        """output_contains with None result should be False."""
        ctx = {"steps": {"search": {"status": "done", "result": None}}, "params": {}}
        assert evaluate_condition(
            {"step": "search", "status": "done", "output_contains": "found"},
            ctx,
        ) is False

    def test_param_exists(self):
        ctx = {"steps": {}, "params": {"dry_run": True}}
        assert evaluate_condition({"param": "dry_run"}, ctx) is True

    def test_param_missing(self):
        ctx = {"steps": {}, "params": {}}
        assert evaluate_condition({"param": "dry_run"}, ctx) is False

    def test_param_equals(self):
        ctx = {"steps": {}, "params": {"dry_run": True}}
        assert evaluate_condition({"param": "dry_run", "equals": True}, ctx) is True

    def test_param_equals_false(self):
        ctx = {"steps": {}, "params": {"dry_run": False}}
        assert evaluate_condition({"param": "dry_run", "equals": True}, ctx) is False

    def test_param_equals_string(self):
        ctx = {"steps": {}, "params": {"quality": "1080p"}}
        assert evaluate_condition({"param": "quality", "equals": "1080p"}, ctx) is True

    def test_all_compound(self):
        ctx = {
            "steps": {"a": {"status": "done"}, "b": {"status": "done"}},
            "params": {},
        }
        cond = {"all": [
            {"step": "a", "status": "done"},
            {"step": "b", "status": "done"},
        ]}
        assert evaluate_condition(cond, ctx) is True

    def test_all_compound_one_false(self):
        ctx = {
            "steps": {"a": {"status": "done"}, "b": {"status": "failed"}},
            "params": {},
        }
        cond = {"all": [
            {"step": "a", "status": "done"},
            {"step": "b", "status": "done"},
        ]}
        assert evaluate_condition(cond, ctx) is False

    def test_any_compound(self):
        ctx = {
            "steps": {"a": {"status": "failed"}, "b": {"status": "done"}},
            "params": {},
        }
        cond = {"any": [
            {"step": "a", "status": "done"},
            {"step": "b", "status": "done"},
        ]}
        assert evaluate_condition(cond, ctx) is True

    def test_any_compound_all_false(self):
        ctx = {
            "steps": {"a": {"status": "failed"}, "b": {"status": "failed"}},
            "params": {},
        }
        cond = {"any": [
            {"step": "a", "status": "done"},
            {"step": "b", "status": "done"},
        ]}
        assert evaluate_condition(cond, ctx) is False

    def test_not_compound(self):
        ctx = {"steps": {"a": {"status": "failed"}}, "params": {}}
        assert evaluate_condition({"not": {"step": "a", "status": "done"}}, ctx) is True

    def test_not_compound_negates_true(self):
        ctx = {"steps": {"a": {"status": "done"}}, "params": {}}
        assert evaluate_condition({"not": {"step": "a", "status": "done"}}, ctx) is False

    def test_nested_compound(self):
        """all + any + not nesting."""
        ctx = {
            "steps": {"a": {"status": "failed"}, "b": {"status": "done"}},
            "params": {"enabled": True},
        }
        cond = {
            "all": [
                {"any": [
                    {"step": "a", "status": "done"},
                    {"step": "b", "status": "done"},
                ]},
                {"not": {"param": "enabled", "equals": False}},
            ]
        }
        assert evaluate_condition(cond, ctx) is True

    def test_unknown_condition_returns_false(self):
        """Unrecognized condition shape returns False."""
        assert evaluate_condition({"unknown_key": "value"}, {}) is False


# ---------------------------------------------------------------------------
# render_prompt
# ---------------------------------------------------------------------------

class TestRenderPrompt:
    def test_simple_param_substitution(self):
        result = render_prompt(
            'Search for "{{series_name}}" at {{quality}}.',
            {"series_name": "Breaking Bad", "quality": "1080p"},
            [], [],
        )
        assert result == 'Search for "Breaking Bad" at 1080p.'

    def test_step_result_reference(self):
        steps = [{"id": "search"}, {"id": "report"}]
        step_states = [
            {"status": "done", "result": "Found 3 results"},
            {"status": "pending"},
        ]
        result = render_prompt(
            "Report on: {{steps.search.result}}",
            {},
            step_states,
            steps,
        )
        assert result == "Report on: Found 3 results"

    def test_step_status_reference(self):
        steps = [{"id": "search"}]
        step_states = [{"status": "done", "result": "ok"}]
        result = render_prompt(
            "Search status: {{steps.search.status}}",
            {},
            step_states,
            steps,
        )
        assert result == "Search status: done"

    def test_missing_param_left_as_is(self):
        result = render_prompt(
            "Hello {{name}}, status is {{unknown}}.",
            {"name": "Alice"},
            [], [],
        )
        assert result == "Hello Alice, status is {{unknown}}."

    def test_missing_step_reference_left_as_is(self):
        result = render_prompt(
            "Result: {{steps.missing.result}}",
            {},
            [], [],
        )
        assert result == "Result: {{steps.missing.result}}"

    def test_whitespace_in_template(self):
        result = render_prompt(
            "{{ name }}",
            {"name": "Bob"},
            [], [],
        )
        assert result == "Bob"


# ---------------------------------------------------------------------------
# validate_params
# ---------------------------------------------------------------------------

class TestValidateParams:
    def test_required_param_present(self):
        defs = {"name": {"type": "string", "required": True}}
        result = validate_params(defs, {"name": "test"})
        assert result == {"name": "test"}

    def test_required_param_missing_raises(self):
        defs = {"name": {"type": "string", "required": True}}
        with pytest.raises(ValueError, match="Required parameter 'name' is missing"):
            validate_params(defs, {})

    def test_default_applied(self):
        defs = {"quality": {"type": "string", "default": "1080p"}}
        result = validate_params(defs, {})
        assert result == {"quality": "1080p"}

    def test_default_overridden(self):
        defs = {"quality": {"type": "string", "default": "1080p"}}
        result = validate_params(defs, {"quality": "4K"})
        assert result == {"quality": "4K"}

    def test_type_coercion_number(self):
        defs = {"count": {"type": "number", "required": True}}
        result = validate_params(defs, {"count": "42"})
        assert result == {"count": 42.0}

    def test_type_coercion_boolean(self):
        defs = {"dry_run": {"type": "boolean", "required": True}}
        result = validate_params(defs, {"dry_run": "true"})
        assert result == {"dry_run": True}

    def test_invalid_number_raises(self):
        defs = {"count": {"type": "number", "required": True}}
        with pytest.raises(ValueError, match="must be a number"):
            validate_params(defs, {"count": "not-a-number"})

    def test_optional_param_omitted(self):
        defs = {"name": {"type": "string"}}
        result = validate_params(defs, {})
        assert result == {}


# ---------------------------------------------------------------------------
# validate_secrets
# ---------------------------------------------------------------------------

class TestValidateSecrets:
    def test_empty_secrets_passes(self):
        validate_secrets([])

    def test_missing_secrets_raises(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.workflow_executor.validate_secrets.__module__",
            "app.services.workflow_executor",
        )
        # Patch get_env_dict to return empty
        import app.services.workflow_executor as mod
        from unittest.mock import patch
        with patch("app.services.secret_values.get_env_dict", return_value={}):
            with pytest.raises(ValueError, match="Missing secrets"):
                validate_secrets(["MY_SECRET"])

    def test_available_secrets_passes(self):
        from unittest.mock import patch
        with patch("app.services.secret_values.get_env_dict", return_value={"MY_SECRET": "val"}):
            validate_secrets(["MY_SECRET"])


# ---------------------------------------------------------------------------
# _post_workflow_chat_message
# ---------------------------------------------------------------------------

class TestPostWorkflowChatMessage:
    """Tests for the workflow chat message posting helper."""

    @pytest.mark.asyncio
    async def test_no_op_when_no_channel_id(self):
        """Should silently return when run has no channel_id."""
        run = MagicMock()
        run.channel_id = None

        # Should not raise
        await _post_workflow_chat_message(run, "Test WF", "started", "Hello")

    @pytest.mark.asyncio
    async def test_no_op_when_no_active_session(self):
        """Should return when channel has no active_session_id."""
        run = MagicMock()
        run.channel_id = uuid.uuid4()
        run.bot_id = "test-bot"
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"

        channel = MagicMock()
        channel.active_session_id = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=channel)
        mock_db.add = MagicMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.agent.bots.get_bot", side_effect=Exception("no bot")),
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()
            await _post_workflow_chat_message(run, "Test WF", "started", "Hello")
            # Should not have added a message
            mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_posts_message_to_active_session(self):
        """Should create a Message record with correct metadata for non-step events."""
        run = MagicMock()
        run.channel_id = uuid.uuid4()
        run.bot_id = "test-bot"
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"

        session_id = uuid.uuid4()
        channel = MagicMock()
        channel.active_session_id = session_id

        bot = MagicMock()
        bot.display_name = "Test Bot"
        bot.name = "test-bot"

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=channel)
        mock_db.add = MagicMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.agent.bots.get_bot", return_value=bot),
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()
            # Use "started" event — always creates a new message
            await _post_workflow_chat_message(
                run, "My Workflow", "started", "Workflow started",
                total_steps=3, completed_steps=0,
            )

            # Verify a message was added
            mock_db.add.assert_called_once()
            msg = mock_db.add.call_args[0][0]
            assert msg.session_id == session_id
            assert msg.role == "assistant"
            assert msg.content == "Workflow started"
            assert msg.metadata_["trigger"] == "workflow"
            assert msg.metadata_["workflow_event"] == "started"
            assert msg.metadata_["workflow_name"] == "My Workflow"
            assert msg.metadata_["total_steps"] == 3
            assert msg.metadata_["completed_steps"] == 0
            assert msg.metadata_["sender_display_name"] == "Test Bot"
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_step_done_creates_message_when_no_existing(self):
        """First step_done should create a new message (no existing to update)."""
        run = MagicMock()
        run.channel_id = uuid.uuid4()
        run.bot_id = "test-bot"
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"

        session_id = uuid.uuid4()
        channel = MagicMock()
        channel.active_session_id = session_id

        bot = MagicMock()
        bot.display_name = "Test Bot"
        bot.name = "test-bot"

        # Make the select query return no existing message
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=channel)
        mock_db.add = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.agent.bots.get_bot", return_value=bot),
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()
            await _post_workflow_chat_message(
                run, "My Workflow", "step_done", "Step completed",
                step_id="search", step_index=0, total_steps=3, completed_steps=1,
            )

            # Should create new message since no existing found
            mock_db.add.assert_called_once()
            msg = mock_db.add.call_args[0][0]
            assert msg.content == "Step completed"
            assert msg.metadata_["workflow_event"] == "step_done"
            assert msg.metadata_["step_id"] == "search"
            assert msg.metadata_["completed_steps"] == 1

    @pytest.mark.asyncio
    async def test_step_done_updates_existing_message(self):
        """Subsequent step_done should update the existing progress message in-place."""
        run = MagicMock()
        run.channel_id = uuid.uuid4()
        run.bot_id = "test-bot"
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"

        session_id = uuid.uuid4()
        channel = MagicMock()
        channel.active_session_id = session_id

        bot = MagicMock()
        bot.display_name = "Test Bot"
        bot.name = "test-bot"

        # Simulate an existing step_done message
        existing_msg = MagicMock()
        existing_msg.content = "Old step result"
        existing_msg.metadata_ = {"workflow_event": "step_done", "completed_steps": 1}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_msg

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=channel)
        mock_db.add = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workflow_executor.flag_modified") as mock_flag,
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()
            await _post_workflow_chat_message(
                run, "My Workflow", "step_done", "Step 2 completed",
                step_id="analyze", step_index=1, total_steps=3, completed_steps=2,
            )

            # Should NOT create a new message
            mock_db.add.assert_not_called()
            # Should update the existing message
            assert existing_msg.content == "Step 2 completed"
            assert existing_msg.metadata_["workflow_event"] == "step_done"
            assert existing_msg.metadata_["step_id"] == "analyze"
            assert existing_msg.metadata_["completed_steps"] == 2
            mock_flag.assert_called_once_with(existing_msg, "metadata_")
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self):
        """Posting failures should be silently caught, not bubble up."""
        run = MagicMock()
        run.channel_id = uuid.uuid4()
        run.bot_id = "test-bot"
        run.id = uuid.uuid4()
        run.workflow_id = "test-wf"

        with patch("app.services.workflow_executor.async_session", side_effect=RuntimeError("db down")):
            # Should not raise
            await _post_workflow_chat_message(run, "WF", "started", "Hello")


# ---------------------------------------------------------------------------
# trigger_workflow error handling
# ---------------------------------------------------------------------------

class TestTriggerWorkflowErrorHandling:
    """Tests that trigger_workflow wraps advance_workflow failures."""

    @pytest.mark.asyncio
    async def test_advance_failure_marks_run_as_failed(self):
        """If advance_workflow raises during trigger, run should be marked failed."""
        from app.services.workflow_executor import trigger_workflow

        workflow = MagicMock()
        workflow.name = "Test"
        workflow.steps = [{"id": "s1", "prompt": "Do."}]
        workflow.params = {}
        workflow.secrets = []
        workflow.defaults = {"bot_id": "test-bot"}
        workflow.triggers = {}
        workflow.session_mode = "isolated"

        run_id = uuid.uuid4()

        # Track the run that gets created and updated
        created_run = None
        failed_run = MagicMock()
        failed_run.status = "running"

        mock_db = AsyncMock()

        async def mock_get(model, id_, **kw):
            if hasattr(model, '__tablename__'):
                if model.__tablename__ == 'channels':
                    return None
                if model.__tablename__ == 'workflow_runs':
                    return failed_run
            return failed_run

        mock_db.get = AsyncMock(side_effect=mock_get)
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with (
            patch("app.services.workflow_executor.async_session") as mock_session,
            patch("app.services.workflows.get_workflow", return_value=workflow),
            patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
            patch("app.services.workflow_executor._post_workflow_chat_message", new_callable=AsyncMock),
        ):
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock()

            result = await trigger_workflow("test-wf", {}, bot_id="test-bot")

            # The run should have been marked as failed
            assert failed_run.status == "failed"
            assert "Initial advancement failed" in (failed_run.error or "")


# ---------------------------------------------------------------------------
# create_workflow (app/services/workflows.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def _clear_workflow_registry():
    _workflows_mod._registry.clear()
    yield
    _workflows_mod._registry.clear()


@pytest.mark.asyncio
class TestCreateWorkflow:
    pytestmark = pytest.mark.usefixtures("_clear_workflow_registry")

    async def test_when_required_fields_provided_then_row_persisted(self, db_session, patched_async_sessions):
        wf_id = f"wf-{uuid.uuid4().hex[:8]}"
        data = {"id": wf_id, "name": "My Workflow", "steps": [{"type": "tool", "tool": "ping"}]}

        await create_workflow(data)

        row = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one_or_none()
        assert row is not None
        assert row.name == "My Workflow"

    async def test_when_created_then_added_to_registry(self, db_session, patched_async_sessions):
        wf_id = f"wf-{uuid.uuid4().hex[:8]}"

        result = await create_workflow({"id": wf_id})

        assert wf_id in _workflows_mod._registry
        assert _workflows_mod._registry[wf_id].id == wf_id

    async def test_when_optional_fields_omitted_then_defaults_applied(self, db_session, patched_async_sessions):
        wf_id = f"wf-{uuid.uuid4().hex[:8]}"

        result = await create_workflow({"id": wf_id})

        assert result.session_mode == "isolated"
        assert result.source_type == "manual"
        assert result.params == {}

    async def test_when_duplicate_id_then_integrity_error(self, db_session, patched_async_sessions):
        wf_id = f"wf-{uuid.uuid4().hex[:8]}"
        await create_workflow({"id": wf_id})

        with pytest.raises(IntegrityError):
            await create_workflow({"id": wf_id})
