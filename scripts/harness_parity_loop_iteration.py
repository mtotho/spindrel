#!/usr/bin/env python3
"""One iteration of the harness parity loop.

Defers ALL stack lifecycle to ``.agents/skills/spindrel-e2e-development/SKILL.md``.
This script never brings up the e2e stack and never tears it down.

Behavior per invocation:

1. Refuse to run inside ``SPINDREL_PROJECT_RUN_GUARD=1`` (Project task agents
   must not invoke ``prepare-harness-parity`` recursively — see e2e skill
   lines 296-301).
2. Read ``scratch/agent-e2e/harness-parity.env`` (written by
   ``agent_e2e_dev.py prepare-harness-parity``) so the parity runner has
   ``E2E_PORT``, ``HARNESS_PARITY_*_CHANNEL_ID`` etc. on its env.
3. Invoke ``./scripts/run_harness_parity_local_batch.sh --preset <preset>``
   (or ``--tier <tier>``) with ``--junitxml`` pointed at a per-iteration
   path so we get structured failures back.
4. Parse the JUnit; cross-reference each failing test_id against the parity
   matrix in ``docs/guides/harness-parity.md`` to enrich with
   (tier, spec_anchor, owning_module heuristic).
5. Render a markdown gap report and write it under
   ``.spindrel/audits/harness-parity/<YYYYMMDD-HHMM>.md`` of the canonical
   Spindrel repo.
6. Print the report path on stdout for the calling skill to read.

Usage:

    # default: tier=core, write report under <repo>/.spindrel/audits/...
    python scripts/harness_parity_loop_iteration.py

    # different tier or batch preset
    python scripts/harness_parity_loop_iteration.py --tier bridge
    python scripts/harness_parity_loop_iteration.py --preset sdk

    # dry-run: parse an existing JUnit instead of invoking the suite
    python scripts/harness_parity_loop_iteration.py --junit /tmp/junit.xml
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = REPO_ROOT / "scratch" / "agent-e2e" / "harness-parity.env"
DEFAULT_REPORT_REL = Path(".spindrel/audits/harness-parity")
PARITY_GUIDE = REPO_ROOT / "docs" / "guides" / "harness-parity.md"
PARITY_TEST_FILE = REPO_ROOT / "tests" / "e2e" / "scenarios" / "test_harness_live_parity.py"


@dataclass
class GapEntry:
    test_id: str
    tier: str
    classname: str
    failure_kind: str
    failure_message: str
    spec_row: str | None
    owning_module: str | None


@dataclass
class IterationResult:
    passed: int
    failed: int
    skipped: int
    gaps: list[GapEntry] = field(default_factory=list)
    junit_path: Path | None = None


def refuse_inside_project_run() -> None:
    if os.environ.get("SPINDREL_PROJECT_RUN_GUARD") != "1":
        return
    if os.environ.get("SPINDREL_ALLOW_REPO_DEV_BOOTSTRAP") == "1":
        return
    sys.stderr.write(
        "ERROR: SPINDREL_PROJECT_RUN_GUARD=1 is set without "
        "SPINDREL_ALLOW_REPO_DEV_BOOTSTRAP=1. Harness parity is the documented "
        "infrastructure-task case for the bootstrap escape hatch — set "
        "SPINDREL_ALLOW_REPO_DEV_BOOTSTRAP=1 before running prepare-harness-parity "
        "and this script. See scripts/agent_e2e_dev.py:_reject_project_run_bootstrap.\n"
    )
    raise SystemExit(78)


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a `KEY=value` env file (no shell expansion) into a dict.

    Lines starting with '#' or blank are skipped. Values are stripped of one
    layer of surrounding quotes. Returns {} when the file does not exist —
    callers decide whether that is fatal.
    """
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        data[key.strip()] = value
    return data


