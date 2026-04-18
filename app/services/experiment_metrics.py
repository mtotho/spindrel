"""Experiment metric library — pure functions used by the autoresearch harness.

Each metric scores a list of per-case eval captures and returns a structured
result. The harness composes a `primary` metric (the scalar that's
hill-climbed) with zero or more `guards` (independent metrics whose
min_pass / max thresholds can reject a variant even if its primary improves).

A variant is **valid** iff every guard passes. Invalid variants are still
recorded in history (with guard failures) so the proposer agent can learn
from them, but they cannot become `current_best`.

Metric kinds shipped in v1:
- llm_judge_rubric          (LLM judge with caller-supplied rubric)
- tool_selection_accuracy   (was the right tool the first call?)
- regex_match               (response_text matches a pattern)
- schema_compliance         (response parses against a JSON schema)
- token_count_under         (cost / brevity guard, supports baseline-relative)
- exec_exit_code            (for `exec` evaluator results)
"""
from __future__ import annotations

import json
import logging
import re
import statistics
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Threshold expression resolution
# ---------------------------------------------------------------------------

_BASELINE_EXPR_RE = re.compile(
    r"^\s*baseline\s*([+\-*/])\s*([0-9]*\.?[0-9]+)\s*$"
)


def resolve_threshold(value: Any, baseline: float | None) -> float | None:
    """Resolve a threshold value that may be literal, baseline-relative, or None.

    Accepted forms:
      - None            -> None (no threshold)
      - 0.8 / "0.8"     -> 0.8
      - "baseline"      -> baseline value
      - "baseline + 0.1", "baseline - 0.5", "baseline * 1.2", "baseline / 2"
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        raise ValueError(f"unsupported threshold value type: {type(value).__name__}")
    s = value.strip()
    if not s:
        return None
    if s.lower() == "baseline":
        if baseline is None:
            raise ValueError("threshold references baseline but no baseline supplied")
        return float(baseline)
    m = _BASELINE_EXPR_RE.match(s)
    if m:
        if baseline is None:
            raise ValueError(f"threshold '{s}' references baseline but no baseline supplied")
        op, num = m.group(1), float(m.group(2))
        b = float(baseline)
        return {"+": b + num, "-": b - num, "*": b * num, "/": b / num if num else float("inf")}[op]
    # Bare numeric string
    try:
        return float(s)
    except ValueError as e:
        raise ValueError(f"could not parse threshold '{value}'") from e


# ---------------------------------------------------------------------------
# Per-case capture access helpers
# ---------------------------------------------------------------------------

def _get_field(captured: dict, field: str) -> Any:
    """Read a possibly-nested field from a per-case capture.

    Supports dotted paths and list indexing: ``tool_calls[0].name``.
    Returns None when any segment is missing.
    """
    if not field:
        return None
    obj: Any = captured
    parts = re.split(r"\.|\[(\d+)\]", field)
    for raw in parts:
        if raw is None or raw == "":
            continue
        if raw.isdigit():
            try:
                obj = obj[int(raw)]
            except (IndexError, TypeError, KeyError):
                return None
        else:
            if isinstance(obj, dict):
                obj = obj.get(raw)
            else:
                return None
        if obj is None:
            return None
    return obj


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def metric_tool_selection_accuracy(
    cases: list[dict],
    args: dict,
) -> dict:
    """Score: fraction of cases where the bot's first tool call matched the
    expected tool.

    Per-case input shape:
      {
        "case": {"input": "...", "expected_tool": "HassTurnOn"},  # gold
        "captured": {"tool_calls": [{"name": "HassTurnOn", "args": {...}}], ...}
      }

    Args:
      field: case-key holding the truth (default "expected_tool")
      score_first_call_only: if True (default), only the first tool counts;
          if False, give credit if the expected tool appears anywhere.
      partial_credit_for_either_of: when expected is a list (ambiguous),
          score this fraction (default 0.5) when the bot picked any of them.
    """
    field = args.get("field", "expected_tool")
    first_only = args.get("score_first_call_only", True)
    partial = float(args.get("partial_credit_for_either_of", 0.5))

    per_case: list[dict] = []
    for entry in cases:
        captured = entry.get("captured") or {}
        case = entry.get("case") or {}
        expected = case.get(field)
        tool_calls = captured.get("tool_calls") or []
        called = [tc.get("name") for tc in tool_calls if isinstance(tc, dict)]

        if expected is None:
            per_case.append({"score": 0.0, "reason": f"case missing field '{field}'"})
            continue

        if isinstance(expected, list):
            target_set = {str(x) for x in expected}
            if first_only:
                hit = bool(called) and called[0] in target_set
            else:
                hit = any(c in target_set for c in called)
            score = partial if hit else 0.0
            per_case.append({
                "score": score,
                "reason": f"either-of {sorted(target_set)} {'hit' if hit else 'miss'} (called={called[:3]})",
            })
        else:
            target = str(expected)
            if first_only:
                hit = bool(called) and called[0] == target
            else:
                hit = target in called
            per_case.append({
                "score": 1.0 if hit else 0.0,
                "reason": f"expected={target} {'hit' if hit else 'miss'} (called={called[:3]})",
            })

    aggregate = (
        statistics.mean(c["score"] for c in per_case) if per_case else 0.0
    )
    return {"per_case": per_case, "aggregate": aggregate}


def metric_regex_match(cases: list[dict], args: dict) -> dict:
    """Score: fraction of cases whose captured field matches a regex.

    Args:
      pattern: regex (required)
      field: dotted path into capture (default "response_text")
      flags: "i" / "s" / "m" combinations (default "")
    """
    pattern = args.get("pattern")
    if not pattern:
        raise ValueError("regex_match requires 'pattern'")
    field = args.get("field", "response_text")
    flag_str = args.get("flags", "")
    flags = 0
    if "i" in flag_str: flags |= re.IGNORECASE
    if "s" in flag_str: flags |= re.DOTALL
    if "m" in flag_str: flags |= re.MULTILINE
    rx = re.compile(pattern, flags)

    per_case = []
    for entry in cases:
        captured = entry.get("captured") or {}
        val = _get_field(captured, field)
        if val is None:
            per_case.append({"score": 0.0, "reason": f"field '{field}' missing"})
            continue
        text = val if isinstance(val, str) else json.dumps(val)
        hit = bool(rx.search(text))
        per_case.append({
            "score": 1.0 if hit else 0.0,
            "reason": f"regex {'matched' if hit else 'no-match'}",
        })
    aggregate = statistics.mean(c["score"] for c in per_case) if per_case else 0.0
    return {"per_case": per_case, "aggregate": aggregate}


def metric_schema_compliance(cases: list[dict], args: dict) -> dict:
    """Score: fraction of cases whose response_text parses as JSON conforming
    to the supplied schema.

    Args:
      json_schema: inline jsonschema dict (required unless schema_ref given)
      schema_ref: name of a registered shared schema (resolved by caller; v1
          accepts but does not yet resolve named refs — falls back to raw shape)
      field: dotted path into capture (default "response_text")
    """
    schema = args.get("json_schema")
    if schema is None and "schema_ref" not in args:
        raise ValueError("schema_compliance requires 'json_schema' or 'schema_ref'")
    field = args.get("field", "response_text")

    try:
        from jsonschema import Draft7Validator  # type: ignore
        validator: Any = Draft7Validator(schema) if schema else None
    except ImportError:
        validator = None

    per_case = []
    for entry in cases:
        captured = entry.get("captured") or {}
        val = _get_field(captured, field)
        if val is None:
            per_case.append({"score": 0.0, "reason": f"field '{field}' missing"})
            continue
        text = val if isinstance(val, str) else json.dumps(val)
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError) as e:
            per_case.append({"score": 0.0, "reason": f"not valid JSON: {e}"})
            continue
        if validator is None:
            # Best-effort shape check: just verify it parses
            per_case.append({"score": 1.0, "reason": "parsed (no schema validator)"})
            continue
        errors = list(validator.iter_errors(parsed))
        if errors:
            per_case.append({
                "score": 0.0,
                "reason": f"schema errors: {'; '.join(e.message for e in errors[:3])}",
            })
        else:
            per_case.append({"score": 1.0, "reason": "schema ok"})
    aggregate = statistics.mean(c["score"] for c in per_case) if per_case else 0.0
    return {"per_case": per_case, "aggregate": aggregate}


def metric_token_count_under(cases: list[dict], args: dict) -> dict:
    """Cost / brevity metric. Aggregate is the *average* token count
    (lower-is-better). Threshold args (p50_max, p95_max, mean_max) apply at
    guard-resolution time, not inside this metric.

    Args:
      field: dotted path into capture (default "token_count")
    """
    field = args.get("field", "token_count")
    counts: list[float] = []
    per_case = []
    for entry in cases:
        captured = entry.get("captured") or {}
        val = _get_field(captured, field)
        if not isinstance(val, (int, float)):
            per_case.append({"score": 0.0, "reason": f"field '{field}' missing or not numeric"})
            continue
        counts.append(float(val))
        per_case.append({"score": float(val), "reason": f"{int(val)} tokens"})
    aggregate = statistics.mean(counts) if counts else 0.0
    extras: dict = {}
    if counts:
        sorted_counts = sorted(counts)
        n = len(sorted_counts)
        extras["p50"] = sorted_counts[n // 2]
        extras["p95"] = sorted_counts[min(int(n * 0.95), n - 1)]
        extras["mean"] = aggregate
        extras["max"] = sorted_counts[-1]
    return {"per_case": per_case, "aggregate": aggregate, "extras": extras}


def metric_exec_exit_code(cases: list[dict], args: dict) -> dict:
    """Score: fraction of cases whose exec exit_code matched expected.

    Args:
      expected: int (default 0)
      field: dotted path into capture (default "exit_code")
    """
    expected = int(args.get("expected", 0))
    field = args.get("field", "exit_code")
    per_case = []
    for entry in cases:
        captured = entry.get("captured") or {}
        val = _get_field(captured, field)
        try:
            code = int(val) if val is not None else None
        except (ValueError, TypeError):
            code = None
        hit = code == expected
        per_case.append({
            "score": 1.0 if hit else 0.0,
            "reason": f"exit_code={code} expected={expected}",
        })
    aggregate = statistics.mean(c["score"] for c in per_case) if per_case else 0.0
    return {"per_case": per_case, "aggregate": aggregate}


# llm_judge_rubric is async — fans out one judge call per case. It's defined
# below the registry so the registry can stay a plain dict of sync callables.
# The runner detects the async signature and awaits.

async def metric_llm_judge_rubric(cases: list[dict], args: dict) -> dict:
    """Score: LLM-judge each case against a caller-supplied rubric.

    Args:
      rubric: free-text scoring instructions (required). Should ask for JSON.
      score_field: which JSON field in the judge's reply is the scalar score.
          Default "overall". If absent, falls back to first numeric field.
      aggregate: "mean" (default) | "min" | "median"
      judge_model: optional model override; defaults to a fast judge model
          (currently haiku — caller can override via env or args)
    """
    rubric = args.get("rubric")
    if not rubric:
        raise ValueError("llm_judge_rubric requires 'rubric'")
    score_field = args.get("score_field", "overall")
    aggregate_mode = args.get("aggregate", "mean")

    # Lazy import — keeps the metric library importable in test contexts that
    # don't have the LLM stack wired up.
    from app.services.judge import judge_single_case  # local helper, see below

    per_case_results: list[dict] = []
    for entry in cases:
        captured = entry.get("captured") or {}
        case = entry.get("case") or {}
        try:
            judgment = await judge_single_case(rubric, case, captured, args)
        except Exception as e:
            per_case_results.append({"score": 0.0, "reason": f"judge error: {e}"})
            continue
        # Extract scalar score from judge's structured output
        score = _extract_judge_score(judgment, score_field)
        per_case_results.append({
            "score": float(score) if score is not None else 0.0,
            "reason": json.dumps(judgment)[:300] if isinstance(judgment, dict) else str(judgment)[:300],
        })

    scores = [c["score"] for c in per_case_results]
    if not scores:
        aggregate = 0.0
    elif aggregate_mode == "min":
        aggregate = min(scores)
    elif aggregate_mode == "median":
        aggregate = statistics.median(scores)
    else:
        aggregate = statistics.mean(scores)
    return {"per_case": per_case_results, "aggregate": aggregate}


def _extract_judge_score(judgment: Any, preferred_field: str) -> float | None:
    """Pull a numeric score out of a judge's reply. Tries preferred_field,
    then any numeric field, then None."""
    if isinstance(judgment, (int, float)):
        return float(judgment)
    if not isinstance(judgment, dict):
        return None
    val = judgment.get(preferred_field)
    if isinstance(val, (int, float)):
        return float(val)
    for v in judgment.values():
        if isinstance(v, (int, float)):
            return float(v)
    return None


# ---------------------------------------------------------------------------
# Metric registry
# ---------------------------------------------------------------------------

_SYNC_METRICS: dict[str, Callable[[list[dict], dict], dict]] = {
    "tool_selection_accuracy": metric_tool_selection_accuracy,
    "regex_match": metric_regex_match,
    "schema_compliance": metric_schema_compliance,
    "token_count_under": metric_token_count_under,
    "exec_exit_code": metric_exec_exit_code,
}

_ASYNC_METRICS = {
    "llm_judge_rubric": metric_llm_judge_rubric,
}


def list_metric_kinds() -> list[str]:
    return sorted(set(_SYNC_METRICS) | set(_ASYNC_METRICS))


async def run_metric(kind: str, cases: list[dict], args: dict) -> dict:
    """Dispatch a metric by kind. Always async-callable; sync metrics run
    inline."""
    if kind in _ASYNC_METRICS:
        return await _ASYNC_METRICS[kind](cases, args)
    if kind in _SYNC_METRICS:
        return _SYNC_METRICS[kind](cases, args)
    raise ValueError(f"unknown metric kind '{kind}'. Available: {list_metric_kinds()}")


# ---------------------------------------------------------------------------
# Guard resolution
# ---------------------------------------------------------------------------

# Threshold-key → (compare_fn, default_baseline_field)
# compare_fn(value, threshold) -> True iff guard passes
_GUARD_KEYS: dict[str, Callable[[float, float], bool]] = {
    "min_pass": lambda v, t: v >= t,
    "max": lambda v, t: v <= t,
    "p50_max": lambda v, t: v <= t,
    "p95_max": lambda v, t: v <= t,
    "mean_max": lambda v, t: v <= t,
}


def _resolve_guard_outcome(
    guard_args: dict,
    metric_result: dict,
    baseline_aggregate: float | None,
) -> tuple[bool, float, str]:
    """Decide whether a guard passed. Returns (passed, observed_value, reason).

    Pulls the right value from metric_result depending on which threshold key
    is set. p50_max/p95_max/mean_max read from result['extras']; everything
    else compares against result['aggregate'].
    """
    extras = metric_result.get("extras") or {}
    aggregate = float(metric_result.get("aggregate", 0.0))
    # Find the first threshold key present
    for key, cmp in _GUARD_KEYS.items():
        if key not in guard_args:
            continue
        threshold = resolve_threshold(guard_args[key], baseline_aggregate)
        if threshold is None:
            return True, aggregate, f"no threshold for {key}"
        if key == "p50_max":
            value = float(extras.get("p50", aggregate))
        elif key == "p95_max":
            value = float(extras.get("p95", aggregate))
        elif key == "mean_max":
            value = float(extras.get("mean", aggregate))
        else:
            value = aggregate
        passed = cmp(value, threshold)
        return passed, value, f"{key} {value:.4f} vs threshold {threshold:.4f}"
    # No threshold specified → guard always passes (informational only)
    return True, aggregate, "no threshold specified"


# ---------------------------------------------------------------------------
# Top-level runner: primary + guards
# ---------------------------------------------------------------------------

async def score_eval_results(
    metric_block: dict,
    eval_results: list[dict],
    baseline: dict | None = None,
) -> dict:
    """Score a list of per-case eval results against a primary metric and any
    guards. Returns a structured dict suitable for serialization to
    history.jsonl.

    metric_block shape:
      {
        "primary": {"kind": "tool_selection_accuracy", "args": {...}},
        "guards": [
          {"name": "still_polite", "kind": "llm_judge_rubric", "args": {...},
           "min_pass": "baseline - 0.5"},
          ...
        ]
      }

    eval_results shape (one per case):
      [
        {"case": {...}, "captured": {...}, "error": null | str},
        ...
      ]

    baseline shape (optional, used to resolve baseline-relative thresholds):
      {"primary": <float>, "guards": {"name": <float>, ...}}
    """
    primary_def = metric_block.get("primary") or {}
    primary_kind = primary_def.get("kind")
    if not primary_kind:
        raise ValueError("metric_block.primary.kind is required")
    primary_args = primary_def.get("args") or {}

    primary_result = await run_metric(primary_kind, eval_results, primary_args)
    primary_aggregate = float(primary_result.get("aggregate", 0.0))

    guards_in = metric_block.get("guards") or []
    baseline_guards = (baseline or {}).get("guards") or {}
    guard_outcomes: list[dict] = []
    variant_valid = True

    for guard_def in guards_in:
        name = guard_def.get("name") or guard_def.get("kind", "guard")
        kind = guard_def.get("kind")
        if not kind:
            guard_outcomes.append({
                "name": name, "passed": False, "value": None,
                "reason": "missing kind",
            })
            variant_valid = False
            continue
        args = guard_def.get("args") or {}
        try:
            gresult = await run_metric(kind, eval_results, args)
        except Exception as e:
            guard_outcomes.append({
                "name": name, "passed": False, "value": None,
                "reason": f"metric error: {e}",
            })
            variant_valid = False
            continue
        # Pull threshold keys directly off the guard def (not args) — that's
        # where the spec puts them. Also accept threshold under args for
        # backwards-symmetry with single-metric calls.
        thresh_args: dict = {}
        for tk in _GUARD_KEYS:
            if tk in guard_def:
                thresh_args[tk] = guard_def[tk]
            elif tk in args:
                thresh_args[tk] = args[tk]
        baseline_for_guard = baseline_guards.get(name)
        passed, value, reason = _resolve_guard_outcome(
            thresh_args, gresult, baseline_for_guard,
        )
        guard_outcomes.append({
            "name": name, "kind": kind, "passed": passed,
            "value": value, "reason": reason,
            "extras": gresult.get("extras"),
        })
        if not passed:
            variant_valid = False

    return {
        "primary": {
            "kind": primary_kind,
            "aggregate": primary_aggregate,
            "per_case": primary_result.get("per_case", []),
        },
        "guards": guard_outcomes,
        "variant_valid": variant_valid,
    }


# ---------------------------------------------------------------------------
# Apply adapters — resolve target.kind to read/write functions
# ---------------------------------------------------------------------------

def get_apply_adapter(target_kind: str):
    """Return (read_fn, write_fn) for a target kind.

    read_fn(target: dict) -> Awaitable[Any]   - current value
    write_fn(target: dict, value: Any) -> Awaitable[dict]  - apply result

    v1 supports: bot_field, skill_field, exec
    """
    if target_kind == "bot_field":
        return _bot_field_read, _bot_field_write
    if target_kind == "skill_field":
        return _skill_field_read, _skill_field_write
    if target_kind == "exec":
        return _exec_read, _exec_write
    raise ValueError(f"unsupported target.kind '{target_kind}'")


async def _bot_field_read(target: dict) -> Any:
    from app.tools.registry import call_local_tool
    bot_id = target["bot_id"]
    field = target["field"]
    raw = await call_local_tool("call_api", json.dumps({
        "method": "GET", "path": f"/api/v1/admin/bots/{bot_id}",
    }))
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return body.get(field)


async def _bot_field_write(target: dict, value: Any) -> dict:
    from app.tools.registry import call_local_tool
    bot_id = target["bot_id"]
    field = target["field"]
    raw = await call_local_tool("call_api", json.dumps({
        "method": "PATCH", "path": f"/api/v1/admin/bots/{bot_id}",
        "body": {field: value},
    }))
    return {"raw": raw}


async def _skill_field_read(target: dict) -> Any:
    from app.tools.registry import call_local_tool
    skill_id = target["skill_id"]
    field = target["field"]
    raw = await call_local_tool("call_api", json.dumps({
        "method": "GET", "path": f"/api/v1/admin/skills/{skill_id}",
    }))
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return body.get(field)


async def _skill_field_write(target: dict, value: Any) -> dict:
    from app.tools.registry import call_local_tool
    skill_id = target["skill_id"]
    field = target["field"]
    raw = await call_local_tool("call_api", json.dumps({
        "method": "PATCH", "path": f"/api/v1/admin/skills/{skill_id}",
        "body": {field: value},
    }))
    return {"raw": raw}


async def _exec_read(target: dict) -> Any:
    # exec targets don't have a "current value" per se — the read is a noop.
    return None


async def _exec_write(target: dict, value: Any) -> dict:
    # value is a dict like {"apply_cmd": "..."} or just a string.
    cmd = target.get("apply_cmd") or (value if isinstance(value, str) else value.get("apply_cmd"))
    if not cmd:
        raise ValueError("exec target requires apply_cmd in target or value")
    # Run via shell — caller's responsibility to ensure safety.
    import asyncio
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return {
        "exit_code": proc.returncode,
        "stdout": stdout.decode("utf-8", errors="replace")[:4000],
        "stderr": stderr.decode("utf-8", errors="replace")[:4000],
    }
