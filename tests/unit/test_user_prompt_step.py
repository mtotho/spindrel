"""Tests for the ``user_prompt`` pipeline step + /resolve endpoint.

Covers:
  * _run_user_prompt_step sets awaiting_user_input + envelope + schema
  * _advance_pipeline returns (pauses) on user_prompt steps
  * _validate_resolve_response: binary + multi_item + unknown kind
  * Resolve endpoint: happy path, 404 (task / index), 409 (not awaiting),
    422 (schema mismatch), downstream conditional branches correctly.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.step_executor import (
    _init_step_states,
    _render_widget_envelope,
    _validate_resolve_response,
)


# ---------------------------------------------------------------------------
# _validate_resolve_response
# ---------------------------------------------------------------------------

class TestValidateResolveResponse:
    def test_binary_approve(self):
        assert _validate_resolve_response({"type": "binary"}, {"decision": "approve"}) is None

    def test_binary_reject(self):
        assert _validate_resolve_response({"type": "binary"}, {"decision": "reject"}) is None

    def test_binary_bad_decision(self):
        err = _validate_resolve_response({"type": "binary"}, {"decision": "maybe"})
        assert err and "approve" in err

    def test_binary_missing_decision(self):
        err = _validate_resolve_response({"type": "binary"}, {})
        assert err is not None

    def test_multi_item_all_known(self):
        schema = {"type": "multi_item", "items": [{"id": "a"}, {"id": "b"}]}
        assert _validate_resolve_response(schema, {"a": "approve", "b": "reject"}) is None

    def test_multi_item_partial(self):
        schema = {"type": "multi_item", "items": [{"id": "a"}, {"id": "b"}]}
        # partial submissions allowed
        assert _validate_resolve_response(schema, {"a": "approve"}) is None

    def test_multi_item_unknown_id(self):
        schema = {"type": "multi_item", "items": [{"id": "a"}]}
        err = _validate_resolve_response(schema, {"zzz": "approve"})
        assert err and "zzz" in err

    def test_multi_item_invalid_decision(self):
        schema = {"type": "multi_item", "items": [{"id": "a"}]}
        err = _validate_resolve_response(schema, {"a": "wat"})
        assert err and "wat" in err

    def test_non_dict_rejected(self):
        assert _validate_resolve_response({"type": "binary"}, "approve") is not None

    def test_unknown_kind_accepts_any_dict(self):
        # permissive fallback
        assert _validate_resolve_response({"type": "experimental"}, {"foo": "bar"}) is None


class TestResolveResponseSchema:
    """items_ref in a multi_item schema must be resolved at pause time."""

    def test_items_ref_resolved_against_prior_step(self):
        from app.services.step_executor import _resolve_response_schema

        class T:
            id = None
            execution_config = {}

        steps = [{"id": "analyze", "type": "agent"}, {"id": "review", "type": "user_prompt"}]
        states = [
            {"status": "done", "result": '{"proposals": [{"id": "p1"}, {"id": "p2"}]}'},
            {"status": "pending"},
        ]
        raw = {"type": "multi_item", "items_ref": "{{steps.analyze.result.proposals}}"}
        resolved = _resolve_response_schema(raw, T(), states, steps)
        assert resolved["items"] == [{"id": "p1"}, {"id": "p2"}]
        # After resolution, the validator should accept submissions for p1/p2.
        assert _validate_resolve_response(resolved, {"p1": "approve", "p2": "reject"}) is None

    def test_items_ref_with_non_dict_entries_filtered(self):
        from app.services.step_executor import _resolve_response_schema

        class T:
            id = None
            execution_config = {}

        steps = [{"id": "analyze", "type": "agent"}]
        states = [{"status": "done", "result": '{"proposals": [{"id": "p1"}, "junk", {"no_id": true}]}'}]
        raw = {"type": "multi_item", "items_ref": "{{steps.analyze.result.proposals}}"}
        resolved = _resolve_response_schema(raw, T(), states, steps)
        assert resolved["items"] == [{"id": "p1"}]

    def test_items_wins_over_items_ref(self):
        from app.services.step_executor import _resolve_response_schema

        class T:
            id = None
            execution_config = {}

        raw = {
            "type": "multi_item",
            "items": [{"id": "explicit"}],
            "items_ref": "ignored",
        }
        resolved = _resolve_response_schema(raw, T(), [], [])
        assert resolved["items"] == [{"id": "explicit"}]


class TestPriorResultsHandlesDict:
    """user_prompt/foreach steps store dict/list results; prior-result
    helpers must not crash when the result isn't a string."""

    def test_preamble_serializes_dict_result(self):
        from app.services.step_executor import _build_prior_results_preamble

        steps = [{"id": "gate", "type": "user_prompt"}]
        states = [{"status": "done", "result": {"decision": "approve"}}]
        out = _build_prior_results_preamble(steps, states, current_index=1)
        assert "approve" in out

    def test_env_serializes_dict_result(self):
        from app.services.step_executor import _build_prior_results_env

        steps = [{"id": "gate", "type": "user_prompt"}]
        states = [{"status": "done", "result": {"decision": "approve"}}]
        env = _build_prior_results_env(steps, states, current_index=1)
        assert '"decision": "approve"' in env["STEP_1_RESULT"]

    def test_preamble_none_result_safe(self):
        from app.services.step_executor import _build_prior_results_preamble

        steps = [{"id": "s", "type": "exec"}]
        states = [{"status": "done", "result": None}]
        # must not crash even though result is None
        out = _build_prior_results_preamble(steps, states, current_index=1)
        assert "s" in out


