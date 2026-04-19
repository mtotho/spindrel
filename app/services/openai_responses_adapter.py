"""OpenAI-compatible adapter wrapping the Codex Responses API.

Provides an ``OpenAIResponsesAdapter`` that exposes
``client.chat.completions.create(**kwargs)`` — the same interface as
``openai.AsyncOpenAI`` — but internally translates to/from the
``POST /responses`` endpoint at ``https://chatgpt.com/backend-api/codex``
using a ChatGPT OAuth Bearer token.

This is the wire format used by OpenAI's Codex CLI when a user signs in
with their ChatGPT subscription (Plus/Pro/Business/Edu/Enterprise). It is
distinct from the public ``api.openai.com/v1/chat/completions`` endpoint:
the token type, the request/response shape, and the headers all differ.

Design mirrors ``app/services/anthropic_adapter.py`` — a drop-in AsyncOpenAI
shim so ``app/agent/llm.py`` can treat this provider identically to any
other. Token refresh is delegated to a caller-supplied async callable, so
the adapter itself has no DB or filesystem dependencies.

Endpoints, headers, and client_id values come from OpenAI's public Codex
CLI source (github.com/openai/codex, codex-rs/login) plus the community
OAuth plugins that reuse them. See ``openai_subscription_driver.py`` for
the client_id constant.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx
import openai

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Wire-level constants
# ---------------------------------------------------------------------------
# Codex Responses API base URL. `/responses` is appended for chat turns.
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"

# Required beta header — the Responses API is still gated behind this flag
# when accessed via the ChatGPT subscription endpoint.
_OPENAI_BETA_HEADER_VALUE = "responses=experimental"

# Identifies the caller to OpenAI's backend. Matches the value the official
# Codex CLI sends (`codex_cli_rs`). Using the same originator keeps us on
# the well-tested codepath and mirrors what community tools do.
_ORIGINATOR_HEADER_VALUE = "codex_cli_rs"

# OpenAI's endpoints reject bare python-httpx User-Agents at the edge.
# Keep this in sync with ``openai_oauth._CODEX_USER_AGENT``.
_CODEX_USER_AGENT = f"{_ORIGINATOR_HEADER_VALUE}/0.45.0 (linux; x86_64) spindrel"


# ---------------------------------------------------------------------------
# Exception translation: httpx / Responses API → openai.*
# ---------------------------------------------------------------------------
# `llm.py` catches `openai.*` exceptions to drive retry / fallback. HTTP
# errors from the Responses endpoint must surface as those classes for the
# agent loop to behave correctly.

def _exc_for_status(status: int, msg: str, resp: httpx.Response, body: Any) -> Exception:
    if status == 400:
        return openai.BadRequestError(message=msg, response=resp, body=body)
    if status == 401:
        return openai.AuthenticationError(message=msg, response=resp, body=body)
    if status == 403:
        return openai.PermissionDeniedError(message=msg, response=resp, body=body)
    if status == 404:
        return openai.NotFoundError(message=msg, response=resp, body=body)
    if status == 429:
        return openai.RateLimitError(message=msg, response=resp, body=body)
    if status >= 500:
        return openai.InternalServerError(message=msg, response=resp, body=body)
    return openai.APIStatusError(message=msg, response=resp, body=body)


def _raise_for_httpx(resp: httpx.Response) -> None:
    """Raise the appropriate ``openai.*`` exception for a non-2xx response."""
    if resp.is_success:
        return
    try:
        body = resp.json()
    except (json.JSONDecodeError, ValueError):
        body = resp.text
    msg = f"Responses API returned {resp.status_code}: {body if isinstance(body, str) else json.dumps(body)[:500]}"
    raise _exc_for_status(resp.status_code, msg, resp, body)


def _log_error_body(request_body: dict, status_code: int, response_body: Any) -> None:
    """On 4xx, log the exact request the Codex endpoint rejected.

    The rejection message sometimes names a model different from the one in
    the request (observed with stale fallback chains pointing at providers
    that no longer resolve), so we log both to make the mismatch obvious.
    """
    if status_code < 400:
        return
    try:
        tools = request_body.get("tools") or []
        summary = {
            "model": request_body.get("model"),
            "stream": request_body.get("stream"),
            "store": request_body.get("store"),
            "instructions_len": len(request_body.get("instructions") or ""),
            "input_items": len(request_body.get("input") or []),
            "tool_count": len(tools),
            "tool_names": [t.get("name") for t in tools if isinstance(t, dict)][:20],
            "has_tool_choice": "tool_choice" in request_body,
        }
        logger.warning(
            "Responses API %s rejected request — sent %s, response body: %s",
            status_code,
            json.dumps(summary),
            (response_body if isinstance(response_body, str) else json.dumps(response_body))[:500],
        )
    except Exception:
        # Logging must never mask the original exception.
        logger.warning("Responses API %s rejected request (summary unavailable)", status_code)


# ---------------------------------------------------------------------------
# Lightweight dataclass shims that mimic openai response objects
# ---------------------------------------------------------------------------
# These match the shape of ``openai.types.chat.*`` just enough for
# ``StreamAccumulator`` / ``_llm_call`` in ``llm.py`` to consume them.

@dataclass
class _Function:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    type: str
    function: _Function
    index: int = 0


@dataclass
class _ChoiceDelta:
    role: str | None = None
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None
    reasoning_content: str | None = None


@dataclass
class _Choice:
    index: int = 0
    delta: _ChoiceDelta = field(default_factory=_ChoiceDelta)
    finish_reason: str | None = None
    message: Any = None


@dataclass
class _PromptTokensDetails:
    cached_tokens: int = 0


@dataclass
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_tokens_details: _PromptTokensDetails | None = None


@dataclass
class _ChatCompletionChunk:
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: list[_Choice] = field(default_factory=list)
    usage: _Usage | None = None


@dataclass
class _Message:
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None

    def model_dump(self, exclude_none: bool = False) -> dict:
        d: dict[str, Any] = {"role": self.role}
        if self.content is not None or not exclude_none:
            d["content"] = self.content
        if self.tool_calls is not None or not exclude_none:
            if self.tool_calls is not None:
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in self.tool_calls
                ]
            else:
                d["tool_calls"] = None
        return d


@dataclass
class _ChatCompletion:
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[_Choice] = field(default_factory=list)
    usage: _Usage | None = None


# ---------------------------------------------------------------------------
# Request translation: OpenAI chat.completions → Responses API
# ---------------------------------------------------------------------------

def _translate_content(content: Any) -> list[dict]:
    """Convert OpenAI content (string | list of parts) to Responses input-content blocks.

    Responses uses ``input_text`` / ``input_image`` / ``input_file`` where
    Chat Completions uses ``text`` / ``image_url``. Output messages use
    ``output_text`` — but output blocks only appear in assistant turns that
    we read back from the API, not in what we send.
    """
    if content is None:
        return [{"type": "input_text", "text": ""}]
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}]
    if not isinstance(content, list):
        return [{"type": "input_text", "text": str(content)}]

    blocks: list[dict] = []
    for part in content:
        if not isinstance(part, dict):
            blocks.append({"type": "input_text", "text": str(part)})
            continue
        ptype = part.get("type")
        if ptype == "text":
            blocks.append({"type": "input_text", "text": part.get("text", "")})
        elif ptype == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            detail = (part.get("image_url") or {}).get("detail", "auto")
            blocks.append({"type": "input_image", "image_url": url, "detail": detail})
        elif ptype in ("input_text", "input_image", "input_file"):
            # Already in Responses format — pass through.
            blocks.append(part)
        else:
            # Unknown block — serialize as text so we don't lose information.
            blocks.append({"type": "input_text", "text": json.dumps(part)})
    if not blocks:
        blocks = [{"type": "input_text", "text": ""}]
    return blocks


_CODEX_CALL_ID_MAX = 64
# Codex Responses caps `call_id` at 64 chars. History frequently carries ids
# from other providers (LiteLLM/Gemini emit long opaque ids, Anthropic uses
# `toolu_...`, etc.); if we replay them verbatim the Codex endpoint rejects
# the whole request with "string too long". Collapse any oversize id to a
# deterministic short form so the function_call ↔ function_call_output pairing
# still matches within the same request.

def _normalize_call_id(raw: str) -> str:
    if not raw or len(raw) <= _CODEX_CALL_ID_MAX:
        return raw
    import hashlib
    digest = hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:24]
    normalized = f"call_{digest}"
    logger.warning(
        "Truncating tool_call_id for Codex Responses API (was %d chars, >%d): %r → %r",
        len(raw), _CODEX_CALL_ID_MAX, raw[:40] + "...", normalized,
    )
    return normalized


def _translate_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Convert chat.completions messages to (instructions, input[]).

    - ``role=system`` → concatenated into ``instructions`` (Responses has
      no system role; it uses the top-level ``instructions`` field).
    - ``role=user`` / ``role=assistant`` → message items with role + content.
    - ``assistant`` message with ``tool_calls`` → each tool call becomes a
      separate ``function_call`` input item.
    - ``role=tool`` → ``function_call_output`` input item keyed by call_id.
    """
    instruction_parts: list[str] = []
    items: list[dict] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role == "system":
            if isinstance(content, str) and content:
                instruction_parts.append(content)
            elif isinstance(content, list):
                txt = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
                if txt.strip():
                    instruction_parts.append(txt)
            continue

        if role == "user":
            items.append({
                "type": "message",
                "role": "user",
                "content": _translate_content(content),
            })
            continue

        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            if content:
                items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content if isinstance(content, str) else str(content)}],
                })
            if tool_calls:
                for tc in tool_calls:
                    func = tc.get("function") or {}
                    args_raw = func.get("arguments", "{}")
                    if not isinstance(args_raw, str):
                        args_raw = json.dumps(args_raw)
                    items.append({
                        "type": "function_call",
                        "call_id": _normalize_call_id(tc.get("id", "")),
                        "name": func.get("name", ""),
                        "arguments": args_raw,
                    })
            continue

        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": _normalize_call_id(msg.get("tool_call_id", "")),
                "output": str(content) if content is not None else "",
            })
            continue

    instructions = "\n\n".join(instruction_parts)
    return instructions, items


