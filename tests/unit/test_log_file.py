"""Durable JSONL log handler — install + survive on disk."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.services import log_file


@pytest.fixture(autouse=True)
def _reset_log_file_state():
    log_file._reset_for_tests()
    yield
    log_file._reset_for_tests()


def test_install_writes_jsonl_records(tmp_path: Path):
    handler = log_file.install_jsonl_log_handler(log_dir=tmp_path)
    assert handler is not None

    logger = logging.getLogger("test.log_file")
    logger.error("boom %s", "ok")
    handler.flush()

    log_path = tmp_path / log_file.DEFAULT_LOG_FILE
    assert log_path.exists()
    raw = log_path.read_text(encoding="utf-8").strip()
    assert raw, "expected at least one record written"
    last = json.loads(raw.splitlines()[-1])
    assert last["level"] == "ERROR"
    assert last["logger"] == "test.log_file"
    assert "boom ok" in last["message"]
    assert "ts" in last


def test_install_captures_exc_info(tmp_path: Path):
    handler = log_file.install_jsonl_log_handler(log_dir=tmp_path)
    assert handler is not None

    logger = logging.getLogger("test.exc")
    try:
        raise ValueError("nope")
    except ValueError:
        logger.exception("caught")
    handler.flush()

    log_path = tmp_path / log_file.DEFAULT_LOG_FILE
    raw = log_path.read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(raw[-1])
    assert "ValueError" in last["exc_info"]
    assert "nope" in last["exc_info"]


def test_install_is_idempotent(tmp_path: Path):
    h1 = log_file.install_jsonl_log_handler(log_dir=tmp_path)
    h2 = log_file.install_jsonl_log_handler(log_dir=tmp_path)
    assert h1 is h2


def test_install_returns_none_when_dir_unwritable(tmp_path: Path, monkeypatch):
    bogus = tmp_path / "definitely-not-here" / "nested"
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    handler = log_file.install_jsonl_log_handler(log_dir=bogus)
    assert handler is None


def test_get_log_path_respects_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SPINDREL_LOG_DIR", str(tmp_path))
    assert log_file.get_log_path() == tmp_path / log_file.DEFAULT_LOG_FILE
