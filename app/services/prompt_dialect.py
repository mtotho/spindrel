"""Prompt dialect rendering.

Single canonical framework prompts use ``{% section "Title" %} ... {% endsection %}``
markers. The ``render`` function rewrites those sections according to the
``prompt_style`` capability flag on ``ProviderModel``:

- ``markdown`` → ``## Title\\n\\n...`` (default; works for OpenAI / Gemini /
  local / anything openai-compatible)
- ``xml`` → ``<title>\\n...\\n</title>`` (Anthropic native API)
- ``structured`` → alias of ``markdown`` for v1 (reserved slot; no fragments
  use it yet)

Content between markers is preserved verbatim — only the structural envelope
changes. Unknown styles and unmarked prompts pass through unmodified.

This is intentionally not Jinja. One directive, a hand-written resolver, and
a pure ``str -> str`` function make the transform trivial to unit-test and
reason about.
"""
from __future__ import annotations

import re
from typing import Final

PROMPT_STYLES: Final[tuple[str, ...]] = ("markdown", "xml", "structured")
DEFAULT_STYLE: Final[str] = "markdown"

_SECTION_RE = re.compile(
    r'\{\%\s*section\s+"(?P<title>[^"]+)"\s*\%\}(?P<body>.*?)\{\%\s*endsection\s*\%\}',
    re.DOTALL,
)


def _xml_tag(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug or "section"


def _render_markdown(title: str, body: str) -> str:
    return f"## {title}\n{body.rstrip()}"


def _render_xml(title: str, body: str) -> str:
    tag = _xml_tag(title)
    return f"<{tag}>\n{body.strip()}\n</{tag}>"


def render(canonical: str, style: str) -> str:
    """Resolve section markers according to ``style``.

    Unknown styles fall through to markdown. Prompts with no markers return
    as-is. Body content is preserved exactly; only the title envelope flips.
    """
    if style not in PROMPT_STYLES:
        style = DEFAULT_STYLE

    def _sub(match: re.Match[str]) -> str:
        title = match.group("title").strip()
        body = match.group("body")
        body = body.lstrip("\n")
        if style == "xml":
            return _render_xml(title, body)
        return _render_markdown(title, body)

    return _SECTION_RE.sub(_sub, canonical)
