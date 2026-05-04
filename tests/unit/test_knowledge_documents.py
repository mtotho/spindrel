from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.knowledge_documents import (
    KnowledgeDocumentSurface,
    authorize_knowledge_document,
    create_document,
    default_session_binding,
    delete_document,
    list_documents,
    parse_frontmatter,
    read_document,
    render_frontmatter,
    update_session_binding,
    write_document,
)


def test_surface_validates_scope_combinations(tmp_path: Path):
    surface = KnowledgeDocumentSurface(root=str(tmp_path), kb_rel="knowledge-base", scope="channel", channel_id="ch-1")
    assert surface.documents_root == str(tmp_path / "knowledge-base" / "notes")

    with pytest.raises(ValueError):
        KnowledgeDocumentSurface(root=str(tmp_path), kb_rel="knowledge-base", scope="user")

    with pytest.raises(ValueError):
        KnowledgeDocumentSurface(root=str(tmp_path), kb_rel="knowledge-base", scope="user", user_id="u1", channel_id="ch-1")


def test_frontmatter_round_trips_envelope_and_unknown_keys():
    original = {
        "spindrel_kind": "note",
        "entry_id": "entry-1",
        "status": "pending_review",
        "session_binding": {"mode": "inline", "session_id": "session-1"},
        "extra": {"ingredients": ["flour"], "temperature": 450},
        "provenance": {"source_message_id": "msg-1"},
        "unknown_key": ["a", "b"],
    }

    parsed, body = parse_frontmatter(render_frontmatter(original) + "# Body\n")

    assert parsed == original
    assert body == "# Body\n"


def test_create_write_and_list_document_preserves_unknown_frontmatter(tmp_path: Path):
    surface = KnowledgeDocumentSurface(root=str(tmp_path), kb_rel="knowledge-base", scope="channel", channel_id="ch-1")

    doc = create_document(
        surface,
        title="Captured Fact",
        content="---\ncustom: value\nextra:\n  nested: true\n---\n\n# Captured Fact\n\nBody",
        frontmatter={"status": "pending_review", "confidence": 0.7},
        session_binding=default_session_binding("inline", "session-1"),
    )

    loaded = read_document(surface, doc["slug"])
    meta, _body = parse_frontmatter(loaded["content"])
    assert meta["custom"] == "value"
    assert meta["extra"] == {"nested": True}
    assert meta["status"] == "pending_review"
    assert meta["confidence"] == 0.7
    assert meta["session_binding"] == {"mode": "inline", "session_id": "session-1"}
    assert list_documents(surface, status="pending_review")[0]["entry_id"] == loaded["entry_id"]

    updated = write_document(surface, doc["slug"], loaded["content"].replace("Body", "Updated body"), loaded["content_hash"])
    updated_meta, _ = parse_frontmatter(updated["content"])
    assert updated_meta["custom"] == "value"
    assert "Updated body" in updated["content"]


def test_update_session_binding_modes(tmp_path: Path):
    surface = KnowledgeDocumentSurface(root=str(tmp_path), kb_rel="knowledge-base", scope="channel", channel_id="ch-1")
    doc = create_document(surface, title="Session Modes")

    inline = update_session_binding(surface, doc["slug"], {"mode": "inline", "session_id": "s1"})
    assert inline["session_binding"] == {"mode": "inline", "session_id": "s1"}

    attached = update_session_binding(surface, doc["slug"], {"mode": "attached", "session_id": "s2"})
    assert attached["session_binding"] == {"mode": "attached", "session_id": "s2"}


def test_delete_document_removes_file_and_returns_prior_document(tmp_path: Path):
    surface = KnowledgeDocumentSurface(root=str(tmp_path), kb_rel="knowledge-base", scope="channel", channel_id="ch-1")
    doc = create_document(surface, title="Delete Me")

    deleted = delete_document(surface, doc["slug"])

    assert deleted["title"] == "Delete Me"
    assert not (tmp_path / "knowledge-base" / "notes" / "delete-me.md").exists()


def test_authorize_user_scope_rejects_cross_user():
    surface = KnowledgeDocumentSurface(root="/tmp/root", kb_rel="users/u1/knowledge-base", scope="user", user_id="u1")

    authorize_knowledge_document(SimpleNamespace(id="u1", is_admin=False), surface, "read")
    authorize_knowledge_document(SimpleNamespace(id="admin", is_admin=True), surface, "write")

    with pytest.raises(HTTPException) as exc:
        authorize_knowledge_document(SimpleNamespace(id="u2", is_admin=False), surface, "read")
    assert exc.value.status_code == 403
