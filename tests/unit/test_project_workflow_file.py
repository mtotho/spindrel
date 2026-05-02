"""Tests for the per-Project workflow contract parser (Phase 4BE.0)."""
from __future__ import annotations

import textwrap
from types import SimpleNamespace

from app.services import project_workflow_file as workflow_module
from app.services.project_workflow_file import (
    STANDARD_SECTIONS,
    WORKFLOW_RELATIVE_PATH,
    WorkflowFile,
    parse_workflow_file,
    project_workflow_file,
    write_workflow_starter,
)


def test_workflow_relative_path_is_dotspindrel_workflow_md():
    assert WORKFLOW_RELATIVE_PATH == ".spindrel/WORKFLOW.md"


def test_standard_sections_match_documented_contract():
    # If this changes, the get_project_factory_state surface (4BE.1) must be
    # updated in lockstep so consumers don't silently lose a section.
    assert STANDARD_SECTIONS == ("policy", "intake", "runs", "hooks", "dependencies")


def test_parse_workflow_file_with_frontmatter_and_sections():
    text = textwrap.dedent("""\
        ---
        name: spindrel
        version: 1
        ---

        # Spindrel WORKFLOW

        ## Policy
        Branch from master. Open PR via gh.

        ## Intake
        Inbox at docs/inbox.md.

        ## Hooks
        before_run: ./scripts/check.sh
        """)

    frontmatter, sections = parse_workflow_file(text)

    assert frontmatter == {"name": "spindrel", "version": 1}
    assert sections["policy"].startswith("Branch from master")
    assert sections["intake"] == "Inbox at docs/inbox.md."
    assert "before_run" in sections["hooks"]


def test_parse_workflow_file_no_frontmatter():
    text = "## Policy\nBranch from master.\n"
    frontmatter, sections = parse_workflow_file(text)
    assert frontmatter == {}
    assert sections == {"policy": "Branch from master."}


def test_parse_workflow_file_normalizes_section_heading_case_and_punct():
    text = "## Run Hooks\nbody\n"
    _, sections = parse_workflow_file(text)
    assert "run-hooks" in sections, "headings normalize to kebab-slug"


def test_parse_workflow_file_handles_empty_text():
    assert parse_workflow_file("") == ({}, {})


def test_parse_workflow_file_swallows_bad_yaml():
    text = "---\n: : not: valid: yaml: [\n---\n## Policy\nbody\n"
    frontmatter, sections = parse_workflow_file(text)
    assert frontmatter == {}, "bad YAML must not raise; surface empty frontmatter"
    assert sections == {"policy": "body"}


def test_parse_workflow_file_keeps_subheadings_inside_section():
    text = textwrap.dedent("""\
        ## Policy
        Top of policy.

        ### Branch rules
        Off master only.

        ## Intake
        Inbox path.
        """)
    _, sections = parse_workflow_file(text)
    assert "### Branch rules" in sections["policy"]
    assert "Off master only." in sections["policy"]
    assert sections["intake"] == "Inbox path."


def test_parse_workflow_file_last_duplicate_heading_wins():
    text = "## Policy\nold\n## Policy\nnew\n"
    _, sections = parse_workflow_file(text)
    assert sections["policy"] == "new", "later override replaces earlier section"


def test_workflow_file_section_lookup_normalizes_caller_input():
    wf = WorkflowFile(
        relative_path=WORKFLOW_RELATIVE_PATH,
        host_path="/x/.spindrel/WORKFLOW.md",
        present=True,
        sections={"run-hooks": "body"},
    )
    assert wf.section("Run Hooks") == "body"
    assert wf.section("RUN HOOKS") == "body"
    assert wf.section("missing") is None


def test_project_workflow_file_absent_when_no_canonical_repo(monkeypatch):
    monkeypatch.setattr(
        workflow_module, "project_canonical_repo_host_path", lambda *_, **__: None
    )
    project = SimpleNamespace(metadata_={})
    wf = project_workflow_file(project)
    assert wf.present is False
    assert wf.host_path is None
    assert wf.relative_path == WORKFLOW_RELATIVE_PATH


def test_project_workflow_file_absent_when_file_missing(tmp_path, monkeypatch):
    canonical = tmp_path / "repo"
    canonical.mkdir()
    monkeypatch.setattr(
        workflow_module,
        "project_canonical_repo_host_path",
        lambda *_, **__: str(canonical),
    )

    wf = project_workflow_file(SimpleNamespace())

    assert wf.present is False
    assert wf.host_path == str(canonical / ".spindrel/WORKFLOW.md")
    assert wf.sections == {}
    assert wf.frontmatter == {}