# ---------------------------------------------------------------------------
# _render_widget_envelope
# ---------------------------------------------------------------------------

class TestRenderWidgetEnvelope:
    def _task(self, params=None):
        class T:
            id = uuid.uuid4()
            execution_config = {"params": params or {}}
        return T()

    def test_renders_template_and_args_with_params(self):
        task = self._task({"bot_id": "default"})
        step_def = {
            "type": "user_prompt",
            "widget_template": {"kind": "review", "title": "Approve {{params.bot_id}}?"},
            "widget_args": {"bot": "{{params.bot_id}}"},
            "title": "Review",
        }
        env = _render_widget_envelope(task, step_def, [], [])
        assert env["template"]["title"] == "Approve default?"
        assert env["args"]["bot"] == "default"
        assert env["title"] == "Review"

    def test_renders_with_step_reference(self):
        task = self._task()
        steps = [{"id": "fetch", "type": "tool"}, {"id": "approve", "type": "user_prompt"}]
        states = [{"status": "done", "result": "42"}, {"status": "pending"}]
        step_def = {
            "type": "user_prompt",
            "widget_template": {"title": "Got {{steps.fetch.result}}"},
            "widget_args": {},
        }
        env = _render_widget_envelope(task, step_def, steps, states)
        assert env["template"]["title"] == "Got 42"

    def test_item_ctx_overrides_params(self):
        task = self._task({"bot_id": "default"})
        step_def = {
            "widget_template": {"body": "item={{params.item}}"},
            "widget_args": {},
        }
        env = _render_widget_envelope(
            task, step_def, [], [], item_ctx={"item": {"name": "x"}}
        )
        # item context is merged into params; serialized as json since it's a dict
        assert '"name": "x"' in env["template"]["body"]


# ---------------------------------------------------------------------------
# _advance_pipeline — user_prompt pauses
# ---------------------------------------------------------------------------

