"""OpenAI-compatible adapter wrapping the Anthropic SDK.

Provides an ``AnthropicOpenAIAdapter`` that exposes
``client.chat.completions.create(**kwargs)`` — the same interface as
``openai.AsyncOpenAI`` — but internally translates to/from the Anthropic
Messages API using ``anthropic.AsyncAnthropic``.

This lets ``llm.py`` treat Anthropic and Anthropic-compatible providers
(MiniMax, etc.) exactly the same as OpenAI providers, with zero changes
to the agent loop.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import anthropic
import openai

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception translation: Anthropic → OpenAI
# ---------------------------------------------------------------------------
# llm.py catches openai.* exceptions for retry/fallback.  The adapter must
# translate Anthropic SDK exceptions so the retry logic works transparently.

def _translate_exception(exc: Exception) -> Exception:
    """Translate an Anthropic SDK exception to the corresponding openai exception.

    Both SDKs use httpx under the hood, so response/request objects are compatible.
    """
    msg = str(exc)

    # HTTP status errors (have a response object)
    if isinstance(exc, anthropic.APIStatusError):
        resp = exc.response
        body = getattr(exc, "body", None)
        if isinstance(exc, anthropic.BadRequestError):
            return openai.BadRequestError(message=msg, response=resp, body=body)
        if isinstance(exc, anthropic.AuthenticationError):
            return openai.AuthenticationError(message=msg, response=resp, body=body)
        if isinstance(exc, anthropic.PermissionDeniedError):
            return openai.PermissionDeniedError(message=msg, response=resp, body=body)
        if isinstance(exc, anthropic.NotFoundError):
            return openai.NotFoundError(message=msg, response=resp, body=body)
        if isinstance(exc, anthropic.RateLimitError):
            return openai.RateLimitError(message=msg, response=resp, body=body)
        if isinstance(exc, anthropic.InternalServerError):
            return openai.InternalServerError(message=msg, response=resp, body=body)
        # Generic status error → map by status code
        status = exc.status_code
        if status == 429:
            return openai.RateLimitError(message=msg, response=resp, body=body)
        if status >= 500:
            return openai.InternalServerError(message=msg, response=resp, body=body)
        return openai.APIStatusError(message=msg, response=resp, body=body)

    # Connection-level errors (no response)
    if isinstance(exc, anthropic.APITimeoutError):
        return openai.APITimeoutError(request=getattr(exc, "request", None))  # type: ignore[arg-type]
    if isinstance(exc, anthropic.APIConnectionError):
        return openai.APIConnectionError(message=msg, request=getattr(exc, "request", None))  # type: ignore[arg-type]

    # Unknown anthropic error — return as-is
    return exc

# Default max_tokens when the caller doesn't specify one (Anthropic requires it)
_DEFAULT_MAX_TOKENS = 16384


# ---------------------------------------------------------------------------
# Lightweight dataclass shims that look like openai response objects
# ---------------------------------------------------------------------------

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
    message: Any = None  # used in non-streaming


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
    """Mimics openai.types.chat.ChatCompletionChunk."""
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
    """Mimics openai.types.chat.ChatCompletion."""
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[_Choice] = field(default_factory=list)
    usage: _Usage | None = None


# ---------------------------------------------------------------------------
# Message translation: OpenAI → Anthropic
# ---------------------------------------------------------------------------

def _translate_messages(messages: list[dict]) -> tuple[str | list[dict], list[dict]]:
    """Convert OpenAI-format messages to Anthropic-format.

    Returns (system, anthropic_messages) where system is either a plain
    string or a list of content blocks (for cache_control support).
    """
    system_parts: list[dict | str] = []
    anthropic_msgs: list[dict] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role == "system":
            # Support content-block format (cache_control breakpoints)
            if isinstance(content, list):
                system_parts.extend(content)
            elif content:
                system_parts.append({"type": "text", "text": content})

        elif role == "user":
            anthropic_msgs.append({"role": "user", "content": _translate_content(content)})

        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                # Assistant message with tool_calls → content blocks
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in tool_calls:
                    func = tc.get("function", {})
                    args_raw = func.get("arguments", "{}")
                    try:
                        input_obj = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    except (json.JSONDecodeError, TypeError):
                        input_obj = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func.get("name", ""),
                        "input": input_obj,
                    })
                anthropic_msgs.append({"role": "assistant", "content": blocks})
            else:
                anthropic_msgs.append({"role": "assistant", "content": _translate_content(content)})

        elif role == "tool":
            # Tool results → user message with tool_result content block
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": str(content) if content is not None else "",
            }
            # Merge into preceding user message if possible, else create new
            if anthropic_msgs and anthropic_msgs[-1]["role"] == "user":
                prev_content = anthropic_msgs[-1]["content"]
                if isinstance(prev_content, list):
                    prev_content.append(tool_result_block)
                else:
                    anthropic_msgs[-1]["content"] = [
                        {"type": "text", "text": str(prev_content)} if prev_content else {"type": "text", "text": ""},
                        tool_result_block,
                    ]
            else:
                anthropic_msgs.append({
                    "role": "user",
                    "content": [tool_result_block],
                })

    # Collapse system_parts
    if not system_parts:
        system: str | list[dict] = ""
    elif len(system_parts) == 1 and isinstance(system_parts[0], dict) and "cache_control" not in system_parts[0]:
        system = system_parts[0].get("text", "")
    else:
        # Keep as list of content blocks (preserves cache_control)
        system = system_parts  # type: ignore[assignment]

    # Anthropic requires alternating user/assistant.  Merge consecutive same-role.
    anthropic_msgs = _merge_consecutive_roles(anthropic_msgs)

    return system, anthropic_msgs


def _translate_content(content: Any) -> str | list[dict]:
    """Normalize content to string or content-block list."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return content
    return str(content)


