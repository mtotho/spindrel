#!/usr/bin/env python3
"""Audit a live Spindrel instance's Project Factory orchestration config.

Reads `/api/v1/projects` and `/api/v1/projects/{id}/orchestration-policy` from
a deployed Spindrel server, surfaces gaps that block bounded-loop work
(unset concurrency cap, missing intake convention, absent WORKFLOW.md, etc.),
and optionally PATCHes the project to apply sensible defaults.

Usage:

    # Read-only report against the local server (default)
    python scripts/spindrel_live_config_audit.py

    # Against a specific host with explicit API key
    python scripts/spindrel_live_config_audit.py \
        --host http://10.10.30.208:8000 --api-key "$KEY"

    # Apply suggested defaults (PATCHes intake config, drops a starter
    # WORKFLOW.md when missing). Concurrency cap stays manual because it
    # belongs in the Blueprint, not on the project.
    python scripts/spindrel_live_config_audit.py --apply

When --host is not supplied and the script is run on the Spindrel host, it
defaults to http://localhost:8000 and tries to discover the API key from the
running app container's environment via
`docker exec agent-server-agent-server-1 printenv API_KEY`.

This is a thin orchestration helper; it does NOT mutate code, restart any
services, or touch the host filesystem outside the canonical repo root that
the live API reports.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_HOST = "http://localhost:8000"
SUGGESTED_CONCURRENCY_CAP = 2
SUGGESTED_INTAKE_KIND = "repo_file"
SUGGESTED_INTAKE_TARGET = "docs/inbox.md"
WORKFLOW_RELATIVE_PATH = ".spindrel/WORKFLOW.md"
WORKFLOW_STARTER = """\
---
title: Project Workflow
summary: Repo-resident overrides for the generic project skill cluster.
---

# Workflow

This file is the override for the generic `skills/project/*` cluster.
Sections below win over Spindrel defaults.

## policy

- max_concurrent_runs: leave on Blueprint (do not duplicate here).
- turn_timeout_seconds: 1800.

## intake

- kind: repo_file
- target: docs/inbox.md
- schema: light. One `## YYYY-MM-DD HH:MM <slug>` heading per note.

## runs

- branch: feature/<slug>
- tests: `. .venv/bin/activate && PYTHONPATH=. pytest tests/unit -q`
- pr: open against `development`; do not merge from agent.

## hooks

- pre_commit: none.
- post_commit: none.

## dependencies

