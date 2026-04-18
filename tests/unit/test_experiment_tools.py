"""Unit tests for app.tools.local.experiment_tools.

Covers the workspace-file helpers the `experiment.iterate` pipeline depends
on: read_experiment_state, check_experiment_budget,
append_experiment_history, update_best_if_improved, build_experiment_record.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from app.agent.context import current_bot_id, current_channel_id


@pytest.fixture
def exp_context():
    """Mount a temp directory as the channel workspace root, bind bot/channel
    ContextVars, and yield (experiment_id, abs_exp_dir, tmp_root)."""
    bot = SimpleNamespace(id="sprout")
    with tempfile.TemporaryDirectory() as tmp:
        exp_id = "phase2-demo"

        # Both get_channel_workspace_root and ensure_channel_workspace are
        # imported *inside* _resolve_experiment_dir, so patching at the source
        # module is the durable approach.
        with patch("app.services.channel_workspace.get_channel_workspace_root", return_value=tmp), \
             patch("app.services.channel_workspace.ensure_channel_workspace"), \
             patch("app.agent.bots.get_bot", return_value=bot):
            ch_token = current_channel_id.set(uuid.uuid4())
            bot_token = current_bot_id.set("sprout")
            try:
                yield exp_id, os.path.join(tmp, "data", "experiments", exp_id), tmp
            finally:
                current_channel_id.reset(ch_token)
                current_bot_id.reset(bot_token)


@pytest.fixture
def seeded_spec(exp_context):
    """Seed a minimal spec.yaml at the experiment dir."""
    exp_id, exp_dir, _ = exp_context
    os.makedirs(exp_dir, exist_ok=True)
    spec = {
        "id": exp_id,
        "target": {"kind": "bot_field", "bot_id": "sprout", "field": "system_prompt"},
        "cases": {"source": "literal", "items": [{"input": "hi"}]},
        "metric": {
            "primary": {"kind": "regex_match", "args": {"pattern": ".+"}},
            "guards": [],
        },
        "budget": {"max_iterations": 3},
    }
    Path(exp_dir, "spec.yaml").write_text(yaml.safe_dump(spec))
    return spec


# ---------------------------------------------------------------------------
# read_experiment_state
# ---------------------------------------------------------------------------

class TestReadExperimentState:
    @pytest.mark.asyncio
    async def test_returns_null_pieces_when_dir_empty(self, exp_context):
        from app.tools.local.experiment_tools import read_experiment_state
        exp_id, exp_dir, _ = exp_context
        os.makedirs(exp_dir, exist_ok=True)
        out = json.loads(await read_experiment_state(exp_id))
        assert out["spec"] is None
        assert out["baseline"] is None
        assert out["history"] == []
        assert out["iterations_so_far"] == 0

    @pytest.mark.asyncio
    async def test_loads_spec_and_history(self, exp_context, seeded_spec):
        from app.tools.local.experiment_tools import read_experiment_state
        exp_id, exp_dir, _ = exp_context
        # seed a history row
        Path(exp_dir, "history.jsonl").write_text(json.dumps({"iteration_n": 0}) + "\n")
        out = json.loads(await read_experiment_state(exp_id))
        assert out["spec"]["target"]["bot_id"] == "sprout"
        assert out["iterations_so_far"] == 1
        assert out["history"][0]["iteration_n"] == 0


# ---------------------------------------------------------------------------
# check_experiment_budget
# ---------------------------------------------------------------------------

class TestCheckBudget:
    @pytest.mark.asyncio
    async def test_ok_when_no_history(self, exp_context, seeded_spec):
        from app.tools.local.experiment_tools import check_experiment_budget
        exp_id, _, _ = exp_context
        out = json.loads(await check_experiment_budget(exp_id))
        assert out["status"] == "BUDGET_OK"
        assert out["iterations_used"] == 0
        assert out["remaining"] == 3

    @pytest.mark.asyncio
    async def test_exhausted_when_history_full(self, exp_context, seeded_spec):
        from app.tools.local.experiment_tools import check_experiment_budget
        exp_id, exp_dir, _ = exp_context
        lines = [json.dumps({"iteration_n": i}) for i in range(3)]
        Path(exp_dir, "history.jsonl").write_text("\n".join(lines) + "\n")
        out = json.loads(await check_experiment_budget(exp_id))
        assert out["status"] == "BUDGET_EXHAUSTED"
        assert out["iterations_used"] == 3

    @pytest.mark.asyncio
    async def test_missing_spec_treated_as_exhausted(self, exp_context):
        from app.tools.local.experiment_tools import check_experiment_budget
        exp_id, exp_dir, _ = exp_context
        os.makedirs(exp_dir, exist_ok=True)
        out = json.loads(await check_experiment_budget(exp_id))
        assert out["status"] == "BUDGET_EXHAUSTED"
        assert "spec" in out["reason"].lower()


# ---------------------------------------------------------------------------
# build_experiment_record
# ---------------------------------------------------------------------------

class TestBuildExperimentRecord:
    @pytest.mark.asyncio
    async def test_canonical_shape(self):
        from app.tools.local.experiment_tools import build_experiment_record
        scores = {"primary": {"aggregate": 0.8}, "variant_valid": True}
        out = json.loads(await build_experiment_record(
            iteration_n="2",
            variant_prompt="Be polite.",
            variant_rationale="shorter",
            scores_json=json.dumps(scores),
        ))
        assert out["iteration_n"] == 2
        assert out["variant"]["prompt"] == "Be polite."
        assert out["variant"]["rationale"] == "shorter"
        assert out["scores"]["primary"]["aggregate"] == 0.8
        assert "created_at" in out

    @pytest.mark.asyncio
    async def test_malformed_scores_surfaces_error(self):
        from app.tools.local.experiment_tools import build_experiment_record
        out = json.loads(await build_experiment_record(
            iteration_n="0", variant_prompt="x", scores_json="not-json",
        ))
        assert "error" in out


# ---------------------------------------------------------------------------
# append_experiment_history
# ---------------------------------------------------------------------------

class TestAppendExperimentHistory:
    @pytest.mark.asyncio
    async def test_appends_line_per_call(self, exp_context, seeded_spec):
        from app.tools.local.experiment_tools import append_experiment_history
        exp_id, exp_dir, _ = exp_context
        for i in range(2):
            await append_experiment_history(
                exp_id, json.dumps({"iteration_n": i}),
            )
        content = Path(exp_dir, "history.jsonl").read_text().strip().splitlines()
        assert len(content) == 2
        assert json.loads(content[0])["iteration_n"] == 0
        assert json.loads(content[1])["iteration_n"] == 1


# ---------------------------------------------------------------------------
# update_best_if_improved
# ---------------------------------------------------------------------------

class TestUpdateBestIfImproved:
    @pytest.mark.asyncio
    async def test_writes_when_no_prior_best(self, exp_context, seeded_spec):
        from app.tools.local.experiment_tools import update_best_if_improved
        exp_id, exp_dir, _ = exp_context
        cand = {
            "iteration_n": 0,
            "variant": {"prompt": "v1"},
            "scores": {"primary": {"aggregate": 0.5}, "variant_valid": True},
        }
        out = json.loads(await update_best_if_improved(exp_id, json.dumps(cand)))
        assert out["updated"] is True
        saved = json.loads(Path(exp_dir, "current_best.json").read_text())
        assert saved["variant"]["prompt"] == "v1"

    @pytest.mark.asyncio
    async def test_rejects_invalid_variant(self, exp_context, seeded_spec):
        from app.tools.local.experiment_tools import update_best_if_improved
        exp_id, exp_dir, _ = exp_context
        cand = {
            "scores": {"primary": {"aggregate": 0.99}, "variant_valid": False},
        }
        out = json.loads(await update_best_if_improved(exp_id, json.dumps(cand)))
        assert out["updated"] is False
        assert "invalid" in out["reason"].lower()
        assert not Path(exp_dir, "current_best.json").exists()

    @pytest.mark.asyncio
    async def test_rejects_non_improvement(self, exp_context, seeded_spec):
        from app.tools.local.experiment_tools import update_best_if_improved
        exp_id, exp_dir, _ = exp_context
        incumbent = {
            "iteration_n": 0,
            "variant": {"prompt": "best"},
            "scores": {"primary": {"aggregate": 0.9}, "variant_valid": True},
        }
        Path(exp_dir, "current_best.json").write_text(json.dumps(incumbent))
        cand = {
            "iteration_n": 1,
            "variant": {"prompt": "worse"},
            "scores": {"primary": {"aggregate": 0.8}, "variant_valid": True},
        }
        out = json.loads(await update_best_if_improved(exp_id, json.dumps(cand)))
        assert out["updated"] is False
        assert "improvement" in out["reason"].lower()
        saved = json.loads(Path(exp_dir, "current_best.json").read_text())
        assert saved["variant"]["prompt"] == "best"

    @pytest.mark.asyncio
    async def test_overwrites_on_strict_improvement(self, exp_context, seeded_spec):
        from app.tools.local.experiment_tools import update_best_if_improved
        exp_id, exp_dir, _ = exp_context
        Path(exp_dir, "current_best.json").write_text(json.dumps({
            "scores": {"primary": {"aggregate": 0.5}, "variant_valid": True},
            "variant": {"prompt": "old"},
        }))
        cand = {
            "variant": {"prompt": "new"},
            "scores": {"primary": {"aggregate": 0.6}, "variant_valid": True},
        }
        out = json.loads(await update_best_if_improved(exp_id, json.dumps(cand)))
        assert out["updated"] is True
        saved = json.loads(Path(exp_dir, "current_best.json").read_text())
        assert saved["variant"]["prompt"] == "new"
