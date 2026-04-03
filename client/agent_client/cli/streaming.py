"""Streaming chat and event handling."""
from __future__ import annotations

import time

import httpx

from agent_client.client import AgentClient
from agent_client.cli.display import StreamDisplay, console, print_error, print_warning
from agent_client.cli.events import EventHandler


def send_streaming(
    client: AgentClient,
    message: str,
    ctx: dict,
    audio_data: str | None = None,
    audio_format: str | None = None,
    audio_native: bool | None = None,
) -> dict:
    """Send a message via streaming and display results in real time.

    Returns a dict with 'response', 'transcript', 'client_actions', 'cancelled'.
    """
    display = StreamDisplay()
    verbose = ctx.get("_verbose", False)
    handler = EventHandler(display, client, verbose=verbose)

    # Show a spinner while waiting for the first event
    status = console.status("[dim]Sending...[/dim]", spinner="dots")
    status.start()
    first_event = True

    try:
        for event in client.chat_stream(
            message=message,
            session_id=ctx["session_id"],
            bot_id=ctx["bot_id"],
            client_id=ctx.get("client_id", "cli"),
            channel_id=ctx.get("channel_id"),
            model_override=ctx.get("model_override"),
            model_provider_id_override=ctx.get("model_provider_id_override"),
            attachments=ctx.get("_attachments"),
            audio_data=audio_data,
            audio_format=audio_format,
            audio_native=audio_native,
        ):
            if first_event:
                status.stop()
                first_event = False

            signal = handler.handle(event)
            if signal and signal.startswith("queued:"):
                task_id = signal.split(":", 1)[1]
                display.finish()
                return _poll_task(client, task_id)

    except httpx.RemoteProtocolError:
        if first_event:
            status.stop()
        display.pause()
        print_warning("Connection lost mid-stream. Use /history to see the response.")
        return _result(handler, cancelled=True)
    except httpx.ReadError:
        if first_event:
            status.stop()
        display.pause()
        print_warning("Read error mid-stream. Use /history to see the response.")
        return _result(handler, cancelled=True)
    except KeyboardInterrupt:
        if first_event:
            status.stop()
        display.pause()
        try:
            result = client.cancel(ctx["bot_id"], ctx.get("client_id", "cli"))
            if result.get("cancelled"):
                print_warning("Cancelled.")
            else:
                print_warning("Cancel sent (may already be finishing).")
        except Exception:
            print_warning("Interrupted.")
        return _result(handler, cancelled=True)

    if first_event:
        status.stop()

    # Flush any remaining context summary
    handler._flush_context_summary()
    display.finish()
    return _result(handler)


def _result(handler: EventHandler, cancelled: bool = False) -> dict:
    return {
        "response": handler.response_text,
        "transcript": handler.transcript_text,
        "client_actions": handler.client_actions,
        "cancelled": cancelled or handler.was_cancelled,
    }


def _poll_task(client: AgentClient, task_id: str) -> dict:
    """Poll a queued task until it completes, with a Rich spinner."""
    with console.status("[dim]Waiting for queued task...[/dim]", spinner="dots"):
        while True:
            try:
                task = client.get_task(task_id)
            except Exception as e:
                print_error(f"Error polling task: {e}")
                return {"response": "", "transcript": "", "client_actions": [], "cancelled": False}

            status = task.get("status", "")
            if status in ("complete", "completed"):
                result_text = task.get("result", "")
                if result_text:
                    from rich.markdown import Markdown
                    console.print(Markdown(result_text))
                    console.print()
                return {"response": result_text or "", "transcript": "", "client_actions": [], "cancelled": False}
            elif status == "failed":
                error = task.get("error", "Task failed")
                print_error(error)
                return {"response": "", "transcript": "", "client_actions": [], "cancelled": False}
            elif status == "cancelled":
                print_warning("Task was cancelled.")
                return {"response": "", "transcript": "", "client_actions": [], "cancelled": True}

            try:
                time.sleep(2)
            except KeyboardInterrupt:
                print_warning("Stopped polling.")
                return {"response": "", "transcript": "", "client_actions": [], "cancelled": True}
