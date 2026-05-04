"""Path-prefix retrieval filters for filesystem RAG."""

from sqlalchemy.dialects import postgresql

from app.agent.fs_indexer import (
    _knowledge_document_chunk_metadata,
    _path_prefix_exclude_filters,
    _path_prefix_include_filters,
)
from app.db.models import FilesystemChunk


def _compiled_where(filters: list) -> str:
    compiled = (
        FilesystemChunk.__table__.select()
        .where(*filters)
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    return str(compiled)


def test_include_prefix_filter_matches_descendants_and_exact_path():
    sql = _compiled_where(_path_prefix_include_filters(["bots/bot-1/knowledge-base"]))

    assert "filesystem_chunks.file_path LIKE 'bots/bot-1/knowledge-base/' || '%%'" in sql
    assert "filesystem_chunks.file_path = 'bots/bot-1/knowledge-base'" in sql


def test_include_prefix_filter_combines_multiple_prefixes_with_or():
    sql = _compiled_where(_path_prefix_include_filters(["docs", "knowledge-base/"]))

    assert "docs/" in sql
    assert "knowledge-base/" in sql
    assert " OR " in sql


def test_exclude_prefix_filter_keeps_existing_descendant_and_exact_exclusion():
    sql = _compiled_where(_path_prefix_exclude_filters(["channels/ch-1/knowledge-base"]))

    assert "filesystem_chunks.file_path NOT LIKE 'channels/ch-1/knowledge-base/' || '%%'" in sql
    assert "filesystem_chunks.file_path != 'channels/ch-1/knowledge-base'" in sql


def test_knowledge_document_metadata_for_user_scope_uses_path_and_frontmatter():
    metadata = _knowledge_document_chunk_metadata(
        "users/user-1/knowledge-base/notes/fact.md",
        "---\nentry_id: entry-1\nstatus: pending_review\ntype: note\n---\n\n# Fact",
    )

    assert metadata == {
        "knowledge_scope": "user",
        "kd_status": "pending_review",
        "entry_id": "entry-1",
        "owner_user_id": "user-1",
    }


def test_knowledge_document_metadata_for_non_kd_path_is_empty():
    assert _knowledge_document_chunk_metadata("bots/bot-1/docs/fact.md", "# Fact") == {}


def test_metadata_filters_compile_for_knowledge_document_retrieval():
    filters = [
        FilesystemChunk.metadata_["knowledge_scope"].as_string() == "user",
        FilesystemChunk.metadata_["owner_user_id"].as_string() == "user-1",
        FilesystemChunk.metadata_["kd_status"].as_string() != "pending_review",
    ]
    sql = _compiled_where(filters)

    assert "knowledge_scope" in sql
    assert "owner_user_id" in sql
    assert "kd_status" in sql
