import asyncio
from functools import partial

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings

_pool_kwargs: dict = {}
_connect_args: dict = {}
if "sqlite" not in settings.DATABASE_URL:
    _pool_kwargs = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    }
    # Hard safety net at the Postgres level. Any leaked transaction (a
    # session that opened a transaction and forgot to commit/rollback —
    # historically caused by long-lived request handlers like SSE that
    # held a `Depends(get_db)` session for the whole stream lifetime)
    # gets terminated by Postgres itself after these timeouts, returning
    # the connection to the pool instead of pinning it forever. Without
    # this, a single bug in a session-holding code path can exhaust the
    # entire pool and DDoS the app.
    #
    # Values are in milliseconds. 60s statement timeout protects against
    # runaway queries; 30s idle-in-txn timeout protects the pool from
    # buggy code paths.
    _connect_args = {
        "server_settings": {
            "statement_timeout": "60000",
            "idle_in_transaction_session_timeout": "30000",
        }
    }

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=_connect_args,
    **_pool_kwargs,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def run_migrations():
    cfg = Config("alembic.ini")
    await asyncio.to_thread(partial(command.upgrade, cfg, "head"))
