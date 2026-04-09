"""Bot path hooks — in-memory registry, cooldown tracking, path matching, execution."""
from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import BotHook

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory cache: bot_id -> list[BotHook]
# ---------------------------------------------------------------------------
_hooks_by_bot: dict[str, list[BotHook]] = {}

# Cooldown tracking: hook_id -> last_fired (monotonic)
_cooldowns: dict[uuid.UUID, float] = {}

# Re-entrancy guard — prevents hooks from triggering during hook execution
_hook_executing: ContextVar[bool] = ContextVar("_hook_executing", default=False)

# After-write debounce: hook_id -> asyncio.TimerHandle
_pending_after_write: dict[uuid.UUID, asyncio.TimerHandle] = {}
AFTER_WRITE_DEBOUNCE_SECONDS = 2.0

# Valid trigger types (V1: path-based; future: tool-based, turn-based)
VALID_TRIGGERS = {"before_access", "after_write", "after_exec"}

# Triggers where on_failure defaults to "block"
BLOCKING_TRIGGERS = {"before_access"}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

async def load_bot_hooks() -> None:
    """Load all enabled hooks from DB into in-memory cache. Called at startup."""
    _hooks_by_bot.clear()
    async with async_session() as db:
        rows = (await db.execute(
            select(BotHook).where(BotHook.enabled == True)  # noqa: E712
        )).scalars().all()
    for row in rows:
        _hooks_by_bot.setdefault(row.bot_id, []).append(row)
    total = sum(len(v) for v in _hooks_by_bot.values())
    if total:
        logger.info("Loaded %d bot hook(s) for %d bot(s)", total, len(_hooks_by_bot))


# ---------------------------------------------------------------------------
# Path matching
# ---------------------------------------------------------------------------

def _matches_conditions(hook: BotHook, container_path: str) -> bool:
    """Check if a hook's conditions match the given container path.

    For path-based triggers, checks conditions["path"] as a glob.
    Future triggers will add their own condition matching here.
    """
    conditions = hook.conditions or {}
    path_pattern = conditions.get("path")
    if path_pattern:
        return fnmatch.fnmatch(container_path, path_pattern)
    # No path condition — matches everything (for future non-path triggers)
    return not conditions


def _find_matching_hooks(bot_id: str, trigger: str, container_path: str) -> list[BotHook]:
    """Return all enabled hooks for this bot/trigger that match the given path."""
    if _hook_executing.get():
        return []
    hooks = _hooks_by_bot.get(bot_id, [])
    return [
        h for h in hooks
        if h.trigger == trigger and _matches_conditions(h, container_path)
    ]


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------

def _check_cooldown(hook: BotHook) -> bool:
    """Return True if the hook is allowed to fire (cooldown elapsed). Updates tracker."""
    now = time.monotonic()
    last = _cooldowns.get(hook.id)
    if last is not None and (now - last) < hook.cooldown_seconds:
        return False
    _cooldowns[hook.id] = now
    return True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

async def _execute_hook(hook: BotHook) -> tuple[bool, str]:
    """Execute a hook's command via workspace_service. Returns (success, output)."""
    from app.agent.bots import get_bot
    from app.services.workspace import workspace_service

    bot = get_bot(hook.bot_id)
    if not bot or not bot.workspace.enabled:
        return False, "Bot workspace not available"

    token = _hook_executing.set(True)
    try:
        result = await workspace_service.exec(
            hook.bot_id, hook.command, bot.workspace, working_dir="", bot=bot,
        )
        success = result.exit_code == 0
        output = (result.stdout or "") + (result.stderr or "")
        if not success:
            logger.warning(
                "Bot hook %s (%s) failed (exit %d): %s",
                hook.name, hook.id, result.exit_code, output[:500],
            )
        else:
            logger.debug("Bot hook %s (%s) completed successfully", hook.name, hook.id)
        return success, output
    except Exception as e:
        logger.exception("Bot hook %s (%s) execution error", hook.name, hook.id)
        return False, str(e)
    finally:
        _hook_executing.reset(token)