def _translate_tools(tools: list[dict] | None) -> list[dict] | None:
    """Convert chat.completions tool defs to Responses function tools.

    Responses hoists the function schema to the top level of each tool
    object — there's no nested ``function: {...}`` wrapper.
    """
    if not tools:
        return None
    out: list[dict] = []
    for tool in tools:
        if tool.get("type") != "function":
            out.append(tool)
            continue
        func = tool.get("function") or {}
        out.append({
            "type": "function",
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "parameters": func.get("parameters", {"type": "object", "properties": {}}),
        })
    return out or None


def _translate_tool_choice(tool_choice: Any) -> Any:
    """Convert chat.completions tool_choice to Responses format.

    Responses accepts: ``"auto"``, ``"none"``, ``"required"``, or
    ``{"type": "function", "name": "..."}``. Chat Completions wraps the
    named case as ``{"type": "function", "function": {"name": "..."}}``.
    """
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        return tool_choice
    if isinstance(tool_choice, dict):
        func = tool_choice.get("function") or {}
        name = func.get("name")
        if name:
            return {"type": "function", "name": name}
    return tool_choice


def _build_request_body(
    *,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    tool_choice: Any,
    stream: bool,
    extra: dict,
) -> dict:
    instructions, items = _translate_messages(messages)
    body: dict[str, Any] = {
        "model": model,
        "input": items,
        "stream": stream,
        "store": False,
    }
    if instructions:
        body["instructions"] = instructions
    resp_tools = _translate_tools(tools)
    if resp_tools:
        body["tools"] = resp_tools
        tc = _translate_tool_choice(tool_choice)
        if tc is not None:
            body["tool_choice"] = tc
        if extra.get("parallel_tool_calls") is not None:
            body["parallel_tool_calls"] = extra["parallel_tool_calls"]

    for passthrough in ("temperature", "top_p", "max_output_tokens", "reasoning"):
        if passthrough in extra and extra[passthrough] is not None:
            body[passthrough] = extra[passthrough]

    if "max_tokens" in extra and extra["max_tokens"] is not None and "max_output_tokens" not in body:
        body["max_output_tokens"] = extra["max_tokens"]

    return body


