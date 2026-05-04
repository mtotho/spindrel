from __future__ import annotations

import pytest
from sqlalchemy.exc import InterfaceError

from app import dependencies


class _CloseFailsWithClosedConnection:
    invalidated = False

    async def close(self):
        raise InterfaceError(
            "ROLLBACK",
            None,
            RuntimeError("cannot call Transaction.rollback(): the underlying connection is closed"),
        )

    async def invalidate(self):
        self.invalidated = True


class _ReadTransactionSession:
    rolled_back = False

    def in_transaction(self):
        return True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_get_db_invalidates_closed_connection_cleanup_error(monkeypatch):
    session = _CloseFailsWithClosedConnection()

    monkeypatch.setattr(dependencies, "async_session", lambda: session)

    gen = dependencies.get_db()
    yielded = await anext(gen)
    assert yielded is session

    with pytest.raises(StopAsyncIteration):
        await anext(gen)

    assert session.invalidated is True


@pytest.mark.asyncio
async def test_release_db_read_transaction_rolls_back_open_read_transaction():
    session = _ReadTransactionSession()

    await dependencies.release_db_read_transaction(session, context="test read")

    assert session.rolled_back is True
