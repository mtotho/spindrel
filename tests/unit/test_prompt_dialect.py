"""Unit tests for app.services.prompt_dialect.render."""
from app.services.prompt_dialect import DEFAULT_STYLE, PROMPT_STYLES, render


class TestRender:
    def test_no_markers_passes_through_unchanged(self):
        text = "Plain prompt with no directives."
        assert render(text, "markdown") == text
        assert render(text, "xml") == text
        assert render(text, "structured") == text

    def test_markdown_style_produces_heading(self):
        text = '{% section "Operating Rules" %}\n- Rule one\n- Rule two\n{% endsection %}'
        out = render(text, "markdown")
        assert out.startswith("## Operating Rules\n")
        assert "- Rule one" in out
        assert "- Rule two" in out
        assert "{% section" not in out
        assert "{% endsection" not in out

    def test_xml_style_produces_tag_envelope(self):
        text = '{% section "Operating Rules" %}\n- Rule one\n{% endsection %}'
        out = render(text, "xml")
        assert "<operating_rules>" in out
        assert "</operating_rules>" in out
        assert "- Rule one" in out
        assert "##" not in out
        assert "{% section" not in out

    def test_xml_slug_handles_special_chars(self):
        text = '{% section "Self-Improvement & Skills" %}body{% endsection %}'
        out = render(text, "xml")
        assert "<self_improvement_skills>" in out
        assert "</self_improvement_skills>" in out

    def test_xml_slug_fallback_when_title_empty_of_alnum(self):
        text = '{% section "---" %}body{% endsection %}'
        out = render(text, "xml")
        assert "<section>" in out
        assert "</section>" in out

    def test_unknown_style_falls_back_to_markdown(self):
        text = '{% section "A" %}body{% endsection %}'
        out = render(text, "klingon")
        assert out.startswith("## A\n")

    def test_structured_style_aliases_markdown_in_v1(self):
        text = '{% section "A" %}body{% endsection %}'
        markdown_out = render(text, "markdown")
        structured_out = render(text, "structured")
        # Neither should produce XML envelope; body must appear either way.
        # v1 reserves 'structured' as a slot but no fragment uses it yet, so
        # it falls through to the default branch (markdown).
        assert "<a>" not in structured_out
        assert "body" in structured_out
        assert "body" in markdown_out

    def test_multiple_sections_are_all_resolved(self):
        text = (
            '{% section "First" %}\none\n{% endsection %}\n\n'
            '{% section "Second" %}\ntwo\n{% endsection %}'
        )
        md = render(text, "markdown")
        assert "## First" in md
        assert "## Second" in md
        assert "one" in md and "two" in md

        xml = render(text, "xml")
        assert "<first>" in xml and "</first>" in xml
        assert "<second>" in xml and "</second>" in xml

    def test_body_content_preserved_verbatim(self):
        body = "- **Bold** _italic_ and `code`\n- Line two"
        text = f'{{% section "T" %}}\n{body}\n{{% endsection %}}'
        md = render(text, "markdown")
        assert body in md

    def test_default_style_is_markdown(self):
        assert DEFAULT_STYLE == "markdown"
        assert "markdown" in PROMPT_STYLES
        assert "xml" in PROMPT_STYLES
        assert "structured" in PROMPT_STYLES

    def test_content_with_curly_braces_for_format_survives(self):
        """Render must not mangle `{foo}` placeholders intended for later .format()."""
        text = '{% section "Paths" %}\nWorkspace at {workspace_path}\n{% endsection %}'
        md = render(text, "markdown")
        assert "{workspace_path}" in md
        xml = render(text, "xml")
        assert "{workspace_path}" in xml