# ---------------------------------------------------------------------------
# Response translation: Responses API → ChatCompletion shim
# ---------------------------------------------------------------------------

def _build_usage(usage_obj: dict | None) -> _Usage:
    if not usage_obj:
        return _Usage()
    input_tokens = usage_obj.get("input_tokens", 0) or 0
    output_tokens = usage_obj.get("output_tokens", 0) or 0
    details = usage_obj.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", 0) or 0
    return _Usage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        prompt_tokens_details=_PromptTokensDetails(cached_tokens=cached),
    )


def _extract_message_and_tool_calls(output_items: list[dict]) -> tuple[str | None, list[_ToolCall]]:
    """Walk the Responses output array, collecting text + function_call blocks."""
    text_parts: list[str] = []
    tool_calls: list[_ToolCall] = []
    for idx, item in enumerate(output_items):
        itype = item.get("type")
        if itype == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    text_parts.append(part.get("text", ""))
        elif itype == "function_call":
            tool_calls.append(_ToolCall(
                id=item.get("call_id") or item.get("id") or "",
                type="function",
                function=_Function(
                    name=item.get("name", ""),
                    arguments=item.get("arguments", "") or "",
                ),
                index=idx,
            ))
    content = "".join(text_parts) if text_parts else None
    return content, tool_calls


