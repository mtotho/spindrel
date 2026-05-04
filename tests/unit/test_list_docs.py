"""Unit tests for list_docs."""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from app.agent import docs as docs_mod
from app.tools.local import docs as docs_tool


def _seed(root: Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_list_docs_walks_tree(tmp_path: Path):
    _seed(tmp_path, "guides/index.md", "---\ntitle: Guides\n---\nbody")
    _seed(
        tmp_path,
        "reference/widgets/sdk.md",
        "---\ntitle: SDK\nsummary: short\ntags: [widgets, reference]\n---\nbody",
    )
    _seed(tmp_path, "reference/pipelines/authoring.md", "---\ntitle: Pipelines\n---\nbody")
    _seed(tmp_path, "tracks/foo.md", "no frontmatter just text")

    docs = docs_mod.list_docs(docs_dir=tmp_path)
    ids = [d.id for d in docs]
    assert "guides/index" in ids
    assert "reference/widgets/sdk" in ids
    assert "reference/pipelines/authoring" in ids
    assert "tracks/foo" in ids

    sdk = next(d for d in docs if d.id == "reference/widgets/sdk")
    assert sdk.title == "SDK"
    assert sdk.summary == "short"
    assert sdk.tags == ["widgets", "reference"]


def test_list_docs_area_filter(tmp_path: Path):
    _seed(tmp_path, "guides/index.md", "---\ntitle: Guides\n---\n")
    _seed(tmp_path, "reference/widgets/sdk.md", "---\ntitle: SDK\n---\n")
    _seed(tmp_path, "reference/pipelines/authoring.md", "---\ntitle: P\n---\n")

    refs = docs_mod.list_docs(area="reference", docs_dir=tmp_path)
    ids = [d.id for d in refs]
    assert all(i.startswith("reference/") for i in ids)
    assert "reference/widgets/sdk" in ids
    assert "reference/pipelines/authoring" in ids
    assert "guides/index" not in ids


def test_list_docs_area_unknown_returns_empty(tmp_path: Path):
    _seed(tmp_path, "guides/x.md", "body")
    assert docs_mod.list_docs(area="does-not-exist", docs_dir=tmp_path) == []


def test_list_docs_rejects_traversal_area(tmp_path: Path):
    _seed(tmp_path, "guides/x.md", "body")
    # Traversal in the area arg must not escape the docs root.
    assert docs_mod.list_docs(area="../", docs_dir=tmp_path) == []
    assert docs_mod.list_docs(area="/etc", docs_dir=tmp_path) == []


def test_list_docs_returns_empty_when_dir_missing(tmp_path: Path):
    missing = tmp_path / "no-docs-here"
    assert docs_mod.list_docs(docs_dir=missing) == []


@pytest.mark.asyncio
async def test_list_docs_tool_envelope(tmp_path: Path, monkeypatch):
    _seed(tmp_path, "reference/x.md", "---\ntitle: X\nsummary: s\n---\nbody")
    monkeypatch.setattr(docs_mod, "DOCS_DIR", tmp_path)
    out = await docs_tool.list_docs(area="reference")
    payload = json.loads(out)
    assert payload["count"] == 1
    assert payload["docs"][0]["id"] == "reference/x"
    assert payload["docs"][0]["title"] == "X"
    assert payload["docs"][0]["summary"] == "s"
