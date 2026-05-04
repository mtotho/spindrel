from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _ApiKeyRow:
    is_active = True
    expires_at = None
    scopes = ["chat"]

    def __init__(self, *, last_used_at):
        self.last_used_at = last_used_at


@pytest.mark.asyncio
async def test_validate_api_key_commits_when_last_used_at_is_fresh(monkeypatch):
    from app.services import api_keys

    now = datetime.now(timezone.utc)
    row = _ApiKeyRow(last_used_at=now - timedelta(seconds=30))
    db = AsyncMock()
    db.execute.return_value = _Result(row)
    monkeypatch.setattr(api_keys, "hash_key", lambda raw_key: "hash")

    validated = await api_keys.validate_api_key(db, "ask_test")

    assert validated is row
    db.commit.assert_awaited_once()
    assert row.last_used_at < now


@pytest.mark.asyncio
async def test_validate_api_key_updates_stale_last_used_at(monkeypatch):
    from app.services import api_keys

    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    row = _ApiKeyRow(last_used_at=stale)
    db = AsyncMock()
    db.execute.return_value = _Result(row)
    monkeypatch.setattr(api_keys, "hash_key", lambda raw_key: "hash")

    validated = await api_keys.validate_api_key(db, "ask_test")

    assert validated is row
    db.commit.assert_awaited_once()
    assert row.last_used_at > stale
