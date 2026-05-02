"""Phase 4BD.3 - capture_project_intake tool routes by intake_config.kind.

Pure unit coverage focuses on the routing branches that don't need a real DB:
schema/enum integrity and the fact that the tool reads `intake_config` from
the Project (verified via the project/intake skill markers).
"""
from __future__ import annotations


def test_capture_project_intake_tool_is_registered_with_expected_schema():
    """Tool exposes title/kind/area/body and the kind enum matches the writer."""
    import app.tools.local  # noqa: F401  - triggers auto-load
    from app.services.project_intake_writer import VALID_KINDS
    from app.tools.registry import _tools

    entry = _tools.get("capture_project_intake")
    assert entry is not None, "capture_project_intake must be registered"

    fn = entry["schema"]["function"]
    assert fn["name"] == "capture_project_intake"
    params = fn["parameters"]
    assert "title" in params["required"], "title is the only required field"
    props = params["properties"]
    for required_param in ("title", "kind", "area", "body", "project_id"):
        assert required_param in props, f"missing param {required_param!r} in tool schema"

    enum_values = props["kind"]["enum"]
    assert set(enum_values) == set(VALID_KINDS), (
        "Tool schema enum must match VALID_KINDS in project_intake_writer; "
        "update both sides if changing."
    )


def test_project_intake_skill_routes_via_capture_tool_not_publish():
    """The rewritten skill must point at capture_project_intake, not the legacy publisher."""
    from pathlib import Path

    skill_path = Path(__file__).resolve().parents[2] / "skills/project/intake.md"
    text = skill_path.read_text()

    assert "capture_project_intake" in text, (
        "Skill must reference the new capture tool as the canonical write path."
    )
    assert "intake_config" in text, (
        "Skill must read intake_config from get_project_factory_state to know which substrate to use."
    )
    assert "publish_issue_intake" not in text, (
        "Phase 4BD.6 - publish_issue_intake is removed; the skill must not reference it."
    )
    assert "repo_workflow.sections.intake" in text, (
        "Phase 4BE.2 - skill must read the WORKFLOW.md ## Intake section first "
        "before falling back to intake_config."
    )
    assert ".spindrel/WORKFLOW.md" in text, (
        "Skill must name the canonical repo-owned contract path."
    )
