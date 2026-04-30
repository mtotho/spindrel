"""Read-only WorkSurface isolation audit.

This module codifies the intended resource boundary so the security audit can
surface drift while the larger cleanup happens in phases. It intentionally uses
static source checks: the first pass is about making legacy seams visible, not
mutating runtime behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


Severity = Literal["critical", "high", "medium", "info"]
Status = Literal["pass", "fail", "warning"]


@dataclass(frozen=True)
class WorkSurfaceIsolationFinding:
    id: str
    severity: Severity
    status: Status
    title: str
    evidence: str
    recommendation: str

    def payload(self) -> dict[str, str]:
        return {
            "id": self.id,
            "severity": self.severity,
            "status": self.status,
            "title": self.title,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


POLICY_TARGET = {
    "boundary": "Every turn/tool resolves to exactly one WorkSurface: channel, project, or project_instance.",
    "project_sharing": "Project-bound channels intentionally share Project files/search/context.",
    "private_state": "Bot memory, credentials, auth, and authored skills stay private unless explicitly published/shared.",
    "execution": "Exec, harnesses, files, search, widgets, and context admission must honor the resolved WorkSurface.",
    "secrets": "Execution receives only explicit per-bot, per-Project/runtime, or per-integration secret bindings.",
    "operator_power": "Legacy cross_workspace_access becomes an explicit operator capability with policy and audit.",
}

WORKSURFACE_CONSUMERS = {
    "context_admission": "app/agent/context_admission.py",
    "file_tool": "app/tools/local/file_ops.py",
    "exec_command": "app/tools/local/exec_command.py",
    "delegate_to_exec": "app/tools/local/exec_tool.py",
    "harness_paths": "app/services/agent_harnesses/project.py",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def audit_worksurface_isolation(repo_root: Path | None = None) -> list[WorkSurfaceIsolationFinding]:
    """Return current WorkSurface isolation findings.

    Findings are intentionally stable and human-readable so they can be shown in
    the admin security audit and copied into vault remediation notes.
    """
    root = repo_root or _repo_root()
    findings: list[WorkSurfaceIsolationFinding] = []

    projects_source = _read(root, "app/services/projects.py")
    if "class WorkSurface" in projects_source and all(kind in projects_source for kind in ('"project"', '"project_instance"', '"channel"')):
        findings.append(WorkSurfaceIsolationFinding(
            id="worksurface_policy_object_present",
            severity="info",
            status="pass",
            title="WorkSurface policy object exists",
            evidence="app/services/projects.py defines channel, project, and project_instance WorkSurface variants.",
            recommendation="Keep new file/search/context/exec/harness/widget resolution behind this policy object.",
        ))
    else:
        findings.append(WorkSurfaceIsolationFinding(
            id="worksurface_policy_object_present",
            severity="critical",
            status="fail",
            title="Missing canonical WorkSurface policy object",
            evidence="app/services/projects.py does not expose the expected WorkSurface variants.",
            recommendation="Define a single policy object before adding more workspace/path resolvers.",
        ))

    missing_consumers: list[str] = []
    for name, rel in WORKSURFACE_CONSUMERS.items():
        source = _read(root, rel)
        if "resolve_channel_work_surface" not in source and "resolve_channel_work_surface_by_id" not in source:
            missing_consumers.append(f"{name}:{rel}")
    findings.append(WorkSurfaceIsolationFinding(
        id="critical_consumers_use_worksurface",
        severity="high" if missing_consumers else "info",
        status="fail" if missing_consumers else "pass",
        title="Critical consumers route through WorkSurface resolution",
        evidence=(
            "Missing WorkSurface resolver in " + ", ".join(missing_consumers)
            if missing_consumers
            else "Context admission, file tool, exec tools, and harness path resolution call WorkSurface resolution."
        ),
        recommendation="Route any missing consumer through app.services.projects before resolving host paths.",
    ))

    shared_workspace_source = _read(root, "app/services/shared_workspace.py")
    if "get_env_dict" in shared_workspace_source and "current_allowed_secrets" not in shared_workspace_source:
        findings.append(WorkSurfaceIsolationFinding(
            id="shared_workspace_unscoped_secret_injection",
            severity="critical",
            status="fail",
            title="Shared workspace exec injects all Secret Values by default",
            evidence="app/services/shared_workspace.py reads secret_values.get_env_dict() without the current_allowed_secrets filter used by sandbox exec.",
            recommendation=(
                "Change shared workspace exec to inject only explicit runtime bindings: Project runtime env, "
                "per-bot allowed secrets, or integration-specific bindings. Do not pass the global Secret Values vault by default."
            ),
        ))
    else:
        findings.append(WorkSurfaceIsolationFinding(
            id="shared_workspace_unscoped_secret_injection",
            severity="info",
            status="pass",
            title="Shared workspace exec uses scoped secret injection",
            evidence="Shared workspace exec no longer injects the full Secret Values vault by default.",
            recommendation="Keep secret injection explicit and binding-driven.",
        ))

    file_ops_source = _read(root, "app/tools/local/file_ops.py")
    bots_source = _read(root, "app/agent/bots.py")
    if "cross_workspace_access" in file_ops_source or "cross_workspace_access" in bots_source:
        findings.append(WorkSurfaceIsolationFinding(
            id="legacy_cross_workspace_access_flag",
            severity="high",
            status="warning",
            title="Legacy cross_workspace_access bypasses the WorkSurface vocabulary",
            evidence="app/tools/local/file_ops.py and app/agent/bots.py still expose cross_workspace_access for sibling-channel workspace resolution.",
            recommendation=(
                "Migrate this into an explicit operator/orchestrator capability that names which WorkSurface "
                "boundaries may be crossed and emits durable audit events when used."
            ),
        ))

    harness_project_source = _read(root, "app/services/agent_harnesses/project.py")
    if "bot.harness_workdir" in harness_project_source:
        findings.append(WorkSurfaceIsolationFinding(
            id="harness_workdir_absolute_escape",
            severity="high",
            status="warning",
            title="Harness workdir can bypass resolved WorkSurface",
            evidence="app/services/agent_harnesses/project.py falls back to bot.harness_workdir after Project/instance resolution.",
            recommendation=(
                "Treat harness_workdir as an operator target, not an ordinary default. Prefer WorkSurface cwd, "
                "or require an explicit operator grant and path-within-root proof."
            ),
        ))

    widget_paths_source = _read(root, "app/services/widget_paths.py")
    if "widget://workspace" in widget_paths_source and "shared_root" in widget_paths_source:
        findings.append(WorkSurfaceIsolationFinding(
            id="widget_workspace_scope_needs_worksurface_review",
            severity="medium",
            status="warning",
            title="Widget workspace scope is shared-root based, not WorkSurface based",
            evidence="app/services/widget_paths.py resolves widget://workspace under the shared workspace .widget_library root.",
            recommendation=(
                "Decide whether workspace widgets are truly shared-workspace artifacts or should become "
                "WorkSurface-scoped/published assets with explicit provenance."
            ),
        ))

    return findings


def summarize_worksurface_isolation(findings: list[WorkSurfaceIsolationFinding]) -> dict[str, int]:
    summary = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "info": 0,
        "fail": 0,
        "warning": 0,
        "pass": 0,
    }
    for finding in findings:
        summary[finding.severity] += 1
        summary[finding.status] += 1
    return summary
