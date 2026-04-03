import asyncio
from functools import partial

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings

_pool_kwargs = {}
if "sqlite" not in settings.DATABASE_URL:
    _pool_kwargs = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
    }

engine = create_async_engine(settings.DATABASE_URL, echo=False, **_pool_kwargs)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def run_migrations():
    cfg = Config("alembic.ini")
    await asyncio.to_thread(partial(command.upgrade, cfg, "head"))