def _finish_reason_from_response(resp_obj: dict, tool_calls: list[_ToolCall]) -> str:
    # Responses exposes `status` ("completed", "incomplete", "failed") and
    # `incomplete_details.reason` ("max_output_tokens", etc.). Map onto the
    # chat-completions vocabulary that StreamAccumulator / llm.py expect.
    if tool_calls:
        return "tool_calls"
    status = resp_obj.get("status")
    incomplete = (resp_obj.get("incomplete_details") or {}).get("reason")
    if incomplete == "max_output_tokens":
        return "length"
    if status == "failed":
        return "stop"
    return "stop"


def _response_to_completion(resp_obj: dict) -> _ChatCompletion:
    content, tool_calls = _extract_message_and_tool_calls(resp_obj.get("output") or [])
    message = _Message(role="assistant", content=content, tool_calls=tool_calls or None)
    return _ChatCompletion(
        id=resp_obj.get("id", ""),
        model=resp_obj.get("model", ""),
        created=int(resp_obj.get("created_at") or time.time()),
        choices=[_Choice(
            index=0,
            message=message,
            finish_reason=_finish_reason_from_response(resp_obj, tool_calls),
        )],
        usage=_build_usage(resp_obj.get("usage")),
    )


# ---------------------------------------------------------------------------
# Streaming translation
# ---------------------------------------------------------------------------
# The Responses API streams Server-Sent Events with event names like
# ``response.output_text.delta`` / ``response.function_call_arguments.delta``
# / ``response.completed``. We translate each event into one or more
# ``_ChatCompletionChunk`` objects that look like OpenAI chat.completions
# stream chunks.

