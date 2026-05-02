"""Phase 4BD.3 - file-write helpers for repo-resident intake substrate."""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services.project_intake_writer import (
    CapturedIntakeNote,
    append_to_repo_file,
    kebab_slug,
    render_inbox_entry,
    write_to_repo_folder,
)


def test_kebab_slug_normalizes_punctuation_and_caps_length():
    assert kebab_slug("Chat scroll jitter!") == "chat-scroll-jitter"
    assert kebab_slug("UPPER Case   Mixed") == "upper-case-mixed"
    assert kebab_slug("a" * 200, max_len=10) == "a" * 10
    assert kebab_slug("___") == "note", "empty/punct-only falls back to a stable placeholder"
    assert kebab_slug("foo-bar---baz") == "foo-bar-baz"


def test_render_inbox_entry_emits_documented_schema():
    note = CapturedIntakeNote(
        title="Chat scroll jitter",
        kind="bug",
        area="ui/chat",
        body="Scroll jumps when new messages arrive while user is mid-scroll.",
        captured_at=datetime(2026, 5, 2, 14, 32),
    )
    rendered = render_inbox_entry(note)
    assert rendered.startswith("## 2026-05-02 14:32 chat-scroll-jitter\n")
    assert "**kind:** bug · **area:** ui/chat · **status:** open" in rendered
    assert "Scroll jumps when new messages arrive" in rendered
    assert rendered.endswith("\n")


def test_render_inbox_entry_drops_area_when_unset():
    note = CapturedIntakeNote(
        title="random idea",
        kind="idea",
        captured_at=datetime(2026, 5, 2, 14, 32),
    )
    rendered = render_inbox_entry(note)
    assert "**area:** -" in rendered, "area must always be present in the tag line for grep stability"


def test_append_to_repo_file_creates_file_when_missing(tmp_path):
    canonical = tmp_path / "repo"
    canonical.mkdir()
    note = CapturedIntakeNote(
        title="first note",
        kind="idea",
        captured_at=datetime(2026, 5, 2, 14, 32),
    )

    result = append_to_repo_file(str(canonical), "docs/inbox.md", note)

    written = (canonical / "docs/inbox.md").read_text()
    assert "## 2026-05-02 14:32 first-note" in written
    assert result.created_file is True
    assert result.appended is False
    assert result.relative_path == "docs/inbox.md"
    assert result.host_path == str(canonical / "docs/inbox.md")
    assert result.slug == "first-note"


def test_append_to_repo_file_preserves_existing_content_and_appends(tmp_path):
    canonical = tmp_path / "repo"
    inbox_dir = canonical / "docs"
    inbox_dir.mkdir(parents=True)
    inbox_file = inbox_dir / "inbox.md"
    inbox_file.write_text(
        "---\n"
        "title: Inbox\n"
        "---\n"
        "\n"
        "## Open\n"
        "\n"
        "## 2026-05-01 10:00 prior-note\n"
        "**kind:** bug · **area:** - · **status:** open\n"
        "Earlier capture.\n"
    )
    note = CapturedIntakeNote(
        title="Second note",
        kind="bug",
        area="ui/chat",
        body="New observation",
        captured_at=datetime(2026, 5, 2, 14, 32),
    )

    result = append_to_repo_file(str(canonical), "docs/inbox.md", note)

    text = inbox_file.read_text()
    assert "title: Inbox" in text, "frontmatter and prior content must survive intact"
    assert "## 2026-05-01 10:00 prior-note" in text
    assert "## 2026-05-02 14:32 second-note" in text
    assert text.index("prior-note") < text.index("second-note"), "newer entries append after older ones"
    assert result.appended is True
    assert result.created_file is False


def test_write_to_repo_folder_uses_timestamped_filename(tmp_path):
    canonical = tmp_path / "repo"
    canonical.mkdir()
    note = CapturedIntakeNote(
        title="Pricing page slow",
        kind="bug",
        area="ui/pricing",
        captured_at=datetime(2026, 5, 2, 14, 32),
    )

    result = write_to_repo_folder(str(canonical), "docs/inbox/", note)

    assert result.relative_path == "docs/inbox/20260502-1432-pricing-page-slow.md"
    written = (canonical / result.relative_path).read_text()
    assert "## 2026-05-02 14:32 pricing-page-slow" in written
    assert result.created_file is True


def test_write_to_repo_folder_avoids_collision_within_same_minute(tmp_path):
    canonical = tmp_path / "repo"
    canonical.mkdir()
    note_a = CapturedIntakeNote(
        title="dup name",
        captured_at=datetime(2026, 5, 2, 14, 32),
    )
    note_b = CapturedIntakeNote(
        title="dup name",
        captured_at=datetime(2026, 5, 2, 14, 32),
    )

    first = write_to_repo_folder(str(canonical), "docs/inbox", note_a)
    second = write_to_repo_folder(str(canonical), "docs/inbox", note_b)

    assert first.relative_path == "docs/inbox/20260502-1432-dup-name.md"
    assert second.relative_path == "docs/inbox/20260502-1432-dup-name-2.md"
    assert (canonical / first.relative_path).exists()
    assert (canonical / second.relative_path).exists()
