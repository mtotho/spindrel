from pathlib import Path

from app.services.agent_harnesses.turn_host import (
    _build_project_file_context_hints,
    parse_harness_project_context_tags,
)


def test_parse_harness_project_context_tags_dedupes_files_and_project_items():
    files, project_items = parse_harness_project_context_tags(
        "Use @file:.agents/skills/demo/SKILL.md and @project:dependencies "
        "then reread @file:.agents/skills/demo/SKILL.md."
    )

    assert files == (".agents/skills/demo/SKILL.md",)
    assert project_items == ("dependencies",)


def test_project_file_context_hint_points_to_path_and_includes_small_selected_text(tmp_path):
    target = tmp_path / ".agents" / "skills" / "demo" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Demo\n\nFollow the local runbook.\n", encoding="utf-8")

    hints = _build_project_file_context_hints(
        root=str(tmp_path),
        file_paths=(".agents/skills/demo/SKILL.md",),
    )

    assert len(hints) == 1
    hint = hints[0]
    assert hint.kind == "project_file"
    assert "Path, relative to your current working directory: .agents/skills/demo/SKILL.md" in hint.text
    assert "# Demo" in hint.text
    assert "Use your normal shell/file tools to inspect the file directly" in hint.text


def test_project_file_context_hint_blocks_escape(tmp_path):
    outside = tmp_path.parent / "outside-project-context.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        hints = _build_project_file_context_hints(root=str(tmp_path), file_paths=("../outside-project-context.txt",))
        assert "escapes the active Project work surface" in hints[0].text
    finally:
        outside.unlink(missing_ok=True)
