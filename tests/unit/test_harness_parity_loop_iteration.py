"""Unit tests for the harness-parity loop iteration runner.

Goals (no docker, no live stack, no e2e suite):
- ``refuse_inside_project_run`` exits cleanly when SPINDREL_PROJECT_RUN_GUARD=1
- env-file parser handles quotes, comments, blanks
- JUnit parser counts pass/fail/skip and lifts failure metadata
- ``lookup_spec_row`` finds the parity-matrix row by test name
- ``guess_owning_module`` routes well-known test name shapes
- ``render_report`` emits frontmatter + a Gaps section when there are failures
- ``write_report`` lands the artifact under the canonical-repo audits folder
- end-to-end: --junit dry-run path produces a report file
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import harness_parity_loop_iteration as mod


def test_refuse_inside_project_run_exits_when_guard_set(monkeypatch):
    monkeypatch.setenv("SPINDREL_PROJECT_RUN_GUARD", "1")
    with pytest.raises(SystemExit) as excinfo:
        mod.refuse_inside_project_run()
    assert excinfo.value.code == 78


def test_refuse_inside_project_run_passes_when_guard_unset(monkeypatch):
    monkeypatch.delenv("SPINDREL_PROJECT_RUN_GUARD", raising=False)
    mod.refuse_inside_project_run()


def test_load_env_file_parses_quoted_values_and_skips_comments(tmp_path):
    env = tmp_path / "x.env"
    env.write_text(
        '# comment\nFOO="bar"\nBAZ=qux\n\nQUOTED_SINGLE=\'hello world\'\nMISSING\n',
        encoding="utf-8",
    )
    data = mod.load_env_file(env)
    assert data == {"FOO": "bar", "BAZ": "qux", "QUOTED_SINGLE": "hello world"}


def test_load_env_file_returns_empty_for_missing_file(tmp_path):
    assert mod.load_env_file(tmp_path / "nope.env") == {}


def _write_junit(path: Path, *, passed: int = 0, failed: int = 0, skipped: int = 0, fail_name: str = "test_x", fail_msg: str = "boom") -> None:
    cases = []
    for i in range(passed):
        cases.append(f'<testcase classname="tests.e2e.scenarios" name="test_pass_{i}"/>')
    for i in range(skipped):
        cases.append(
            f'<testcase classname="tests.e2e.scenarios" name="test_skip_{i}"><skipped message="not enabled"/></testcase>'
        )
    for i in range(failed):
        name = fail_name if i == 0 else f"{fail_name}_{i}"
        cases.append(
            f'<testcase classname="tests.e2e.scenarios" name="{name}">'
            f'<failure type="AssertionError" message="{fail_msg}">Trace</failure></testcase>'
        )
    body = (
        f'<?xml version="1.0"?>'
        f'<testsuite name="parity" tests="{passed + failed + skipped}" failures="{failed}" skipped="{skipped}">'
        + "".join(cases)
        + "</testsuite>"
    )
    path.write_text(body, encoding="utf-8")


def test_parse_junit_counts_pass_fail_skip(tmp_path):
    junit = tmp_path / "junit.xml"
    _write_junit(junit, passed=2, failed=1, skipped=1, fail_name="test_live_harness_codex_native_bridge")
    result = mod.parse_junit(junit, tier_default="core")
    assert (result.passed, result.failed, result.skipped) == (2, 1, 1)
    assert len(result.gaps) == 1
    gap = result.gaps[0]
    assert gap.test_id == "test_live_harness_codex_native_bridge"
    assert gap.tier == "core"
    assert gap.failure_kind == "AssertionError"
    assert gap.failure_message == "boom"
    assert gap.owning_module == "integrations/codex/harness.py"


def test_lookup_spec_row_finds_row_by_test_name(tmp_path, monkeypatch):
    guide = tmp_path / "harness-parity.md"
    guide.write_text(
        "## Parity Matrix\n\n"
        "| Native surface | Claude Code support | Codex support | Spindrel benefit | Evidence | Gap / next action |\n"
        "|---|---|---|---|---|---|\n"
        "| Native turn loop | Native via Claude | Native via app-server | Browser transcript | `test_live_harness_core_parity_controls_trace_and_context` | Keep drift visible |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "PARITY_GUIDE", guide)
    row = mod.lookup_spec_row("test_live_harness_core_parity_controls_trace_and_context")
    assert row == "Native turn loop"


def test_lookup_spec_row_returns_first_cell_of_matching_row(tmp_path, monkeypatch):
    guide = tmp_path / "p.md"
    guide.write_text(
        "| Native turn loop | a | b | c | `test_live_harness_alpha` | gap |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "PARITY_GUIDE", guide)
    assert mod.lookup_spec_row("test_live_harness_alpha") == "Native turn loop"


def test_lookup_spec_row_misses_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "PARITY_GUIDE", tmp_path / "missing.md")
    assert mod.lookup_spec_row("anything") is None


@pytest.mark.parametrize(
    "test_name,expected",
    [
        ("test_live_harness_codex_native_anything", "integrations/codex/harness.py"),
        ("test_live_harness_claude_native_subagent_persists", "integrations/claude_code/harness.py"),
        ("test_live_harness_native_cli_switching_preserves_thread_and_order", "app/services/agent_harnesses/native_cli_mirror.py"),
        ("test_live_harness_core_native_slash_direct_commands", "app/services/slash_commands.py"),
        ("test_live_harness_busy_turn_queues_followup_and_resumes", "app/services/agent_harnesses/turn_host.py"),
        ("test_live_harness_unknown_shape", None),
    ],
)
def test_guess_owning_module_routes_known_shapes(test_name, expected):
    assert mod.guess_owning_module(test_name) == expected


def test_render_report_includes_frontmatter_and_gaps_section():
    result = mod.IterationResult(
        passed=3,
        failed=1,
        skipped=0,
        gaps=[
            mod.GapEntry(
                test_id="test_live_harness_codex_native_x",
                tier="core",
                classname="tests.e2e.scenarios.test_harness_live_parity",
                failure_kind="AssertionError",
                failure_message="expected codex /context output",
                spec_row="Codex /context",
                owning_module="integrations/codex/harness.py",
            )
        ],
    )
    body = mod.render_report(result, tier="core", preset=None, ran_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc))
    assert body.startswith("---\n")
    assert "status: active" in body
    assert "## Gaps" in body
    assert "test_live_harness_codex_native_x" in body
    assert "integrations/codex/harness.py" in body


def test_render_report_marks_complete_and_skips_gaps_when_all_green():
    result = mod.IterationResult(passed=10, failed=0, skipped=0)
    body = mod.render_report(result, tier="core", preset=None, ran_at=datetime(2026, 5, 2, tzinfo=timezone.utc))
    assert "status: complete" in body
    assert "## Gaps" not in body
    assert "tier_green" in body


def test_write_report_lands_under_audits_folder(tmp_path):
    body = "# hello\n"
    target = mod.write_report(tmp_path, body, datetime(2026, 5, 2, 12, 30, tzinfo=timezone.utc))
    assert target.exists()
    assert target.parent == tmp_path / mod.DEFAULT_REPORT_REL
    assert target.read_text() == body


def test_main_dry_run_with_junit_writes_report(tmp_path, monkeypatch):
    junit = tmp_path / "junit.xml"
    _write_junit(junit, passed=1, failed=1, fail_name="test_live_harness_codex_alpha")
    monkeypatch.delenv("SPINDREL_PROJECT_RUN_GUARD", raising=False)

    rc = mod.main(["--junit", str(junit), "--canonical-repo", str(tmp_path), "--tier", "core"])

    assert rc == 1  # one failure → loop should continue
    audits = tmp_path / mod.DEFAULT_REPORT_REL
    written = list(audits.glob("*.md"))
    assert len(written) == 1
    text = written[0].read_text()
    assert "test_live_harness_codex_alpha" in text
    assert "integrations/codex/harness.py" in text
