"""Unit tests for the get_doc tool and its loader."""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from app.agent import docs as docs_mod
from app.tools.local import docs as docs_tool


def _seed_doc(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_load_doc_parses_frontmatter(tmp_path: Path):
    _seed_doc(
        tmp_path,
        "reference/widgets/sdk.md",
        dedent(
            """\
            ---
            title: Widget SDK
            summary: Reference for window.spindrel SDK helpers.
            tags: [widgets, reference]
            ---

            # body here
            inline content.
            """
        ),
    )
    doc = docs_mod.load_doc("reference/widgets/sdk", docs_dir=tmp_path)
    assert doc is not None
    assert doc.id == "reference/widgets/sdk"
    assert doc.title == "Widget SDK"
    assert doc.summary == "Reference for window.spindrel SDK helpers."
    assert doc.tags == ["widgets", "reference"]
    assert "inline content." in doc.body
    assert doc.body.lstrip().startswith("# body here")


def test_load_doc_handles_missing_frontmatter(tmp_path: Path):
    _seed_doc(tmp_path, "reference/raw.md", "# raw doc, no frontmatter")
    doc = docs_mod.load_doc("reference/raw", docs_dir=tmp_path)
    assert doc is not None
    assert doc.title is None
    assert doc.summary is None
    assert doc.tags == []
    assert doc.body == "# raw doc, no frontmatter"


def test_load_doc_returns_none_for_missing(tmp_path: Path):
    assert docs_mod.load_doc("does/not/exist", docs_dir=tmp_path) is None


def test_load_doc_rejects_path_traversal(tmp_path: Path):
    """`..` in the ID must not escape the docs root."""
    secret = tmp_path.parent / "secret.md"
    secret.write_text("---\ntitle: secret\n---\nshhh", encoding="utf-8")
    try:
        # Walk above docs/ via traversal; must be rejected.
        assert docs_mod.load_doc("../secret", docs_dir=tmp_path) is None
        assert docs_mod.load_doc("reference/../../secret", docs_dir=tmp_path) is None
    finally:
        secret.unlink(missing_ok=True)


def test_load_doc_rejects_absolute_id(tmp_path: Path):
    _seed_doc(tmp_path, "reference/x.md", "body")
    assert docs_mod.load_doc("/etc/passwd", docs_dir=tmp_path) is None
    assert docs_mod.load_doc("/reference/x", docs_dir=tmp_path) is None


def test_load_doc_accepts_id_with_md_suffix(tmp_path: Path):
    _seed_doc(tmp_path, "reference/x.md", "body")
    doc = docs_mod.load_doc("reference/x.md", docs_dir=tmp_path)
    assert doc is not None
    assert doc.id == "reference/x"


@pytest.mark.asyncio
async def test_get_doc_tool_returns_json_envelope(tmp_path: Path, monkeypatch):
    _seed_doc(
        tmp_path,
        "reference/widgets/sdk.md",
        "---\ntitle: SDK\nsummary: ref\ntags: [widgets]\n---\n# body\n",
    )
    monkeypatch.setattr(docs_mod, "DOCS_DIR", tmp_path)

    out = await docs_tool.get_doc("reference/widgets/sdk")
    payload = json.loads(out)
    assert payload["id"] == "reference/widgets/sdk"
    assert payload["title"] == "SDK"
    assert payload["summary"] == "ref"
    assert payload["tags"] == ["widgets"]
    assert "# body" in payload["body"]


@pytest.mark.asyncio
async def test_get_doc_tool_returns_error_for_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(docs_mod, "DOCS_DIR", tmp_path)
    out = await docs_tool.get_doc("nope/missing")
    payload = json.loads(out)
    assert payload["id"] == "nope/missing"
    assert "not found" in payload["error"].lower()


@pytest.mark.asyncio
async def test_get_doc_tool_rejects_traversal(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(docs_mod, "DOCS_DIR", tmp_path)
    out = await docs_tool.get_doc("../etc/passwd")
    payload = json.loads(out)
    assert "error" in payload
