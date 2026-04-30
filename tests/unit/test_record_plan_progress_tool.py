from __future__ import annotations

from types import SimpleNamespace

from app.tools.local.record_plan_progress import (
    _claims_step_verification,
    _tool_call_is_readback,
)


def test_step_done_verification_claim_requires_readback_guard() -> None:
    assert _claims_step_verification(
        outcome="step_done",
        summary="Created the planned marker file",
        status_note="Marker file created and verified",
    )
    assert not _claims_step_verification(
        outcome="step_done",
        summary="Created the planned marker file",
        status_note=None,
    )
    assert not _claims_step_verification(
        outcome="progress",
        summary="Verification still pending",
        status_note=None,
    )


def test_file_readback_matches_evidence_path() -> None:
    read_tool = SimpleNamespace(
        status="done",
        error=None,
        tool_name="file",
        arguments={
            "operation": "read",
            "path": ".spindrel-plan-parity/adherence-marker.txt",
        },
    )
    create_tool = SimpleNamespace(
        status="done",
        error=None,
        tool_name="file",
        arguments={
            "operation": "create",
            "path": ".spindrel-plan-parity/adherence-marker.txt",
        },
    )
    other_read_tool = SimpleNamespace(
        status="done",
        error=None,
        tool_name="file",
        arguments={
            "operation": "read",
            "path": ".spindrel-plan-parity/other.txt",
        },
    )

    assert _tool_call_is_readback(read_tool, evidence=".spindrel-plan-parity/adherence-marker.txt")
    assert not _tool_call_is_readback(create_tool, evidence=".spindrel-plan-parity/adherence-marker.txt")
    assert not _tool_call_is_readback(other_read_tool, evidence=".spindrel-plan-parity/adherence-marker.txt")