def _merge_consecutive_roles(messages: list[dict]) -> list[dict]:
    """Merge consecutive messages with the same role (Anthropic requires alternation)."""
    if not messages:
        return messages
    merged: list[dict] = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == merged[-1]["role"]:
            # Merge content
            prev = merged[-1]["content"]
            curr = msg["content"]
            if isinstance(prev, str) and isinstance(curr, str):
                merged[-1]["content"] = prev + "\n" + curr
            else:
                prev_blocks = prev if isinstance(prev, list) else [{"type": "text", "text": prev}]
                curr_blocks = curr if isinstance(curr, list) else [{"type": "text", "text": curr}]
                merged[-1]["content"] = prev_blocks + curr_blocks
        else:
            merged.append(msg)
    return merged


# ---------------------------------------------------------------------------
# Tool translation: OpenAI → Anthropic
# ---------------------------------------------------------------------------

def _translate_tools(tools: list[dict] | None) -> list[dict] | None:
    """Convert OpenAI function-calling tool defs to Anthropic tool format."""
    if not tools:
        return None
    result = []
    for tool in tools:
        if tool.get("type") == "function":
            func = tool["function"]
            result.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        else:
            # Pass through non-function tools (shouldn't happen but be safe)
            result.append(tool)
    return result or None


def _translate_tool_choice(tool_choice: str | dict | None) -> dict | None:
    """Convert OpenAI tool_choice to Anthropic format."""
    if tool_choice is None or tool_choice == "auto":
        return {"type": "auto"}
    if tool_choice == "required":
        return {"type": "any"}
    if tool_choice == "none":
        return None  # Anthropic: omit tool_choice + tools to disable
    if isinstance(tool_choice, dict):
        # OpenAI: {"type": "function", "function": {"name": "..."}}
        func = tool_choice.get("function", {})
        name = func.get("name")
        if name:
            return {"type": "tool", "name": name}
    return {"type": "auto"}


# ---------------------------------------------------------------------------
# Response translation: Anthropic → OpenAI shims
# ---------------------------------------------------------------------------

def _translate_stop_reason(stop_reason: str | None) -> str:
    """Map Anthropic stop_reason to OpenAI finish_reason."""
    mapping = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
    }
    return mapping.get(stop_reason or "", "stop")


def _build_usage(anthropic_usage: Any) -> _Usage:
    """Build an OpenAI-compatible Usage from Anthropic usage."""
    input_tokens = getattr(anthropic_usage, "input_tokens", 0) or 0
    output_tokens = getattr(anthropic_usage, "output_tokens", 0) or 0
    cache_read = getattr(anthropic_usage, "cache_read_input_tokens", 0) or 0
    return _Usage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        prompt_tokens_details=_PromptTokensDetails(cached_tokens=cache_read),
    )


def _message_to_completion(msg: anthropic.types.Message) -> _ChatCompletion:
    """Wrap an Anthropic Message in an OpenAI-shaped ChatCompletion."""
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[_ToolCall] = []
    idx = 0
    for block in msg.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "thinking":
            thinking_parts.append(getattr(block, "thinking", ""))
        elif block.type == "tool_use":
            tool_calls.append(_ToolCall(
                id=block.id,
                type="function",
                function=_Function(name=block.name, arguments=json.dumps(block.input)),
                index=idx,
            ))
            idx += 1

    content_str = "\n".join(text_parts) if text_parts else None
    # Wrap thinking in <think> tags so ThinkTagParser / strip_think_tags can handle it
    if thinking_parts:
        thinking_str = "\n".join(thinking_parts)
        content_str = f"<think>{thinking_str}</think>{content_str or ''}" or None
    message = _Message(
        role="assistant",
        content=content_str,
        tool_calls=tool_calls if tool_calls else None,
    )

    return _ChatCompletion(
        id=msg.id,
        model=msg.model,
        created=int(time.time()),
        choices=[_Choice(index=0, message=message, finish_reason=_translate_stop_reason(msg.stop_reason))],
        usage=_build_usage(msg.usage),
    )


