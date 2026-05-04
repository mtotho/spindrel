from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / ".agents" / "manifest.json"
DIAGNOSTICS_SKILL_DIR = ROOT / "skills" / "diagnostics"
AGENT_TEST_GUIDANCE_PATHS = [
    ROOT / "AGENTS.md",
    ROOT / ".agents",
    ROOT / "skills" / "workspace" / "project_coding_runs.md",
    ROOT / "docs" / "guides" / "agent-e2e-development.md",
    ROOT / "docs" / "guides" / "projects.md",
    ROOT / "app" / "services" / "run_presets.py",
    ROOT / "app" / "services" / "project_coding_runs.py",
]
DOCKER_UNIT_TEST_PATTERNS = [
    re.compile(r"docker\s+build\s+-f\s+Dockerfile\.test", re.IGNORECASE),
    re.compile(r"docker\s+run[^\n]*(pytest|unit tests?)", re.IGNORECASE),
    re.compile(r"docker\s+compose\s+run[^\n]*(pytest|unit tests?|test command)", re.IGNORECASE),
    re.compile(r"run via Dockerfile\.test", re.IGNORECASE),
]
NEW_SKILL_IDS = {
    "spindrel-backend-operator",
    "spindrel-ui-operator",
    "spindrel-integration-operator",
    "spindrel-widget-operator",
    "spindrel-harness-operator",
    "spindrel-docs-operator",
}
AGENTIC_READINESS_ID = "agentic-readiness"
LIVE_HEALTH_TRIAGE_ID = "spindrel-live-health-triage"


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def _split_frontmatter(skill_markdown: str) -> tuple[dict, str]:
    assert skill_markdown.startswith("---\n")
    _, frontmatter, body = skill_markdown.split("---\n", 2)
    return yaml.safe_load(frontmatter), body


def _agent_guidance_files() -> list[Path]:
    files: list[Path] = []
    for path in AGENT_TEST_GUIDANCE_PATHS:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.is_file()))
        elif path.exists():
            files.append(path)
    return files


def _repo_skill_ids_on_disk() -> set[str]:
    return {
        path.parent.name
        for path in (ROOT / ".agents" / "skills").glob("*/SKILL.md")
        if path.parent.name != "_shared"
    }


def test_repo_agent_manifest_is_repo_dev_only() -> None:
    manifest = _load_manifest()

    assert manifest["schema_version"] == "repo-agent-skills.v1"
    assert manifest["scope"] == "repo-dev-only"
    assert manifest["runtime_import"] is False
    assert "not Spindrel runtime skills" in manifest["notes"]


def test_repo_agent_manifest_indexes_each_skill_folder() -> None:
    manifest = _load_manifest()
    skills = {entry["id"]: entry for entry in manifest["skills"]}

    assert set(skills) == _repo_skill_ids_on_disk()
    empty_skill_dirs = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / ".agents" / "skills").iterdir()
        if path.is_dir() and path.name != "_shared" and not (path / "SKILL.md").exists()
    ]
    assert empty_skill_dirs == []

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

    for skill_id in skills:
        body = (ROOT / skills[skill_id]["path"] / "SKILL.md").read_text().lower()

        assert "repo-dev skill" in body
        assert "not a spindrel runtime skill" in body
        assert re.search(r"must\s+not\s+be\s+imported\s+into\s+app\s+skill\s+tables", body)


def test_repo_agent_skills_do_not_use_harness_specific_delegation_or_docker_test_fallback() -> None:
    offenders: list[str] = []
    for path in (ROOT / ".agents" / "skills").rglob("*.md"):
        rel = path.relative_to(ROOT)
        text = path.read_text(errors="ignore")
        for pattern in (
            re.compile(r"subagent_type=Explore"),
            re.compile(r"run (it )?in Docker/Python 3\.12", re.IGNORECASE),
        ):
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{rel}:{line_no}: {match.group(0)!r}")

    assert offenders == []


def test_agent_facing_guidance_does_not_reintroduce_docker_unit_test_runner() -> None:
    offenders: list[str] = []
    for path in _agent_guidance_files():
        rel = path.relative_to(ROOT)
        text = path.read_text(errors="ignore")
        for pattern in DOCKER_UNIT_TEST_PATTERNS:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{rel}:{line_no}: {match.group(0)!r}")

    assert offenders == []


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
