from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.notes import (
    NotesSurface,
    build_assist_proposal,
    content_hash,
    create_note,
    list_notes,
    parse_frontmatter,
    read_note,
    write_note,
)


def _surface(tmp_path: Path) -> NotesSurface:
    return NotesSurface(root=str(tmp_path), kb_rel="knowledge-base", scope="channel", channel_id="00000000-0000-0000-0000-000000000123")


def test_create_note_writes_markdown_frontmatter_and_lists_rich_metadata(tmp_path: Path):
    surface = _surface(tmp_path)

    note = create_note(surface, title="Magic Note")

    path = tmp_path / "knowledge-base" / note["path"]
    assert path.is_file()
    assert note["path"] == "notes/magic-note.md"
    assert note["workspace_path"] == "knowledge-base/notes/magic-note.md"
    assert note["tool_path"] == "/workspace/channels/00000000-0000-0000-0000-000000000123/knowledge-base/notes/magic-note.md"
    assert note["title"] == "Magic Note"
    assert note["scope"] == "channel"

    meta, body = parse_frontmatter(path.read_text())
    assert meta["spindrel_kind"] == "note"
    assert meta["title"] == "Magic Note"
    assert meta["tags"] == []
    assert body.startswith("# Magic Note")

    listed = list_notes(surface)
    assert listed[0]["title"] == "Magic Note"
    assert listed[0]["word_count"] == 2


def test_write_note_requires_current_hash_and_creates_backup(tmp_path: Path):
    surface = _surface(tmp_path)
    note = create_note(surface, title="Safe Note", content="# Safe Note\n\nOriginal")
    original = read_note(surface, note["slug"])

    with pytest.raises(HTTPException) as exc:
        write_note(surface, note["slug"], "# Safe Note\n\nStale", "not-current")
    assert exc.value.status_code == 409

    updated = write_note(
        surface,
        note["slug"],
        "# Safe Note\n\nUpdated",
        content_hash(original["content"]),
    )
    assert "Updated" in updated["content"]

    note_path = tmp_path / "knowledge-base" / "notes" / "safe-note.md"
    backups = list((note_path.parent / ".versions").glob("safe-note.md.*.bak"))
    assert len(backups) == 1
    assert "Original" in backups[0].read_text()


def test_assist_fallback_produces_structured_markdown_for_minimal_selection():
    proposal = build_assist_proposal(
        "# Untitled\n\nwhats up\n",
        selection={"start": 0, "end": 19, "text": "# Untitled\n\nwhats up\n"},
        instruction=None,
        mode="clarify_structure",
        fallback_reason="fallback",
    )

    assert proposal["target"] == "selection"
    assert proposal["replacement_markdown"] != "# Untitled\n\nwhats up\n"
    assert "## Notes" in proposal["replacement_markdown"]
    assert "- whats up" in proposal["replacement_markdown"]
    assert proposal["diff"]


def test_assist_fallback_turns_note_intent_into_starter_scaffold():
    proposal = build_assist_proposal(
        "# Untitled\n\nI want a note about sour dough\n",
        selection={"start": 13, "end": 43, "text": "I want a note about sour dough"},
        instruction=None,
        mode="clarify_structure",
        fallback_reason="fallback",
    )

    assert "## Sour Dough" in proposal["replacement_markdown"]
    assert "### What this note is for" in proposal["replacement_markdown"]
    assert "- Topic: sour dough" in proposal["replacement_markdown"]
