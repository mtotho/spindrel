"""Phase 4BD.4 - propose_run_packs tool registration + schema integrity.

End-to-end behavior (write to canonical repo, schema replacement) is covered
by tests/unit/test_project_run_pack_writer.py. This file enforces the tool
contract: the schema is registered, required fields are intact, the
category/confidence enums match the writer constants, and the tool is wired
through the auto-load path.
"""
from __future__ import annotations


def test_propose_run_packs_tool_is_registered_with_expected_schema():
    import app.tools.local  # noqa: F401 - triggers auto-load
    from app.services.project_run_pack_writer import VALID_CATEGORIES, VALID_CONFIDENCE
    from app.tools.registry import _tools

    entry = _tools.get("propose_run_packs")
    assert entry is not None, "propose_run_packs must be registered"

    fn = entry["schema"]["function"]
    assert fn["name"] == "propose_run_packs"
    params = fn["parameters"]
    assert set(params["required"]) == {"packs", "source_artifact_path"}

    pack_props = params["properties"]["packs"]["items"]["properties"]
    for required_param in ("title", "summary", "category", "confidence"):
        assert required_param in pack_props, f"missing pack param {required_param!r}"

    assert set(pack_props["category"]["enum"]) == set(VALID_CATEGORIES)
    assert set(pack_props["confidence"]["enum"]) == set(VALID_CONFIDENCE)


def test_propose_run_packs_tool_safety_tier_is_mutating():
    import app.tools.local  # noqa: F401
    from app.tools.registry import _tools

    entry = _tools["propose_run_packs"]
    assert entry.get("safety_tier") == "mutating"
    assert entry.get("requires_bot_context") is True
