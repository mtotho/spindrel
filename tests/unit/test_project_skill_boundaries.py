from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_generic_runtime_project_skills_do_not_reference_spindrel_repo_dev_details():
    runtime_paths = [
        ROOT / "skills" / "workspace" / "project_lifecycle.md",
        ROOT / "skills" / "workspace" / "project_prd.md",
        ROOT / "skills" / "workspace" / "project_stories.md",
        ROOT / "skills" / "workspace" / "project_coding_runs.md",
        ROOT / "skills" / "agent_readiness" / "operator.md",
    ]
    forbidden = [
        ".env.agent-e2e",
        "scripts/agent_e2e_dev.py",
        "spindrel-e2e-development",
        "spindrel-visual-feedback-loop",
        "project-factory-generic-live-loop",
        "project-workspace-",
        "agent-server",
    ]

    for path in runtime_paths:
        text = path.read_text()
        for needle in forbidden:
            assert needle not in text, f"{path.relative_to(ROOT)} leaks {needle!r}"


def test_runtime_project_skill_index_exposes_lifecycle_without_slash_command_dependency():
    text = (ROOT / "skills" / "workspace" / "index.md").read_text()

    assert "workspace/project_lifecycle" in text
    assert "workspace/project_prd" in text
    assert "workspace/project_stories" in text
    assert "@skill:workspace/project_prd" in text
    assert "slash command" not in text.lower()


def test_repo_local_spindrel_skills_document_inside_spindrel_project_handoff():
    e2e = (ROOT / ".agents" / "skills" / "spindrel-e2e-development" / "SKILL.md").read_text()
    visual = (
        ROOT / ".agents" / "skills" / "spindrel-visual-feedback-loop" / "SKILL.md"
    ).read_text()
    readiness = (
        ROOT / ".agents" / "skills" / "agentic-readiness" / "SKILL.md"
    ).read_text()

    assert "workspace/project_coding_runs" in e2e
    assert "Project-local guidance" in e2e
    assert "composer file mentions" in e2e
    normalized_e2e = " ".join(e2e.split())
    assert "ask the user to configure the Project settings" in normalized_e2e

    assert "Project-local guidance" in visual
    assert "selected Project-local guidance" in visual
    assert "confirm the Project exposes the needed dev" in visual

    assert "In-Spindrel repo-dev AX" in readiness
    assert "Project-local instructions" in readiness
    assert "Runtime skills must stay generic" in readiness
