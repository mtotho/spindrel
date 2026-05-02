from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_generic_runtime_project_skills_do_not_reference_spindrel_repo_dev_details():
    runtime_paths = [
        ROOT / "skills" / "project" / "index.md",
        ROOT / "skills" / "project" / "plan" / "prd.md",
        ROOT / "skills" / "project" / "plan" / "run_packs.md",
        ROOT / "skills" / "project" / "runs" / "implement.md",
        ROOT / "skills" / "project" / "runs" / "review.md",
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


def test_runtime_project_skill_index_exposes_cluster_without_slash_command_dependency():
    text = (ROOT / "skills" / "project" / "index.md").read_text()

    assert "get_project_factory_state" in text
    assert "project/setup/init" in text
    assert "project/plan/prd" in text
    assert "project/plan/run_packs" in text
    assert "project/runs/implement" in text
    assert "project/runs/review" in text
    assert "slash command" not in text.lower()


def test_repo_local_spindrel_skills_document_inside_spindrel_project_handoff():
    e2e = (ROOT / ".agents" / "skills" / "spindrel-e2e-development" / "SKILL.md").read_text()
    visual = (
        ROOT / ".agents" / "skills" / "spindrel-visual-feedback-loop" / "SKILL.md"
    ).read_text()
    readiness = (
        ROOT / ".agents" / "skills" / "agentic-readiness" / "SKILL.md"
    ).read_text()

    assert "project/runs/implement" in e2e
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
