"""Shared test infrastructure: env vars, SQLite compilers, db fixtures.

Every test (unit or integration) gets real SQLite-in-memory via ``db_session``
/ ``engine``. Unit tests that don't touch the DB simply don't request the
fixture — pytest fixtures are lazy.

See ``~/.claude/skills/testing-python/SKILL.md`` section G.
"""
import os
import uuid as _uuid_mod

# Set required env vars before any app imports trigger Settings() instantiation.
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("TOOL_POLICY_ENABLED", "false")

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import (
    JSONB,
    UUID as PG_UUID,
    TIMESTAMP as PG_TIMESTAMP,
    TSVECTOR as PG_TSVECTOR,
)
from pgvector.sqlalchemy import Vector


# ---------------------------------------------------------------------------
# Postgres → SQLite type compilers (module-level, self-register on import)
# ---------------------------------------------------------------------------
@compiles(Vector, "sqlite")
def _compile_vector_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@compiles(PG_TSVECTOR, "sqlite")
def _compile_tsvector_sqlite(type_, compiler, **kw):
    return "TEXT"


@compiles(PG_TIMESTAMP, "sqlite")
def _compile_timestamp_sqlite(type_, compiler, **kw):
    return "TIMESTAMP"


# SQLite has no native UUID — round-trip uuid.UUID through CHAR(36).
_orig_bind = PG_UUID.bind_processor
_orig_result = PG_UUID.result_processor


def _patched_bind_processor(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return value
            if isinstance(value, _uuid_mod.UUID):
                return str(value)
            return value
        return process
    return _orig_bind(self, dialect)


def _patched_result_processor(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is None:
                return value
            if isinstance(value, _uuid_mod.UUID):
                return value
            return _uuid_mod.UUID(str(value))
        return process
    return _orig_result(self, dialect, coltype)


PG_UUID.bind_processor = _patched_bind_processor
PG_UUID.result_processor = _patched_result_processor


# SQLite's dialect substitutes its own ``DATETIME`` class for any
# DateTime/TIMESTAMP column via ``SQLiteDialect.colspecs``. Patching PG_TIMESTAMP
# doesn't help — we have to wrap the SQLite DATETIME's result_processor so
# values read back are always UTC-aware, matching Postgres semantics. Without
# this, tests that round-trip ``TIMESTAMP(timezone=True)`` columns hit
# ``can't compare offset-naive and offset-aware datetimes`` at assert time.
import datetime as _dt_mod
from sqlalchemy.dialects.sqlite.base import DATETIME as _SQLITE_DATETIME

_orig_sqlite_dt_result = _SQLITE_DATETIME.result_processor


def _patched_sqlite_dt_result_processor(self, dialect, coltype):
    base = _orig_sqlite_dt_result(self, dialect, coltype)

    def process(value):
        if base is not None:
            value = base(value)
        if isinstance(value, _dt_mod.datetime) and value.tzinfo is None:
            return value.replace(tzinfo=_dt_mod.timezone.utc)
        return value

    return process


_SQLITE_DATETIME.result_processor = _patched_sqlite_dt_result_processor


# Import app.db.models at module load so every table is registered with Base
# before the engine fixture runs create_all. Without this, tables added by
# modules imported lazily at test time are missing from the SQLite schema.
from app.db.models import Base  # noqa: E402


# ---------------------------------------------------------------------------
# Database fixtures (shared across unit + integration)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def engine():

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    from sqlalchemy import text as sa_text
    from sqlalchemy.schema import DefaultClause

    originals = {}
    _REPLACEMENTS = {
        "now()": "CURRENT_TIMESTAMP",
        "gen_random_uuid()": None,
    }
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            sd = col.server_default
            if sd is None:
                continue
            sd_text = str(sd.arg) if hasattr(sd, "arg") else str(sd)
            new_default = None
            needs_replace = False
            for pg_expr, sqlite_expr in _REPLACEMENTS.items():
                if pg_expr in sd_text:
                    needs_replace = True
                    new_default = sqlite_expr
                    break
            if not needs_replace and "::jsonb" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::jsonb", "")
            if not needs_replace and "::json" in sd_text:
                needs_replace = True
                new_default = sd_text.replace("::json", "")
            if needs_replace:
                originals[(table.name, col.name)] = sd
                if new_default:
                    col.server_default = DefaultClause(sa_text(new_default))
                else:
                    col.server_default = None

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    for (tname, cname), default in originals.items():
        table = Base.metadata.tables[tname]
        table.c[cname].server_default = default

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
