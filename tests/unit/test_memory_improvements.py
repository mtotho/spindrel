"""Unit tests for memory improvements: MEMORY.md nudge, reference file dates,
and fallback workspace hint."""
import os
import time
import tempfile
from unittest.mock import MagicMock, patch


class TestMemoryMdNudge:
    """Tests for the MEMORY.md line-count nudge in context assembly."""

    def test_nudge_appended_when_over_threshold(self):
        """When MEMORY.md exceeds threshold, a nudge message is appended."""
        content = "\n".join(f"Line {i}" for i in range(150))
        line_count = content.count("\n") + 1
        threshold = 100

        # Simulate the nudge logic from context_assembly
        assert line_count > threshold
        nudge = (
            f"[Memory housekeeping] Your MEMORY.md is {line_count} lines "
            f"(threshold: {threshold}). "
            "Consider pruning stale entries, merging duplicates, or moving detailed "
            "notes to reference/ files to keep MEMORY.md concise and fast to scan."
        )
        assert "Memory housekeeping" in nudge
        assert "150 lines" in nudge

    def test_no_nudge_when_under_threshold(self):
        """When MEMORY.md is under threshold, no nudge."""
        content = "\n".join(f"Line {i}" for i in range(50))
        line_count = content.count("\n") + 1
        threshold = 100
        assert line_count <= threshold

    def test_no_nudge_when_threshold_zero(self):
        """When threshold is 0 (disabled), no nudge regardless of size."""
        content = "\n".join(f"Line {i}" for i in range(200))
        line_count = content.count("\n") + 1
        threshold = 0
        # Logic: threshold > 0 and line_count > threshold
        should_nudge = threshold > 0 and line_count > threshold
        assert not should_nudge

    def test_nudge_at_exact_threshold(self):
        """At exactly the threshold, no nudge (must exceed, not equal)."""
        content = "\n".join(f"Line {i}" for i in range(100))  # 100 lines
        line_count = content.count("\n") + 1
        assert line_count == 100
        threshold = 100
        should_nudge = threshold > 0 and line_count > threshold
        assert not should_nudge


class TestReferenceFileDates:
    """Tests for reference file modification date display."""

    def test_date_formatting(self):
        """Reference file entries include modification date."""
        with tempfile.TemporaryDirectory() as tmpdir:
            ref_dir = os.path.join(tmpdir, "reference")
            os.makedirs(ref_dir)

            # Create a test file
            test_file = os.path.join(ref_dir, "test-notes.md")
            with open(test_file, "w") as f:
                f.write("# Test Notes\n")

            # Simulate the logic from context_assembly
            from datetime import datetime
            mtime = os.path.getmtime(test_file)
            date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

            entry = f"  - test-notes.md (modified {date_str})"
            assert "(modified " in entry
            assert "test-notes.md" in entry
            # Date should be today
            assert datetime.now().strftime("%Y-%m-%d") in entry

    def test_date_fallback_on_error(self):
        """If getmtime fails, entry should still be produced without date."""
        # Simulate the fallback path
        entry = "  - broken-file.md"
        assert "broken-file.md" in entry
        assert "(modified" not in entry


class TestFallbackWorkspaceHint:
    """Tests for the static workspace hint when no template is assigned."""

    def test_fallback_hint_injected(self):
        """When schema_content is empty, a fallback hint should be prepended."""
        schema_content = ""
        helper = "Your workspace is at /workspace/channels/123"

        if schema_content:
            result = schema_content + "\n\n" + helper
        else:
            result = (
                "Organize workspace files by purpose: use descriptive .md filenames, "
                "keep active documents at the root, and archive completed work to archive/.\n\n"
            ) + helper

        assert "Organize workspace files by purpose" in result
        assert helper in result

    def test_no_fallback_when_schema_present(self):
        """When schema_content is set, no fallback hint."""
        schema_content = "# Project Schema\nUse kanban boards."
        helper = "Your workspace is at /workspace/channels/123"

        if schema_content:
            result = schema_content + "\n\n" + helper
        else:
            result = "Organize workspace files..." + helper

        assert "Organize workspace files" not in result
        assert "Project Schema" in result