# ---------------------------------------------------------------------------
# Public trigger functions — called from file_ops / exec_command
# ---------------------------------------------------------------------------

async def run_before_access(bot_id: str, container_path: str) -> str | None:
    """Fire before_access hooks. Returns error string if blocked, None to proceed."""
    hooks = _find_matching_hooks(bot_id, "before_access", container_path)
    for hook in hooks:
        if not _check_cooldown(hook):
            continue
        success, output = await _execute_hook(hook)
        if not success and hook.on_failure == "block":
            return f"Hook '{hook.name}' failed: {output[:200]}"
    return None


def schedule_after_write(bot_id: str, container_path: str) -> None:
    """Schedule after_write hooks with debounce. Non-blocking."""
    hooks = _find_matching_hooks(bot_id, "after_write", container_path)
    if not hooks:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for hook in hooks:
        existing = _pending_after_write.pop(hook.id, None)
        if existing:
            existing.cancel()
        _pending_after_write[hook.id] = loop.call_later(
            AFTER_WRITE_DEBOUNCE_SECONDS,
            lambda h=hook: asyncio.ensure_future(_fire_after_write(h)),
        )


async def _fire_after_write(hook: BotHook) -> None:
    """Fire after_write hook after debounce period."""
    _pending_after_write.pop(hook.id, None)
    if not _check_cooldown(hook):
        return
    success, output = await _execute_hook(hook)
    if not success:
        logger.warning(
            "after_write hook '%s' failed (%s): %s",
            hook.name, hook.on_failure, output[:200],
        )


async def run_after_exec(bot_id: str, container_working_dir: str) -> None:
    """Fire after_exec hooks. Fire-and-forget."""
    hooks = _find_matching_hooks(bot_id, "after_exec", container_working_dir)
    for hook in hooks:
        if not _check_cooldown(hook):
            continue
        success, output = await _execute_hook(hook)
        if not success:
            logger.warning(
                "after_exec hook '%s' failed (%s): %s",
                hook.name, hook.on_failure, output[:200],
            )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def create_hook(bot_id: str, data: dict) -> BotHook:
    trigger = data["trigger"]
    on_failure_default = "block" if trigger in BLOCKING_TRIGGERS else "warn"
    row = BotHook(
        bot_id=bot_id,
        name=data["name"],
        trigger=trigger,
        conditions=data.get("conditions", {}),
        command=data["command"],
        cooldown_seconds=data.get("cooldown_seconds", 60),
        on_failure=data.get("on_failure", on_failure_default),
        enabled=data.get("enabled", True),
    )
    async with async_session() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    if row.enabled:
        _hooks_by_bot.setdefault(bot_id, []).append(row)
    return row


async def update_hook(hook_id: uuid.UUID, bot_id: str, data: dict) -> BotHook | None:
    async with async_session() as db:
        row = await db.get(BotHook, hook_id)
        if not row or row.bot_id != bot_id:
            return None
        for field in ("name", "trigger", "conditions", "command",
                      "cooldown_seconds", "on_failure", "enabled"):
            if field in data:
                setattr(row, field, data[field])
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(row)
    # Reload cache (simplest way to keep it consistent)
    await load_bot_hooks()
    return row


async def delete_hook(hook_id: uuid.UUID, bot_id: str) -> bool:
    async with async_session() as db:
        row = await db.get(BotHook, hook_id)
        if not row or row.bot_id != bot_id:
            return False
        await db.delete(row)
        await db.commit()
    # Remove from cache
    bot_hooks = _hooks_by_bot.get(bot_id, [])
    _hooks_by_bot[bot_id] = [h for h in bot_hooks if h.id != hook_id]
    _cooldowns.pop(hook_id, None)
    _pending_after_write.pop(hook_id, None)
    return True


async def list_hooks(bot_id: str) -> list[BotHook]:
    """List all hooks for a bot (from DB, includes disabled)."""
    async with async_session() as db:
        rows = (await db.execute(
            select(BotHook).where(BotHook.bot_id == bot_id).order_by(BotHook.created_at)
        )).scalars().all()
    return list(rows)
