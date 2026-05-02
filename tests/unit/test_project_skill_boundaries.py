from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_generic_runtime_project_skills_do_not_reference_spindrel_repo_dev_details():
    runtime_paths = [
        ROOT / "skills" / "project" / "index.md",
        ROOT / "skills" / "project" / "plan" / "prd.md",
        ROOT / "skills" / "project" / "plan" / "run_packs.md",
        ROOT / "skills" / "project" / "runs" / "implement.md",
        ROOT / "skills" / "project" / "runs" / "review.md",
        ROOT / "skills" / "project" / "runs" / "recovery.md",
        ROOT / "skills" / "project" / "runs" / "scheduled.md",
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


def test_phase_4bf_skill_polish_markers_landed():
    """Phase 4BF - confirm the small-model failure modes were closed."""
    init_text = (ROOT / "skills" / "project" / "setup" / "init.md").read_text()
    assert "Prime the repo before recommending anything" in init_text, (
        "4BF.1 - init.md must walk through AGENTS.md / README / package files / git log explicitly"
    )

    prd_text = (ROOT / "skills" / "project" / "plan" / "prd.md").read_text()
    assert "Ask one clarifying question at a time using `AskUserQuestion`" in prd_text, (
        "4BF.2 - prd.md must name the AskUserQuestion drip protocol explicitly"
    )

    implement_text = (ROOT / "skills" / "project" / "runs" / "implement.md").read_text()
    assert "Research before editing" in implement_text, (
        "4BF.3 - implement.md must require a research pass before any edit"
    )
    assert ".spindrel/runs/" in implement_text, (
        "4BF.3 - implement.md must name the per-run plan artifact path"
    )

    scheduled_text = (ROOT / "skills" / "project" / "runs" / "scheduled.md").read_text()
    assert "## Examples" in scheduled_text, "4BF.4 - scheduled.md must carry good/bad examples"
    assert "Why good" in scheduled_text and "Why bad" in scheduled_text

    index_text = (ROOT / "skills" / "project" / "index.md").read_text()
    assert "Channel is not Project-bound" in index_text, (
        "4BF.5 - index.md stage routing must include error rows"
    )
    assert "project/runs/recovery" in index_text, (
        "4BF.6 - index.md must route failure-state runs to the recovery skill"
    )

    recovery_text = (ROOT / "skills" / "project" / "runs" / "recovery.md").read_text()
    for mode in ("continue", "retry", "hand_off", "abandon"):
        assert f"`{mode}`" in recovery_text, f"recovery.md must enumerate the {mode!r} mode"