# ---------------------------------------------------------------------------
# Streaming translation
# ---------------------------------------------------------------------------

class _StreamAdapter:
    """Wraps an Anthropic async stream, yielding OpenAI-shaped chunks.

    Acts as both an async iterable AND an async iterator so that
    ``_consume_stream`` can call ``stream.__anext__()`` directly after
    the ``async for`` loop exits (to drain usage-only chunks).

    The stream is eagerly connected via ``create()`` so that HTTP errors
    (auth, rate-limit, etc.) surface at the same point as the OpenAI SDK
    — inside ``_try_model()`` where the retry loop can catch them.
    """

    def __init__(self, stream_ctx: Any, raw_manager: Any, model: str):
        self._stream_ctx = stream_ctx  # entered context — the event stream
        self._raw_manager = raw_manager  # context manager for cleanup
        self._model = model
        self._message_id = ""
        self._tool_index = -1  # current tool_use block index
        self._tool_id = ""
        self._tool_name = ""
        self._input_json_buf = ""  # accumulated JSON for current tool
        self._inner_iter: AsyncIterator[_ChatCompletionChunk] | None = None
        self._start_usage: _Usage | None = None  # usage from message_start (input tokens)

    @classmethod
    async def create(cls, stream_manager: Any, model: str) -> _StreamAdapter:
        """Create a stream adapter, eagerly connecting to surface HTTP errors."""
        stream_ctx = await stream_manager.__aenter__()
        return cls(stream_ctx, stream_manager, model)

    def __aiter__(self):
        if self._inner_iter is None:
            self._inner_iter = self._iterate()
        return self

    async def __anext__(self) -> _ChatCompletionChunk:
        if self._inner_iter is None:
            self._inner_iter = self._iterate()
        try:
            return await self._inner_iter.__anext__()
        except StopAsyncIteration:
            raise
        except anthropic.APIError as exc:
            raise _translate_exception(exc) from exc

    async def _iterate(self) -> AsyncIterator[_ChatCompletionChunk]:
        try:
            async for event in self._stream_ctx:
                chunks = self._translate_event(event)
                for chunk in chunks:
                    yield chunk
        except anthropic.APIError as exc:
            raise _translate_exception(exc) from exc
        finally:
            await self._raw_manager.__aexit__(None, None, None)

    def _make_chunk(
        self,
        delta: _ChoiceDelta | None = None,
        finish_reason: str | None = None,
        usage: _Usage | None = None,
    ) -> _ChatCompletionChunk:
        choices = []
        if delta is not None or finish_reason is not None:
            choices.append(_Choice(
                index=0,
                delta=delta or _ChoiceDelta(),
                finish_reason=finish_reason,
            ))
        return _ChatCompletionChunk(
            id=self._message_id,
            model=self._model,
            created=int(time.time()),
            choices=choices,
            usage=usage,
        )

    def _translate_event(self, event: Any) -> list[_ChatCompletionChunk]:
        chunks: list[_ChatCompletionChunk] = []
        event_type = event.type

        if event_type == "message_start":
            self._message_id = event.message.id
            if event.message.usage:
                self._start_usage = _build_usage(event.message.usage)
            # Emit a role chunk + initial usage (has input tokens, 0 output)
            chunks.append(self._make_chunk(
                delta=_ChoiceDelta(role="assistant"),
                usage=self._start_usage,
            ))

        elif event_type == "content_block_start":
            block = event.content_block
            if block.type == "tool_use":
                self._tool_index += 1
                self._tool_id = block.id
                self._tool_name = block.name
                self._input_json_buf = ""
                # Emit tool_call start with name + id
                chunks.append(self._make_chunk(
                    delta=_ChoiceDelta(tool_calls=[_ToolCall(
                        id=block.id,
                        type="function",
                        function=_Function(name=block.name, arguments=""),
                        index=self._tool_index,
                    )]),
                ))

        elif event_type == "content_block_delta":
            delta_block = event.delta
            if delta_block.type == "text_delta":
                chunks.append(self._make_chunk(
                    delta=_ChoiceDelta(content=delta_block.text),
                ))
            elif delta_block.type == "input_json_delta":
                self._input_json_buf += delta_block.partial_json
                # Stream arguments incrementally
                chunks.append(self._make_chunk(
                    delta=_ChoiceDelta(tool_calls=[_ToolCall(
                        id="",
                        type="function",
                        function=_Function(name="", arguments=delta_block.partial_json),
                        index=self._tool_index,
                    )]),
                ))
            elif delta_block.type == "thinking_delta":
                # Map to reasoning_content on the delta — StreamAccumulator
                # picks this up via getattr(delta, "reasoning_content", None).
                thinking_text = getattr(delta_block, "thinking", None) or ""
                if thinking_text:
                    chunks.append(self._make_chunk(
                        delta=_ChoiceDelta(reasoning_content=thinking_text),
                    ))

        elif event_type == "content_block_stop":
            pass  # No direct mapping needed

        elif event_type == "message_delta":
            finish = _translate_stop_reason(event.delta.stop_reason)
            # Merge usage: message_start has input tokens, message_delta has output tokens.
            # Anthropic's MessageDeltaUsage only carries output_tokens; input/cache tokens
            # come from message_start.  Build combined usage so StreamAccumulator gets
            # the correct totals.
            usage = None
            if event.usage:
                delta_output = getattr(event.usage, "output_tokens", 0) or 0
                if self._start_usage:
                    usage = _Usage(
                        prompt_tokens=self._start_usage.prompt_tokens,
                        completion_tokens=delta_output,
                        total_tokens=self._start_usage.prompt_tokens + delta_output,
                        prompt_tokens_details=self._start_usage.prompt_tokens_details,
                    )
                else:
                    usage = _build_usage(event.usage)
            chunks.append(self._make_chunk(finish_reason=finish, usage=usage))

        elif event_type == "message_stop":
            pass  # Final event — no output needed

        return chunks


