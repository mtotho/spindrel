"""Bot-to-bot delegation service — run child agents immediately or as deferred tasks."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from app.config import settings
from app.db.engine import async_session
from app.db.models import Task

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)


class DelegationError(Exception):
    pass


class DelegationDepthError(DelegationError):
    pass


class DelegationPermissionError(DelegationError):
    pass


class DelegationService:

    async def run_immediate(
        self,
        parent_session_id: uuid.UUID,
        parent_bot: "BotConfig",
        delegate_bot_id: str,
        prompt: str,
        dispatch_type: str | None,
        dispatch_config: dict | None,
        depth: int,
        root_session_id: uuid.UUID,
        client_id: str | None = None,
        channel_id: uuid.UUID | None = None,
        ephemeral_delegate: bool = False,
        reply_in_thread: bool = False,
    ) -> str:
        """Run a child agent immediately and return its final response."""
        from app.agent.bots import get_bot
        from app.agent.loop import run_stream
        from app.agent.context import (
            restore_agent_context,
            set_agent_context,
            snapshot_agent_context,
        )
        from app.services.sessions import _effective_system_prompt

        # Global flag OR bot has explicit delegate_bots config enables delegation
        if not parent_bot.delegate_bots:
            raise DelegationError(
                "Delegation is disabled. Configure delegate_bots for this bot."
            )

        if depth >= settings.DELEGATION_MAX_DEPTH:
            raise DelegationDepthError(
                f"Delegation depth limit reached ({depth} >= {settings.DELEGATION_MAX_DEPTH}). "
                "Cannot delegate further."
            )

        # Permission check: allowlist or ephemeral @-tag override
        if not ephemeral_delegate and delegate_bot_id not in (parent_bot.delegate_bots or []):
            raise DelegationPermissionError(
                f"Bot {parent_bot.id!r} is not allowed to delegate to {delegate_bot_id!r}. "
                f"Allowed: {parent_bot.delegate_bots or []}"
            )

        delegate_bot = get_bot(delegate_bot_id)
        child_depth = depth + 1

        logger.info(
            "Delegating to bot %r (depth=%d, parent_session=%s)",
            delegate_bot_id,
            child_depth,
            parent_session_id,
        )

        # Build in-memory messages for the delegate (not persisted — the parent's
        # tool call/result already captures the delegation in its own session).
        from app.agent.persona import get_persona
        child_messages: list[dict] = [{"role": "system", "content": _effective_system_prompt(delegate_bot)}]
        if delegate_bot.persona:
            persona_layer = await get_persona(delegate_bot.id)
            if persona_layer:
                child_messages.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})

        correlation_id = uuid.uuid4()
        final_response = ""
        child_client_actions: list[dict] = []

        parent_ctx = snapshot_agent_context()
        try:
            # Child run_stream overwrites ContextVars; restore parent after so the outer
            # agent loop, trace tools, and fire-and-forget record_* tasks see correct ids.
            set_agent_context(
                session_id=parent_session_id,
                client_id=client_id,
                bot_id=delegate_bot_id,
                correlation_id=correlation_id,
                channel_id=channel_id,
                dispatch_type=dispatch_type,
                dispatch_config=dispatch_config,
                session_depth=child_depth,
                root_session_id=root_session_id,
            )

            async for event in run_stream(
                child_messages,
                delegate_bot,
                prompt,
                session_id=parent_session_id,
                client_id=client_id,
                correlation_id=correlation_id,
                channel_id=channel_id,
                dispatch_type=dispatch_type,
                dispatch_config=dispatch_config,
            ):
                if event.get("type") == "response":
                    final_response = event.get("text", "")
                    child_client_actions = event.get("client_actions", [])
        finally:
            await asyncio.sleep(0)
            restore_agent_context(parent_ctx)

        # Post child response via dispatcher (attributed to child bot).
        # In a streaming context (outermost run_stream set the ContextVar), queue the post
        # so it can be emitted as a delegation_post event BEFORE the parent's response —
        # this ensures the child's message appears above the parent's in the timeline.
        # In a non-streaming context (task worker), post immediately.
        if dispatch_type and dispatch_config and final_response:
            from app.agent.context import current_pending_delegation_posts
            pending = current_pending_delegation_posts.get()
            if pending is not None:
                pending.append({
                    "text": final_response,
                    "bot_id": delegate_bot_id,
                    "reply_in_thread": reply_in_thread,
                    "client_actions": child_client_actions,
                })
                from app.services.sessions import store_dispatch_echo
                await store_dispatch_echo(
                    parent_session_id, client_id, delegate_bot_id, final_response
                )
            else:
                posted = await self.post_child_response(
                    dispatch_type, dispatch_config, final_response,
                    delegate_bot_id, reply_in_thread=reply_in_thread,
                    client_actions=child_client_actions,
                )
                if posted:
                    from app.services.sessions import store_dispatch_echo
                    await store_dispatch_echo(
                        parent_session_id, client_id, delegate_bot_id, final_response
                    )

        return final_response

    async def run_deferred(
        self,
        parent_bot: "BotConfig",
        delegate_bot_id: str,
        prompt: str,
        dispatch_type: str | None,
        dispatch_config: dict | None,
        scheduled_at: Optional[datetime],
        client_id: str | None = None,
        parent_session_id: Optional[uuid.UUID] = None,
        channel_id: uuid.UUID | None = None,
        reply_in_thread: bool = False,
        notify_parent: bool = True,
    ) -> str:
        """Create a Task for deferred execution. Returns task_id string."""
        delivery_config = dict(dispatch_config or {})
        delivery_config["reply_in_thread"] = reply_in_thread
        callback_cfg: dict = {}
        if notify_parent and parent_session_id is not None:
            callback_cfg["notify_parent"] = True
            callback_cfg["parent_bot_id"] = parent_bot.id
            callback_cfg["parent_session_id"] = str(parent_session_id)
            if client_id:
                callback_cfg["parent_client_id"] = client_id
        task = Task(
            bot_id=delegate_bot_id,
            client_id=client_id,
            session_id=parent_session_id,
            channel_id=channel_id,
            prompt=prompt,
            scheduled_at=scheduled_at,
            status="pending",
            task_type="delegation",
            dispatch_type=dispatch_type or "none",
            dispatch_config=delivery_config,
            callback_config=callback_cfg or None,
            created_at=datetime.now(timezone.utc),
        )
        async with async_session() as db:
            db.add(task)
            await db.commit()
            await db.refresh(task)

        logger.info(
            "Created deferred delegation task %s for bot %r (parent=%s)",
            task.id,
            delegate_bot_id,
            parent_session_id,
        )
        return str(task.id)

    async def post_child_response(
        self,
        dispatch_type: str,
        dispatch_config: dict,
        text: str,
        bot_id: str,
        reply_in_thread: bool = False,
        client_actions: list[dict] | None = None,
    ) -> bool:
        """Dispatch a child bot's response to the appropriate target.

        Called by the non-streaming run() wrapper when delegation_post events are emitted,
        or as a fallback when the streaming delegation_post queue is unavailable
        (e.g. _with_keepalive Task ContextVar boundary).
        """
        from app.agent import dispatchers
        posted = await dispatchers.get(dispatch_type).post_message(
            dispatch_config, text, bot_id=bot_id, reply_in_thread=reply_in_thread,
            client_actions=client_actions,
        )
        return posted


delegation_service = DelegationService()
