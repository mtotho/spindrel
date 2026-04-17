"""Tests for the ``foreach`` pipeline step.

v1 supports ``tool`` sub-steps only. Nested user_prompt / foreach / agent
are deferred per the plan.

Covers:
  * _resolve_value_ref: steps / params / JSON drill / {{ }} stripping
  * foreach over a 3-item list → 3 iterations, each sub-step runs
  * empty list → completes with 0 iterations
  * sub-step failure with on_failure: abort stops remaining iterations
  * on_failure: continue completes all iterations
  * {{item.*}}, {{item_index}}, {{item_count}} substituted correctly
  * unknown sub-step type fails cleanly
  * when-gate on sub-step skips that sub-step for that iteration
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.step_executor import (
    _init_step_states,
    _resolve_value_ref,
)


# ---------------------------------------------------------------------------
# _resolve_value_ref
# ---------------------------------------------------------------------------

class TestResolveValueRef:
    def test_strips_template_braces(self):
        steps = [{"id": "s1", "type": "tool"}]
        states = [{"status": "done", "result": [1, 2, 3]}]
        assert _resolve_value_ref("{{steps.s1.result}}", {}, states, steps) == [1, 2, 3]

    def test_bare_reference_also_works(self):
        steps = [{"id": "s1", "type": "tool"}]
        states = [{"status": "done", "result": [1, 2, 3]}]
        assert _resolve_value_ref("steps.s1.result", {}, states, steps) == [1, 2, 3]

    def test_steps_json_drill(self):
        steps = [{"id": "s1", "type": "tool"}]
        states = [{"status": "done", "result": '{"items": [{"id": 1}, {"id": 2}]}'}]
        result = _resolve_value_ref("steps.s1.result.items", {}, states, steps)
        assert result == [{"id": 1}, {"id": 2}]

    def test_params_flat(self):
        assert _resolve_value_ref("params.xs", {"xs": [1, 2]}, [], []) == [1, 2]

    def test_params_nested(self):
        assert (
            _resolve_value_ref("params.a.b", {"a": {"b": 7}}, [], []) == 7
        )

    def test_unresolved_returns_none(self):
        assert _resolve_value_ref("steps.missing.result", {}, [], []) is None


# ---------------------------------------------------------------------------
# foreach execution — happy paths
# ---------------------------------------------------------------------------

def _task(params=None):
    class T:
        id = uuid.uuid4()
        bot_id = "orchestrator"
        execution_config = {"params": params or {}}
    return T()


class TestForeachHappyPaths:
    @pytest.mark.asyncio
    async def test_three_items_three_iterations(self):
        from app.services.step_executor import _advance_pipeline

        steps = [
            {"id": "src", "type": "tool", "tool_name": "stub"},
            {
                "id": "loop",
                "type": "foreach",
                "over": "{{steps.src.result.items}}",
                "do": [
                    {"type": "tool", "tool_name": "apply", "tool_args": {"x": "{{item.id}}"}},
                ],
            },
        ]
        states = _init_step_states(steps)
        states[0] = {
            "status": "done",
            "result": '{"items": [{"id": 1}, {"id": 2}, {"id": 3}]}',
        }

        tool_calls: list[tuple[str, str]] = []

        async def fake_tool(name, args_json):
            tool_calls.append((name, args_json))
            return "ok"

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()) as finalize, \
             patch("app.tools.registry.call_local_tool", new=fake_tool):
            await _advance_pipeline(_task(), steps, states, start_index=1)

        loop_state = states[1]
        assert loop_state["status"] == "done"
        assert len(loop_state["iterations"]) == 3
        assert all(sub[0]["status"] == "done" for sub in loop_state["iterations"])
        assert len(tool_calls) == 3
        # each iteration gets the item.id substituted
        assert '"x": "1"' in tool_calls[0][1]
        assert '"x": "2"' in tool_calls[1][1]
        assert '"x": "3"' in tool_calls[2][1]
        finalize.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_list_completes_immediately(self):
        from app.services.step_executor import _advance_pipeline

        steps = [
            {
                "id": "loop",
                "type": "foreach",
                "over": "{{params.xs}}",
                "do": [{"type": "tool", "tool_name": "apply", "tool_args": {}}],
            },
        ]
        states = _init_step_states(steps)

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()), \
             patch("app.tools.registry.call_local_tool", new=AsyncMock(return_value="ok")) as tool:
            await _advance_pipeline(_task({"xs": []}), steps, states)

        assert states[0]["status"] == "done"
        assert states[0]["iterations"] == []
        tool.assert_not_called()

    @pytest.mark.asyncio
    async def test_item_index_and_count_bound(self):
        from app.services.step_executor import _advance_pipeline

        steps = [{
            "id": "loop",
            "type": "foreach",
            "over": "{{params.xs}}",
            "do": [{
                "type": "tool",
                "tool_name": "emit",
                "tool_args": {"idx": "{{item_index}}", "count": "{{item_count}}", "val": "{{item}}"},
            }],
        }]
        states = _init_step_states(steps)
        collected: list[str] = []

        async def fake_tool(name, args_json):
            collected.append(args_json)
            return "ok"

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()), \
             patch("app.tools.registry.call_local_tool", new=fake_tool):
            await _advance_pipeline(_task({"xs": ["a", "b"]}), steps, states)

        assert len(collected) == 2
        assert '"idx": "0"' in collected[0]
        assert '"count": "2"' in collected[0]
        assert '"val": "a"' in collected[0]
        assert '"idx": "1"' in collected[1]
        assert '"val": "b"' in collected[1]


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------

class TestForeachFailureModes:
    @pytest.mark.asyncio
    async def test_abort_stops_after_first_failure(self):
        from app.services.step_executor import _advance_pipeline

        steps = [{
            "id": "loop",
            "type": "foreach",
            "over": "{{params.xs}}",
            "on_failure": "abort",
            "do": [{"type": "tool", "tool_name": "maybe_fail", "tool_args": {"x": "{{item}}"}}],
        }]
        states = _init_step_states(steps)

        async def fake_tool(name, args_json):
            if '"x": "boom"' in args_json:
                raise RuntimeError("boom!")
            return "ok"

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()) as finalize, \
             patch("app.tools.registry.call_local_tool", new=fake_tool):
            await _advance_pipeline(_task({"xs": ["a", "boom", "c"]}), steps, states)

        iters = states[0]["iterations"]
        assert iters[0][0]["status"] == "done"
        assert iters[1][0]["status"] == "failed"
        assert iters[2][0]["status"] == "skipped"
        assert states[0]["status"] == "failed"
        # pipeline aborts at loop
        finalize.assert_called_once()

    @pytest.mark.asyncio
    async def test_continue_runs_all_iterations(self):
        from app.services.step_executor import _advance_pipeline

        steps = [{
            "id": "loop",
            "type": "foreach",
            "over": "{{params.xs}}",
            "on_failure": "continue",
            "do": [{"type": "tool", "tool_name": "maybe_fail", "tool_args": {"x": "{{item}}"}}],
        }]
        states = _init_step_states(steps)

        async def fake_tool(name, args_json):
            if '"x": "boom"' in args_json:
                raise RuntimeError("boom!")
            return "ok"

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()), \
             patch("app.tools.registry.call_local_tool", new=fake_tool):
            await _advance_pipeline(_task({"xs": ["a", "boom", "c"]}), steps, states)

        iters = states[0]["iterations"]
        assert [row[0]["status"] for row in iters] == ["done", "failed", "done"]
        assert states[0]["status"] == "done"
        assert "failed" in (states[0].get("error") or "")

    @pytest.mark.asyncio
    async def test_unresolved_over_fails_cleanly(self):
        from app.services.step_executor import _advance_pipeline

        steps = [{
            "id": "loop",
            "type": "foreach",
            "over": "{{steps.missing.result}}",
            "do": [{"type": "tool", "tool_name": "apply", "tool_args": {}}],
        }]
        states = _init_step_states(steps)

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()):
            await _advance_pipeline(_task(), steps, states)

        assert states[0]["status"] == "failed"
        assert "did not resolve" in (states[0].get("error") or "")

    @pytest.mark.asyncio
    async def test_over_not_a_list_fails(self):
        from app.services.step_executor import _advance_pipeline

        steps = [{
            "id": "loop",
            "type": "foreach",
            "over": "{{params.x}}",
            "do": [{"type": "tool", "tool_name": "apply", "tool_args": {}}],
        }]
        states = _init_step_states(steps)

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()):
            await _advance_pipeline(_task({"x": "not_a_list"}), steps, states)

        assert states[0]["status"] == "failed"
        assert "must resolve to a list" in (states[0].get("error") or "")

    @pytest.mark.asyncio
    async def test_unsupported_sub_step_type(self):
        from app.services.step_executor import _advance_pipeline

        steps = [{
            "id": "loop",
            "type": "foreach",
            "over": "{{params.xs}}",
            "on_failure": "continue",
            "do": [{"type": "agent", "prompt": "x"}],
        }]
        states = _init_step_states(steps)

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()):
            await _advance_pipeline(_task({"xs": ["a"]}), steps, states)

        sub_state = states[0]["iterations"][0][0]
        assert sub_state["status"] == "failed"
        assert "Unsupported" in (sub_state.get("error") or "")


# ---------------------------------------------------------------------------
# Sub-step when-gate
# ---------------------------------------------------------------------------

class TestForeachSubWhenGate:
    @pytest.mark.asyncio
    async def test_when_skips_sub_step_per_iteration(self):
        from app.services.step_executor import _advance_pipeline

        # when: item must equal "yes" on params — we craft a conditional that
        # only accepts certain items by comparing via a param reference.
        steps = [{
            "id": "loop",
            "type": "foreach",
            "over": "{{params.xs}}",
            "do": [{
                "type": "tool",
                "tool_name": "apply",
                "tool_args": {"x": "{{item}}"},
                "when": {"param": "item", "equals": "yes"},
            }],
        }]
        states = _init_step_states(steps)
        calls: list[str] = []

        async def fake_tool(name, args_json):
            calls.append(args_json)
            return "ok"

        with patch("app.services.step_executor._persist_step_states", new=AsyncMock()), \
             patch("app.services.step_executor._finalize_pipeline", new=AsyncMock()), \
             patch("app.tools.registry.call_local_tool", new=fake_tool):
            await _advance_pipeline(_task({"xs": ["yes", "no", "yes"]}), steps, states)

        iters = states[0]["iterations"]
        statuses = [row[0]["status"] for row in iters]
        assert statuses == ["done", "skipped", "done"]
        assert len(calls) == 2
