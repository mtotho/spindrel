"""Unit tests for app.services.experiment_metrics — the autoresearch
metric library and primary+guards runner.

Smoking-gun shape: each test feeds a list of synthetic per-case capture
dicts and asserts a specific aggregate or guard outcome. No DB, no LLM
(judge tests use a stub).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services.experiment_metrics import (
    _GUARD_KEYS,
    get_apply_adapter,
    list_metric_kinds,
    metric_exec_exit_code,
    metric_regex_match,
    metric_schema_compliance,
    metric_token_count_under,
    metric_tool_selection_accuracy,
    resolve_threshold,
    run_metric,
    score_eval_results,
)


# ---------------------------------------------------------------------------
# resolve_threshold — baseline-relative expressions
# ---------------------------------------------------------------------------

class TestResolveThreshold:
    def test_literal_number(self):
        assert resolve_threshold(0.8, baseline=None) == 0.8
        assert resolve_threshold(2, baseline=None) == 2.0

    def test_literal_string_number(self):
        assert resolve_threshold("0.8", baseline=None) == 0.8

    def test_none_returns_none(self):
        assert resolve_threshold(None, baseline=None) is None
        assert resolve_threshold(None, baseline=4.0) is None

    def test_baseline_literal(self):
        assert resolve_threshold("baseline", baseline=4.0) == 4.0

    def test_baseline_addition(self):
        assert resolve_threshold("baseline + 0.1", baseline=4.0) == pytest.approx(4.1)

    def test_baseline_subtraction(self):
        assert resolve_threshold("baseline - 0.5", baseline=4.0) == 3.5

    def test_baseline_multiplication(self):
        assert resolve_threshold("baseline * 1.2", baseline=10.0) == 12.0

    def test_baseline_division(self):
        assert resolve_threshold("baseline / 2", baseline=10.0) == 5.0

    def test_baseline_required_raises(self):
        with pytest.raises(ValueError, match="baseline"):
            resolve_threshold("baseline + 0.1", baseline=None)

    def test_unparseable_raises(self):
        with pytest.raises(ValueError):
            resolve_threshold("not a number", baseline=4.0)


# ---------------------------------------------------------------------------
# tool_selection_accuracy
# ---------------------------------------------------------------------------

def _entry(case: dict, tool_calls: list[dict] | None = None, **extras) -> dict:
    cap = {"tool_calls": tool_calls or [], **extras}
    return {"case": case, "captured": cap, "error": None}


class TestToolSelectionAccuracy:
    def test_first_call_match_scores_one(self):
        cases = [_entry({"expected_tool": "HassTurnOn"}, [{"name": "HassTurnOn", "args": {}}])]
        out = metric_tool_selection_accuracy(cases, {})
        assert out["aggregate"] == 1.0
        assert out["per_case"][0]["score"] == 1.0

    def test_first_call_miss_scores_zero(self):
        cases = [_entry({"expected_tool": "HassTurnOn"}, [{"name": "HassTurnOff"}])]
        out = metric_tool_selection_accuracy(cases, {})
        assert out["aggregate"] == 0.0

    def test_no_tool_call_scores_zero(self):
        cases = [_entry({"expected_tool": "HassTurnOn"}, [])]
        out = metric_tool_selection_accuracy(cases, {})
        assert out["aggregate"] == 0.0

    def test_either_of_partial_credit(self):
        cases = [_entry({"expected_tool": ["HassTurnOn", "HassToggle"]}, [{"name": "HassToggle"}])]
        out = metric_tool_selection_accuracy(cases, {"partial_credit_for_either_of": 0.5})
        assert out["aggregate"] == 0.5

    def test_either_of_miss(self):
        cases = [_entry({"expected_tool": ["A", "B"]}, [{"name": "C"}])]
        out = metric_tool_selection_accuracy(cases, {})
        assert out["aggregate"] == 0.0

    def test_score_first_call_only_false(self):
        cases = [_entry({"expected_tool": "B"}, [{"name": "A"}, {"name": "B"}])]
        out = metric_tool_selection_accuracy(cases, {"score_first_call_only": False})
        assert out["aggregate"] == 1.0

    def test_score_first_call_only_true_default(self):
        cases = [_entry({"expected_tool": "B"}, [{"name": "A"}, {"name": "B"}])]
        out = metric_tool_selection_accuracy(cases, {})
        assert out["aggregate"] == 0.0

    def test_aggregate_is_mean_across_cases(self):
        cases = [
            _entry({"expected_tool": "A"}, [{"name": "A"}]),
            _entry({"expected_tool": "B"}, [{"name": "C"}]),
            _entry({"expected_tool": "D"}, [{"name": "D"}]),
        ]
        out = metric_tool_selection_accuracy(cases, {})
        assert out["aggregate"] == pytest.approx(2 / 3)

    def test_custom_field_name(self):
        cases = [_entry({"my_tool": "A"}, [{"name": "A"}])]
        out = metric_tool_selection_accuracy(cases, {"field": "my_tool"})
        assert out["aggregate"] == 1.0

    def test_missing_expected_field_scores_zero(self):
        cases = [_entry({}, [{"name": "A"}])]
        out = metric_tool_selection_accuracy(cases, {})
        assert out["aggregate"] == 0.0
        assert "missing field" in out["per_case"][0]["reason"]


# ---------------------------------------------------------------------------
# regex_match
# ---------------------------------------------------------------------------

class TestRegexMatch:
    def test_simple_match(self):
        cases = [{"case": {}, "captured": {"response_text": "hello world"}}]
        out = metric_regex_match(cases, {"pattern": "world"})
        assert out["aggregate"] == 1.0

    def test_no_match(self):
        cases = [{"case": {}, "captured": {"response_text": "goodbye"}}]
        out = metric_regex_match(cases, {"pattern": "world"})
        assert out["aggregate"] == 0.0

    def test_case_insensitive_flag(self):
        cases = [{"case": {}, "captured": {"response_text": "HELLO"}}]
        out = metric_regex_match(cases, {"pattern": "hello", "flags": "i"})
        assert out["aggregate"] == 1.0

    def test_alternative_field(self):
        cases = [{"case": {}, "captured": {"stdout": "OK"}}]
        out = metric_regex_match(cases, {"pattern": "OK", "field": "stdout"})
        assert out["aggregate"] == 1.0

    def test_nested_field(self):
        cases = [{"case": {}, "captured": {"tool_calls": [{"name": "HassTurnOn"}]}}]
        out = metric_regex_match(
            cases, {"pattern": ".+", "field": "tool_calls[0].name"}
        )
        assert out["aggregate"] == 1.0

    def test_missing_pattern_raises(self):
        with pytest.raises(ValueError):
            metric_regex_match([], {})

    def test_missing_field_scores_zero(self):
        cases = [{"case": {}, "captured": {}}]
        out = metric_regex_match(cases, {"pattern": "x"})
        assert out["aggregate"] == 0.0

    def test_aggregate_is_pass_rate(self):
        cases = [
            {"case": {}, "captured": {"response_text": "hello"}},
            {"case": {}, "captured": {"response_text": "world"}},
            {"case": {}, "captured": {"response_text": "nope"}},
        ]
        out = metric_regex_match(cases, {"pattern": "hello|world"})
        assert out["aggregate"] == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# schema_compliance
# ---------------------------------------------------------------------------

class TestSchemaCompliance:
    def test_valid_json_passes(self):
        cases = [{"case": {}, "captured": {"response_text": '{"name": "x"}'}}]
        schema = {"type": "object", "required": ["name"]}
        out = metric_schema_compliance(cases, {"json_schema": schema})
        assert out["aggregate"] == 1.0

    def test_invalid_json_scores_zero(self):
        cases = [{"case": {}, "captured": {"response_text": "not json"}}]
        out = metric_schema_compliance(cases, {"json_schema": {}})
        assert out["aggregate"] == 0.0
        assert "not valid JSON" in out["per_case"][0]["reason"]

    def test_schema_violation(self):
        # Skip if jsonschema isn't installed (the metric falls back to
        # parse-only which would always pass).
        pytest.importorskip("jsonschema")
        cases = [{"case": {}, "captured": {"response_text": '{}'}}]
        schema = {"type": "object", "required": ["name"]}
        out = metric_schema_compliance(cases, {"json_schema": schema})
        assert out["aggregate"] == 0.0
        assert "schema errors" in out["per_case"][0]["reason"]

    def test_missing_schema_raises(self):
        with pytest.raises(ValueError):
            metric_schema_compliance([], {})


# ---------------------------------------------------------------------------
# token_count_under
# ---------------------------------------------------------------------------

class TestTokenCountUnder:
    def test_aggregate_is_mean(self):
        cases = [
            {"case": {}, "captured": {"token_count": 100}},
            {"case": {}, "captured": {"token_count": 200}},
        ]
        out = metric_token_count_under(cases, {})
        assert out["aggregate"] == 150.0

    def test_extras_include_p95(self):
        cases = [{"case": {}, "captured": {"token_count": float(i * 10)}} for i in range(1, 21)]
        out = metric_token_count_under(cases, {})
        assert out["extras"]["p95"] >= out["extras"]["p50"]
        assert out["extras"]["max"] == 200.0
        assert out["extras"]["mean"] == out["aggregate"]

    def test_missing_field_skipped(self):
        cases = [
            {"case": {}, "captured": {}},
            {"case": {}, "captured": {"token_count": 50}},
        ]
        out = metric_token_count_under(cases, {})
        assert out["aggregate"] == 50.0


# ---------------------------------------------------------------------------
# exec_exit_code
# ---------------------------------------------------------------------------

class TestExecExitCode:
    def test_match_default_zero(self):
        cases = [{"case": {}, "captured": {"exit_code": 0}}]
        out = metric_exec_exit_code(cases, {})
        assert out["aggregate"] == 1.0

    def test_mismatch(self):
        cases = [{"case": {}, "captured": {"exit_code": 1}}]
        out = metric_exec_exit_code(cases, {})
        assert out["aggregate"] == 0.0

    def test_custom_expected(self):
        cases = [{"case": {}, "captured": {"exit_code": 7}}]
        out = metric_exec_exit_code(cases, {"expected": 7})
        assert out["aggregate"] == 1.0


# ---------------------------------------------------------------------------
# Registry / dispatch
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_list_includes_all_six(self):
        kinds = list_metric_kinds()
        for k in (
            "tool_selection_accuracy", "regex_match", "schema_compliance",
            "token_count_under", "exec_exit_code", "llm_judge_rubric",
        ):
            assert k in kinds

    @pytest.mark.asyncio
    async def test_run_metric_sync(self):
        cases = [_entry({"expected_tool": "A"}, [{"name": "A"}])]
        out = await run_metric("tool_selection_accuracy", cases, {})
        assert out["aggregate"] == 1.0

    @pytest.mark.asyncio
    async def test_run_metric_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown metric"):
            await run_metric("nope", [], {})

    @pytest.mark.asyncio
    async def test_run_metric_async_judge(self):
        # Stub the judge so we don't hit the LLM.
        with patch("app.services.judge.judge_single_case", new=AsyncMock(return_value={"overall": 4.5})):
            out = await run_metric("llm_judge_rubric", [{"case": {}, "captured": {}}], {"rubric": "x"})
        assert out["aggregate"] == 4.5
        assert out["per_case"][0]["score"] == 4.5


# ---------------------------------------------------------------------------
# score_eval_results — the primary + guards runner
# ---------------------------------------------------------------------------

class TestScoreEvalResults:
    @pytest.mark.asyncio
    async def test_primary_only_no_guards(self):
        cases = [_entry({"expected_tool": "A"}, [{"name": "A"}])]
        block = {"primary": {"kind": "tool_selection_accuracy", "args": {}}}
        out = await score_eval_results(block, cases)
        assert out["primary"]["aggregate"] == 1.0
        assert out["guards"] == []
        assert out["variant_valid"] is True

    @pytest.mark.asyncio
    async def test_guard_passes_marks_valid(self):
        cases = [_entry({"expected_tool": "A"}, [{"name": "A"}], response_text="ok")]
        block = {
            "primary": {"kind": "tool_selection_accuracy", "args": {}},
            "guards": [
                {"name": "g1", "kind": "regex_match",
                 "args": {"pattern": "ok"}, "min_pass": 0.9},
            ],
        }
        out = await score_eval_results(block, cases)
        assert out["variant_valid"] is True
        assert out["guards"][0]["passed"] is True

    @pytest.mark.asyncio
    async def test_guard_fails_marks_invalid(self):
        cases = [_entry({"expected_tool": "A"}, [{"name": "A"}], response_text="bad")]
        block = {
            "primary": {"kind": "tool_selection_accuracy", "args": {}},
            "guards": [
                {"name": "must_say_ok", "kind": "regex_match",
                 "args": {"pattern": "ok"}, "min_pass": 1.0},
            ],
        }
        out = await score_eval_results(block, cases)
        # Primary still scores 1.0 (the bot called the right tool)
        assert out["primary"]["aggregate"] == 1.0
        # But guard breached → variant invalid
        assert out["variant_valid"] is False
        assert out["guards"][0]["passed"] is False

    @pytest.mark.asyncio
    async def test_baseline_relative_threshold(self):
        # token_count: variant produces 130 mean tokens vs baseline 100 mean.
        # Guard says "p95_max: baseline * 1.2" → 120 ceiling. Variant breaches.
        cases = [{"case": {}, "captured": {"token_count": 130}} for _ in range(3)]
        block = {
            "primary": {"kind": "regex_match", "args": {"pattern": ".*", "field": "token_count"}},
            "guards": [
                {"name": "brevity", "kind": "token_count_under",
                 "args": {}, "p95_max": "baseline * 1.2"},
            ],
        }
        baseline = {"primary": 1.0, "guards": {"brevity": 100.0}}
        out = await score_eval_results(block, cases, baseline=baseline)
        assert out["guards"][0]["passed"] is False  # 130 > 120
        assert out["variant_valid"] is False

    @pytest.mark.asyncio
    async def test_multiple_guards_all_must_pass(self):
        cases = [_entry({"expected_tool": "A"}, [{"name": "A"}], response_text="ok", token_count=50)]
        block = {
            "primary": {"kind": "tool_selection_accuracy", "args": {}},
            "guards": [
                {"name": "g1", "kind": "regex_match", "args": {"pattern": "ok"}, "min_pass": 1.0},
                {"name": "g2", "kind": "token_count_under", "args": {}, "p95_max": 30},  # 50 > 30 → breach
            ],
        }
        out = await score_eval_results(block, cases)
        assert out["guards"][0]["passed"] is True
        assert out["guards"][1]["passed"] is False
        assert out["variant_valid"] is False

    @pytest.mark.asyncio
    async def test_missing_primary_raises(self):
        with pytest.raises(ValueError, match="primary.kind"):
            await score_eval_results({"primary": {}}, [])

    @pytest.mark.asyncio
    async def test_guard_metric_error_marks_invalid(self):
        cases = [_entry({"expected_tool": "A"}, [{"name": "A"}])]
        block = {
            "primary": {"kind": "tool_selection_accuracy", "args": {}},
            "guards": [
                {"name": "broken", "kind": "regex_match",  # missing pattern → ValueError
                 "args": {}, "min_pass": 1.0},
            ],
        }
        out = await score_eval_results(block, cases)
        assert out["variant_valid"] is False
        assert "metric error" in out["guards"][0]["reason"]


# ---------------------------------------------------------------------------
# Apply adapters — resolver only (write-fns are tested at integration level)
# ---------------------------------------------------------------------------

class TestApplyAdapters:
    def test_bot_field_adapter_pair(self):
        read, write = get_apply_adapter("bot_field")
        assert callable(read) and callable(write)

    def test_skill_field_adapter_pair(self):
        read, write = get_apply_adapter("skill_field")
        assert callable(read) and callable(write)

    def test_exec_adapter_pair(self):
        read, write = get_apply_adapter("exec")
        assert callable(read) and callable(write)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="unsupported target.kind"):
            get_apply_adapter("nonsense")
