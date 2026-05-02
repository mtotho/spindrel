"""Tests for app/services/skill_aliases.py - legacy ID -> canonical resolution."""
from __future__ import annotations

import pytest

from app.services.skill_aliases import (
    LEGACY_SKILL_ID_ALIASES,
    is_legacy_alias,
    resolve_skill_id,
)


@pytest.mark.parametrize("legacy_id, canonical_id", [
    ("workspace/project_lifecycle", "project"),
    ("workspace/project_init", "project/setup/init"),
    ("workspace/project_prd", "project/plan/prd"),
    ("workspace/project_stories", "project/plan/run_packs"),
    ("workspace/project_coding_runs", "project/runs/implement"),
    ("workspace/issue_intake", "project/intake"),
])
def test_legacy_workspace_project_ids_resolve_to_new_cluster(legacy_id, canonical_id):
    assert resolve_skill_id(legacy_id) == canonical_id
    assert is_legacy_alias(legacy_id) is True


def test_unknown_skill_id_passes_through_unchanged():
    assert resolve_skill_id("project/setup/init") == "project/setup/init"
    assert resolve_skill_id("workspace/files") == "workspace/files"
    assert resolve_skill_id("not/a/real/skill") == "not/a/real/skill"
    assert is_legacy_alias("project/setup/init") is False
    assert is_legacy_alias("workspace/files") is False


def test_alias_targets_are_real_skill_files():
    """Every alias target should correspond to a file under skills/project/.

    This is a structural guard: if a project skill is renamed/moved without
    updating the alias map, this test fires.
    """
    from pathlib import Path

    skills_root = Path(__file__).resolve().parents[2] / "skills"
    for legacy_id, canonical_id in LEGACY_SKILL_ID_ALIASES.items():
        # Folder-layout skill IDs map to either skills/<id>/index.md
        # or skills/<id>.md when the deepest segment is a leaf file.
        index_path = skills_root / canonical_id / "index.md"
        leaf_path = skills_root.joinpath(*canonical_id.split("/")).with_suffix(".md")
        assert index_path.exists() or leaf_path.exists(), (
            f"Alias {legacy_id} -> {canonical_id} but no skill file found at "
            f"{index_path} or {leaf_path}"
        )
