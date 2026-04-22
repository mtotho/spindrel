"""SSE event handler mapping server events to display actions."""
from __future__ import annotations

from typing import Any

from agent_client.cli.display import (
    StreamDisplay,
    console,
    print_error,
    print_status,
    print_warning,
    tool_status,
)
from agent_client.cli.tools import execute_client_tool


class EventHandler:
    """Maps SSE event types to display actions.

    Accumulates response text, transcript, and client_actions across the stream.
    Returns special signals for events that need caller attention (queued, approval).
    """

    def __init__(self, display: StreamDisplay, client: Any, verbose: bool = False):
        self.display = display
        self.client = client
        self.verbose = verbose
        self.response_text: str = ""
        self.transcript_text: str = ""
        self.client_actions: list[dict] = []
        self.was_cancelled: bool = False
        self._queued_task_id: str | None = None
        self._context_items: list[str] = []

    def handle(self, event: dict) -> str | None:
        """Process a single SSE event. Returns a signal string or None.

        Signals:
          'queued:<task_id>' — caller should switch to task polling
        """
        etype = event.get("type", "")
        handler = _HANDLERS.get(etype)
        if handler is not None:
            return handler(self, event)
        return None

    def _flush_context_summary(self) -> None:
        """Print accumulated context items as a single summary line."""
        if self._context_items:
            summary = ", ".join(self._context_items)
            print_status(summary)
            self._context_items.clear()

    # --- Core response events ---

    def _on_assistant_text(self, event: dict) -> None:
        self._flush_context_summary()
        text = event.get("text", "")
        if not self.display.is_active:
            self.display.start()
        self.display.update_markdown(text)

    def _on_response(self, event: dict) -> None:
        if event.get("compaction"):
            return
        self._flush_context_summary()
        self.response_text = event.get("text", "")
        self.client_actions = event.get("client_actions", [])

    def _on_transcript(self, event: dict) -> None:
        self.transcript_text = event.get("text", "")
        print_status(f"heard: {self.transcript_text}")

    def _on_thinking_content(self, event: dict) -> None:
        text = event.get("text", "")
        if text:
            lines = text.strip().split("\n")
            preview = lines[0][:80]
            if len(lines) > 1 or len(lines[0]) > 80:
                preview += "..."
            print_status(f"thinking: {preview}")

    # --- Tool events ---

    def _on_tool_start(self, event: dict) -> None:
        self._flush_context_summary()
        label = tool_status(event.get("tool", ""))
        if label:
            prefix = "Compaction: " if event.get("compaction") else ""
            print_status(f"{prefix}{label}...")

    def _on_tool_request(self, event: dict) -> None:
        tool_name = event.get("tool", "")
        arguments = event.get("arguments", {})
        request_id = event.get("request_id", "")
        self.display.pause()
        result = execute_client_tool(tool_name, arguments)
        try:
            self.client.submit_tool_result(request_id, result)
        except Exception as e:
            print_error(f"Error submitting tool result: {e}")
        self.display.resume()

    def _on_tool_result(self, event: dict) -> None:
        if "error" in event:
            print_error(f"Tool error: {event['error']}")
        elif event.get("compaction"):
            tool_name = event.get("tool", "")
            if tool_name:
                label = tool_status(tool_name) or tool_name
                print_status(f"Compaction: {label}")

    # --- Approval events ---

    def _on_approval_request(self, event: dict) -> str | None:
        approval_id = event.get("approval_id", "")
        tool_name = event.get("tool", "")  # server sends "tool", not "tool_name"
        arguments = event.get("arguments", {})
        reason = event.get("reason", "")

        self.display.pause()
        console.print()
        console.print(f"  [bold yellow]Approval required[/bold yellow]: {tool_name}")
        if reason:
            console.print(f"  [dim]Reason: {reason}[/dim]")
        if arguments:
            import json
            from rich.syntax import Syntax
            arg_text = json.dumps(arguments, indent=2)[:500]
            console.print(Syntax(arg_text, "json", padding=1))
        try:
            answer = console.input("  Approve? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        approved = answer in ("", "y", "yes")
        try:
            self.client.decide_approval(approval_id, approved)
            if approved:
                console.print("  [green]Approved[/green]")
            else:
                console.print("  [red]Denied[/red]")
        except Exception as e:
            print_error(f"Error deciding approval: {e}")
        self.display.resume()
        return None

    def _on_approval_resolved(self, event: dict) -> None:
        verdict = event.get("verdict", "")
        tool_name = event.get("tool", "")  # server sends "tool", not "tool_name"
        if verdict == "approved":
            print_status(f"Approved: {tool_name}")
        else:
            print_warning(f"Denied: {tool_name}")

    # --- Queue / session busy ---

    def _on_queued(self, event: dict) -> str | None:
        task_id = event.get("task_id", "")
        reason = event.get("reason", "session busy")
        print_warning(f"Request queued ({reason})")
        self._queued_task_id = task_id
        return f"queued:{task_id}"

    # --- Status / info events ---

    def _on_error(self, event: dict) -> None:
        detail = event.get("detail") or event.get("message") or "Unknown error"
        print_error(detail)

    def _on_warning(self, event: dict) -> None:
        msg = event.get("message", "")
        print_warning(msg)

    def _on_cancelled(self, _event: dict) -> None:
        self.was_cancelled = True
        print_warning("Request cancelled.")

    def _on_rate_limit_wait(self, event: dict) -> None:
        wait = event.get("wait_seconds", 0)
        provider = event.get("provider_id", "")
        msg = f"Rate limited \u2014 waiting {wait}s"
        if provider:
            msg += f" ({provider})"
        print_warning(msg)

    def _on_fallback(self, event: dict) -> None:
        from_model = event.get("from_model", "")
        to_model = event.get("to_model", "")
        print_warning(f"Switching model: {from_model} \u2192 {to_model}")

    def _on_secret_warning(self, event: dict) -> None:
        patterns = event.get("patterns", [])
        types = [p.get("type", "unknown") for p in patterns]
        print_error(f"Secret detected in message: {', '.join(types)}")

    def _on_context_budget(self, event: dict) -> None:
        used = event.get("used_tokens", 0)
        budget = event.get("budget_tokens", 0)
        if budget:
            pct = int(used / budget * 100)
            print_status(f"Context: {pct}% ({used:,}/{budget:,} tokens)")

    # --- Context assembly events ---
    # Collected into a summary line, printed when the first non-context event arrives.
    # In verbose mode, each gets its own line.

    def _on_skill_context(self, event: dict) -> None:
        count = event.get("count", 0)
        if self.verbose:
            print_status(f"Using {count} skill chunk{'s' if count != 1 else ''}")
        else:
            self._context_items.append(f"{count} skill{'s' if count != 1 else ''}")

    def _on_memory_scheme(self, event: dict) -> None:
        etype = event.get("type", "")
        chars = event.get("chars", 0)
        if self.verbose:
            if "bootstrap" in etype:
                print_status(f"Memory: loaded MEMORY.md ({chars:,} chars)")
            elif "today" in etype:
                print_status(f"Memory: today's log ({chars:,} chars)")
            elif "yesterday" in etype:
                print_status(f"Memory: yesterday's log ({chars:,} chars)")
            elif "reference" in etype:
                count = event.get("count", 0)
                print_status(f"Memory: {count} reference file{'s' if count != 1 else ''}")
        else:
            if "bootstrap" in etype:
                self._context_items.append("memory")
            # Skip individual memory sub-events in summary — "memory" covers it

    def _on_channel_workspace_context(self, event: dict) -> None:
        count = event.get("count", 0)
        if self.verbose:
            print_status(f"Workspace: {count} active file{'s' if count != 1 else ''}")
        else:
            self._context_items.append(f"{count} workspace file{'s' if count != 1 else ''}")

    def _on_section_context(self, event: dict) -> None:
        count = event.get("count", 0)
        if self.verbose:
            print_status(f"History: {count} section{'s' if count != 1 else ''}")
        else:
            if not any("history" in item for item in self._context_items):
                self._context_items.append("history")

    def _on_fs_context(self, event: dict) -> None:
        count = event.get("count", 0)
        if self.verbose:
            print_status(f"Filesystem: {count} chunk{'s' if count != 1 else ''}")
        else:
            self._context_items.append(f"{count} fs chunk{'s' if count != 1 else ''}")

    def _on_rag_rerank(self, event: dict) -> None:
        if self.verbose:
            kept = event.get("kept", 0)
            total = event.get("total", 0)
            print_status(f"Reranked: kept {kept}/{total} chunks")

    def _on_delegation_post(self, event: dict) -> None:
        bot_id = event.get("bot_id", "")
        self._flush_context_summary()
        print_status(f"Delegating to {bot_id}...")

    # --- Compaction events ---

    def _on_compaction_start(self, _event: dict) -> None:
        print_status("Compacting context...")

    def _on_compaction_done(self, event: dict) -> None:
        title = event.get("title", "")
        if title:
            print_status(f"Compaction done: {title!r}")
        else:
            print_status("Compaction done")


# Dispatch table: event type -> handler method
_HANDLERS: dict[str, Any] = {
    "assistant_text": EventHandler._on_assistant_text,
    "response": EventHandler._on_response,
    "transcript": EventHandler._on_transcript,
    "thinking_content": EventHandler._on_thinking_content,
    "tool_start": EventHandler._on_tool_start,
    "tool_request": EventHandler._on_tool_request,
    "tool_result": EventHandler._on_tool_result,
    "approval_request": EventHandler._on_approval_request,
    "approval_resolved": EventHandler._on_approval_resolved,
    "queued": EventHandler._on_queued,
    "error": EventHandler._on_error,
    "warning": EventHandler._on_warning,
    "cancelled": EventHandler._on_cancelled,
    "rate_limit_wait": EventHandler._on_rate_limit_wait,
    "fallback": EventHandler._on_fallback,
    "secret_warning": EventHandler._on_secret_warning,
    "context_budget": EventHandler._on_context_budget,
    "skill_context": EventHandler._on_skill_context,
    "skill_pinned_context": EventHandler._on_skill_context,
    "memory_scheme_bootstrap": EventHandler._on_memory_scheme,
    "memory_scheme_today_log": EventHandler._on_memory_scheme,
    "memory_scheme_yesterday_log": EventHandler._on_memory_scheme,
    "memory_scheme_reference_index": EventHandler._on_memory_scheme,
    "channel_workspace_context": EventHandler._on_channel_workspace_context,
    "section_context": EventHandler._on_section_context,
    "section_index_context": EventHandler._on_section_context,
    "fs_context": EventHandler._on_fs_context,
    "rag_rerank": EventHandler._on_rag_rerank,
    "delegation_post": EventHandler._on_delegation_post,
    "compaction_start": EventHandler._on_compaction_start,
    "compaction_done": EventHandler._on_compaction_done,
}
