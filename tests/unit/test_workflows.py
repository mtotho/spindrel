"""Unit tests for workflow condition evaluator, prompt rendering, and param validation."""
import pytest

from app.services.workflow_executor import (
    evaluate_condition,
    render_prompt,
    validate_params,
    validate_secrets,
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