def invoke_parity(tier: str | None, preset: str | None, junit_path: Path, env: dict[str, str]) -> int:
    """Run the local batch runner and return its exit code."""
    cmd = [str(REPO_ROOT / "scripts" / "run_harness_parity_local_batch.sh")]
    if preset:
        cmd += ["--preset", preset]
    if tier:
        cmd += ["--tier", tier]
    cmd += ["--", f"--junitxml={junit_path}"]
    full_env = {**os.environ, **env, "HARNESS_PARITY_PYTEST_JUNIT_XML": str(junit_path)}
    return subprocess.call(cmd, env=full_env, cwd=str(REPO_ROOT))


def parse_junit(junit_path: Path, tier_default: str) -> IterationResult:
    """Parse a pytest JUnit XML into an IterationResult."""
    tree = ET.parse(junit_path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))

    result = IterationResult(passed=0, failed=0, skipped=0, junit_path=junit_path)
    for suite in suites:
        for case in suite.iter("testcase"):
            test_name = case.get("name") or "unknown"
            classname = case.get("classname") or ""
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            if failure is not None or error is not None:
                node = failure if failure is not None else error
                kind = node.get("type") or ("failure" if failure is not None else "error")
                msg = (node.get("message") or "").strip() or (node.text or "").strip()[:240]
                gap = GapEntry(
                    test_id=test_name,
                    tier=tier_default,
                    classname=classname,
                    failure_kind=kind,
                    failure_message=msg,
                    spec_row=lookup_spec_row(test_name),
                    owning_module=guess_owning_module(test_name),
                )
                result.failed += 1
                result.gaps.append(gap)
            elif skipped is not None:
                result.skipped += 1
            else:
                result.passed += 1
    return result


def lookup_spec_row(test_id: str) -> str | None:
    """Find the parity-matrix row whose Evidence cell mentions ``test_id``.

    Returns the leading ``Native surface`` cell of that row when found.
    """
    if not PARITY_GUIDE.exists():
        return None
    text = PARITY_GUIDE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if test_id in line and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells:
                return cells[0]
    return None


_OWNING_HEURISTICS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"codex"), "integrations/codex/harness.py"),
    (re.compile(r"claude_native|claude.*subagent|claude.*sdk"), "integrations/claude_code/harness.py"),
    (re.compile(r"native_cli"), "app/services/agent_harnesses/native_cli_mirror.py"),
    (re.compile(r"approval"), "app/services/agent_harnesses/approvals.py"),
    (re.compile(r"settings|model_effort|model_selection"), "app/services/agent_harnesses/settings.py"),
    (re.compile(r"context|compact|streams_partial"), "app/services/agent_harnesses/session_state.py"),
    (re.compile(r"bridge"), "app/services/agent_harnesses/tools.py"),
    (re.compile(r"slash"), "app/services/slash_commands.py"),
    (re.compile(r"resume|multiturn"), "app/services/agent_harnesses/turn_host.py"),
    (re.compile(r"queued|followup"), "app/services/agent_harnesses/turn_host.py"),
)


def guess_owning_module(test_id: str) -> str | None:
    for pattern, module in _OWNING_HEURISTICS:
        if pattern.search(test_id):
            return module
    return None


