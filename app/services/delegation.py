"""Bot-to-bot delegation service — run child agents immediately or as deferred tasks."""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import httpx

from app.config import settings
from app.db.engine import async_session
from app.db.models import Session, Task

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=60.0)


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
        from app.services.sessions import load_or_create, persist_turn

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

        child_session_id = uuid.uuid4()
        child_depth = depth + 1
        child_root_id = root_session_id

        # Create child session row
        async with async_session() as db:
            child_session = Session(
                id=child_session_id,
                client_id=client_id or "delegation",
                bot_id=delegate_bot_id,
                parent_session_id=parent_session_id,
                root_session_id=child_root_id,
                depth=child_depth,
            )
            db.add(child_session)
            await db.commit()

        logger.info(
            "Delegating to bot %r (session %s, depth=%d, parent=%s)",
            delegate_bot_id,
            child_session_id,
            child_depth,
            parent_session_id,
        )

        # Build initial messages for child session
        from app.services.sessions import _effective_system_prompt
        from app.agent.persona import get_persona
        child_messages: list[dict] = [{"role": "system", "content": _effective_system_prompt(delegate_bot)}]
        if delegate_bot.persona:
            persona_layer = await get_persona(delegate_bot.id)
            if persona_layer:
                child_messages.append({"role": "system", "content": f"[PERSONA]\n{persona_layer}"})

        correlation_id = uuid.uuid4()
        final_response = ""

        parent_ctx = snapshot_agent_context()
        try:
            # Child run_stream overwrites ContextVars; restore parent after so the outer
            # agent loop, trace tools, and fire-and-forget record_* tasks see correct ids.
            set_agent_context(
                session_id=child_session_id,
                client_id=client_id,
                bot_id=delegate_bot_id,
                correlation_id=correlation_id,
                dispatch_type=dispatch_type,
                dispatch_config=dispatch_config,
                session_depth=child_depth,
                root_session_id=child_root_id,
            )

            turn_start = len(child_messages)

            async for event in run_stream(
                child_messages,
                delegate_bot,
                prompt,
                session_id=child_session_id,
                client_id=client_id,
                correlation_id=correlation_id,
                dispatch_type=dispatch_type,
                dispatch_config=dispatch_config,
            ):
                if event.get("type") == "response":
                    final_response = event.get("text", "")

            # Persist child turn
            async with async_session() as db:
                await persist_turn(
                    db,
                    child_session_id,
                    delegate_bot,
                    child_messages,
                    turn_start,
                    correlation_id=correlation_id,
                )
        finally:
            await asyncio.sleep(0)
            restore_agent_context(parent_ctx)

        # Post to Slack (attributed to child bot) if dispatch_type is slack.
        # In a streaming context (outermost run_stream set the ContextVar), queue the post
        # so it can be emitted as a delegation_post event BEFORE the parent's response —
        # this ensures the child's message appears above the parent's in Slack's timeline.
        # In a non-streaming context (task worker), post immediately.
        if dispatch_type == "slack" and dispatch_config and final_response:
            from app.agent.context import current_pending_delegation_posts
            pending = current_pending_delegation_posts.get()
            if pending is not None:
                pending.append({
                    "text": final_response,
                    "bot_id": delegate_bot_id,
                    "reply_in_thread": reply_in_thread,
                })
                from app.services.sessions import store_slack_echo_as_passive
                await store_slack_echo_as_passive(
                    parent_session_id, client_id, delegate_bot_id, final_response
                )
            else:
                posted = await self._post_to_slack(
                    final_response, delegate_bot, dispatch_config, reply_in_thread=reply_in_thread
                )
                if posted:
                    from app.services.sessions import store_slack_echo_as_passive
                    await store_slack_echo_as_passive(
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
        reply_in_thread: bool = False,
        notify_parent: bool = True,
    ) -> str:
        """Create a Task for deferred execution. Returns task_id string."""
        merged_config = dict(dispatch_config or {})
        merged_config["reply_in_thread"] = reply_in_thread
        if notify_parent and parent_session_id is not None:
            merged_config["_notify_parent"] = True
            merged_config["_parent_bot_id"] = parent_bot.id
            merged_config["_parent_session_id"] = str(parent_session_id)
            if client_id:
                merged_config["_parent_client_id"] = client_id
        task = Task(
            bot_id=delegate_bot_id,
            client_id=client_id,
            session_id=parent_session_id,
            prompt=prompt,
            scheduled_at=scheduled_at,
            status="pending",
            dispatch_type=dispatch_type or "none",
            dispatch_config=merged_config,
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
    ) -> bool:
        """Dispatch a child bot's response to the appropriate target.

        Called by the non-streaming run() wrapper when delegation_post events are emitted.
        Routing is driven by dispatch_type so the agent loop stays integration-agnostic.
        """
        if dispatch_type == "slack" and dispatch_config:
            from app.agent.bots import get_bot as _get_bot
            try:
                bot = _get_bot(bot_id)
            except Exception:
                logger.warning("post_child_response: unknown bot %r", bot_id)
                return False
            return await self._post_to_slack(text, bot, dispatch_config, reply_in_thread=reply_in_thread)
        # Future dispatch types (webhook, internal, …) can be added here.
        return False

    async def _post_to_slack(
        self,
        text: str,
        bot: "BotConfig",
        dispatch_config: dict,
        reply_in_thread: bool = False,
    ) -> bool:
        """Post child bot's response to Slack, attributed to the child bot. Returns whether Slack OK."""
        channel_id = dispatch_config.get("channel_id")
        thread_ts = dispatch_config.get("thread_ts")
        token = dispatch_config.get("token")
        if not channel_id or not token:
            logger.warning("Slack delegation post skipped: missing channel_id or token")
            return False

        payload: dict = {"channel": channel_id, "text": text}
        if reply_in_thread and thread_ts:
            payload["thread_ts"] = thread_ts

        username = bot.display_name or bot.name
        if username:
            payload["username"] = username
        slack_cfg = bot.integration_config.get("slack", {})
        if slack_cfg.get("icon_emoji"):
            payload["icon_emoji"] = slack_cfg["icon_emoji"]
        elif bot.avatar_url:
            payload["icon_url"] = bot.avatar_url

        try:
            r = await _http.post(
                "https://slack.com/api/chat.postMessage",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            data = r.json()
            if not data.get("ok"):
                logger.warning("Slack delegation post failed: %s", data.get("error"))
                return False
            return True
        except Exception as exc:
            logger.warning("Failed to post delegation result to Slack: %s", exc)
            return False


delegation_service = DelegationService()
