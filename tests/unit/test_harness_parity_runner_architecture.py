"""Architecture guards for harness parity Module ownership.

Five guards pin the canonical-home invariants:

1. ``TIER_ORDER`` is defined only in ``tests/e2e/harness/parity_runner.py``.
2. Shell scripts must not redefine ``TIER_ORDER`` as a dict literal.
3. ``DEFAULT_ALLOWED_SKIP_REGEX`` is defined only in ``parity_runner.py``.
4. ``parity_presets.py`` is data-only — no import of ``parity_runner`` (avoids
   a cycle and keeps the preset table independently testable).
5. ``HARNESS_PARITY_RUNTIME_CONFIG`` is defined only in ``parity_runner.py``;
   ``scripts/agent_e2e_dev.py`` keeps a re-export alias.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY_RUNNER = REPO_ROOT / "tests" / "e2e" / "harness" / "parity_runner.py"
PARITY_PRESETS = REPO_ROOT / "tests" / "e2e" / "harness" / "parity_presets.py"
PARITY_TEST_FILE = REPO_ROOT / "tests" / "e2e" / "scenarios" / "test_harness_live_parity.py"
AGENT_E2E_DEV = REPO_ROOT / "scripts" / "agent_e2e_dev.py"
JUNIT_SHIM = REPO_ROOT / "scripts" / "harness_parity_junit_skips.py"
SHELL_SCRIPTS = (
    REPO_ROOT / "scripts" / "run_harness_parity_live.sh",
    REPO_ROOT / "scripts" / "run_harness_parity_local.sh",
    REPO_ROOT / "scripts" / "run_harness_parity_local_batch.sh",
)


def _module_assignments(path: Path, name: str) -> int:
    """Count top-level ``name = ...`` assignments in a Python module.

    Imports of ``name`` (``from X import name``) do not count — those are
    re-exports, not definitions. Annotated assignments (``name: T = ...``)
    do count, since they bind a new module-level value.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    count = 0
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    count += 1
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == name
                and node.value is not None
            ):
                count += 1
    return count


def _imports(path: Path, target_module_suffix: str) -> bool:
    """True if ``path`` imports any name from ``target_module_suffix``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.endswith(target_module_suffix):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith(target_module_suffix):
                    return True
    return False


# ---------------------------------------------------------------------------
# 1. TIER_ORDER has exactly one Python definition
# ---------------------------------------------------------------------------


def test_tier_order_defined_only_in_parity_runner():
    assert _module_assignments(PARITY_RUNNER, "TIER_ORDER") == 1
    # Consumers must import from parity_runner, not redefine.
    for path in (PARITY_TEST_FILE, AGENT_E2E_DEV, PARITY_PRESETS):
        assert _module_assignments(path, "TIER_ORDER") == 0, (
            f"{path.relative_to(REPO_ROOT)} redefines TIER_ORDER; "
            "import it from tests.e2e.harness.parity_runner instead."
        )


# ---------------------------------------------------------------------------
# 2. Shell scripts must not redefine TIER_ORDER as a dict literal
# ---------------------------------------------------------------------------


def test_shell_scripts_do_not_redefine_tier_order():
    # Match either a Python dict literal of tier→rank pairs or a bash
    # associative array; both are signs that the shell forked the registry.
    pattern = re.compile(
        r'"core"\s*:\s*0\b.*"bridge"\s*:\s*1\b',
        re.DOTALL,
    )
    associative_pattern = re.compile(
        r'\[core\]=0\b.*\[bridge\]=1\b',
        re.DOTALL,
    )
    for script in SHELL_SCRIPTS:
        text = script.read_text()
        assert not pattern.search(text), (
            f"{script.relative_to(REPO_ROOT)} contains an inline TIER_ORDER "
            "dict; query parity_runner via `python -m tests.e2e.harness."
            "parity_runner tier-rank|tier-at-least` instead."
        )
        assert not associative_pattern.search(text), (
            f"{script.relative_to(REPO_ROOT)} contains an inline tier "
            "associative array; query parity_runner instead."
        )


# ---------------------------------------------------------------------------
# 3. DEFAULT_ALLOWED_SKIP_REGEX has exactly one Python definition
# ---------------------------------------------------------------------------


def test_default_allowed_skip_regex_defined_only_in_parity_runner():
    assert _module_assignments(PARITY_RUNNER, "DEFAULT_ALLOWED_SKIP_REGEX") == 1
    # The shim re-exports via ``from ... import DEFAULT_ALLOWED_SKIP_REGEX`` —
    # not a top-level Assign — so the count there must be 0.
    assert _module_assignments(JUNIT_SHIM, "DEFAULT_ALLOWED_SKIP_REGEX") == 0


# ---------------------------------------------------------------------------
# 4. parity_presets.py is data-only — no orchestration import
# ---------------------------------------------------------------------------


def test_parity_presets_does_not_import_orchestration():
    assert not _imports(PARITY_PRESETS, "parity_runner"), (
        "parity_presets.py must not import parity_runner; the data table "
        "is consumed by the orchestrator, not the other way around. Closing "
        "this edge would create an import cycle."
    )


# ---------------------------------------------------------------------------
# 5. HARNESS_PARITY_RUNTIME_CONFIG has exactly one Python definition
# ---------------------------------------------------------------------------


def test_runtime_config_defined_only_in_parity_runner():
    assert _module_assignments(PARITY_RUNNER, "HARNESS_PARITY_RUNTIME_CONFIG") == 1
    # agent_e2e_dev.py keeps a top-level ``from ... import ...`` re-export, not
    # an Assign. The count here must therefore be 0.
    assert _module_assignments(AGENT_E2E_DEV, "HARNESS_PARITY_RUNTIME_CONFIG") == 0