# ---------------------------------------------------------------------------
# The adapter: looks like AsyncOpenAI to callers
# ---------------------------------------------------------------------------

class _Completions:
    """Namespace that provides ``create()`` matching ``client.chat.completions.create()``."""

    def __init__(self, client: anthropic.AsyncAnthropic):
        self._client = client

    async def create(self, **kwargs) -> Any:
        """Translate an OpenAI-style chat completions call to Anthropic Messages API."""
        model = kwargs.get("model", "")
        messages = kwargs.get("messages", [])
        tools = kwargs.get("tools")
        tool_choice = kwargs.get("tool_choice")
        stream = kwargs.get("stream", False)
        max_tokens = kwargs.get("max_tokens") or _DEFAULT_MAX_TOKENS

        # Translate
        system, anthropic_messages = _translate_messages(messages)
        anthropic_tools = _translate_tools(tools)

        # Build Anthropic kwargs
        api_kwargs: dict[str, Any] = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": max_tokens,
        }

        if system:
            api_kwargs["system"] = system

        # Only send tools if tool_choice is not "none"
        tc = _translate_tool_choice(tool_choice) if anthropic_tools else None
        if anthropic_tools and tc is not None:
            api_kwargs["tools"] = anthropic_tools
            api_kwargs["tool_choice"] = tc

        # Pass through simple params (translate stop → stop_sequences)
        for param in ("temperature", "top_p", "top_k"):
            if param in kwargs and kwargs[param] is not None:
                api_kwargs[param] = kwargs[param]
        if "stop" in kwargs and kwargs["stop"] is not None:
            stop = kwargs["stop"]
            api_kwargs["stop_sequences"] = [stop] if isinstance(stop, str) else stop

        try:
            if stream:
                # Eagerly connect so HTTP errors surface here (where retry logic catches them)
                raw_stream = self._client.messages.stream(**api_kwargs)
                return await _StreamAdapter.create(raw_stream, model)
            else:
                response = await self._client.messages.create(**api_kwargs)
                return _message_to_completion(response)
        except anthropic.APIError as exc:
            raise _translate_exception(exc) from exc


class _Chat:
    """Namespace that provides ``chat.completions``."""

    def __init__(self, client: anthropic.AsyncAnthropic):
        self.completions = _Completions(client)


class AnthropicOpenAIAdapter:
    """Drop-in replacement for ``AsyncOpenAI`` that uses the Anthropic SDK internally.

    Usage::

        adapter = AnthropicOpenAIAdapter(api_key="sk-...", base_url="https://api.anthropic.com")
        # Works exactly like AsyncOpenAI:
        response = await adapter.chat.completions.create(model="claude-...", messages=[...], stream=True)
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 0,
    ):
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "max_retries": max_retries,
            "timeout": timeout,
        }
        if base_url:
            # Anthropic SDK expects base_url without /v1 suffix
            clean_url = base_url.rstrip("/")
            if clean_url.endswith("/v1"):
                clean_url = clean_url[:-3]
            client_kwargs["base_url"] = clean_url

        self._anthropic = anthropic.AsyncAnthropic(**client_kwargs)
        self.chat = _Chat(self._anthropic)

        # Expose some attributes that llm.py might log
        self.api_key = api_key
        self.base_url = base_url or "https://api.anthropic.com"

    @property
    def models(self):
        """Stub: Anthropic SDK model listing (not supported in same way as OpenAI)."""
        raise NotImplementedError("Use the driver's list_models() instead")