class _ResponsesStreamAdapter:
    """Wraps the SSE stream from POST /responses, yielding OpenAI-shape chunks.

    Acts as both an async iterable and an async iterator so ``_consume_stream``
    in ``app/agent/llm.py`` can call ``__anext__`` directly after the normal
    ``async for`` exits (to drain trailing usage-only chunks).

    Built eagerly via ``create()`` so HTTP errors surface inside the caller's
    retry loop rather than inside ``async for``.
    """

    def __init__(self, response: httpx.Response, model: str):
        self._response = response
        self._model = model
        self._response_id: str = ""
        # output_index → tool_call shim (for streaming function_call items)
        self._tool_calls: dict[int, dict] = {}
        # output_index for tool_calls (so StreamAccumulator's delta.index matches)
        self._tool_index_seq: int = -1
        self._output_index_to_tool_index: dict[int, int] = {}
        self._inner_iter: AsyncIterator[_ChatCompletionChunk] | None = None
        self._final_usage: _Usage | None = None
        self._finish_reason: str | None = None

    @classmethod
    async def create(cls, client: httpx.AsyncClient, url: str, headers: dict, body: dict, model: str) -> "_ResponsesStreamAdapter":
        """Open the streaming request and return the adapter.

        Errors from the initial request are translated to ``openai.*`` and
        raised here so ``_llm_call_stream`` can catch them in the retry loop.
        """
        req = client.build_request("POST", url, headers=headers, json=body)
        response = await client.send(req, stream=True)
        if not response.is_success:
            try:
                text = await response.aread()
                try:
                    parsed = json.loads(text.decode("utf-8", errors="replace"))
                except (json.JSONDecodeError, ValueError):
                    parsed = text.decode("utf-8", errors="replace")
            finally:
                await response.aclose()
            _log_error_body(body, response.status_code, parsed)
            msg = f"Responses API returned {response.status_code}: {parsed if isinstance(parsed, str) else json.dumps(parsed)[:500]}"
            raise _exc_for_status(response.status_code, msg, response, parsed)
        return cls(response, model)

    def __aiter__(self):
        if self._inner_iter is None:
            self._inner_iter = self._iterate()
        return self

    async def __anext__(self) -> _ChatCompletionChunk:
        if self._inner_iter is None:
            self._inner_iter = self._iterate()
        return await self._inner_iter.__anext__()

    async def aclose(self) -> None:
        try:
            await self._response.aclose()
        except Exception:
            pass

    async def _iterate(self) -> AsyncIterator[_ChatCompletionChunk]:
        try:
            event_name: str = ""
            data_lines: list[str] = []
            async for line in self._response.aiter_lines():
                # SSE framing: event: / data: lines, blank line = dispatch.
                if line == "":
                    if event_name or data_lines:
                        for chunk in self._handle_event(event_name, "\n".join(data_lines)):
                            yield chunk
                    event_name = ""
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue  # SSE comment
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
            # Drain any trailing event that didn't get a blank line.
            if event_name or data_lines:
                for chunk in self._handle_event(event_name, "\n".join(data_lines)):
                    yield chunk
        finally:
            await self.aclose()

    def _make_chunk(
        self,
        delta: _ChoiceDelta | None = None,
        finish_reason: str | None = None,
        usage: _Usage | None = None,
    ) -> _ChatCompletionChunk:
        choices: list[_Choice] = []
        if delta is not None or finish_reason is not None:
            choices.append(_Choice(
                index=0,
                delta=delta or _ChoiceDelta(),
                finish_reason=finish_reason,
            ))
        return _ChatCompletionChunk(
            id=self._response_id,
            model=self._model,
            created=int(time.time()),
            choices=choices,
            usage=usage,
        )

    def _handle_event(self, event_name: str, data: str) -> list[_ChatCompletionChunk]:
        if not data:
            return []
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(payload, dict):
            return []

        # Some event names include both as `type` and as SSE `event:`. Prefer
        # the payload's type, falling back to the SSE event name.
        evt_type = payload.get("type") or event_name

        if evt_type == "response.created":
            resp = payload.get("response") or {}
            self._response_id = resp.get("id", "")
            return [self._make_chunk(delta=_ChoiceDelta(role="assistant"))]

        if evt_type == "response.output_text.delta":
            text = payload.get("delta") or ""
            if not text:
                return []
            return [self._make_chunk(delta=_ChoiceDelta(content=text))]

        if evt_type == "response.output_item.added":
            item = payload.get("item") or {}
            output_index = payload.get("output_index", 0)
            if item.get("type") == "function_call":
                self._tool_index_seq += 1
                tool_idx = self._tool_index_seq
                self._output_index_to_tool_index[output_index] = tool_idx
                self._tool_calls[tool_idx] = {
                    "id": item.get("call_id", "") or item.get("id", ""),
                    "name": item.get("name", ""),
                    "arguments": "",
                }
                return [self._make_chunk(delta=_ChoiceDelta(tool_calls=[_ToolCall(
                    id=self._tool_calls[tool_idx]["id"],
                    type="function",
                    function=_Function(name=self._tool_calls[tool_idx]["name"], arguments=""),
                    index=tool_idx,
                )]))]
            return []

        if evt_type == "response.function_call_arguments.delta":
            output_index = payload.get("output_index", 0)
            tool_idx = self._output_index_to_tool_index.get(output_index)
            if tool_idx is None:
                return []
            delta_args = payload.get("delta") or ""
            if not delta_args:
                return []
            self._tool_calls[tool_idx]["arguments"] += delta_args
            return [self._make_chunk(delta=_ChoiceDelta(tool_calls=[_ToolCall(
                id="",
                type="function",
                function=_Function(name="", arguments=delta_args),
                index=tool_idx,
            )]))]

        if evt_type == "response.output_item.done":
            # Finalization event for an output item. For function_call items
            # that never streamed any arguments (fast-path emit — gpt-5-codex
            # does this for short args), we haven't filled `arguments` yet;
            # backfill from the completed item so the tool call isn't empty.
            item = payload.get("item") or {}
            if item.get("type") != "function_call":
                return []
            output_index = payload.get("output_index", 0)
            tool_idx = self._output_index_to_tool_index.get(output_index)
            if tool_idx is None:
                return []
            final_args = item.get("arguments", "") or ""
            accumulated = self._tool_calls[tool_idx].get("arguments", "")
            if not final_args or final_args == accumulated:
                return []
            # Emit only the missing tail so the downstream accumulator sees
            # every byte exactly once.
            tail = final_args[len(accumulated):] if final_args.startswith(accumulated) else final_args
            self._tool_calls[tool_idx]["arguments"] = final_args
            return [self._make_chunk(delta=_ChoiceDelta(tool_calls=[_ToolCall(
                id="",
                type="function",
                function=_Function(name="", arguments=tail),
                index=tool_idx,
            )]))]

        if evt_type in ("response.completed", "response.incomplete"):
            resp = payload.get("response") or {}
            usage = _build_usage(resp.get("usage"))
            # Derive finish_reason: tool_calls wins when we emitted any,
            # else stop; response.incomplete with reason=max_output_tokens
            # maps to "length" so llm.py treats it as a truncation event.
            finish = "tool_calls" if self._tool_calls else "stop"
            incomplete = (resp.get("incomplete_details") or {}).get("reason")
            if incomplete == "max_output_tokens" or evt_type == "response.incomplete":
                finish = "length"
            self._final_usage = usage
            self._finish_reason = finish
            return [self._make_chunk(finish_reason=finish, usage=usage)]

        if evt_type in ("response.failed", "error"):
            err = payload.get("error") or payload.get("response", {}).get("error") or {}
            msg = err.get("message") or "Responses stream returned error event"
            # Synthesize a request so openai.* exception signatures validate.
            raise openai.InternalServerError(
                message=msg, response=self._response, body=payload,
            )

        return []


