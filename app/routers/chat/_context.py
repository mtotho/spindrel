"""Unified context preparation for all chat paths.

Every path that runs a bot (chat, chat_stream, _run_member_bot_reply) calls
prepare_bot_context() to get a consistent BotContext.  This eliminates the
three divergent inline pipelines that caused recurring multi-bot identity bugs.
"""
import copy
import logging
import re
from dataclasses import dataclass

from app.agent import bots as _bots_mod
from app.agent.message_formatting import (
    compose_attribution_prefix,
    compose_thread_context_block,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Context mutation helpers (moved here from top-level chat.py)
# ---------------------------------------------------------------------------

# Matches any leading ``[<speaker>]: `` attribution block — covers the plain
# ``[Alice]:`` shape and the mention-token variant ``[Alice (<@U123>)]:``.
# First-group character class excludes ``]`` so a body containing brackets
# later doesn't match.
_ATTRIBUTION_PREFIX_RE = re.compile(r"^\[[^\]]+\]:\s")


def _apply_user_attribution(messages: list[dict]) -> None:
    """Prefix user messages with an attribution header built from ``_metadata``.

    Single source of truth for the ``[Speaker]:`` / ``[Speaker (<@U…>)]:`` line
    the LLM sees on user turns — integrations MUST NOT bake their own prefix
    into content (see ``docs/integrations/message-ingest-contract.md``). The
    prefix shape is composed by
    :func:`app.agent.message_formatting.compose_attribution_prefix` from the
    metadata contract (``sender_display_name`` required, ``mention_token``
    optional for platforms that need a native tag token).

    Idempotent: re-entry on an already-prefixed message leaves it alone.
    Must run while ``_metadata`` is still present (before
    ``strip_metadata_keys``).
    """
    for msg in messages:
        if msg.get("role") != "user":
            continue
        meta = msg.get("_metadata") or {}
        prefix = compose_attribution_prefix(meta)
        if not prefix:
            continue
        content = msg.get("content", "")
        # Skip multimodal messages (list content from image attachments)
        if not isinstance(content, str):
            continue
        if content.startswith(prefix):
            continue
        # Generic idempotency guard: skip if ANY [Name]: or [Name (<@U…>)]:
        # attribution prefix is already present. Covers the display-name
        # drift case (`[Alicia]` replacing `[Alice]`) that the old
        # single-name ``legacy_prefix`` check missed — first attribution
        # wins so we don't emit ``[Alicia]: [Alice]: …`` into the LLM.
        if _ATTRIBUTION_PREFIX_RE.match(content):
            continue
        msg["content"] = f"{prefix} {content}"


def _inject_thread_context_blocks(messages: list[dict]) -> None:
    """Insert a system message containing each user turn's ``thread_context``.

    When an integration supplies a multi-line summary of prior thread messages
    via ``_metadata.thread_context`` (e.g. Slack threaded replies), we expose
    that to the LLM as a system block placed immediately before the user turn
    it belongs to — never concatenated into the user's own text.

    Must run while ``_metadata`` is still present (before
    ``strip_metadata_keys``). Idempotent: re-entry does nothing because the
    injected system messages have no metadata.
    """
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") != "user":
            i += 1
            continue
        meta = msg.get("_metadata") or {}
        block = compose_thread_context_block(meta)
        if not block:
            i += 1
            continue
        messages.insert(i, {"role": "system", "content": block})
        i += 2  # skip the inserted block and the user message itself


def _rewrite_history_for_member_bot(
    messages: list[dict],
    member_bot_id: str,
    primary_bot_name: str | None = None,
    is_primary: bool = False,
) -> None:
    """Rewrite conversation history so a bot has proper identity.

    In a shared session, all assistant messages have role="assistant" but may
    come from different bots.  Without rewriting, the bot sees another bot's
    responses as its own (the LLM treats role=assistant as "I said that").

    This function:
    - For the primary bot: keeps its own assistant messages, rewrites others'
    - For member bots: rewrites ALL assistant messages to user role with
      ``[BotName]: ...`` attribution.  This prevents poisoned history (prior
      identity-confused responses persisted with the member bot's sender_id)
      from teaching the model the wrong voice.  The member bot builds its
      voice entirely from system prompt + persona, not from history.
    - Adds speaker attribution to user messages
    - Drops other bots' tool_call/tool messages (not relevant to the target bot)
    - When ``is_primary=True``, untagged messages are treated as the primary bot's
      own (they predate multi-bot metadata and were authored by the primary bot)
    """
    member_sender_id = f"bot:{member_bot_id}"
    fallback_label = primary_bot_name or "Other bot"
    i = 0
    while i < len(messages):
        msg = messages[i]
        meta = msg.get("_metadata") or {}
        role = msg.get("role")

        # Remove hidden messages (member-mention trigger prompts, etc.)
        # These are system-injected prompts for specific bots, not real user input.
        if meta.get("hidden"):
            messages.pop(i)
            continue

        if role == "assistant":
            sender_id = meta.get("sender_id", "")
            sender_name = meta.get("sender_display_name", "")

            # Primary bot: keep its own messages as assistant role
            if is_primary:
                if sender_id == member_sender_id or not sender_id:
                    i += 1
                    continue
            # Member bot: rewrite ALL assistant messages (including "own")
            # to prevent poisoned history from reinforcing wrong identity.

            # Drop tool-call messages and their results (from any bot)
            if msg.get("tool_calls"):
                tool_call_ids = {
                    tc.get("id") for tc in msg["tool_calls"] if tc.get("id")
                }
                messages.pop(i)
                # Remove following tool result messages
                while i < len(messages) and messages[i].get("role") == "tool":
                    if messages[i].get("tool_call_id") in tool_call_ids:
                        messages.pop(i)
                    else:
                        break
                continue
            # Rewrite text-only assistant message to user with attribution
            content = msg.get("content", "")
            label = sender_name or fallback_label
            msg["role"] = "user"
            msg["content"] = f"[{label}]: {content}"
        elif role == "user":
            sender_name = meta.get("sender_display_name", "")
            if sender_name:
                content = msg.get("content", "")
                # Skip multimodal messages (list content from image attachments)
                if not isinstance(content, str):
                    i += 1
                    continue
                # Don't double-prefix if already prefixed
                if not content.startswith(f"[{sender_name}]:"):
                    msg["content"] = f"[{sender_name}]: {content}"
        i += 1


def _inject_member_config(messages: list[dict], config: dict) -> None:
    """Inject member-level config overrides as system messages."""
    parts: list[str] = []
    if config.get("system_prompt_addon"):
        parts.append(config["system_prompt_addon"])
    style = config.get("response_style")
    if style:
        style_map = {
            "brief": "Keep your responses brief and concise.",
            "normal": "Respond with a normal level of detail.",
            "detailed": "Provide detailed, thorough responses.",
        }
        parts.append(style_map.get(style, f"Response style: {style}."))
    if parts:
        messages.append({
            "role": "system",
            "content": f"[Member bot instructions for this channel]\n" + "\n".join(parts),
        })


# ---------------------------------------------------------------------------
# Identity preamble builder
# ---------------------------------------------------------------------------

def _build_identity_preamble(
    *, bot, primary_bot_id: str, primary_bot_name: str | None,
    is_primary: bool,
    mentioning_bot_id: str | None = None,
    invocation_message: str = "",
) -> str | None:
    """Build the system_preamble for identity reinforcement.

    Returns None for the primary bot (no reinforcement needed).
    """
    if is_primary:
        return None

    primary_label = primary_bot_name or primary_bot_id

    if mentioning_bot_id:
        try:
            mentioning_bot = _bots_mod.get_bot(mentioning_bot_id)
            mentioning_name = mentioning_bot.name
        except Exception:
            mentioning_name = mentioning_bot_id

        if invocation_message:
            return (
                f"IDENTITY: You are {bot.name} (bot_id: {bot.id}). "
                f"You are NOT {primary_label}. "
                f"{mentioning_name} (@{mentioning_bot_id}) invoked you with this context: {invocation_message} "
                f"Read the conversation and respond naturally. Do not @-mention yourself."
            )
        else:
            return (
                f"IDENTITY: You are {bot.name} (bot_id: {bot.id}). "
                f"You are NOT {primary_label}. "
                f"{mentioning_name} (@{mentioning_bot_id}) mentioned you. "
                f"Read the conversation and respond naturally. Do not @-mention yourself."
            )
    else:
        # Routed bot (user @-mentioned in chat/chat_stream)
        return (
            f"IDENTITY: You are {bot.name} (bot_id: {bot.id}). "
            f"You are NOT {primary_label} and NOT {primary_bot_id}. "
            f"The conversation history contains messages from other bots — those are NOT yours. "
            f"The user addressed you directly. Respond only as {bot.name}."
        )


# ---------------------------------------------------------------------------
# Unified context preparation
# ---------------------------------------------------------------------------

@dataclass
class BotContext:
    """Result of prepare_bot_context — everything a caller needs to run a bot."""
    messages: list[dict]            # Ready for run/run_stream
    system_preamble: str | None     # Identity reinforcement (None for primary)
    model_override: str | None      # From member_config
    provider_id_override: str | None # From member_config
    raw_snapshot: list[dict]        # Pre-rewrite copy for member bot chaining
    extracted_user_prompt: str      # User msg pulled from snapshot end (member path)
    is_primary: bool


async def prepare_bot_context(
    *,
    messages: list[dict],
    bot,
    primary_bot_id: str,
    channel_id,
    member_config: dict | None = None,
    user_message: str = "",
    msg_metadata: dict | None = None,
    db=None,
    from_snapshot: bool = False,
    mentioning_bot_id: str | None = None,
    invocation_message: str = "",
) -> BotContext:
    """Prepare messages for a bot run — single pipeline for all three paths.

    Invariant pipeline order (always the same, all paths):
    1. If non-primary: swap system prompt + persona
    2. Save raw snapshot (deep copy, pre-rewrite)
    3. If from_snapshot: extract user prompt from end
    4. _rewrite_history_for_member_bot()
    5. _apply_user_attribution()
    5b. _inject_thread_context_blocks()
    6. strip_metadata_keys()
    7. _inject_member_config()
    8. _build_identity_preamble() → returns preamble or None
    """
    member_config = member_config or {}
    is_primary = bot.id == primary_bot_id

    # --- Step 1: swap system prompt + persona for non-primary bots ---
    primary_bot_name: str | None = None
    if not is_primary:
        try:
            _pb = _bots_mod.get_bot(primary_bot_id)
            primary_bot_name = _pb.name if _pb else primary_bot_id
        except Exception:
            primary_bot_name = primary_bot_id

        from app.services.sessions import _effective_system_prompt, _resolve_workspace_base_prompt_enabled
        if db is not None:
            ws_base = await _resolve_workspace_base_prompt_enabled(db, bot.id, channel_id)
        else:
            # Open a temporary session for workspace resolution
            from app.db.engine import async_session as _async_session
            async with _async_session() as _tmp_db:
                ws_base = await _resolve_workspace_base_prompt_enabled(_tmp_db, bot.id, channel_id)

        _member_model_override = member_config.get("model_override")
        _member_provider_override = member_config.get("model_provider_id_override")
        new_sys = _effective_system_prompt(
            bot,
            workspace_base_prompt_enabled=ws_base,
            model_override=_member_model_override,
            provider_id_override=_member_provider_override,
        )
        messages[:] = [m for m in messages if m.get("role") != "system"]
        messages.insert(0, {"role": "system", "content": new_sys})
        if bot.persona:
            from app.agent.persona import get_persona
            persona = await get_persona(bot.id, workspace_id=bot.shared_workspace_id)
            if persona:
                messages.insert(1, {"role": "system", "content": f"[PERSONA]\n{persona}"})

    # --- Step 2: save raw snapshot (deep copy, pre-rewrite) ---
    raw_snapshot = copy.deepcopy(messages)
    if user_message and not from_snapshot:
        # For route paths: append user message to snapshot for member bot chaining
        raw_snapshot.append({
            "role": "user",
            "content": user_message,
            "_metadata": msg_metadata or {},
        })

    # --- Step 3: if from_snapshot, extract user prompt from end ---
    extracted_user_prompt = ""
    if from_snapshot and messages:
        last = messages[-1]
        last_meta = last.get("_metadata") or {}
        if last.get("role") == "user" and last_meta.get("sender_type") != "bot":
            extracted_user_prompt = last.get("content", "")
            if not isinstance(extracted_user_prompt, str):
                extracted_user_prompt = ""

    # --- Step 4: rewrite history for multi-bot identity ---
    _rewrite_history_for_member_bot(
        messages, bot.id,
        primary_bot_name=primary_bot_name,
        is_primary=is_primary,
    )

    # --- Step 5: apply user attribution (THE BUG FIX) ---
    _apply_user_attribution(messages)

    # --- Step 5b: inject per-turn thread_context blocks as system messages ---
    _inject_thread_context_blocks(messages)

    # --- Step 6: strip metadata ---
    from app.services.sessions import strip_metadata_keys
    messages[:] = strip_metadata_keys(messages)

    # Remove extracted user message from messages to avoid duplication
    # (assemble_context will append it at the end via prompt=).
    # Must happen BEFORE _inject_member_config which may append system messages.
    if extracted_user_prompt and messages and messages[-1].get("role") == "user":
        messages.pop()

    # --- Step 7: inject member config ---
    _inject_member_config(messages, member_config)

    # --- Step 8: build identity preamble ---
    system_preamble = _build_identity_preamble(
        bot=bot,
        primary_bot_id=primary_bot_id,
        primary_bot_name=primary_bot_name,
        is_primary=is_primary,
        mentioning_bot_id=mentioning_bot_id,
        invocation_message=invocation_message,
    )

    model_override = member_config.get("model_override")
    provider_id_override = member_config.get("model_provider_id_override")

    return BotContext(
        messages=messages,
        system_preamble=system_preamble,
        model_override=model_override,
        provider_id_override=provider_id_override,
        raw_snapshot=raw_snapshot,
        extracted_user_prompt=extracted_user_prompt,
        is_primary=is_primary,
    )