- See `docker-compose.yml`. Stack lifecycle is owned by the operator.
"""


@dataclass
class ProjectFinding:
    project_id: str
    slug: str
    name: str
    blocking: list[str] = field(default_factory=list)
    suggested: list[str] = field(default_factory=list)
    apply_actions: list[str] = field(default_factory=list)


def _resolve_api_key(arg: str | None) -> str | None:
    if arg:
        return arg
    try:
        result = subprocess.run(
            ["docker", "exec", "agent-server-agent-server-1", "printenv", "API_KEY"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        key = result.stdout.strip()
        return key or None
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _request(host: str, path: str, api_key: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, Any]:
    url = host.rstrip("/") + path
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {api_key}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode() or "null")
        except (json.JSONDecodeError, ValueError):
            detail = None
        return exc.code, detail


def audit_project(host: str, api_key: str, project: dict) -> ProjectFinding:
    finding = ProjectFinding(
        project_id=project["id"],
        slug=project.get("slug") or project["id"],
        name=project.get("name") or project["id"],
    )

    factory_status, _factory_body = _request(host, f"/api/v1/projects/{project['id']}/factory-state", api_key)
    if factory_status >= 500:
        finding.blocking.append(
            f"factory-state endpoint returns {factory_status} — investigate before running any bounded loop"
        )

    policy_status, policy = _request(host, f"/api/v1/projects/{project['id']}/orchestration-policy", api_key)
    if policy_status != 200 or not isinstance(policy, dict):
        finding.blocking.append(
            f"orchestration-policy endpoint returns {policy_status} — cannot inspect orchestration config"
        )
        return finding

    concurrency = policy.get("concurrency") or {}
    if concurrency.get("max_concurrent_runs") is None:
        finding.suggested.append(
            f"concurrency.max_concurrent_runs unset — Blueprint default of {SUGGESTED_CONCURRENCY_CAP} would prevent runaway parallel runs (set on the Blueprint, not the Project)"
        )

    intake = policy.get("intake") or {}
    if not intake.get("configured"):
        finding.suggested.append(
            f"intake.kind = {intake.get('kind') or 'unset'} — defaulting to {SUGGESTED_INTAKE_KIND} → {SUGGESTED_INTAKE_TARGET}"
        )
        finding.apply_actions.append("patch_intake")

    workflow = policy.get("repo_workflow") or {}
    if not workflow.get("present"):
        rel = workflow.get("relative_path") or WORKFLOW_RELATIVE_PATH
        finding.suggested.append(
            f"{rel} not present — drop a starter so future agents read overrides from one place"
        )
        finding.apply_actions.append("write_workflow")

    timeouts = policy.get("timeouts") or {}
    if timeouts.get("turn_timeout_seconds") is None:
        finding.suggested.append(
            "timeouts.turn_timeout_seconds unset — leave alone unless you want to enforce a per-turn cap"
        )

    return finding


def render_report(findings: list[ProjectFinding], runtime_status: dict[str, int]) -> str:
    lines: list[str] = []
    lines.append("== Spindrel live config audit ==")
    lines.append("")
    lines.append("runtime_registry:")
    for name, status in runtime_status.items():
        ok = "ok" if status == 200 else f"HTTP {status}"
        lines.append(f"  {name}: {ok}")
    lines.append("")
    if not findings:
        lines.append("(no projects found — check API key scope)")
        return "\n".join(lines)
    for finding in findings:
        lines.append(f"project: {finding.slug} ({finding.project_id})")
        if finding.blocking:
            for note in finding.blocking:
                lines.append(f"  BLOCKING: {note}")
        if finding.suggested:
            for note in finding.suggested:
                lines.append(f"  suggest:  {note}")
        if not finding.blocking and not finding.suggested:
            lines.append("  (no gaps)")
        lines.append("")
    return "\n".join(lines)


def apply_intake(host: str, api_key: str, project: dict) -> str:
    status, body = _request(
        host,
        f"/api/v1/projects/{project['id']}",
        api_key,
        method="PATCH",
        body={
            "intake_kind": SUGGESTED_INTAKE_KIND,
            "intake_target": SUGGESTED_INTAKE_TARGET,
        },
    )
    if status >= 400:
        return f"FAIL PATCH project: {status} {body!r}"
    return f"set intake_kind={SUGGESTED_INTAKE_KIND} target={SUGGESTED_INTAKE_TARGET}"


def apply_workflow(host: str, api_key: str, project: dict, policy: dict) -> str:
    canonical = (policy.get("canonical_repo") or {})
    host_path = canonical.get("host_path")
    if not host_path:
        return "skip workflow write: no canonical repo host_path resolved"
    target = Path(host_path) / WORKFLOW_RELATIVE_PATH
    if target.exists():
        return f"skip workflow write: {target} already present"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(WORKFLOW_STARTER, encoding="utf-8")
    except OSError as exc:
        return f"FAIL workflow write {target}: {exc}"
    return f"wrote starter {target}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Spindrel API base URL (default {DEFAULT_HOST})")
    parser.add_argument("--api-key", default=None, help="Bearer key (auto-discovered via docker exec when omitted)")
    parser.add_argument("--apply", action="store_true", help="Apply suggested defaults instead of just reporting")
    args = parser.parse_args(argv)

    api_key = _resolve_api_key(args.api_key)
    if not api_key:
        print("ERROR: no API key. Pass --api-key, or run on the host so docker exec can resolve it.", file=sys.stderr)
        return 2

    runtime_status: dict[str, int] = {}
    for runtime in ("codex", "claude_code"):
        status, _ = _request(args.host, f"/api/v1/runtimes/{runtime}/capabilities", api_key)
        runtime_status[runtime] = status

    projects_status, projects = _request(args.host, "/api/v1/projects", api_key)
    if projects_status != 200 or not isinstance(projects, list):
        print(f"ERROR: cannot list projects (HTTP {projects_status})", file=sys.stderr)
        return 3

    findings = [audit_project(args.host, api_key, project) for project in projects]
    print(render_report(findings, runtime_status))

    if not args.apply:
        return 0

    print("== applying ==")
    for project, finding in zip(projects, findings):
        if finding.blocking:
            print(f"skip {finding.slug}: blocking issues unresolved")
            continue
        if not finding.apply_actions:
            continue
        _, policy = _request(args.host, f"/api/v1/projects/{project['id']}/orchestration-policy", api_key)
        for action in finding.apply_actions:
            if action == "patch_intake":
                print(f"  {finding.slug}: {apply_intake(args.host, api_key, project)}")
            elif action == "write_workflow":
                print(f"  {finding.slug}: {apply_workflow(args.host, api_key, project, policy or {})}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