# ---------------------------------------------------------------------------
# Adapter: the AsyncOpenAI-shaped entry point
# ---------------------------------------------------------------------------

TokensSource = Callable[[], Awaitable[dict]]
"""Awaitable that returns a dict with at least:
    access_token: str
    account_id:   str
It may also return ``client_user_agent`` etc.; extra keys are ignored.
"""


class _Completions:
    def __init__(self, adapter: "OpenAIResponsesAdapter"):
        self._adapter = adapter

    async def create(self, **kwargs) -> Any:
        model = kwargs.pop("model", "")
        messages = kwargs.pop("messages", [])
        tools = kwargs.pop("tools", None)
        tool_choice = kwargs.pop("tool_choice", None)
        stream = kwargs.pop("stream", False)
        # stream_options is a Chat Completions concept; Responses always
        # includes usage in the `response.completed` event when streaming.
        kwargs.pop("stream_options", None)
        kwargs.pop("response_format", None)  # unsupported — drop silently

        body = _build_request_body(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
            extra=kwargs,
        )

        tokens = await self._adapter._tokens_source()
        headers = self._adapter._build_headers(tokens)
        url = f"{self._adapter._base_url.rstrip('/')}/responses"

        client = self._adapter._http_client

        if stream:
            return await _ResponsesStreamAdapter.create(client, url, headers, body, model)

        try:
            resp = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise openai.APITimeoutError(request=getattr(exc, "request", None)) from exc  # type: ignore[arg-type]
        except httpx.RequestError as exc:
            raise openai.APIConnectionError(message=str(exc), request=getattr(exc, "request", None)) from exc  # type: ignore[arg-type]

        if not resp.is_success:
            try:
                err_body = resp.json()
            except (json.JSONDecodeError, ValueError):
                err_body = resp.text
            _log_error_body(body, resp.status_code, err_body)
        _raise_for_httpx(resp)
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise openai.APIStatusError(
                message=f"Non-JSON response from Responses API: {resp.text[:500]}",
                response=resp, body=resp.text,
            ) from exc
        return _response_to_completion(data)


