"""Tests for fs_indexer _process_file skip logic — hash, model, and version checks."""
import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.fs_indexer import _process_file


@pytest.fixture
def tmp_file(tmp_path):
    """Create a simple text file for indexing."""
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    return f


@pytest.fixture
def file_hash(tmp_file):
    return hashlib.sha256(tmp_file.read_bytes()).hexdigest()


def _mock_settings(**overrides):
    s = MagicMock()
    defaults = dict(
        EMBEDDING_MODEL="test-model",
        EMBEDDING_DIMENSIONS=1536,
        CONTEXTUAL_RETRIEVAL_ENABLED=False,
        CONTEXTUAL_RETRIEVAL_BATCH_SIZE=5,
        CONTEXTUAL_RETRIEVAL_MODEL="",
        CONTEXTUAL_RETRIEVAL_MAX_TOKENS=150,
        CONTEXTUAL_RETRIEVAL_PROVIDER_ID="",
        COMPACTION_MODEL="",
        FS_INDEX_MAX_FILE_BYTES=500_000,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


class TestProcessFileSkipLogic:
    """Verify the 3-way skip check: hash + model + chunking version."""

    async def test_skips_when_hash_model_version_match(self, tmp_file, file_hash, tmp_path):
        """File unchanged → skipped."""
        with patch("app.agent.fs_indexer.settings", _mock_settings()), \
             patch("app.agent.fs_indexer.chunk_file", return_value=[MagicMock(content="chunk")]):
            result = await _process_file(
                tmp_file, tmp_path, None, None,
                "test-model", None,
                {tmp_file.name: file_hash},  # existing_hashes
                {tmp_file.name: "test-model"},  # existing_models
                {tmp_file.name: "v2"},  # existing_versions (matches CHUNKING_VERSION)
                [], asyncio.Semaphore(1), None,
            )
        assert result.status == "skipped"

    async def test_reindexes_when_version_differs(self, tmp_file, file_hash, tmp_path):
        """Chunking version changed (e.g. CR toggled) → re-indexed, not skipped."""
        mock_embed = AsyncMock(return_value=[[0.1] * 1536])
        mock_cr = AsyncMock(return_value=[None])

        with patch("app.agent.fs_indexer.settings", _mock_settings()), \
             patch("app.agent.fs_indexer.chunk_file", return_value=[MagicMock(content="chunk", language=None, symbol=None, start_line=1, end_line=1)]), \
             patch("app.agent.fs_indexer.embed_batch", mock_embed), \
             patch("app.agent.fs_indexer.generate_batch_contexts", mock_cr), \
             patch("app.agent.fs_indexer.async_session") as mock_session:
            # Mock the DB session
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _process_file(
                tmp_file, tmp_path, None, None,
                "test-model", None,
                {tmp_file.name: file_hash},  # hash matches
                {tmp_file.name: "test-model"},  # model matches
                {tmp_file.name: "v1"},  # OLD version → should trigger re-index
                [], asyncio.Semaphore(1), None,
            )
        # Should NOT be skipped — version mismatch forces re-processing
        assert result.status != "skipped"

    async def test_reindexes_when_cr_enabled_changes_version(self, tmp_file, file_hash, tmp_path):
        """Enabling contextual retrieval changes effective version → re-indexed."""
        mock_embed = AsyncMock(return_value=[[0.1] * 1536])
        mock_cr = AsyncMock(return_value=[None])

        cr_settings = _mock_settings(CONTEXTUAL_RETRIEVAL_ENABLED=True)
        with patch("app.agent.fs_indexer.settings", cr_settings), \
             patch("app.agent.contextual_retrieval.settings", cr_settings), \
             patch("app.agent.fs_indexer.chunk_file", return_value=[MagicMock(content="chunk", language=None, symbol=None, start_line=1, end_line=1)]), \
             patch("app.agent.fs_indexer.embed_batch", mock_embed), \
             patch("app.agent.fs_indexer.generate_batch_contexts", mock_cr), \
             patch("app.agent.fs_indexer.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _process_file(
                tmp_file, tmp_path, None, None,
                "test-model", None,
                {tmp_file.name: file_hash},  # hash matches
                {tmp_file.name: "test-model"},  # model matches
                {tmp_file.name: "v2"},  # stored as "v2" but effective is now "v2+cr"
                [], asyncio.Semaphore(1), None,
            )
        assert result.status != "skipped"

    async def test_reindexes_when_no_existing_version(self, tmp_file, file_hash, tmp_path):
        """Legacy rows without version in metadata → re-indexed to stamp version."""
        mock_embed = AsyncMock(return_value=[[0.1] * 1536])
        mock_cr = AsyncMock(return_value=[None])

        with patch("app.agent.fs_indexer.settings", _mock_settings()), \
             patch("app.agent.fs_indexer.chunk_file", return_value=[MagicMock(content="chunk", language=None, symbol=None, start_line=1, end_line=1)]), \
             patch("app.agent.fs_indexer.embed_batch", mock_embed), \
             patch("app.agent.fs_indexer.generate_batch_contexts", mock_cr), \
             patch("app.agent.fs_indexer.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _process_file(
                tmp_file, tmp_path, None, None,
                "test-model", None,
                {tmp_file.name: file_hash},
                {tmp_file.name: "test-model"},
                {},  # no existing version → None → triggers re-index
                [], asyncio.Semaphore(1), None,
            )
        assert result.status != "skipped"
