"""Admin API — AI-assisted prompt generation."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Prompt generation guide (shipped file, cached by mtime)
# ---------------------------------------------------------------------------

_GUIDE_PATH = Path(__file__).resolve().parents[3] / "prompts" / "prompt_generation_guide.md"
_guide_cache: tuple[float, str] = (0.0, "")


def _load_prompt_guide() -> str:
    """Read the prompt generation guide, cached by mtime."""
    global _guide_cache
    try:
        mtime = os.path.getmtime(_GUIDE_PATH)
        if mtime != _guide_cache[0]:
            _guide_cache = (mtime, _GUIDE_PATH.read_text())
        return _guide_cache[1]
    except OSError:
        logger.warning("Prompt generation guide not found at %s", _GUIDE_PATH)
        return ""


def _extract_field_section(guide: str, field_type: str) -> str:
    """Pull the ### field_type section from the guide."""
    if not guide or not field_type:
        return ""
    pattern = rf"^### {re.escape(field_type)}\s*$"
    match = re.search(pattern, guide, re.MULTILINE)
    if not match:
        return ""
    start = match.start()
    # Find next ### or ## heading or end of string
    next_heading = re.search(r"^#{2,3}\s", guide[match.end():], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(guide)
    return guide[start:end].strip()


# ---------------------------------------------------------------------------
# Context gathering per field type
# ---------------------------------------------------------------------------

# What context to gather for each field type
_CONTEXT_SPEC: dict[str, dict[str, bool]] = {
    "system_prompt":   {"bot_info": True,  "system_excerpt": False, "channel_info": False, "workspace_files": False},
    "channel_prompt":  {"bot_info": True,  "system_excerpt": True,  "channel_info": True,  "workspace_files": True},
    "heartbeat":       {"bot_info": True,  "system_excerpt": True,  "channel_info": True,  "workspace_files": True},
    "memory_flush":    {"bot_info": True,  "system_excerpt": False, "channel_info": True,  "workspace_files": True},
    "task_prompt":     {"bot_info": True,  "system_excerpt": True,  "channel_info": True,  "workspace_files": False},
    "memory_prompt":   {"bot_info": True,  "system_excerpt": False, "channel_info": False, "workspace_files": False},
    "compaction_prompt": {"bot_info": True, "system_excerpt": False, "channel_info": True,  "workspace_files": False},
}


async def _gather_context(field_type: str, bot_id: str | None, channel_id: str | None) -> str:
    """Gather relevant context based on field type, bot, and channel."""
    spec = _CONTEXT_SPEC.get(field_type, {})
    if not spec:
        return ""

    parts: list[str] = []
    bot = None
    channel = None

    # Load bot config (in-memory, no DB hit)
    if bot_id and any(spec.get(k) for k in ("bot_info", "system_excerpt")):
        try:
            from app.agent.bots import get_bot
            bot = get_bot(bot_id)
        except Exception:
            pass

    # Load channel (single DB query)
    if channel_id and any(spec.get(k) for k in ("channel_info", "workspace_files")):
        try:
            import uuid
            from app.db.engine import async_session
            from app.db.models import Channel
            async with async_session() as db:
                channel = await db.get(Channel, uuid.UUID(channel_id))
        except Exception:
            pass

    # If we have a channel but no bot, try to get bot from channel
    if channel and not bot and channel.bot_id:
        try:
            from app.agent.bots import get_bot
            bot = get_bot(channel.bot_id)
        except Exception:
            pass

    # Bot info
    if spec.get("bot_info") and bot:
        info = [f"Bot: {bot.name} (model: {bot.model})"]
        if bot.skill_ids:
            info.append(f"Skills: {', '.join(bot.skill_ids[:10])}")
        if bot.local_tools:
            info.append(f"Tools: {', '.join(bot.local_tools[:10])}")
        if bot.memory_scheme:
            info.append(f"Memory scheme: {bot.memory_scheme}")
        parts.append("\n".join(info))

    # System prompt excerpt
    if spec.get("system_excerpt") and bot and bot.system_prompt:
        excerpt = bot.system_prompt[:800]
        if len(bot.system_prompt) > 800:
            excerpt += "..."
        parts.append(f"Bot system prompt (excerpt):\n{excerpt}")

    # Channel info
    if spec.get("channel_info") and channel:
        info = []
        if channel.name:
            info.append(f"Channel: {channel.name}")
        if channel.history_mode:
            info.append(f"History mode: {channel.history_mode}")
        if channel.channel_prompt:
            info.append(f"Channel prompt (excerpt):\n{channel.channel_prompt[:500]}")
        if info:
            parts.append("\n".join(info))

    # Workspace file names
    if spec.get("workspace_files") and channel and channel.channel_workspace_enabled and bot:
        try:
            from app.services.channel_workspace import list_workspace_files
            files = list_workspace_files(str(channel.id), bot)
            if files:
                names = [f["name"] for f in files[:10]]
                parts.append(f"Workspace files: {', '.join(names)}")
        except Exception:
            pass

    return "\n\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class GeneratePromptIn(BaseModel):
    field_type: str = ""          # "system_prompt"|"channel_prompt"|"heartbeat"|etc.
    bot_id: str | None = None     # gather bot context
    channel_id: str | None = None # gather channel context
    context: str = ""             # DEPRECATED — still accepted for backward compat
    user_input: str = ""          # description/instruction, partial prompt, or empty
    mode: str = "generate"        # "generate" = full prompt rewrite, "inline" = replace selected text
    surrounding_context: str = "" # rest of the document (for inline mode)
    guidance: str = ""            # user guidance about what to generate


class GeneratePromptOut(BaseModel):
    prompt: str


# ---------------------------------------------------------------------------
# Inline mode prompt (unchanged)
# ---------------------------------------------------------------------------

_INLINE_PROMPT = """\
You are assisting a user who is editing a prompt template. They have selected a portion of their text and want you to generate a replacement.

The selected text may be:
- A question or instruction — generate the answer or fulfillment
- Text to transform or improve — rewrite it appropriately

{surrounding_section}
Produce ONLY the replacement text. No explanations, no markdown fences, no preamble."""


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/generate-prompt", response_model=GeneratePromptOut)
async def generate_prompt(body: GeneratePromptIn):
    from app.services.providers import get_llm_client

    if body.mode == "inline":
        surrounding_section = ""
        if body.surrounding_context.strip():
            surrounding_section = (
                "SURROUNDING CONTEXT (the rest of the template around the selection):\n"
                f"```\n{body.surrounding_context}\n```\n"
            )
        system_msg = _INLINE_PROMPT.format(surrounding_section=surrounding_section)
        user_msg = body.user_input
    else:
        # Build smart meta-prompt from guide + context
        guide = _load_prompt_guide()

        # Core principles
        core_section = ""
        if guide:
            # Extract everything between "## Core Principles" and the next ## heading
            core_match = re.search(r"^## Core Principles\s*$(.*?)(?=^## |\Z)", guide, re.MULTILINE | re.DOTALL)
            if core_match:
                core_section = core_match.group(1).strip()

        # Field-specific section from guide
        field_section = _extract_field_section(guide, body.field_type) if body.field_type else ""

        # Gather system context (bot config, channel info, workspace files)
        system_context = await _gather_context(body.field_type, body.bot_id, body.channel_id)

        # Build the meta-prompt
        parts = ["You are an expert prompt engineer for an AI agent platform."]

        if core_section:
            parts.append(f"PROMPT WRITING PRINCIPLES:\n{core_section}")

        if field_section:
            parts.append(f"FIELD-SPECIFIC GUIDANCE:\n{field_section}")

        if system_context:
            parts.append(f"SYSTEM CONTEXT (the bot/channel this prompt is for):\n{system_context}")

        # Fall back to old-style context if no field_type provided
        if not body.field_type and body.context:
            parts.append(f"PURPOSE: {body.context}")

        if body.guidance.strip():
            parts.append(f"USER GUIDANCE: {body.guidance.strip()}")

        if body.user_input.strip():
            parts.append(
                f"The user's current prompt text or description:\n\"\"\"\n{body.user_input}\n\"\"\"\n"
                "Rewrite or generate a prompt based on this input."
            )
        else:
            parts.append("Write a high-quality prompt from scratch.")

        parts.append("Output ONLY the prompt text — no explanations, no markdown fences, no preamble.")

        system_msg = "\n\n".join(parts)
        user_msg = "Generate the prompt now."

    model = settings.PROMPT_GENERATION_MODEL or settings.COMPACTION_MODEL
    client = get_llm_client(None)

    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=settings.PROMPT_GENERATION_TEMPERATURE,
        max_tokens=2000,
    )
    text = (resp.choices[0].message.content or "").strip()

    return GeneratePromptOut(prompt=text)
