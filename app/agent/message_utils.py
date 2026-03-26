"""Pure message transformation helpers for the agent loop."""
import json
import re
from typing import Any

from app.agent.bots import BotConfig
from app.tools.client_tools import get_client_tool_schemas
from app.tools.mcp import fetch_mcp_tools
from app.tools.registry import get_local_tool_schemas

_TRANSCRIPT_RE = re.compile(r"\[transcript\](.*?)\[/transcript\]", re.DOTALL)

_AUDIO_TRANSCRIPT_INSTRUCTION = (
    "The user's message includes audio input. Before your response, include an exact "
    "transcription of what the user said in [transcript]...[/transcript] tags. "
    "Place the transcript on its own line before your actual reply. Example:\n"
    "[transcript]Hello, how are you?[/transcript]\n"
    "I'm doing well! How can I help?"
)


def _build_user_message_content(text: str, attachments: list[dict] | None) -> str | list[dict]:
    """OpenAI-style multimodal user content for LiteLLM. `attachments` items: type image, content (base64), mime_type."""
    if not attachments:
        return text
    parts: list[dict] = [{"type": "text", "text": text or "(no text)"}]
    for att in attachments:
        if att.get("type") != "image":
            continue
        mime = att.get("mime_type") or "image/jpeg"
        b64 = att.get("content") or ""
        if not b64:
            continue
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })
    return parts


def _build_audio_user_message(audio_data: str, audio_format: str | None) -> dict:
    """Construct a multimodal user message with an audio content part."""
    fmt = audio_format or "m4a"
    return {
        "role": "user",
        "content": [
            {
                "type": "input_audio",
                "input_audio": {"data": audio_data, "format": fmt},
            },
        ],
    }


def _extract_transcript(text: str) -> tuple[str, str]:
    """Parse [transcript]...[/transcript] from model response.

    Returns (transcript, clean_response). If no tags found, transcript is empty
    and clean_response is the original text.
    """
    match = _TRANSCRIPT_RE.search(text)
    if not match:
        return "", text

    transcript = match.group(1).strip()
    clean = text[:match.start()] + text[match.end():]
    return transcript, clean.strip()


def _extract_client_actions(messages: list[dict], from_index: int) -> list[dict]:
    """Scan messages added during this turn for client_action tool calls."""
    actions = []
    for msg in messages[from_index:]:
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            continue
        for tc in msg["tool_calls"]:
            if tc.get("function", {}).get("name") == "client_action":
                try:
                    args = json.loads(tc["function"]["arguments"])
                    actions.append(args)
                except (json.JSONDecodeError, KeyError):
                    pass
    return actions


def _event_with_compaction_tag(event: dict[str, Any], compaction: bool) -> dict[str, Any]:
    if compaction:
        return {**event, "compaction": True}
    return event


def _merge_tool_schemas(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for t in group:
            fn = t.get("function") or {}
            name = fn.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(t)
    return out


_WORKSPACE_TOOLS = ["exec_command", "search_workspace", "reindex_workspace", "delegate_to_exec"]


async def _all_tool_schemas_by_name(bot: BotConfig) -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    # Auto-inject workspace tools when workspace is enabled
    extra_local = list(bot.local_tools)
    if bot.workspace.enabled or bot.shared_workspace_id:
        for wt in _WORKSPACE_TOOLS:
            if wt not in extra_local:
                extra_local.append(wt)
    for t in get_local_tool_schemas(extra_local):
        by_name[t["function"]["name"]] = t
    for t in await fetch_mcp_tools(bot.mcp_servers):
        by_name[t["function"]["name"]] = t
    for t in get_client_tool_schemas(bot.client_tools):
        by_name[t["function"]["name"]] = t
    return by_name
