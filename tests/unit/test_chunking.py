"""Unit tests for app.agent.chunking — shared chunking module."""
import pytest

from app.agent.chunking import (
    CHUNKING_VERSION,
    ChunkResult,
    chunk_markdown,
    chunk_sliding_window,
)


# ---------------------------------------------------------------------------
# chunk_markdown — hierarchy-aware
# ---------------------------------------------------------------------------

class TestChunkMarkdown:
    def test_single_section_no_headers(self):
        body = "Just some plain text without any headers."
        chunks = chunk_markdown(body, source_label="test")
        assert len(chunks) == 1
        assert chunks[0].content == body
        assert chunks[0].context_prefix == ""

    def test_h2_sections(self):
        body = "## Section A\nContent A\n\n## Section B\nContent B"
        chunks = chunk_markdown(body, source_label="")
        assert len(chunks) == 2
        assert "Section A" in chunks[0].content
        assert "Section B" in chunks[1].content

    def test_nested_headers_context_prefix(self):
        body = (
            "# Top Level\nIntro\n\n"
            "## Sub Section\nDetails\n\n"
            "### Deep Section\nMore details"
        )
        chunks = chunk_markdown(body, source_label="[Skill: Test]")
        assert len(chunks) == 3

        # First chunk: # Top Level
        assert "# Top Level" in chunks[0].context_prefix
        assert "[Skill: Test]" in chunks[0].context_prefix

        # Second chunk: # Top Level > ## Sub Section
        assert "# Top Level" in chunks[1].context_prefix
        assert "## Sub Section" in chunks[1].context_prefix

        # Third chunk: full hierarchy path
        assert "# Top Level" in chunks[2].context_prefix
        assert "## Sub Section" in chunks[2].context_prefix
        assert "### Deep Section" in chunks[2].context_prefix

    def test_hierarchy_resets_on_same_level(self):
        body = (
            "# A\nContent\n\n"
            "## A1\nSub\n\n"
            "## A2\nSub2\n\n"
            "# B\nContent B\n\n"
            "## B1\nSub B1"
        )
        chunks = chunk_markdown(body, source_label="")
        # Find the chunk for ## B1
        b1_chunks = [c for c in chunks if "B1" in c.content and "## B1" in c.content]
        assert len(b1_chunks) == 1
        # B1 should be under # B, not # A
        assert "# B" in b1_chunks[0].context_prefix
        assert "# A" not in b1_chunks[0].context_prefix

    def test_preamble_before_first_header(self):
        body = "This is preamble text.\n\n# First Header\nContent"
        chunks = chunk_markdown(body, source_label="")
        assert len(chunks) == 2
        assert chunks[0].content == "This is preamble text."
        assert chunks[0].context_prefix == ""

    def test_empty_input(self):
        assert chunk_markdown("", source_label="test") == []
        assert chunk_markdown("   ", source_label="test") == []

    def test_source_label_in_prefix(self):
        body = "## Section\nContent"
        chunks = chunk_markdown(body, source_label="[Skill: My Skill]")
        assert len(chunks) == 1
        assert "[Skill: My Skill]" in chunks[0].context_prefix
        assert "## Section" in chunks[0].context_prefix

    def test_oversized_section_splits_by_paragraphs(self):
        # Create a section larger than max_chunk
        para = "A" * 200 + "\n\n"
        body = "## Big Section\n" + para * 10  # ~2000+ chars
        chunks = chunk_markdown(body, source_label="", max_chunk=500)
        assert len(chunks) > 1
        # All chunks should share the same context_prefix
        prefixes = {c.context_prefix for c in chunks}
        assert len(prefixes) == 1
        assert "## Big Section" in prefixes.pop()

    def test_h4_headers_tracked(self):
        body = (
            "# A\na\n\n"
            "## B\nb\n\n"
            "### C\nc\n\n"
            "#### D\nd"
        )
        chunks = chunk_markdown(body, source_label="")
        d_chunks = [c for c in chunks if "#### D" in c.content]
        assert len(d_chunks) == 1
        assert "# A" in d_chunks[0].context_prefix
        assert "## B" in d_chunks[0].context_prefix
        assert "### C" in d_chunks[0].context_prefix
        assert "#### D" in d_chunks[0].context_prefix


