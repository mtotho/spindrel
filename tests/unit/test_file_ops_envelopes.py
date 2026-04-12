"""Envelope-shape tests for the file_ops migration.

Each `_op_*` operation (and the `file()` dispatcher's read wrapper) emits a
`{"_envelope": {...}}` payload alongside its existing JSON shape. The new
mimetypes are:

  text/plain                                  → read (default extension)
  text/markdown                               → read (.md/.mdx), delete/mkdir/move status
  application/json                            → read (.json)
  application/vnd.spindrel.diff+text          → write/edit/append
  application/vnd.spindrel.file-listing+json  → list/glob/grep

Legacy fields (`ok`, `bytes`, `replacements`, `entries`, `paths`, `matches`)
remain on the JSON return so existing tests and the LLM-side parsing path
keep working byte-identically.
"""
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.local.file_ops import (
    _op_read,
    _op_write,
    _op_append,
    _op_edit,
    _op_list,
    _op_delete,
    _op_mkdir,
    _op_move,
    _op_grep,
    _op_glob,
    file as file_tool,
)


def _mock_bot(ws_root: str, bot_id: str = "test_bot"):
    from types import SimpleNamespace
    return SimpleNamespace(
        id=bot_id,
        workspace=ws_root,
        shared_workspace_id=None,
        shared_workspace_role=None,
        cross_workspace_access=False,
    )


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "hello.txt").write_text("Hello world\n")
    (tmp_path / "data.json").write_text('{"a": 1, "b": 2}\n')
    (tmp_path / "notes.md").write_text("# Heading\nA paragraph.\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "inside.py").write_text("def hello():\n    return 'world'\n")
    return tmp_path


@pytest.fixture
def mock_ctx(ws):
    bot = _mock_bot(str(ws))
    with patch("app.tools.local.file_ops.current_bot_id") as mock_bid:
        mock_bid.get.return_value = "test_bot"
        with patch("app.tools.local.file_ops._get_bot_and_workspace_root") as mock_get:
            mock_get.return_value = (bot, "test_bot", str(ws))
            yield ws, bot


# ---------------------------------------------------------------------------
# read — wrapper applied at the file() dispatcher level
# ---------------------------------------------------------------------------


class TestReadEnvelope:
    @pytest.mark.asyncio
    async def test_read_text_file(self, mock_ctx):
        result = await file_tool(operation="read", path="hello.txt")
        parsed = json.loads(result)
        assert "_envelope" in parsed
        env = parsed["_envelope"]
        assert env["content_type"] == "text/plain"
        assert "Hello world" in env["body"]
        assert env["display"] == "inline"
        # The bot still gets the line-numbered text via "llm"
        assert "Hello world" in parsed["llm"]
        assert "1\t" in parsed["llm"]

    @pytest.mark.asyncio
    async def test_read_markdown_picks_markdown_mimetype(self, mock_ctx):
        result = await file_tool(operation="read", path="notes.md")
        parsed = json.loads(result)
        assert parsed["_envelope"]["content_type"] == "text/markdown"
        assert "Heading" in parsed["_envelope"]["body"]

    @pytest.mark.asyncio
    async def test_read_json_picks_json_mimetype(self, mock_ctx):
        result = await file_tool(operation="read", path="data.json")
        parsed = json.loads(result)
        assert parsed["_envelope"]["content_type"] == "application/json"
        # body is the raw JSON file content, not pretty-printed — the renderer parses it
        body_parsed = json.loads(parsed["_envelope"]["body"])
        assert body_parsed == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_read_nonexistent_keeps_error_shape(self, mock_ctx):
        result = await file_tool(operation="read", path="nope.txt")
        parsed = json.loads(result)
        assert "error" in parsed
        # No envelope wrap on errors
        assert "_envelope" not in parsed


# ---------------------------------------------------------------------------
# write / edit / append → unified diff
# ---------------------------------------------------------------------------


class TestWriteEnvelope:
    def test_write_new_file_emits_diff(self, ws):
        path = str(ws / "new.txt")
        result = json.loads(_op_write(path, "line1\nline2\n"))
        # Legacy fields preserved
        assert result["ok"] is True
        assert result["bytes"] > 0
        # Envelope present with diff content_type
        env = result["_envelope"]
        assert env["content_type"] == "application/vnd.spindrel.diff+text"
        assert "+line1" in env["body"]
        assert "+line2" in env["body"]
        assert "Created" in env["plain_body"] or "+2 lines" in env["plain_body"]

    def test_write_overwrite_diffs_against_old(self, ws):
        path = str(ws / "hello.txt")  # exists with "Hello world\n"
        result = json.loads(_op_write(path, "Goodbye world\n"))
        env = result["_envelope"]
        assert "−" not in env["body"]  # diff uses ASCII -, not Unicode minus
        assert "-Hello world" in env["body"]
        assert "+Goodbye world" in env["body"]


class TestAppendEnvelope:
    def test_append_emits_diff_of_added_lines(self, ws):
        path = str(ws / "hello.txt")
        result = json.loads(_op_append(path, "extra line\n"))
        assert result["ok"] is True
        env = result["_envelope"]
        assert env["content_type"] == "application/vnd.spindrel.diff+text"
        assert "+extra line" in env["body"]


class TestEditEnvelope:
    def test_edit_emits_diff_with_replacement_count(self, ws):
        path = str(ws / "hello.txt")
        result = json.loads(_op_edit(path, find="Hello", replace="Goodbye", replace_all=False))
        assert result["ok"] is True
        assert result["replacements"] == 1
        env = result["_envelope"]
        assert env["content_type"] == "application/vnd.spindrel.diff+text"
        assert "-Hello world" in env["body"]
        assert "+Goodbye world" in env["body"]
        assert "1 replacement" in env["plain_body"]


# ---------------------------------------------------------------------------
# delete / mkdir / move → text/markdown status
# ---------------------------------------------------------------------------


class TestStatusEnvelopes:
    def test_delete_emits_markdown_status(self, ws):
        path = str(ws / "hello.txt")
        result = json.loads(_op_delete(path))
        assert result["ok"] is True
        env = result["_envelope"]
        assert env["content_type"] == "text/markdown"
        assert "Deleted" in env["body"]
        assert "hello.txt" in env["body"]

    def test_mkdir_emits_markdown_status(self, ws):
        path = str(ws / "newdir")
        result = json.loads(_op_mkdir(path))
        assert result["ok"] is True
        env = result["_envelope"]
        assert env["content_type"] == "text/markdown"
        assert "Created directory" in env["body"]


class TestMoveEnvelope:
    @pytest.mark.asyncio
    async def test_move_emits_markdown_status(self, ws):
        bot = _mock_bot(str(ws))
        src = str(ws / "hello.txt")
        result = json.loads(await _op_move(src, "renamed.txt", str(ws), bot))
        assert result["ok"] is True
        env = result["_envelope"]
        assert env["content_type"] == "text/markdown"
        assert "Moved" in env["body"]
        assert "renamed.txt" in env["body"]


# ---------------------------------------------------------------------------
# list / glob / grep → file-listing JSON
# ---------------------------------------------------------------------------


class TestListEnvelope:
    def test_list_emits_file_listing(self, ws):
        result = json.loads(_op_list(str(ws), str(ws)))
        assert "entries" in result  # legacy field
        env = result["_envelope"]
        assert env["content_type"] == "application/vnd.spindrel.file-listing+json"
        body_parsed = json.loads(env["body"])
        assert "entries" in body_parsed
        names = {e["name"] for e in body_parsed["entries"]}
        assert "hello.txt" in names


class TestGlobEnvelope:
    def test_glob_emits_file_listing_with_kind(self, ws):
        result = json.loads(_op_glob(str(ws), "**/*.py", str(ws), None))
        env = result["_envelope"]
        assert env["content_type"] == "application/vnd.spindrel.file-listing+json"
        body_parsed = json.loads(env["body"])
        assert body_parsed["kind"] == "glob"
        assert any(p.endswith("inside.py") for p in body_parsed["paths"])


class TestGrepEnvelope:
    def test_grep_emits_file_listing_with_matches(self, ws):
        result = json.loads(_op_grep(str(ws), "Hello", None, str(ws), None))
        env = result["_envelope"]
        assert env["content_type"] == "application/vnd.spindrel.file-listing+json"
        body_parsed = json.loads(env["body"])
        assert body_parsed["kind"] == "grep"
        assert body_parsed["count"] >= 1
        assert any(m["file"] == "hello.txt" for m in body_parsed["matches"])
        # plain_body has the human summary
        assert "match" in env["plain_body"]


# ---------------------------------------------------------------------------
# Plain-body fallbacks — every op must set plain_body for the LLM-headless
# integration delivery path (used by Slack downgrade if we ever ship it).
# ---------------------------------------------------------------------------


class TestPlainBodyFallbacks:
    @pytest.mark.parametrize("op_call,expected_substr", [
        (lambda ws: _op_list(str(ws), str(ws)), "Listed"),
        (lambda ws: _op_glob(str(ws), "*.txt", str(ws), None), "file"),
        (lambda ws: _op_grep(str(ws), "Hello", None, str(ws), None), "match"),
        (lambda ws: _op_mkdir(str(ws / "x")), "Created"),
    ])
    def test_plain_body_set(self, ws, op_call, expected_substr):
        result = json.loads(op_call(ws))
        env = result["_envelope"]
        assert env["plain_body"]
        assert expected_substr.lower() in env["plain_body"].lower()