def render_report(result: IterationResult, tier: str | None, preset: str | None, ran_at: datetime) -> str:
    lines: list[str] = []
    lines.append("---")
    lines.append("title: Harness parity loop iteration")
    lines.append(
        f"summary: {result.passed} passed, {result.failed} failed, {result.skipped} skipped — "
        f"{'tier=' + tier if tier else ''}{' preset=' + preset if preset else ''}"
    )
    lines.append(f"status: {'complete' if result.failed == 0 else 'active'}")
    lines.append("tags: [spindrel, harness-parity, loop-iteration]")
    lines.append(f"created: {ran_at.strftime('%Y-%m-%d')}")
    lines.append(f"updated: {ran_at.strftime('%Y-%m-%d')}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Harness parity iteration — {ran_at.isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(
        f"**Result**: {result.passed} passed · {result.failed} failed · {result.skipped} skipped"
    )
    if tier:
        lines.append(f"**Tier**: `{tier}`")
    if preset:
        lines.append(f"**Preset**: `{preset}`")
    if result.junit_path:
        lines.append(f"**JUnit**: `{result.junit_path}`")
    lines.append("")
    if result.failed == 0:
        lines.append("All targeted parity checks passed. Loop should publish "
                     "`{decision: \"stop\", reason: \"tier_green\"}` and exit.")
        return "\n".join(lines) + "\n"

    lines.append("## Gaps")
    lines.append("")
    for idx, gap in enumerate(result.gaps, start=1):
        lines.append(f"### {idx}. `{gap.test_id}`")
        lines.append("")
        if gap.spec_row:
            lines.append(f"- **Spec row**: {gap.spec_row}")
        if gap.owning_module:
            lines.append(f"- **Owning module (heuristic)**: `{gap.owning_module}`")
        lines.append(f"- **Failure kind**: {gap.failure_kind}")
        lines.append(f"- **Classname**: `{gap.classname}`")
        if gap.failure_message:
            lines.append("")
            lines.append("```")
            lines.append(gap.failure_message[:1200])
            lines.append("```")
        lines.append("")
    lines.append("## Loop instruction")
    lines.append("")
    lines.append(
        "Pick the first gap (lowest tier first when ties), open the spec row "
        "and the owning module, make the smallest fix that satisfies the spec, "
        "re-run the single failing test in isolation, commit + push, and "
        "publish `{decision: \"continue\", fixed: <test_id>}` on the receipt."
    )
    return "\n".join(lines) + "\n"


def write_report(canonical_repo: Path, body: str, ran_at: datetime) -> Path:
    target_dir = canonical_repo / DEFAULT_REPORT_REL
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{ran_at.strftime('%Y%m%d-%H%M')}.md"
    target.write_text(body, encoding="utf-8")
    return target


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--tier", default=None, help="Tier name passed through to parity_runner (e.g. core, bridge).")
    parser.add_argument("--preset", default=None, help="Batch preset (smoke, fast, sdk, ...).")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="harness-parity.env emitted by prepare-harness-parity.")
    parser.add_argument("--junit", type=Path, default=None, help="Existing JUnit XML to parse instead of invoking the suite (dry-run).")
    parser.add_argument("--canonical-repo", type=Path, default=REPO_ROOT, help="Where to write the gap-report artifact.")
    args = parser.parse_args(argv)

    refuse_inside_project_run()

    if args.junit is None and not args.tier and not args.preset:
        # Default behavior: tier=core matches the cheapest meaningful sweep.
        args.tier = "core"

    ran_at = datetime.now(tz=timezone.utc)
    tier_label = args.tier or "core"

    if args.junit:
        junit_path = args.junit
        if not junit_path.exists():
            print(f"ERROR: --junit {junit_path} does not exist", file=sys.stderr)
            return 2
    else:
        env = load_env_file(args.env_file)
        if not env:
            print(
                f"ERROR: {args.env_file} not found. Run "
                "`python scripts/agent_e2e_dev.py prepare-harness-parity` first "
                "(see .agents/skills/spindrel-e2e-development/SKILL.md).",
                file=sys.stderr,
            )
            return 3
        junit_dir = REPO_ROOT / "scratch" / "agent-e2e" / "harness-parity-loop"
        junit_dir.mkdir(parents=True, exist_ok=True)
        junit_path = junit_dir / f"{ran_at.strftime('%Y%m%dT%H%M%SZ')}-junit.xml"
        rc = invoke_parity(args.tier, args.preset, junit_path, env)
        if not junit_path.exists():
            print(f"ERROR: parity runner exited {rc} and produced no JUnit at {junit_path}", file=sys.stderr)
            return 4

    result = parse_junit(junit_path, tier_label)
    body = render_report(result, args.tier, args.preset, ran_at)
    report_path = write_report(args.canonical_repo, body, ran_at)
    print(report_path)
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
