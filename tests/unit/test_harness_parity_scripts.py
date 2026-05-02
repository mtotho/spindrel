from __future__ import annotations

import os
import subprocess
from pathlib import Path
import textwrap

from scripts.harness_parity_junit_skips import unexpected_skips


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_script(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("TERM", "xterm")
    return subprocess.run(
        [str(REPO_ROOT / "scripts" / "run_harness_parity_local_batch.sh"), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )


def test_harness_parity_shell_runners_are_syntax_valid() -> None:
    scripts = [
        "scripts/run_harness_parity_live.sh",
        "scripts/run_harness_parity_local.sh",
        "scripts/run_harness_parity_local_batch.sh",
    ]

    proc = subprocess.run(
        ["bash", "-n", *scripts],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )

    assert proc.returncode == 0, proc.stderr


def test_harness_parity_local_runner_uses_agent_owned_state_dir() -> None:
    local_runner = (REPO_ROOT / "scripts" / "run_harness_parity_local.sh").read_text()
    batch_runner = (REPO_ROOT / "scripts" / "run_harness_parity_local_batch.sh").read_text()

    assert "SPINDREL_AGENT_E2E_STATE_DIR" in local_runner
    assert 'NATIVE_ENV="$AGENT_STATE_DIR/native-api.env"' in local_runner
    assert 'HARNESS_ENV="$AGENT_STATE_DIR/harness-parity.env"' in local_runner
    assert "SPINDREL_AGENT_E2E_STATE_DIR" in batch_runner
    assert 'RUN_DIR="$AGENT_STATE_DIR/harness-parity-runs/$(date -u +%Y%m%dT%H%M%SZ)"' in batch_runner


def test_harness_parity_local_runner_checks_only_harness_docs_refs() -> None:
    local_runner = (REPO_ROOT / "scripts" / "run_harness_parity_local.sh").read_text()

    assert "agent-harnesses.md" in local_runner
    assert "harness-" in local_runner
    assert "python -m scripts.screenshots check" not in local_runner


def test_harness_screenshot_cleanup_is_best_effort() -> None:
    screenshot_runner = (REPO_ROOT / "scripts" / "screenshots" / "harness_live.py").read_text()

    assert "warning: failed to restore harness screenshot chat_mode" in screenshot_runner
    assert "with contextlib.suppress(Exception):" in screenshot_runner


def test_harness_parity_local_batch_all_preset_is_strict_full_suite() -> None:
    proc = _run_script("--preset", "all", "--screenshots", "docs", "--dry-run")

    assert proc.returncode == 0, proc.stderr
    assert "python scripts/agent_e2e_dev.py prepare-harness-parity" in proc.stdout
    assert "HARNESS_PARITY_FAIL_ON_SKIPS=true" in proc.stdout
    assert "HARNESS_PARITY_PYTEST_JUNIT_XML=" in proc.stdout
    assert "./scripts/run_harness_parity_local.sh --tier replay --screenshots docs" in proc.stdout
    assert " -k " not in proc.stdout


def test_harness_parity_local_batch_all_list_documents_no_selector() -> None:
    proc = _run_script("--preset", "all", "--list")

    assert proc.returncode == 0, proc.stderr
    assert "<full suite; no -k selector; fail-on-skips enabled>" in proc.stdout


def test_harness_parity_local_batch_sdk_preset_covers_deep_sdk_scenarios() -> None:
    proc = _run_script("--preset", "sdk", "--screenshots", "docs", "--dry-run")

    assert proc.returncode == 0, proc.stderr
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-\\*-streaming-deltas" in proc.stdout
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-\\*-image-semantic-reasoning" in proc.stdout
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-\\*-project-instruction-discovery" in proc.stdout
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-claude-todowrite-progress" in proc.stdout
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-claude-toolsearch-discovery" in proc.stdout
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-claude-native-subagent" in proc.stdout
    assert "--tier core --screenshots docs -k core_streams_partial_text_before_final" in proc.stdout
    assert "--tier skills --screenshots docs -k native_image_semantic_reasoning" in proc.stdout
    assert "--tier project --screenshots docs -k project_instruction_file_discovery" in proc.stdout
    assert "--tier skills --screenshots docs -k claude\\ and\\ claude_native_todo_progress_persists" in proc.stdout
    assert "--tier skills --screenshots docs -k claude\\ and\\ claude_native_toolsearch_persists" in proc.stdout
    assert "--tier skills --screenshots docs -k claude\\ and\\ claude_native_subagent_persists" in proc.stdout


def test_local_harness_parity_preserves_prepared_channels_after_focused_pytest_runs() -> None:
    conftest = Path("tests/e2e/conftest.py").read_text(encoding="utf-8")

    assert 'os.environ.get("HARNESS_PARITY_LOCAL") == "1"' in conftest
    assert 'os.environ.get("HARNESS_PARITY_NATIVE_APP") == "1"' in conftest
    assert "Preserving local harness parity fixture channels after focused run" in conftest


def test_harness_parity_local_batch_slash_preset_targets_native_slash_screenshots() -> None:
    proc = _run_script("--preset", "slash", "--screenshots", "docs", "--dry-run")

    assert proc.returncode == 0, proc.stderr
    assert (
        "HARNESS_PARITY_SCREENSHOT_ONLY="
        "harness-native-slash-picker-dark\\,harness-codex-native-plugins-result-dark\\,"
        "harness-codex-native-resume-result-dark\\,harness-codex-native-agents-result-dark\\,"
        "harness-codex-native-cloud-result-dark\\,harness-codex-native-approvals-result-dark\\,"
        "harness-codex-native-apps-result-dark\\,harness-codex-native-skills-result-dark\\,"
        "harness-codex-native-mcp-status-result-dark\\,harness-codex-native-features-result-dark"
    ) in proc.stdout
    assert (
        "HARNESS_PARITY_SCREENSHOT_ONLY="
        "harness-claude-native-skills-result-dark\\,harness-claude-native-agents-result-dark\\,"
        "harness-claude-native-hooks-result-dark\\,harness-claude-native-status-result-dark\\,"
        "harness-claude-native-doctor-result-dark"
    ) in proc.stdout
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-codex-native-plugin-install-handoff-dark" in proc.stdout
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-claude-native-custom-skill-result-dark" in proc.stdout
    assert "-k native_slash_mutating_commands_handoff" in proc.stdout
    assert "native_command_terminal_handoff" not in proc.stdout


def test_harness_parity_local_batch_bridge_preset_avoids_unfiltered_screenshot_suite() -> None:
    proc = _run_script("--preset", "bridge", "--screenshots", "docs", "--dry-run")

    assert proc.returncode == 0, proc.stderr
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-\\*-bridge-default" in proc.stdout
    assert "HARNESS_PARITY_SCREENSHOT_ONLY=harness-\\*-terminal-write" in proc.stdout
    assert "--tier writes --screenshots off -k safe_workspace_write_read_delete" in proc.stdout
    assert "--tier memory --screenshots off -k memory_hint_requires_explicit_read" in proc.stdout


def test_harness_parity_local_batch_ui_preset_uses_current_pytest_selectors() -> None:
    proc = _run_script("--preset", "ui", "--screenshots", "docs", "--dry-run")

    assert proc.returncode == 0, proc.stderr
    assert "--tier terminal --screenshots off -k terminal_tool_output_is_sequential" in proc.stdout
    assert "--tier replay --screenshots off -k persisted_tool_replay_survives_refetch" in proc.stdout
    assert "mobile_context_panel" not in proc.stdout


def test_harness_parity_strict_skip_gate_allows_intentional_runtime_skips(tmp_path) -> None:
    junit = tmp_path / "pytest.xml"
    junit.write_text(textwrap.dedent(
        """\
        <?xml version="1.0" encoding="utf-8"?>
        <testsuites>
          <testsuite name="pytest" tests="2" skipped="2">
            <testcase classname="tests.e2e.scenarios.test_harness_live_parity" name="test_claude_only[codex]">
              <skipped message="project-local native skill invocation is Claude Code-specific" />
            </testcase>
            <testcase classname="tests.e2e.scenarios.test_harness_live_parity" name="test_codex_only[claude]">
              <skipped message="Codex app-server owns skill and image input items" />
            </testcase>
          </testsuite>
        </testsuites>
        """
    ))

    assert unexpected_skips(str(junit)) == []


def test_harness_parity_strict_skip_gate_reports_unexpected_skip(tmp_path) -> None:
    junit = tmp_path / "pytest.xml"
    junit.write_text(textwrap.dedent(
        """\
        <?xml version="1.0" encoding="utf-8"?>
        <testsuites>
          <testsuite name="pytest" tests="1" skipped="1">
            <testcase classname="tests.e2e.scenarios.test_harness_live_parity" name="test_real_gap">
              <skipped message="browser_automation docker stacks missing" />
            </testcase>
          </testsuite>
        </testsuites>
        """
    ))

    assert unexpected_skips(str(junit)) == [
        (
            "tests.e2e.scenarios.test_harness_live_parity.test_real_gap",
            "browser_automation docker stacks missing",
        )
    ]
