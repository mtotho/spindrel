from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / ".agents" / "manifest.json"
DIAGNOSTICS_SKILL_DIR = ROOT / "skills" / "diagnostics"
NEW_SKILL_IDS = {
    "spindrel-backend-operator",
    "spindrel-ui-operator",
    "spindrel-integration-operator",
    "spindrel-widget-operator",
    "spindrel-harness-operator",
    "spindrel-docs-operator",
}
EXPECTED_SKILL_IDS = NEW_SKILL_IDS | {"spindrel-visual-feedback-loop"}
AGENTIC_READINESS_ID = "agentic-readiness"
LIVE_HEALTH_TRIAGE_ID = "spindrel-live-health-triage"


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def _split_frontmatter(skill_markdown: str) -> tuple[dict, str]:
    assert skill_markdown.startswith("---\n")
    _, frontmatter, body = skill_markdown.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


def test_repo_agent_manifest_is_repo_dev_only() -> None:
    manifest = _load_manifest()

    assert manifest["schema_version"] == "repo-agent-skills.v1"
    assert manifest["scope"] == "repo-dev-only"
    assert manifest["runtime_import"] is False
    assert "not Spindrel runtime skills" in manifest["notes"]


def test_repo_agent_manifest_indexes_each_skill_folder() -> None:
    manifest = _load_manifest()
    skills = {entry["id"]: entry for entry in manifest["skills"]}

    assert (EXPECTED_SKILL_IDS | {AGENTIC_READINESS_ID, LIVE_HEALTH_TRIAGE_ID}).issubset(skills)

    for skill_id, entry in skills.items():
        skill_dir = ROOT / entry["path"]
        skill_path = skill_dir / "SKILL.md"

        assert skill_path.exists(), skill_id
        assert entry["path"] == f".agents/skills/{skill_id}"
        assert entry["description"]
        assert all(isinstance(trigger, str) and trigger for trigger in entry["triggers"])
        assert all(
            isinstance(command, str) and command
            for command in entry["verification_commands"]
        )


def test_repo_agent_manifest_canonical_guides_exist() -> None:
    manifest = _load_manifest()

    for entry in manifest["skills"]:
        for guide in entry["canonical_guides"]:
            assert (ROOT / guide).exists(), f"{entry['id']} references missing {guide}"


def test_repo_agent_skill_frontmatter_matches_manifest() -> None:
    manifest = _load_manifest()

    for entry in manifest["skills"]:
        skill_path = ROOT / entry["path"] / "SKILL.md"
        frontmatter, body = _split_frontmatter(skill_path.read_text())

        assert frontmatter["name"] == entry["id"]
        assert frontmatter["description"]
        assert body.strip()


def test_new_repo_agent_skills_keep_runtime_boundary_explicit() -> None:
    manifest = _load_manifest()
    skills = {entry["id"]: entry for entry in manifest["skills"]}

    for skill_id in NEW_SKILL_IDS:
        body = (ROOT / skills[skill_id]["path"] / "SKILL.md").read_text().lower()

        assert "repo-dev skill" in body
        assert "not a spindrel runtime skill" in body
        assert "must not be imported into app skill tables" in body


def test_integration_skill_preserves_integration_boundaries() -> None:
    manifest = _load_manifest()
    skills = {entry["id"]: entry for entry in manifest["skills"]}
    integration_entry = skills["spindrel-integration-operator"]
    skill_text = (
        ROOT / integration_entry["path"] / "SKILL.md"
    ).read_text().lower()

    assert "docs/guides/integrations.md" in integration_entry["canonical_guides"]
    assert "activation" in skill_text
    assert "binding" in skill_text
    assert "no integration-specific code in `app/`" in skill_text


def test_agentic_readiness_skill_preserves_repo_runtime_boundary() -> None:
    manifest = _load_manifest()
    skills = {entry["id"]: entry for entry in manifest["skills"]}
    entry = skills[AGENTIC_READINESS_ID]
    skill_dir = ROOT / entry["path"]
    skill_text = (skill_dir / "SKILL.md").read_text()
    skill_lower = skill_text.lower()

    assert entry["path"] == ".agents/skills/agentic-readiness"
    assert "skill design" in entry["triggers"]
    assert "feature should be a skill" in entry["triggers"]
    assert "repo-dev skill" in skill_lower
    assert "not a spindrel runtime skill" in skill_lower
    assert "must not be imported into app skill tables" in skill_lower
    assert "runtime agents use runtime tools" in skill_lower
    assert "references/feature-placement-rubric.md" in skill_text
    assert "references/internal-agent-readiness.md" in skill_text
    assert len(skill_text.splitlines()) < 160


def test_agentic_readiness_references_and_metadata_exist() -> None:
    manifest = _load_manifest()
    skills = {entry["id"]: entry for entry in manifest["skills"]}
    skill_dir = ROOT / skills[AGENTIC_READINESS_ID]["path"]

    for reference in (
        "feature-placement-rubric.md",
        "external-agent-readiness.md",
        "internal-agent-readiness.md",
        "small-model-guidance.md",
    ):
        text = (skill_dir / "references" / reference).read_text()
        assert "# " in text
        assert "runtime skill" in text.lower() or "repo" in text.lower()

    metadata = yaml.safe_load((skill_dir / "agents" / "openai.yaml").read_text())
    assert metadata["interface"]["display_name"] == "Agentic Readiness"
    assert "repo-dev" in metadata["interface"]["short_description"]
    assert "runtime agents" in metadata["interface"]["short_description"]


def test_live_health_triage_skill_preserves_boundaries_and_resolution_rules() -> None:
    manifest = _load_manifest()
    skills = {entry["id"]: entry for entry in manifest["skills"]}
    entry = skills[LIVE_HEALTH_TRIAGE_ID]
    skill_dir = ROOT / entry["path"]
    skill_text = (skill_dir / "SKILL.md").read_text()
    skill_lower = skill_text.lower()

    assert entry["path"] == ".agents/skills/spindrel-live-health-triage"
    assert "docs/guides/heartbeats.md" in entry["canonical_guides"]
    assert "repo-dev skill" in skill_lower
    assert "not a spindrel runtime skill" in skill_lower
    assert "must not be imported into app skill tables" in skill_lower
    assert "/api/v1/system-health/recent-errors" in skill_text
    assert "/api/v1/workspace/attention/{id}/resolve" in skill_text
    assert "never resolve `likely_code_bug`" in skill_lower

    metadata = yaml.safe_load((skill_dir / "agents" / "openai.yaml").read_text())
    assert metadata["interface"]["display_name"] == "Spindrel Live Health Triage"
    assert "repo-dev" in metadata["interface"]["short_description"].lower()


def test_runtime_health_triage_skill_is_indexed_and_runtime_scoped() -> None:
    skill_text = (DIAGNOSTICS_SKILL_DIR / "health_triage.md").read_text()
    index_text = (DIAGNOSTICS_SKILL_DIR / "index.md").read_text()
    recent_text = (DIAGNOSTICS_SKILL_DIR / "recent_errors.md").read_text()

    assert "Health Triage" in index_text
    assert "health_triage.md" in index_text
    assert "Health Triage" in recent_text
    assert "Spindrel runtime skill" in skill_text
    assert "does not assume access to the Git repo" in skill_text
    assert "/api/v1/system-health/recent-errors/promote" in skill_text
    assert "/api/v1/workspace/attention/{id}/resolve" in skill_text
    assert "Unknown is not benign" in skill_text