class _Chat:
    def __init__(self, adapter: "OpenAIResponsesAdapter"):
        self.completions = _Completions(adapter)


class OpenAIResponsesAdapter:
    """Drop-in replacement for ``AsyncOpenAI`` that talks to the Codex Responses API.

    Parameters
    ----------
    tokens_source : TokensSource
        Awaitable returning ``{access_token, account_id, ...}``. Called on
        every ``chat.completions.create`` so callers can handle refresh /
        rotation outside the adapter.
    base_url : str, optional
        Defaults to ``https://chatgpt.com/backend-api/codex``.
    timeout : float, optional
        Per-request timeout seconds.
    session_id : str, optional
        Overrides the generated per-adapter session UUID.
    """

    def __init__(
        self,
        *,
        tokens_source: TokensSource,
        base_url: str | None = None,
        timeout: float = 120.0,
        session_id: str | None = None,
    ):
        self._tokens_source = tokens_source
        self._base_url = base_url or DEFAULT_CODEX_BASE_URL
        self._timeout = timeout
        self._session_id = session_id or str(uuid.uuid4())
        self._http_client = httpx.AsyncClient(timeout=timeout)
        self.chat = _Chat(self)
        # Attributes that llm.py logs.
        self.api_key = ""
        self.base_url = self._base_url

    def _build_headers(self, tokens: dict) -> dict:
        access_token = tokens.get("access_token", "")
        account_id = tokens.get("account_id", "")
        if not access_token:
            # Surface as an auth error so the retry/fallback chain handles it.
            raise openai.AuthenticationError(
                message="OpenAI subscription provider has no access_token — reconnect via the admin UI.",
                response=httpx.Response(401, request=httpx.Request("POST", self._base_url)),
                body=None,
            )
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
            "User-Agent": _CODEX_USER_AGENT,
            "OpenAI-Beta": _OPENAI_BETA_HEADER_VALUE,
            "originator": _ORIGINATOR_HEADER_VALUE,
            "session_id": self._session_id,
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id
        return headers

    @property
    def models(self):
        raise NotImplementedError("Use the driver's list_models() for OpenAI-subscription providers")

    async def aclose(self) -> None:
        await self._http_client.aclose()