def test_project_workflow_file_reads_and_parses_when_present(tmp_path, monkeypatch):
    canonical = tmp_path / "repo"
    (canonical / ".spindrel").mkdir(parents=True)
    (canonical / ".spindrel/WORKFLOW.md").write_text(
        textwrap.dedent("""\
            ---
            name: spindrel
            ---

            ## Policy
            Branch from master.

            ## Intake
            Inbox at docs/inbox.md.
            """),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        workflow_module,
        "project_canonical_repo_host_path",
        lambda *_, **__: str(canonical),
    )

    wf = project_workflow_file(SimpleNamespace())

    assert wf.present is True
    assert wf.host_path == str(canonical / ".spindrel/WORKFLOW.md")
    assert wf.frontmatter == {"name": "spindrel"}
    assert wf.section("policy") == "Branch from master."
    assert wf.section("Intake") == "Inbox at docs/inbox.md."
    assert wf.raw is not None and "Branch from master" in wf.raw


def test_write_workflow_starter_creates_file_when_absent(tmp_path, monkeypatch):
    canonical = tmp_path / "repo"
    canonical.mkdir()
    monkeypatch.setattr(
        workflow_module,
        "project_canonical_repo_host_path",
        lambda *_, **__: str(canonical),
    )
    project = SimpleNamespace(name="DemoProject")

    result = write_workflow_starter(project)

    assert result.ok is True
    assert result.error is None
    assert result.host_path == str(canonical / WORKFLOW_RELATIVE_PATH)
    written = (canonical / WORKFLOW_RELATIVE_PATH).read_text(encoding="utf-8")
    assert "name: DemoProject" in written, "frontmatter seeds the project name"
    for section in ("## Policy", "## Intake", "## Runs", "## Hooks", "## Dependencies"):
        assert section in written, f"starter must scaffold the {section!r} section"


def test_write_workflow_starter_refuses_to_overwrite(tmp_path, monkeypatch):
    canonical = tmp_path / "repo"
    (canonical / ".spindrel").mkdir(parents=True)
    existing = canonical / WORKFLOW_RELATIVE_PATH
    existing.write_text("# hand-authored\n", encoding="utf-8")
    monkeypatch.setattr(
        workflow_module,
        "project_canonical_repo_host_path",
        lambda *_, **__: str(canonical),
    )

    result = write_workflow_starter(SimpleNamespace(name="x"))

    assert result.ok is False
    assert "already exists" in (result.error or "")
    assert existing.read_text(encoding="utf-8") == "# hand-authored\n", (
        "existing repo-owned content must survive untouched"
    )


def test_write_workflow_starter_refuses_when_no_canonical_repo(monkeypatch):
    monkeypatch.setattr(
        workflow_module, "project_canonical_repo_host_path", lambda *_, **__: None
    )

    result = write_workflow_starter(SimpleNamespace(name="x"))

    assert result.ok is False
    assert result.host_path is None
    assert "canonical repo" in (result.error or "")


def test_write_project_workflow_starter_tool_is_registered():
    """Phase 4BE.4 - tool must be registered with the documented schema."""
    import app.tools.local  # noqa: F401  - triggers auto-load
    from app.tools.registry import _tools

    entry = _tools.get("write_project_workflow_starter")
    assert entry is not None, "write_project_workflow_starter must be registered"
    fn = entry["schema"]["function"]
    assert fn["name"] == "write_project_workflow_starter"
    props = fn["parameters"]["properties"]
    assert "project_id" in props
    # Tool must be safe enough to refuse silently rather than raise on missing
    # canonical repo / existing file - covered by the service tests above.


def test_project_intake_skill_skips_intake_config_step_when_workflow_overrides():
    """4BE.5 - setup/init Step 11 must be conditional on WORKFLOW.md absence."""
    from pathlib import Path

    init_path = Path(__file__).resolve().parents[2] / "skills/project/setup/init.md"
    text = init_path.read_text(encoding="utf-8")
    assert "repo_workflow.sections.intake" in text, (
        "Step 11 must skip the intake_config prompt when WORKFLOW.md ## Intake is present"
    )
    assert "write_project_workflow_starter" in text, (
        "Step 4 must offer the starter writer when WORKFLOW.md is missing"
    )
