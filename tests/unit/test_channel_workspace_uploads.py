import os

import pytest


class _FakeUpload:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)

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
