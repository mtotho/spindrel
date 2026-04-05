"""Tests for MC plan tools — step coercion and registry-level type safety."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.registry import _coerce_args


# ---------------------------------------------------------------------------
# Registry-level coercion: _coerce_args
# ---------------------------------------------------------------------------

class TestCoerceArgs:
    """_coerce_args should fix common LLM type mistakes based on the schema."""

    def test_string_to_array(self):
        """A string value for an array param should be wrapped in a list."""
        schema_props = {
            "steps": {"type": "array", "items": {"type": "string"}},
            "title": {"type": "string"},
        }
        args = {"steps": "Do a barrel roll", "title": "My Plan"}
        result = _coerce_args(args, schema_props)
        assert result["steps"] == ["Do a barrel roll"]
        assert result["title"] == "My Plan"

    def test_list_stays_list(self):
        """Already-correct list values should pass through unchanged."""
        schema_props = {
            "steps": {"type": "array", "items": {"type": "string"}},
        }
        args = {"steps": ["Step 1", "Step 2"]}
        result = _coerce_args(args, schema_props)
        assert result["steps"] == ["Step 1", "Step 2"]

    def test_no_schema_props_passthrough(self):
        """Args without matching schema properties should pass through."""
        schema_props = {}
        args = {"steps": "whatever"}
        result = _coerce_args(args, schema_props)
        assert result["steps"] == "whatever"

    def test_integer_array_from_string(self):
        """An integer value for an integer-array param should be wrapped."""
        schema_props = {
            "ids": {"type": "array", "items": {"type": "integer"}},
        }
        args = {"ids": 42}
        result = _coerce_args(args, schema_props)
        assert result["ids"] == [42]

    def test_already_list_not_double_wrapped(self):
        """A list should never be double-wrapped."""
        schema_props = {
            "tags": {"type": "array", "items": {"type": "string"}},
        }
        args = {"tags": ["a", "b"]}
        result = _coerce_args(args, schema_props)
        assert result["tags"] == ["a", "b"]

    def test_empty_string_to_empty_list(self):
        """An empty string for an array param should become an empty list."""
        schema_props = {
            "steps": {"type": "array", "items": {"type": "string"}},
        }
        args = {"steps": ""}
        result = _coerce_args(args, schema_props)
        assert result["steps"] == [""]

    def test_none_passthrough(self):
        """None values should pass through (optional params)."""
        schema_props = {
            "steps": {"type": "array", "items": {"type": "string"}},
        }
        args = {"steps": None}
        result = _coerce_args(args, schema_props)
        assert result["steps"] is None

    def test_string_to_integer(self):
        """A string value for an integer param should be coerced to int."""
        schema_props = {"num_results": {"type": "integer"}}
        args = {"num_results": "5"}
        result = _coerce_args(args, schema_props)
        assert result["num_results"] == 5
        assert isinstance(result["num_results"], int)

    def test_integer_stays_integer(self):
        """Already-correct integer values should pass through."""
        schema_props = {"num_results": {"type": "integer"}}
        args = {"num_results": 5}
        result = _coerce_args(args, schema_props)
        assert result["num_results"] == 5

    def test_invalid_string_to_integer_passthrough(self):
        """A non-numeric string for an integer param should pass through."""
        schema_props = {"count": {"type": "integer"}}
        args = {"count": "abc"}
        result = _coerce_args(args, schema_props)
        assert result["count"] == "abc"

    def test_string_to_number(self):
        """A string value for a number param should be coerced to float."""
        schema_props = {"threshold": {"type": "number"}}
        args = {"threshold": "0.75"}
        result = _coerce_args(args, schema_props)
        assert result["threshold"] == 0.75
        assert isinstance(result["threshold"], float)

    def test_string_to_boolean(self):
        """A string 'true'/'false' for a boolean param should be coerced."""
        schema_props = {"verbose": {"type": "boolean"}}
        args = {"verbose": "true"}
        result = _coerce_args(args, schema_props)
        assert result["verbose"] is True

        args2 = {"verbose": "false"}
        result2 = _coerce_args(args2, schema_props)
        assert result2["verbose"] is False


# ---------------------------------------------------------------------------
# draft_plan: string steps → should create exactly 1 step, not N characters
# ---------------------------------------------------------------------------

class TestDraftPlanStepCoercion:
    """Regression: passing steps as a string should not create per-character steps."""

    @pytest.mark.asyncio
    async def test_string_steps_creates_one_step(self):
        """draft_plan('Do a barrel roll') → 1 step, not 16 characters."""
        from integrations.mission_control.tools.plans import draft_plan

        added_objects = []

        class FakeSession:
            def add(self, obj):
                added_objects.append(obj)
            async def flush(self):
                pass
            async def commit(self):
                pass

        class FakeCtx:
            async def __aenter__(self):
                return FakeSession()
            async def __aexit__(self, *args):
                pass

        with (
            patch("integrations.mission_control.db.engine.mc_session", return_value=FakeCtx()),
            patch("integrations.mission_control.services._ensure_plans_migrated", new_callable=AsyncMock),
            patch("integrations.mission_control.services._render_plans_md", new_callable=AsyncMock),
            patch("integrations.mission_control.tools.plans.append_timeline", new_callable=AsyncMock),
            patch("app.services.plan_board.generate_plan_id", return_value="plan-test01"),
        ):
            result = await draft_plan(
                channel_id="ch-123",
                title="Test Plan",
                steps="Do a barrel roll",  # string, not list!
            )

        # Should have added 1 McPlan + 1 McPlanStep (not 16 character steps)
        from integrations.mission_control.db.models import McPlanStep
        step_objects = [o for o in added_objects if isinstance(o, McPlanStep)]
        assert len(step_objects) == 1, (
            f"Expected 1 step, got {len(step_objects)}: "
            f"{[s.content for s in step_objects]}"
        )
        assert step_objects[0].content == "Do a barrel roll"

    @pytest.mark.asyncio
    async def test_list_steps_creates_correct_count(self):
        """draft_plan(['Step 1', 'Step 2', 'Step 3']) → 3 steps."""
        from integrations.mission_control.tools.plans import draft_plan

        added_objects = []

        class FakeSession:
            def add(self, obj):
                added_objects.append(obj)
            async def flush(self):
                pass
            async def commit(self):
                pass

        class FakeCtx:
            async def __aenter__(self):
                return FakeSession()
            async def __aexit__(self, *args):
                pass

        with (
            patch("integrations.mission_control.db.engine.mc_session", return_value=FakeCtx()),
            patch("integrations.mission_control.services._ensure_plans_migrated", new_callable=AsyncMock),
            patch("integrations.mission_control.services._render_plans_md", new_callable=AsyncMock),
            patch("integrations.mission_control.tools.plans.append_timeline", new_callable=AsyncMock),
            patch("app.services.plan_board.generate_plan_id", return_value="plan-test02"),
        ):
            result = await draft_plan(
                channel_id="ch-123",
                title="Test Plan",
                steps=["Step 1", "Step 2", "Step 3"],
            )

        from integrations.mission_control.db.models import McPlanStep
        step_objects = [o for o in added_objects if isinstance(o, McPlanStep)]
        assert len(step_objects) == 3
        assert step_objects[0].content == "Step 1"
        assert step_objects[1].content == "Step 2"
        assert step_objects[2].content == "Step 3"


# ---------------------------------------------------------------------------
# Registry call_local_tool: coercion integrated into the call path
# ---------------------------------------------------------------------------

class TestCallLocalToolCoercion:
    """call_local_tool should coerce args before calling the function."""

    @pytest.mark.asyncio
    async def test_string_coerced_to_list_via_registry(self):
        """When LLM passes string for array param, registry should coerce it."""
        from app.tools.registry import _tools, call_local_tool

        captured_args = {}

        async def fake_tool(items: list[str], name: str = "") -> str:
            captured_args["items"] = items
            captured_args["name"] = name
            return "ok"

        _tools["_test_coerce_tool"] = {
            "function": fake_tool,
            "schema": {"type": "function", "function": {
                "name": "_test_coerce_tool",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "string"}},
                        "name": {"type": "string"},
                    },
                },
            }},
        }

        try:
            result = await call_local_tool(
                "_test_coerce_tool",
                json.dumps({"items": "single item", "name": "test"}),
            )
            assert result == "ok"
            assert captured_args["items"] == ["single item"]
            assert captured_args["name"] == "test"
        finally:
            _tools.pop("_test_coerce_tool", None)
