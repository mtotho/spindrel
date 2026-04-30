import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


class _FakeUpload:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        filename: str = "upload.bin",
        content_type: str = "application/octet-stream",
    ):
        self._chunks = list(chunks)
        self.filename = filename
        self.content_type = content_type

    async def read(self, _size: int) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


def test_safe_upload_filename_strips_paths_and_special_chars():
    from app.routers.api_v1_channel_workspace import _safe_upload_filename

    assert _safe_upload_filename("../../etc/passwd") == "passwd"
    assert "<" not in _safe_upload_filename("file<script>.jpg")
    assert _safe_upload_filename("   ") == "upload"


def test_dedupe_upload_path_adds_suffix(tmp_path):
    from app.routers.api_v1_channel_workspace import _dedupe_upload_path

    existing = tmp_path / "report.txt"
    existing.write_text("one")

    filename, path = _dedupe_upload_path(str(tmp_path), "report.txt")

    assert filename == "report-1.txt"
    assert path == os.path.join(str(tmp_path), "report-1.txt")


def test_rewrite_project_attachment_upload_path_maps_legacy_data_upload_prefix():
    from app.routers.api_v1_channel_workspace import _rewrite_project_attachment_upload_path

    assert _rewrite_project_attachment_upload_path("data/uploads/2026-04-30") == ".uploads/2026-04-30"
    assert _rewrite_project_attachment_upload_path(".uploads/2026-04-30") == ".uploads/2026-04-30"
    assert _rewrite_project_attachment_upload_path("docs/assets") is None


@pytest.mark.asyncio
async def test_write_upload_stream_rejects_over_limit_and_removes_partial(tmp_path):
    from fastapi import HTTPException
    from app.routers.api_v1_channel_workspace import _write_upload_stream

    target = tmp_path / "big.bin"
    upload = _FakeUpload([b"1234", b"5678"])

    with pytest.raises(HTTPException) as exc:
        await _write_upload_stream(upload, str(target), max_bytes=5)

    assert exc.value.status_code == 413
    assert not target.exists()


@pytest.mark.asyncio
async def test_write_upload_stream_writes_chunks(tmp_path):
    from app.routers.api_v1_channel_workspace import _write_upload_stream

    target = tmp_path / "ok.bin"
    upload = _FakeUpload([b"abc", b"def"])

    size = await _write_upload_stream(upload, str(target), max_bytes=10)

    assert size == 6
    assert target.read_bytes() == b"abcdef"


@pytest.mark.asyncio
async def test_upload_workspace_file_project_channel_rewrites_attachment_folder(tmp_path):
    from app.routers import api_v1_channel_workspace as mod

    channel_id = uuid.uuid4()
    project_id = uuid.uuid4()
    channel_root = tmp_path / "channel-root"
    project_root = tmp_path / "project-root"
    channel_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)

    fake_channel = SimpleNamespace(id=channel_id, project_id=project_id, bot_id="test-bot", name="Project Channel")
    fake_bot = SimpleNamespace(id="test-bot")
    fake_surface = SimpleNamespace(kind="project", root_host_path=str(project_root))
    upload = _FakeUpload([b"hello"], filename="spec.md", content_type="text/markdown")

    with (
        patch.object(mod, "_require_channel_workspace", AsyncMock(return_value=(fake_channel, fake_bot))),
        patch.object(mod, "_schedule_reindex"),
        patch("app.services.channel_workspace.ensure_channel_workspace", return_value=str(channel_root)),
        patch("app.services.channel_workspace.get_channel_workspace_root", return_value=str(channel_root)),
        patch("app.services.projects.resolve_channel_work_surface", AsyncMock(return_value=fake_surface)),
    ):
        result = await mod.upload_workspace_file(
            channel_id=channel_id,
            file=upload,
            path="data/uploads/2026-04-30",
            db=object(),
            _auth=None,
        )

    assert result["path"].startswith(".uploads/2026-04-30/")
    assert (project_root / result["path"]).is_file()
    assert not (channel_root / result["path"]).exists()


@pytest.mark.asyncio
async def test_upload_workspace_file_non_project_channel_keeps_requested_path(tmp_path):
    from app.routers import api_v1_channel_workspace as mod

    channel_id = uuid.uuid4()
    channel_root = tmp_path / "channel-root"
    channel_root.mkdir(parents=True, exist_ok=True)

    fake_channel = SimpleNamespace(id=channel_id, project_id=None, bot_id="test-bot", name="Regular Channel")
    fake_bot = SimpleNamespace(id="test-bot")
    upload = _FakeUpload([b"hello"], filename="spec.md", content_type="text/markdown")

    with (
        patch.object(mod, "_require_channel_workspace", AsyncMock(return_value=(fake_channel, fake_bot))),
        patch.object(mod, "_schedule_reindex"),
        patch("app.services.channel_workspace.ensure_channel_workspace", return_value=str(channel_root)),
        patch("app.services.channel_workspace.get_channel_workspace_root", return_value=str(channel_root)),
        patch("app.services.projects.resolve_channel_work_surface", AsyncMock(return_value=None)),
    ):
        result = await mod.upload_workspace_file(
            channel_id=channel_id,
            file=upload,
            path="data/uploads/2026-04-30",
            db=object(),
            _auth=None,
        )

    assert result["path"].startswith("data/uploads/2026-04-30/")
    assert (channel_root / result["path"]).is_file()
