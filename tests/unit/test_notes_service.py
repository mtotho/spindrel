from pathlib import Path

import pytest
from fastapi import HTTPException

from app.services.notes import (
    NotesSurface,
    content_hash,
    create_note,
    list_notes,
    parse_frontmatter,
    read_note,
    write_note,
)


def _surface(tmp_path: Path) -> NotesSurface:
    return NotesSurface(root=str(tmp_path), kb_rel="knowledge-base", scope="channel")


def test_create_note_writes_markdown_frontmatter_and_lists_rich_metadata(tmp_path: Path):
    surface = _surface(tmp_path)

    note = create_note(surface, title="Magic Note")

    path = tmp_path / "knowledge-base" / note["path"]
    assert path.is_file()
    assert note["path"] == "notes/magic-note.md"
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