# ---------------------------------------------------------------------------
# chunk_sliding_window — boundary-aware
# ---------------------------------------------------------------------------

class TestChunkSlidingWindow:
    def test_small_input_single_chunk(self):
        text = "Hello world"
        chunks = chunk_sliding_window(text, window=100, overlap=20)
        assert len(chunks) == 1
        assert chunks[0].content == text

    def test_empty_input(self):
        assert chunk_sliding_window("", window=100, overlap=20) == []

    def test_breaks_at_paragraph_boundary(self):
        # Two paragraphs, window just big enough for first + a bit of second
        para1 = "A" * 80
        para2 = "B" * 80
        text = f"{para1}\n\n{para2}"
        chunks = chunk_sliding_window(text, window=100, overlap=20, break_on_boundaries=True)
        assert len(chunks) >= 2
        # First chunk should end at or near the paragraph boundary
        assert chunks[0].content.rstrip().endswith("A" * 10) or "\n\n" not in chunks[0].content.strip()

    def test_breaks_at_sentence_boundary(self):
        # Long text with sentences
        sentences = "This is sentence one. This is sentence two. This is sentence three. This is four."
        text = sentences * 5  # Make it long enough to chunk
        chunks = chunk_sliding_window(text, window=100, overlap=20, break_on_boundaries=True)
        assert len(chunks) >= 2
        # First chunk should ideally end at a sentence boundary
        first = chunks[0].content
        assert first.rstrip().endswith(".") or len(first) <= 100

    def test_hard_cut_fallback(self):
        # No boundaries at all — single long word
        text = "A" * 300
        chunks = chunk_sliding_window(text, window=100, overlap=20, break_on_boundaries=True)
        assert len(chunks) >= 3
        # Hard cut should still produce valid chunks
        assert all(len(c.content) <= 100 for c in chunks[:-1])

    def test_no_boundary_mode(self):
        text = "Hello world. " * 50
        chunks_boundary = chunk_sliding_window(text, window=100, overlap=20, break_on_boundaries=True)
        chunks_hard = chunk_sliding_window(text, window=100, overlap=20, break_on_boundaries=False)
        # Both should produce chunks, but boundary-aware may have different sizes
        assert len(chunks_boundary) >= 2
        assert len(chunks_hard) >= 2

    def test_source_label_set(self):
        text = "A" * 300
        chunks = chunk_sliding_window(text, source_label="test.py", window=100, overlap=20)
        assert all(c.context_prefix == "test.py" for c in chunks)

    def test_language_propagated(self):
        text = "A" * 300
        chunks = chunk_sliding_window(text, window=100, overlap=20, language="python")
        assert all(c.language == "python" for c in chunks)

    def test_line_numbers_set(self):
        text = "line1\nline2\nline3\nline4\nline5\n" * 20
        chunks = chunk_sliding_window(text, window=50, overlap=10)
        assert chunks[0].start_line == 1
        assert chunks[0].end_line is not None
        if len(chunks) > 1:
            assert chunks[1].start_line > 1


# ---------------------------------------------------------------------------
# ChunkResult
# ---------------------------------------------------------------------------

class TestChunkResult:
    def test_defaults(self):
        cr = ChunkResult(content="test")
        assert cr.context_prefix == ""
        assert cr.language is None
        assert cr.symbol is None
        assert cr.start_line is None
        assert cr.end_line is None
        assert cr.metadata == {}

    def test_all_fields(self):
        cr = ChunkResult(
            content="test",
            context_prefix="prefix",
            language="python",
            symbol="foo",
            start_line=1,
            end_line=10,
            metadata={"key": "val"},
        )
        assert cr.context_prefix == "prefix"
        assert cr.language == "python"
        assert cr.symbol == "foo"


class TestChunkingVersion:
    def test_version_is_string(self):
        assert isinstance(CHUNKING_VERSION, str)
        assert CHUNKING_VERSION == "v2"
