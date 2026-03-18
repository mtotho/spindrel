"""Streaming chat and event handling."""
import httpx

from agent_client.client import AgentClient

from agent_client.cli.display import tool_status
from agent_client.cli.tools import execute_client_tool


def send_streaming(
    client: AgentClient,
    message: str,
    ctx: dict,
    audio_data: str | None = None,
    audio_format: str | None = None,
    audio_native: bool | None = None,
) -> dict:
    """Send a message via streaming and display tool status in real time.

    Handles tool_request events by executing client-side tools and posting
    results back to the server, then continues reading the stream.

    Returns a dict with 'response', 'transcript', and 'client_actions'.
    """
    response_text = ""
    transcript_text = ""
    client_actions: list[dict] = []

    for event in client.chat_stream(
        message=message,
        session_id=ctx["session_id"],
        bot_id=ctx["bot_id"],
        audio_data=audio_data,
        audio_format=audio_format,
        audio_native=audio_native,
    ):
        etype = event.get("type")

        if etype == "compaction_start":
            print(f"  [Compaction: saving memories/knowledge...]")

        elif etype == "compaction_done":
            title = event.get("title", "")
            if title:
                print(f"  [Compaction done: {title!r}]")
            else:
                print(f"  [Compaction done]")

        elif etype == "skill_context":
            count = event.get("count", 0)
            print(f"  [Using {count} skill chunk{'s' if count != 1 else ''}...]")

        elif etype == "memory_context":
            count = event.get("count", 0)
            print(f"  [Recalled {count} memor{'ies' if count != 1 else 'y'}...]")
            preview = event.get("memory_preview")
            if preview:
                print(f"    \033[2m{preview}\033[0m")
        elif etype == "knowledge_context":
            count = event.get("count", 0)
            print(f"  [Recalled {count} knowledge chunk{'s' if count != 1 else ''}...]")
            preview = event.get("knowledge_preview")
            if preview:
                print(f"    \033[2m{preview}\033[0m")

        elif etype == "tool_start":
            label = tool_status(event.get("tool", ""))
            if label:
                prefix = "Compaction: " if event.get("compaction") else ""
                print(f"  [{prefix}{label}...]")

        elif etype == "tool_request":
            tool_name = event.get("tool", "")
            arguments = event.get("arguments", {})
            request_id = event.get("request_id", "")
            result = execute_client_tool(tool_name, arguments)
            try:
                client.submit_tool_result(request_id, result)
            except httpx.HTTPError as e:
                print(f"  [error submitting tool result: {e}]")

        elif etype == "tool_result":
            if "error" in event:
                print(f"  [error: {event['error']}]")
            else:
                tool_name = event.get("tool", "")
                prefix = "  [Compaction: " if event.get("compaction") else "  ["
                suffix = "]"
                if tool_name == "search_memories":
                    count = event.get("memory_count")
                    if count is not None:
                        if count == 0:
                            print(f"{prefix}No memories found{suffix}")
                        else:
                            print(f"{prefix}Found {count} memor{'y' if count == 1 else 'ies'}{suffix}")
                            preview = event.get("memory_preview")
                            if preview:
                                print(f"    \033[2m{preview}\033[0m")
                elif tool_name == "save_memory" and event.get("saved"):
                    print(f"{prefix}Saved to memory{suffix}")
                elif event.get("compaction") and tool_name:
                    print(f"{prefix}{tool_status(tool_name) or tool_name}{suffix}")

        elif etype == "transcript":
            transcript_text = event.get("text", "")
            print(f"  [heard: {transcript_text}]")

        elif etype == "response":
            if event.get("compaction"):
                continue
            response_text = event.get("text", "")
            client_actions = event.get("client_actions", [])

        elif etype == "error":
            detail = event.get("detail", "Unknown error")
            print(f"  [error] {detail}")

    return {"response": response_text, "transcript": transcript_text, "client_actions": client_actions}
