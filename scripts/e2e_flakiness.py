#!/usr/bin/env python3
"""Analyze E2E test flakiness across historical runs.

Reads timestamped JSON results from ~/logs/e2e/history/ and reports:
- Tests that fail consistently (every run) — likely real bugs
- Tests that fail intermittently — flaky, need investigation
- Per-test pass rates and failure streaks

Usage:
    python3 scripts/e2e_flakiness.py              # last 20 runs
    python3 scripts/e2e_flakiness.py --runs 50     # last 50 runs
    python3 scripts/e2e_flakiness.py --failing     # only show tests that have failed
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path


def load_runs(history_dir: Path, limit: int) -> list[dict]:
    """Load the most recent N run results, newest first."""
    files = sorted(history_dir.glob("*.json"), reverse=True)[:limit]
    runs = []
    for f in files:
        try:
            with open(f) as fh:
                runs.append(json.load(fh))
        except (json.JSONDecodeError, OSError):
            continue
    return runs


def extract_tests(run: dict) -> dict[str, str]:
    """Extract {test_name: outcome} from a run's tiered structure."""
    tests = {}
    for tier_name, tier_data in run.get("tiers", {}).items():
        if tier_name == "model_smoke":
            # model_smoke is nested: {model: {tests: [...]}}
            for model, bucket in tier_data.items():
                for t in bucket.get("tests", []):
                    key = f"{t['name']}[{model}]"
                    tests[key] = t["outcome"]
        else:
            for t in tier_data.get("tests", []):
                tests[t["name"]] = t["outcome"]
    return tests


def analyze(runs: list[dict]) -> list[dict]:
    """Build per-test statistics across runs."""
    stats: dict[str, dict] = defaultdict(lambda: {
        "total": 0, "passed": 0, "failed": 0, "outcomes": [],
    })

    for run in runs:
        tests = extract_tests(run)
        for name, outcome in tests.items():
            s = stats[name]
            s["total"] += 1
            if outcome == "passed":
                s["passed"] += 1
            else:
                s["failed"] += 1
            s["outcomes"].append(outcome)

    results = []
    for name, s in stats.items():
        # Calculate longest failure streak
        max_streak = 0
        current_streak = 0
        for o in s["outcomes"]:
            if o != "passed":
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        # Current streak (most recent consecutive failures)
        recent_streak = 0
        for o in s["outcomes"]:
            if o != "passed":
                recent_streak += 1
            else:
                break

        pass_rate = s["passed"] / s["total"] if s["total"] else 0
        results.append({
            "name": name,
            "total": s["total"],
            "passed": s["passed"],
            "failed": s["failed"],
            "pass_rate": pass_rate,
            "max_streak": max_streak,
            "recent_streak": recent_streak,
            "category": (
                "always_failing" if pass_rate == 0
                else "always_passing" if pass_rate == 1.0
                else "flaky"
            ),
        })

    return sorted(results, key=lambda r: (r["pass_rate"], r["name"]))


def main():
    parser = argparse.ArgumentParser(description="E2E flakiness analysis")
    parser.add_argument("--runs", type=int, default=20, help="Number of recent runs to analyze")
    parser.add_argument("--failing", action="store_true", help="Only show tests that have failed")
    parser.add_argument("--history-dir", default=os.path.expanduser("~/logs/e2e/e2e-history"),
                        help="Path to history directory")
    args = parser.parse_args()

    history_dir = Path(args.history_dir)
    if not history_dir.exists():
        print(f"No history directory at {history_dir}", file=sys.stderr)
        sys.exit(1)

    runs = load_runs(history_dir, args.runs)
    if not runs:
        print("No run data found", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing {len(runs)} runs from {history_dir}\n")

    results = analyze(runs)
    if args.failing:
        results = [r for r in results if r["failed"] > 0]

    if not results:
        print("All tests passing across all runs!")
        return

    # Group by category
    always_failing = [r for r in results if r["category"] == "always_failing"]
    flaky = [r for r in results if r["category"] == "flaky"]
    always_passing = [r for r in results if r["category"] == "always_passing"]

    if always_failing:
        print(f"=== ALWAYS FAILING ({len(always_failing)}) ===")
        for r in always_failing:
            print(f"  {r['name']}")
            print(f"    failed {r['failed']}/{r['total']} runs, streak: {r['recent_streak']}")
        print()

    if flaky:
        print(f"=== FLAKY ({len(flaky)}) ===")
        for r in flaky:
            pct = r["pass_rate"] * 100
            print(f"  {r['name']}")
            print(f"    pass rate: {pct:.0f}% ({r['passed']}/{r['total']}), "
                  f"current streak: {r['recent_streak']}, max streak: {r['max_streak']}")
        print()

    if not args.failing and always_passing:
        print(f"=== ALWAYS PASSING: {len(always_passing)} tests ===\n")

    # Summary
    total_tests = len(results) if not args.failing else len(results)
    print(f"Summary: {len(always_failing)} always failing, {len(flaky)} flaky, "
          f"{len(always_passing)} stable across {len(runs)} runs")


if __name__ == "__main__":
    main()
