def test_workspace_upload_context_lists_paths_without_user_prefix():
    from app.routers.chat._context import _compose_workspace_upload_context

    block = _compose_workspace_upload_context({
        "workspace_uploads": [{
            "filename": "large-notes.txt",
            "mime_type": "text/plain",
            "size_bytes": 1200,
            "path": "data/uploads/2026-04-28/large-notes.txt",
        }],
    })

    assert block is not None
    assert "uploaded file(s) to this channel workspace" in block
    assert "data/uploads/2026-04-28/large-notes.txt" in block
    assert "large-notes.txt" in block


def test_workspace_upload_context_ignores_empty_or_malformed_metadata():
    from app.routers.chat._context import _compose_workspace_upload_context

    assert _compose_workspace_upload_context({}) is None
    assert _compose_workspace_upload_context({"workspace_uploads": "nope"}) is None
    assert _compose_workspace_upload_context({"workspace_uploads": [{"filename": "missing-path"}]}) is None
