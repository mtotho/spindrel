"""Local tools for the autoresearch / experiments harness.

These tools are pipeline-callable (`type: tool, tool_name: ...`) and provide
the workspace-file IO + scoring primitives the experiment.iterate / .commit
pipelines depend on.

Tool inventory:
  - read_experiment_state    Load spec + history + current_best for an exp_id.
  - append_experiment_history  Append one variant record to history.jsonl.
  - update_current_best      Overwrite current_best.json if improved.
  - score_eval_results_tool  Wrap experiment_metrics.score_eval_results.
  - check_budget             Check remaining budget vs spec, return BUDGET_OK / BUDGET_EXHAUSTED.
  - load_experiment_template Load a packaged template from app/data/experiment_templates.

All of these read/write inside the calling task's channel workspace
(`{channel_workspace}/data/experiments/<exp_id>/`).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

from app.agent.context import current_bot_id, current_channel_id
from app.tools.registry import register

logger = logging.getLogger(__name__)


_EXPERIMENT_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "experiment_templates"
)


# ---------------------------------------------------------------------------
# Path resolution — every experiment lives under the channel workspace.
# ---------------------------------------------------------------------------

def _resolve_experiment_dir(experiment_id: str) -> tuple[str, str] | None:
    """Return (channel_id, abs_dir) for this experiment, or None if context
    can't be resolved.

    The directory may not exist yet; callers handle creation explicitly.
    """
    bot_id = current_bot_id.get()
    ch = current_channel_id.get()
    ch_id = str(ch) if ch else None
    if not bot_id or not ch_id:
        return None
    from app.agent.bots import get_bot
    from app.services.channel_workspace import (
        ensure_channel_workspace, get_channel_workspace_root,
    )
    bot = get_bot(bot_id)
    if not bot:
        return None
    ensure_channel_workspace(ch_id, bot)
    ws_root = get_channel_workspace_root(ch_id, bot)
    safe_id = os.path.basename(experiment_id.strip())
    if not safe_id or safe_id.startswith("."):
        return None
    abs_dir = os.path.join(ws_root, "data", "experiments", safe_id)
    return ch_id, abs_dir


def _safe_jsonl_read(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        return []
    return out


# ---------------------------------------------------------------------------
# read_experiment_state
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "read_experiment_state",
        "description": (
            "Load the full state of an experiment: spec.yaml, baseline.json, "
            "history.jsonl, current_best.json. Returns a JSON object with all "
            "four (missing pieces are null/empty). Reads from the calling "
            "channel's workspace under data/experiments/<experiment_id>/."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "experiment_id": {"type": "string"},
            },
            "required": ["experiment_id"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True)
async def read_experiment_state(experiment_id: str) -> str:
    resolved = _resolve_experiment_dir(experiment_id)
    if not resolved:
        return json.dumps({"error": "no channel/bot context"})
    _, exp_dir = resolved
    spec = None
    spec_path = os.path.join(exp_dir, "spec.yaml")
    if os.path.isfile(spec_path):
        try:
            spec = yaml.safe_load(Path(spec_path).read_text())
        except Exception as e:
            return json.dumps({"error": f"spec.yaml unreadable: {e}"})
    baseline = None
    bp = os.path.join(exp_dir, "baseline.json")
    if os.path.isfile(bp):
        try:
            baseline = json.loads(Path(bp).read_text())
        except Exception:
            baseline = None
    current_best = None
    cb = os.path.join(exp_dir, "current_best.json")
    if os.path.isfile(cb):
        try:
            current_best = json.loads(Path(cb).read_text())
        except Exception:
            current_best = None
    history = _safe_jsonl_read(os.path.join(exp_dir, "history.jsonl"))
    return json.dumps({
        "experiment_id": experiment_id,
        "spec": spec,
        "baseline": baseline,
        "current_best": current_best,
        "history": history,
        "iterations_so_far": len(history),
    })


# ---------------------------------------------------------------------------
# append_experiment_history
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "append_experiment_history",
        "description": (
            "Append a single variant record to the experiment's history.jsonl. "
            "The record should include at minimum: variant (the value tried), "
            "scores (output of score_eval_results), iteration_n, and "
            "rationale. Caller passes record as a JSON string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "experiment_id": {"type": "string"},
                "record_json": {
                    "type": "string",
                    "description": "JSON-serialized record to append.",
                },
            },
            "required": ["experiment_id", "record_json"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True)
async def append_experiment_history(experiment_id: str, record_json: str) -> str:
    resolved = _resolve_experiment_dir(experiment_id)
    if not resolved:
        return json.dumps({"error": "no channel/bot context"})
    _, exp_dir = resolved
    try:
        record = json.loads(record_json)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": f"record_json invalid: {e}"})
    if not isinstance(record, dict):
        return json.dumps({"error": "record must be a JSON object"})
    os.makedirs(exp_dir, exist_ok=True)
    path = os.path.join(exp_dir, "history.jsonl")
    line = json.dumps(record, default=str)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return json.dumps({"appended": True, "path": f"data/experiments/{os.path.basename(exp_dir)}/history.jsonl"})


# ---------------------------------------------------------------------------
# update_current_best
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "update_current_best",
        "description": (
            "Set current_best.json for an experiment. The pipeline is "
            "responsible for deciding *whether* to call this — typically only "
            "when the new variant is valid (all guards passed) AND its "
            "primary score exceeds the existing current_best. Pass the full "
            "best record as a JSON string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "experiment_id": {"type": "string"},
                "record_json": {"type": "string"},
            },
            "required": ["experiment_id", "record_json"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True)
async def update_current_best(experiment_id: str, record_json: str) -> str:
    resolved = _resolve_experiment_dir(experiment_id)
    if not resolved:
        return json.dumps({"error": "no channel/bot context"})
    _, exp_dir = resolved
    try:
        record = json.loads(record_json)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": f"record_json invalid: {e}"})
    os.makedirs(exp_dir, exist_ok=True)
    path = os.path.join(exp_dir, "current_best.json")
    Path(path).write_text(json.dumps(record, indent=2, default=str))
    return json.dumps({"updated": True})


# ---------------------------------------------------------------------------
# build_experiment_record — assemble a canonical iteration record from the
# parts a pipeline has in hand (variant + scores + iteration index). Exists
# because pipeline templating returns scalar strings un-JSON-quoted, so
# hand-constructing a JSON object in YAML would break on escape edge cases.
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "build_experiment_record",
        "description": (
            "Assemble a canonical iteration record for an experiment. Returns "
            "the record as a JSON string suitable for feeding into "
            "append_experiment_history / update_best_if_improved."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "iteration_n": {"type": "string", "description": "0-based iteration index (string for templating compatibility)."},
                "variant_prompt": {"type": "string"},
                "variant_rationale": {"type": "string"},
                "scores_json": {"type": "string", "description": "JSON from score_eval_results."},
            },
            "required": ["iteration_n", "variant_prompt", "scores_json"],
        },
    },
})
async def build_experiment_record(
    iteration_n: str,
    variant_prompt: str,
    scores_json: str,
    variant_rationale: str = "",
) -> str:
    from datetime import datetime, timezone
    try:
        scores = json.loads(scores_json)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": f"scores_json invalid: {e}"})
    try:
        n = int(str(iteration_n).strip())
    except (ValueError, TypeError):
        n = 0
    record = {
        "iteration_n": n,
        "variant": {
            "prompt": variant_prompt,
            "rationale": variant_rationale,
        },
        "scores": scores,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(record)


# ---------------------------------------------------------------------------
# update_best_if_improved — pipeline-friendly wrapper that reads current_best
# and overwrites iff (variant_valid AND primary > existing primary).
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "update_best_if_improved",
        "description": (
            "Read current_best.json for this experiment. If the supplied "
            "candidate is valid (all guards passed) and its primary score "
            "strictly exceeds the current best's primary (or there is no "
            "current_best yet), overwrite current_best.json with the "
            "candidate. Returns {updated: bool, reason: str, previous: dict|null, "
            "current: dict}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "experiment_id": {"type": "string"},
                "candidate_json": {
                    "type": "string",
                    "description": (
                        "JSON with at least {variant, scores, iteration_n}. "
                        "scores.variant_valid and scores.primary.aggregate are "
                        "read; candidate is written verbatim if it wins."
                    ),
                },
            },
            "required": ["experiment_id", "candidate_json"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True)
async def update_best_if_improved(experiment_id: str, candidate_json: str) -> str:
    resolved = _resolve_experiment_dir(experiment_id)
    if not resolved:
        return json.dumps({"error": "no channel/bot context"})
    _, exp_dir = resolved
    try:
        candidate = json.loads(candidate_json)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": f"candidate_json invalid: {e}"})
    if not isinstance(candidate, dict):
        return json.dumps({"error": "candidate must be a JSON object"})

    scores = candidate.get("scores") or {}
    if not scores.get("variant_valid", False):
        return json.dumps({
            "updated": False,
            "reason": "candidate invalid (one or more guards failed)",
        })
    new_primary = (scores.get("primary") or {}).get("aggregate")
    if not isinstance(new_primary, (int, float)):
        return json.dumps({
            "updated": False,
            "reason": "candidate missing scores.primary.aggregate",
        })

    best_path = os.path.join(exp_dir, "current_best.json")
    previous = None
    if os.path.isfile(best_path):
        try:
            previous = json.loads(Path(best_path).read_text())
        except (ValueError, TypeError):
            previous = None

    if previous is not None:
        prev_primary = ((previous.get("scores") or {}).get("primary") or {}).get("aggregate")
        if isinstance(prev_primary, (int, float)) and float(new_primary) <= float(prev_primary):
            return json.dumps({
                "updated": False,
                "reason": f"no improvement ({new_primary} <= {prev_primary})",
                "previous": previous,
            })

    os.makedirs(exp_dir, exist_ok=True)
    Path(best_path).write_text(json.dumps(candidate, indent=2, default=str))
    return json.dumps({
        "updated": True,
        "reason": "new best",
        "previous": previous,
        "current": candidate,
    })


# ---------------------------------------------------------------------------
# score_eval_results_tool
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "score_eval_results",
        "description": (
            "Score a list of per-case eval results against a primary metric "
            "and any guards. Returns {primary, guards, variant_valid}. "
            "Pass metric_block_json (full primary+guards spec) and "
            "eval_results_json (list of {case, captured, error}) as JSON "
            "strings. Optional baseline_json for baseline-relative thresholds."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "metric_block_json": {"type": "string"},
                "eval_results_json": {"type": "string"},
                "baseline_json": {"type": "string"},
            },
            "required": ["metric_block_json", "eval_results_json"],
        },
    },
})
async def score_eval_results_tool(
    metric_block_json: str,
    eval_results_json: str,
    baseline_json: str | None = None,
) -> str:
    from app.services.experiment_metrics import score_eval_results
    try:
        metric_block = json.loads(metric_block_json)
        eval_results = json.loads(eval_results_json)
    except (ValueError, TypeError) as e:
        return json.dumps({"error": f"json parse: {e}"})
    baseline = None
    if baseline_json:
        try:
            baseline = json.loads(baseline_json)
        except (ValueError, TypeError):
            baseline = None
    try:
        out = await score_eval_results(metric_block, eval_results, baseline)
    except Exception as e:
        logger.exception("score_eval_results failed")
        return json.dumps({"error": str(e)})
    return json.dumps(out, default=str)


# ---------------------------------------------------------------------------
# check_budget
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "check_experiment_budget",
        "description": (
            "Check whether an experiment has budget remaining. Reads spec + "
            "history. Returns {status: 'BUDGET_OK' | 'BUDGET_EXHAUSTED', "
            "iterations_used, max_iterations, reason}. Use as a `when:` gate "
            "or `fail_if:` upstream of further iteration steps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "experiment_id": {"type": "string"},
            },
            "required": ["experiment_id"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True)
async def check_experiment_budget(experiment_id: str) -> str:
    resolved = _resolve_experiment_dir(experiment_id)
    if not resolved:
        return json.dumps({"error": "no channel/bot context"})
    _, exp_dir = resolved
    spec_path = os.path.join(exp_dir, "spec.yaml")
    if not os.path.isfile(spec_path):
        return json.dumps({"status": "BUDGET_EXHAUSTED", "reason": "spec.yaml missing"})
    try:
        spec = yaml.safe_load(Path(spec_path).read_text()) or {}
    except Exception as e:
        return json.dumps({"status": "BUDGET_EXHAUSTED", "reason": f"spec unreadable: {e}"})
    budget = (spec.get("budget") or {})
    max_iter = int(budget.get("max_iterations", 0)) or None
    history = _safe_jsonl_read(os.path.join(exp_dir, "history.jsonl"))
    used = len(history)
    if max_iter is not None and used >= max_iter:
        return json.dumps({
            "status": "BUDGET_EXHAUSTED",
            "iterations_used": used,
            "max_iterations": max_iter,
            "reason": f"hit max_iterations={max_iter}",
        })
    # Token / wallclock budgets are advisory in v1 — we record but don't gate.
    return json.dumps({
        "status": "BUDGET_OK",
        "iterations_used": used,
        "max_iterations": max_iter,
        "remaining": (max_iter - used) if max_iter is not None else None,
    })


# ---------------------------------------------------------------------------
# load_experiment_template
# ---------------------------------------------------------------------------

@register({
    "type": "function",
    "function": {
        "name": "load_experiment_template",
        "description": (
            "Load a packaged experiment template by name and substitute "
            "{{params.*}} placeholders. Returns the resulting spec as a "
            "YAML string. Used by experiment.create when params.template is "
            "set."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "template": {"type": "string"},
                "substitutions_json": {
                    "type": "string",
                    "description": (
                        "JSON object of {param_name: value} pairs to "
                        "substitute into {{params.*}} placeholders."
                    ),
                },
            },
            "required": ["template"],
        },
    },
})
async def load_experiment_template(
    template: str,
    substitutions_json: str | None = None,
) -> str:
    safe = os.path.basename(template.strip())
    if not safe.endswith(".yaml"):
        safe = safe + ".yaml"
    path = _EXPERIMENT_TEMPLATE_DIR / safe
    if not path.is_file():
        return json.dumps({"error": f"template not found: {safe}"})
    text = path.read_text()
    subs: dict = {}
    if substitutions_json:
        try:
            subs = json.loads(substitutions_json) or {}
        except (ValueError, TypeError):
            subs = {}
    for k, v in subs.items():
        text = text.replace("{{params." + str(k) + "}}", str(v))
    return text


def _experiment_template_dir() -> Path:
    """Test hook — letting tests inspect / monkeypatch the directory."""
    return _EXPERIMENT_TEMPLATE_DIR
