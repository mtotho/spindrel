"""Static guards for the WorkSurface isolation security model."""

from __future__ import annotations

from app.services.security_audit import (
    Severity,
    Status,
    _check_worksurface_isolation_static,
)
from app.services.worksurface_isolation_audit import (
    POLICY_TARGET,
    audit_worksurface_isolation,
    summarize_worksurface_isolation,
)


def _finding_by_id():
    findings = audit_worksurface_isolation()
    return {finding.id: finding for finding in findings}


def test_policy_target_names_the_decided_isolation_contract():
    assert "WorkSurface" in POLICY_TARGET["boundary"]
    assert "Project-bound channels intentionally share" in POLICY_TARGET["project_sharing"]
    assert "Bot memory" in POLICY_TARGET["private_state"]
    assert "explicit" in POLICY_TARGET["secrets"]
    assert "participant" in POLICY_TARGET["operator_power"]


def test_static_audit_records_worksurface_policy_coverage():
    findings = _finding_by_id()

    assert findings["worksurface_policy_object_present"].status == "pass"
    assert findings["critical_consumers_use_worksurface"].status == "pass"
    assert "Context admission" in findings["critical_consumers_use_worksurface"].evidence


def test_static_audit_clears_unscoped_shared_workspace_secret_injection():
    finding = _finding_by_id()["shared_workspace_unscoped_secret_injection"]

    assert finding.status == "pass"
    assert finding.severity == "info"
    assert "current_allowed_secrets" in finding.evidence
    assert "binding-driven" in finding.recommendation


def test_static_audit_flags_remaining_operator_escape_hatches():
    findings = _finding_by_id()

    cross_workspace = findings["legacy_cross_workspace_access_flag"]
    assert cross_workspace.status == "pass"
    assert cross_workspace.severity == "info"
    assert "ChannelBotMember" in cross_workspace.recommendation

    harness = findings["harness_workdir_absolute_escape"]
    assert harness.status == "pass"
    assert harness.severity == "info"
    assert "WorkSurface cwd" in harness.recommendation

    widget_workspace = findings["widget_workspace_scope_needs_worksurface_review"]
    assert widget_workspace.status == "pass"
    assert widget_workspace.severity == "info"
    assert "shared widget library" in widget_workspace.recommendation


def test_static_audit_summary_counts_findings():
    findings = audit_worksurface_isolation()
    summary = summarize_worksurface_isolation(findings)

    assert summary["pass"] >= 3
    assert summary["fail"] == 0
    assert summary["critical"] == 0


def test_security_audit_surfaces_worksurface_static_findings():
    check = _check_worksurface_isolation_static()

    assert check.id == "worksurface_isolation_static"
    assert check.category == "agentic_boundaries"
    assert check.status == Status.passed
    assert check.severity == Severity.info
    assert check.details is not None
    findings = {finding["id"]: finding for finding in check.details["findings"]}
    assert findings["shared_workspace_unscoped_secret_injection"]["status"] == "pass"
    assert findings["legacy_cross_workspace_access_flag"]["status"] == "pass"
    assert findings["widget_workspace_scope_needs_worksurface_review"]["status"] == "pass"