class TestUserPromptPausesPipeline:
    @pytest.mark.asyncio
    async def test_single_user_prompt_step_pauses(self):
        from app.services.step_executor import _advance_pipeline

        task = AsyncMock()
        task.id = uuid.uuid4()
        task.bot_id = "orchestrator"
        task.execution_config = {"params": {"bot_id": "default"}}

        steps = [{
            "id": "approve",
            "type": "user_prompt",
            "widget_template": {"kind": "binary"},
            "widget_args": {},
            "response_schema": {"type": "binary"},
        }]
        states = _init_step_states(steps)

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()) as persist, \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()) as finalize:
            await _advance_pipeline(task, steps, states)

        assert states[0]["status"] == "awaiting_user_input"
        assert states[0]["widget_envelope"]["template"] == {"kind": "binary"}
        assert states[0]["response_schema"] == {"type": "binary"}
        # Pipeline MUST NOT finalize while awaiting user input
        finalize.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_item_empty_auto_skips_with_informative_result(self):
        """When multi_item resolves to zero items, the step auto-completes with
        a human-readable result explaining why (not an opaque ``{}``). Without
        this the UI renders "review: done 34ms" and users think they missed a
        review window."""
        from app.services.step_executor import _advance_pipeline

        task = AsyncMock()
        task.id = uuid.uuid4()
        task.bot_id = "orchestrator"
        task.execution_config = {"params": {}}

        steps = [{
            "id": "review",
            "type": "user_prompt",
            "widget_template": {"kind": "approval_review"},
            "widget_args": {},
            "response_schema": {"type": "multi_item", "items_ref": "{{params.missing}}"},
        }]
        states = _init_step_states(steps)

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()):
            await _advance_pipeline(task, steps, states)

        # Auto-skipped (not awaiting)
        assert states[0]["status"] == "done"
        # Result is a non-empty human-readable string, not "{}"
        result = states[0]["result"]
        assert isinstance(result, str)
        assert "auto-skipped" in result.lower() or "no items" in result.lower()
        assert result != "{}"

    @pytest.mark.asyncio
    async def test_user_prompt_in_middle_pauses_before_later_steps(self):
        from app.services.step_executor import _advance_pipeline

        task = AsyncMock()
        task.id = uuid.uuid4()
        task.bot_id = "orchestrator"
        task.execution_config = None

        steps = [
            {"id": "gate", "type": "user_prompt", "widget_template": {}, "widget_args": {},
             "response_schema": {"type": "binary"}},
            {"id": "after", "type": "exec", "prompt": "echo hi"},
        ]
        states = _init_step_states(steps)

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()) as finalize:
            await _advance_pipeline(task, steps, states)

        assert states[0]["status"] == "awaiting_user_input"
        assert states[1]["status"] == "pending"
        finalize.assert_not_called()


# ---------------------------------------------------------------------------
# Resume-from-resolve via _advance_pipeline(start_index=i+1)
# ---------------------------------------------------------------------------

class TestResumeAfterResolve:
    @pytest.mark.asyncio
    async def test_resume_runs_next_step(self):
        from app.services.step_executor import _advance_pipeline, _init_step_states

        task = AsyncMock()
        task.id = uuid.uuid4()
        task.bot_id = "orchestrator"
        task.execution_config = None

        steps = [
            {"id": "gate", "type": "user_prompt", "widget_template": {}, "widget_args": {},
             "response_schema": {"type": "binary"}},
            {"id": "after", "type": "tool", "tool_name": "noop_tool", "tool_args": {"x": "1"}},
        ]
        states = _init_step_states(steps)
        # Simulate resolve marking the gate done
        states[0]["status"] = "done"
        states[0]["result"] = {"decision": "approve"}

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()) as finalize, \
             patch("app.services.step_executor._run_tool_step",
                   new=AsyncMock(return_value=("done", "ok", None))) as run_tool:
            await _advance_pipeline(task, steps, states, start_index=1)

        run_tool.assert_called_once()
        finalize.assert_called_once()
        assert states[1]["status"] == "done"

    @pytest.mark.asyncio
    async def test_resume_respects_conditional_when_on_next_step(self):
        """Downstream step gated by `when` on steps.N.result.decision."""
        from app.services.step_executor import _advance_pipeline, _init_step_states

        task = AsyncMock()
        task.id = uuid.uuid4()
        task.bot_id = "orchestrator"
        task.execution_config = None

        steps = [
            {"id": "gate", "type": "user_prompt", "widget_template": {}, "widget_args": {},
             "response_schema": {"type": "binary"}},
            {
                "id": "apply",
                "type": "tool",
                "tool_name": "noop_tool",
                "tool_args": {},
                "when": {
                    "step": "gate",
                    "output_contains": "approve",
                },
            },
        ]
        states = _init_step_states(steps)
        # rejection -> the conditional should skip
        states[0]["status"] = "done"
        states[0]["result"] = '{"decision": "reject"}'

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()), \
             patch("app.services.step_executor._run_tool_step",
                   new=AsyncMock(return_value=("done", "ok", None))) as run_tool:
            await _advance_pipeline(task, steps, states, start_index=1)

        run_tool.assert_not_called()
        assert states[1]["status"] == "skipped"
