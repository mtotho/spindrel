"""Shared fixtures for unit tests.

These fixtures replace the inline ``MagicMock()`` session + stacked ``patch()``
pattern that recurred in the five headline offenders audited on 2026-04-17.
The public fixture pattern lives here instead of depending on private audit
notes or local-only agent skills.

Fixtures here are additive to ``tests/conftest.py`` (which provides the real
SQLite ``engine`` + ``db_session`` fixtures); unit tests that don't touch the
DB simply don't request them.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent import context as agent_context_mod


# ---------------------------------------------------------------------------
# async_session patching
# ---------------------------------------------------------------------------
#
# Four of the five headline offenders drive services that open their own
# ``async with async_session() as db:`` blocks. Two import the alias at module
# level (``tasks.py``, ``workflow_executor.py``); two use function-local
# imports (``bot_skills.py``, ``memory_hygiene.py``). Patch both surfaces so
# either style resolves to the test engine.
#
# ``_MODULE_LEVEL_ALIASES`` covers re-exported names; ``app.db.engine`` is the
# source of truth for function-local imports.

_MODULE_LEVEL_ALIASES = (
    "app.tools.local.tasks.async_session",
    "app.tools.local.pipelines.async_session",
    "app.tools.local.get_trace.async_session",
    "app.tools.local.skills.async_session",
    "app.services.workflow_executor.async_session",
    "app.services.compaction.async_session",
    "app.services.bot_hooks.async_session",
    "app.services.file_sync.async_session",
    "app.services.attachments.async_session",
    "app.services.workflows.async_session",
    "app.services.task_run_anchor.async_session",
    "app.services.skill_enrollment.async_session",
    "app.services.channel_skill_enrollment.async_session",
    "app.services.tool_enrollment.async_session",
    "app.agent.tool_dispatch.async_session",
    "app.services.turn_supervisors.async_session",
    "app.agent.tasks.async_session",
    "app.agent.recording.async_session",
    "app.services.sessions.async_session",
    "app.services.chat_late_input.async_session",
    "app.db.engine.async_session",
)


_PATCH_TARGETS = (
    "app.tools.local.tasks.async_session",
    "app.tools.local.pipelines.async_session",
    "app.tools.local.sub_sessions.async_session",
    "app.tools.local.get_trace.async_session",
    "app.tools.local.skills.async_session",
    "app.services.workflow_executor.async_session",
    "app.services.compaction.async_session",
    "app.services.bot_hooks.async_session",
    "app.services.file_sync.async_session",
    "app.services.attachments.async_session",
    "app.services.workflows.async_session",
    "app.services.task_run_anchor.async_session",
    "app.services.skill_enrollment.async_session",
    "app.services.channel_skill_enrollment.async_session",
    "app.services.tool_enrollment.async_session",
    "app.agent.tool_dispatch.async_session",
    "app.services.turn_supervisors.async_session",
    "app.agent.tasks.async_session",
    "app.agent.recording.async_session",
    "app.services.sessions.async_session",
    "app.services.chat_late_input.async_session",
    "app.tools.local.todos.async_session",
)


@pytest_asyncio.fixture
async def patched_async_sessions(engine):
    """Point every ``async_session()`` call at the test engine.

    Service modules that open their own session inside a function (via
    ``async with async_session() as db:``) will transparently use the
    SQLite-in-memory test DB for the duration of the test.

    Uses ``ExitStack`` so new patch targets can be appended to
    ``_PATCH_TARGETS`` without bumping Python's 20-block nested-``with``
    limit.
    """
    from contextlib import ExitStack

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with ExitStack() as stack:
        stack.enter_context(patch.multiple("app.db.engine", async_session=factory))
        for target in _PATCH_TARGETS:
            stack.enter_context(patch(target, factory))
        yield factory


# ---------------------------------------------------------------------------
# ContextVar harness
# ---------------------------------------------------------------------------
#
# Tests that call bot-tool entry points (``schedule_prompt``, ``manage_bot_skill``,
# etc.) need the per-turn ContextVars set. Setting them inline with no teardown
# leaks state across tests (B.28 hazard). This fixture hands the test a setter
# that records every token and resets them in teardown.

_AGENT_CONTEXT_VARS = {
    "bot_id": agent_context_mod.current_bot_id,
    "session_id": agent_context_mod.current_session_id,
    "channel_id": agent_context_mod.current_channel_id,
    "client_id": agent_context_mod.current_client_id,
    "correlation_id": agent_context_mod.current_correlation_id,
    "dispatch_type": agent_context_mod.current_dispatch_type,
    "dispatch_config": agent_context_mod.current_dispatch_config,
    "turn_id": agent_context_mod.current_turn_id,
    "turn_responded_bots": agent_context_mod.current_turn_responded_bots,
    "invoked_member_bots": agent_context_mod.current_invoked_member_bots,
}


_UNSET = object()


@pytest.fixture
def agent_context():
    """Set app.agent.context ContextVars for the duration of the test.

    Usage::

        async def test_something(agent_context):
            agent_context(bot_id="test-bot", channel_id=uuid.uuid4())
            # ... exercise a tool that reads current_bot_id.get() ...

    Snapshots each var's prior value on first ``_set`` and restores it on
    teardown. Uses ``.get()`` / ``.set()`` rather than tokens because
    pytest-asyncio runs teardown in a different ``contextvars.Context`` than
    the async test body — tokens from the inner context raise ``ValueError``
    on ``.reset()`` from the outer one.
    """
    snapshots: dict = {}

    def _set(**kwargs):
        for key, value in kwargs.items():
            if key not in _AGENT_CONTEXT_VARS:
                raise KeyError(f"Unknown agent context var: {key!r}")
            var = _AGENT_CONTEXT_VARS[key]
            if key not in snapshots:
                snapshots[key] = var.get(_UNSET)
            var.set(value)

    yield _set

    for key, prev in snapshots.items():
        var = _AGENT_CONTEXT_VARS[key]
        # ContextVars in app.agent.context all default to None or an empty
        # collection; restoring to None when the var was unset is close enough
        # for test isolation (the next test's fixture will overwrite anyway).
        var.set(None if prev is _UNSET else prev)


# ---------------------------------------------------------------------------
# Bot registry harness
# ---------------------------------------------------------------------------
#
# ``app.agent.bots.get_bot()`` is a ``_registry`` dict lookup, not a DB query.
# Tests that exercise multi-bot routing (``_multibot.py``) need both (a) a
# ``Bot`` ORM row so SQL joins succeed and (b) a ``BotConfig`` entry in the
# in-memory registry so ``get_bot()`` resolves. This fixture manages (b); the
# test still inserts (a) via ``db_session.merge(build_bot(...))`` where needed.


@pytest.fixture
def bot_registry():
    """Replace ``app.agent.bots._registry`` with an empty dict for the test.

    Usage::

        def test_something(bot_registry):
            helper = bot_registry.register("helper", name="Helper Bot")
            # get_bot("helper") now returns ``helper``

    Snapshot/restore ensures tests don't leak registry state. The fixture
    yields a small object with a ``register(bot_id, **overrides)`` method
    that constructs a minimal ``BotConfig`` and inserts it.
    """
    from app.agent import bots as _bots_mod

    original = dict(_bots_mod._registry)
    _bots_mod._registry.clear()

    class _Harness:
        def register(self, bot_id: str, **overrides) -> "_bots_mod.BotConfig":
            defaults = dict(
                id=bot_id,
                name=overrides.pop("name", bot_id.replace("-", " ").title()),
                model=overrides.pop("model", "test/model"),
                system_prompt=overrides.pop("system_prompt", "You are a test bot."),
            )
            cfg = _bots_mod.BotConfig(**defaults, **overrides)
            _bots_mod._registry[bot_id] = cfg
            return cfg

    yield _Harness()

    _bots_mod._registry.clear()
    _bots_mod._registry.update(original)


# ---------------------------------------------------------------------------
# Bot-skills fixtures (used by test_manage_bot_skill.py)
# ---------------------------------------------------------------------------
#
# ``manage_bot_skill`` has three external/Postgres-only touchpoints that a
# SQLite-in-memory test engine cannot exercise directly:
#
#   1. ``app.agent.skills.re_embed_skill`` — embedding provider call.
#   2. ``app.tools.local.bot_skills._check_skill_dedup`` — pgvector query via
#      ``halfvec_cosine_distance``.
#   3. Three module-level caches that ``_invalidate_cache`` touches, which
#      leak state across tests if not cleared.
#
# These fixtures centralize the patches so every create/update/merge test
# doesn't reinvent them inline.


@pytest.fixture
def embed_skill_patch():
    """Patch the embedding external call. Returns the AsyncMock for per-test tweaks.

    Patches ``app.agent.skills.re_embed_skill`` (the underlying external) rather
    than ``_embed_skill_safe`` (our wrapper) so the wrapper's try/except +
    True/False return is real code under test.
    """
    with patch("app.agent.skills.re_embed_skill", new_callable=AsyncMock) as m:
        m.return_value = None  # re_embed_skill returns None on success
        yield m


@pytest.fixture
def dedup_patch():
    """Patch ``_check_skill_dedup`` (pgvector — Postgres-only).

    Default ``return_value = None`` means no duplicate detected. Tests that
    exercise the duplicate-rejected path set ``m.return_value`` to the JSON
    warning string that the real function would produce.
    """
    with patch(
        "app.tools.local.bot_skills._check_skill_dedup",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = None
        yield m


@pytest.fixture
def bot_skill_cache_reset():
    """Clear the three module-level caches that ``_invalidate_cache`` touches.

    Opt-in (not autouse) — request it on test_manage_bot_skill.py via a
    file-level ``pytestmark = pytest.mark.usefixtures("bot_skill_cache_reset")``.
    Teardown-only: the caches start empty in a fresh process; the hazard is
    residue left by earlier mutations leaking into later tests.
    """
    yield
    # Best-effort — each cache module may not be importable in all test contexts.
    try:
        from app.agent import context_assembly
        if hasattr(context_assembly, "_bot_skill_cache"):
            context_assembly._bot_skill_cache.clear()
    except Exception:  # pragma: no cover
        pass
    try:
        from app.agent import rag
        if hasattr(rag, "invalidate_skill_index_cache"):
            rag.invalidate_skill_index_cache()
    except Exception:  # pragma: no cover
        pass
    try:
        from app.agent import repeated_lookup_detection
        if hasattr(repeated_lookup_detection, "_cache"):
            repeated_lookup_detection._cache.clear()
    except Exception:  # pragma: no cover
        pass
