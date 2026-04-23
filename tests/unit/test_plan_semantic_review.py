from app.services.plan_semantic_review import _deterministic_assessment, _step_is_execution_oriented


def _bundle(*, outcome: str, features: dict, step_label: str = "Implement the change") -> dict:
    return {
        "outcome": {"outcome": outcome},
        "features": features,
        "step": {
            "id": "step-1",
            "label": step_label,
            "note": None,
            "execution_oriented": _step_is_execution_oriented(step_label, None),
        },
    }


def test_step_orientation_treats_audit_as_read_only():
    assert _step_is_execution_oriented("Audit current behavior", None) is False
    assert _step_is_execution_oriented("Implement the fix", None) is True


def test_deterministic_assessment_flags_replan_conflict():
    flags, review = _deterministic_assessment(
        _bundle(
            outcome="step_done",
            features={
                "had_successful_tool": True,
                "had_any_error": False,
                "all_tool_calls_failed": False,
                "read_only_only": False,
                "had_mutation": True,
                "had_verification_signal": False,
                "requested_replan": True,
            },
        )
    )

    assert "requested_replan_conflicts_with_success_claim" in flags
    assert review is not None
    assert review["verdict"] == "needs_replan"


def test_deterministic_assessment_flags_read_only_step_done():
    flags, review = _deterministic_assessment(
        _bundle(
            outcome="step_done",
            features={
                "had_successful_tool": True,
                "had_any_error": False,
                "all_tool_calls_failed": False,
                "read_only_only": True,
                "had_mutation": False,
                "had_verification_signal": False,
                "requested_replan": False,
            },
            step_label="Implement the fix",
        )
    )

    assert "step_done_from_read_only_turn" in flags
    assert review is not None
    assert review["verdict"] == "weak_support"
