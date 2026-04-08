"""LLM call infrastructure — retry/backoff, model fallback, and tool result summarization."""

import asyncio
import json
import logging
import random
import re
import uuid
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import openai

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Think-tag handling
# ---------------------------------------------------------------------------
# Models like DeepSeek/Qwen embed reasoning in <think>...</think> inside
# delta.content instead of using the reasoning_content attribute.  The parser
# below splits streaming text into content vs. thinking on-the-fly.

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


class ThinkTagParser:
    """Streaming state machine that separates <think> blocks from content."""

    def __init__(self):
        self._in_think: bool = False
        self._buffer: str = ""  # held-back chars that might be a partial tag

    def feed(self, text: str) -> tuple[str, str]:
        """Process a chunk of text.  Returns (content_text, thinking_text)."""
        self._buffer += text
        content_out: list[str] = []
        thinking_out: list[str] = []

        while self._buffer:
            if self._in_think:
                idx = self._buffer.find(_THINK_CLOSE)
                if idx != -1:
                    # Emit everything before the close tag as thinking
                    thinking_out.append(self._buffer[:idx])
                    self._buffer = self._buffer[idx + len(_THINK_CLOSE):]
                    self._in_think = False
                else:
                    # Check if the buffer ends with a potential partial close tag
                    safe, held = self._split_at_potential_tag(self._buffer, _THINK_CLOSE)
                    if safe:
                        thinking_out.append(safe)
                    self._buffer = held
                    break
            else:
                idx = self._buffer.find(_THINK_OPEN)
                if idx != -1:
                    # Emit everything before the open tag as content
                    content_out.append(self._buffer[:idx])
                    self._buffer = self._buffer[idx + len(_THINK_OPEN):]
                    self._in_think = True
                else:
                    # Check if the buffer ends with a potential partial open tag
                    safe, held = self._split_at_potential_tag(self._buffer, _THINK_OPEN)
                    if safe:
                        content_out.append(safe)
                    self._buffer = held
                    break

        return "".join(content_out), "".join(thinking_out)

    def flush(self) -> tuple[str, str]:
        """Emit any remaining buffered text (call at end of stream)."""
        remaining = self._buffer
        self._buffer = ""
        if self._in_think:
            return "", remaining
        return remaining, ""

    @staticmethod
    def _split_at_potential_tag(text: str, tag: str) -> tuple[str, str]:
        """Split text into (safe_to_emit, held_back) based on partial tag match.

        If the end of *text* is a prefix of *tag*, hold it back.
        E.g. text="hello<th", tag="<think>" → ("hello", "<th")
        """
        # Check progressively shorter suffixes of text against prefixes of tag
        max_check = min(len(tag) - 1, len(text))
        for length in range(max_check, 0, -1):
            if text[-length:] == tag[:length]:
                return text[:-length], text[-length:]
        return text, ""


class ToolCallXmlFilter:
    """Streaming filter that suppresses XML tool-call fragments from text.

    Some providers (e.g. MiniMax via Anthropic-compatible API) emit tool calls
    as XML text (``<invoke name="...">...</invoke>``, ``</minimax:tool_call>``)
    alongside proper tool_use blocks.  This filter buffers potential XML tag
    openings and suppresses them if they match known tool-call patterns.
    """

    # Tag names (after '<' or '</') that signal tool-call XML.
    _TOOL_PREFIXES = ("invoke", "tool_call", "/invoke", "/tool_call")
    # Namespace-prefixed patterns (e.g. <minimax:tool_call>, </minimax:tool_call>)
    _NS_PREFIXES = ("/",)  # after '<', check for namespaced close tags too

    def __init__(self):
        self._buffer: str = ""
        self._suppressing: bool = False

    def feed(self, text: str) -> str:
        """Process a chunk, returning text safe to emit."""
        self._buffer += text
        output: list[str] = []

        while self._buffer:
            if self._suppressing:
                # Inside a tool-call XML block — consume until end of tag/block
                gt = self._buffer.find(">")
                if gt == -1:
                    break  # need more data
                # Check if this close '>' ends the suppression region.
                # We suppress everything between the opening '<' and the final '>'.
                # For multi-line blocks like <invoke ...>...</invoke>, we keep
                # suppressing until we see '</invoke>' or '</...tool_call>'.
                consumed = self._buffer[:gt + 1]
                self._buffer = self._buffer[gt + 1:]
                # If we just consumed a closing tag, stop suppressing
                if consumed.lstrip().startswith("</"):
                    self._suppressing = False
                # If it's a self-closing tag (/>), stop suppressing
                elif consumed.rstrip().endswith("/>"):
                    self._suppressing = False
                # Otherwise (opening tag like <invoke ...>), keep suppressing
                # for the content + closing tag
            else:
                lt = self._buffer.find("<")
                if lt == -1:
                    output.append(self._buffer)
                    self._buffer = ""
                    break

                # Emit everything before the '<'
                if lt > 0:
                    output.append(self._buffer[:lt])
                    self._buffer = self._buffer[lt:]

                # Now self._buffer starts with '<'
                rest = self._buffer[1:]

                # Need at least a few chars to identify the tag
                if len(rest) < 2:
                    break  # hold back, need more data

                # Check if this looks like a tool-call tag
                is_tool_xml = False
                maybe_tool_xml = False  # partial match, need more data

                # Direct tag match: <invoke, </invoke, <tool_call, etc.
                for prefix in self._TOOL_PREFIXES:
                    if rest.startswith(prefix):
                        is_tool_xml = True
                        break
                    if prefix.startswith(rest[:len(prefix)]) and len(rest) < len(prefix):
                        maybe_tool_xml = True

                # Namespace match: <word:tool_call or </word:tool_call
                if not is_tool_xml and not maybe_tool_xml:
                    # Check for </ns:tool_call> or <ns:tool_call>
                    check = rest.lstrip("/")
                    colon = check.find(":")
                    if colon > 0 and colon < 20:
                        after_colon = check[colon + 1:]
                        if after_colon.startswith("tool_call"):
                            is_tool_xml = True
                        elif "tool_call".startswith(after_colon) and len(after_colon) < len("tool_call"):
                            maybe_tool_xml = True
                    elif colon == -1 and check.isalpha() and len(check) < 20:
                        # Could be start of "ns:" — need more data
                        maybe_tool_xml = True

                if is_tool_xml:
                    self._suppressing = True
                    # Don't emit the '<'; loop will handle suppression
                    continue
                elif maybe_tool_xml:
                    break  # hold buffer, need more data
                else:
                    # Not a tool-call tag — emit the '<' and continue
                    output.append("<")
                    self._buffer = self._buffer[1:]

        return "".join(output)

    def flush(self) -> str:
        """Emit remaining buffer at end of stream."""
        if self._suppressing:
            self._buffer = ""
            return ""
        remaining = self._buffer
        self._buffer = ""
        return remaining


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from text (for non-streaming paths)."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)


def strip_silent_tags(text: str) -> str:
    """Remove [silent]...[/silent] blocks from text.

    Some models (Gemma, roleplay fine-tunes) emit inner-monologue text wrapped
    in [silent] tags.  This is not useful to end users — strip entirely.

    Also strips unpaired [silent] tags (e.g. model opened but never closed)
    and any orphaned [/silent] close tags.
    """
    # Strip paired tags first
    cleaned = re.sub(r"\[silent\].*?\[/silent\]", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Strip unclosed [silent] — everything from [silent] to end of text
    cleaned = re.sub(r"\[silent\].*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    # Strip orphaned [/silent] tags
    cleaned = re.sub(r"\[/silent\]", "", cleaned, flags=re.IGNORECASE)
    return cleaned


# Pattern to match XML-style tool calls that models sometimes emit as plain text
# instead of using the proper OpenAI tool_calls format.  Covers:
#   <invoke name="...">...</invoke>
#   </minimax:tool_call>   (trailing close tag)
#   <tool_call>...</tool_call>
_MALFORMED_TOOL_CALL_RE = re.compile(
    r"<invoke\b[^>]*>.*?</invoke>"       # <invoke …>…</invoke>
    r"|</?\w+:tool_call\b[^>]*>"         # <minimax:tool_call> or </minimax:tool_call>
    r"|<tool_call\b[^>]*>.*?</tool_call>"  # <tool_call>…</tool_call>
    , re.DOTALL,
)


def strip_malformed_tool_calls(text: str) -> str:
    """Strip tool-call fragments (XML or JSON) some models emit as plain text.

    When a model fails to use the OpenAI function-calling format and instead
    returns tool invocations as XML or JSON in text content, this strips them
    so they don't leak into user-facing messages.
    """
    cleaned = _MALFORMED_TOOL_CALL_RE.sub("", text)
    # Also strip JSON objects that look like tool call attempts:
    # {"name": "...", "arguments": ...}
    cleaned = _strip_json_tool_call_fragments(cleaned)
    return cleaned.strip()


def _strip_json_tool_call_fragments(text: str) -> str:
    """Strip JSON objects from text that look like tool call attempts.

    Models sometimes emit {"name": "...", "arguments": {...}} as text
    alongside (or instead of) proper function-calling format. These are
    never useful user-facing content.
    """
    candidates = _find_top_level_json_objects(text)
    if not candidates:
        return text
    # Strip in reverse to preserve indices
    for start, end, obj in reversed(candidates):
        if (
            isinstance(obj.get("name"), str)
            and "arguments" in obj
        ):
            text = text[:start] + text[end:]
    return text


# ---------------------------------------------------------------------------
# JSON tool-call extraction (local model compat)
# ---------------------------------------------------------------------------
# Local models (e.g. Qwen, DeepSeek via Ollama/LiteLLM) sometimes output
# tool calls as raw JSON text instead of using the OpenAI function-calling
# wire format.  This extracts and parses them so they can be dispatched.

# Matches fenced code blocks: ```json ... ``` or ``` ... ```
_CODE_BLOCK_RE = re.compile(r"```(?:\w+)?\s*\n.*?\n\s*```", re.DOTALL)


def _find_top_level_json_objects(text: str) -> list[tuple[int, int, Any]]:
    """Find top-level JSON objects in *text* using brace counting.

    Returns list of (start, end, parsed_obj) tuples.
    Only returns objects (dicts), not arrays or scalars.
    """
    results: list[tuple[int, int, Any]] = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            in_string = False
            escape_next = False
            j = i
            while j < len(text):
                ch = text[j]
                if escape_next:
                    escape_next = False
                elif ch == "\\":
                    if in_string:
                        escape_next = True
                elif ch == '"':
                    in_string = not in_string
                elif not in_string:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = text[i:j + 1]
                            try:
                                obj = json.loads(candidate)
                                if isinstance(obj, dict):
                                    results.append((i, j + 1, obj))
                            except (json.JSONDecodeError, ValueError):
                                pass
                            break
                j += 1
            i = j + 1 if depth == 0 else j + 1
        else:
            i += 1
    return results


def extract_json_tool_calls(
    text: str, known_tool_names: set[str]
) -> tuple[list[dict], str]:
    """Extract JSON-formatted tool calls from text content.

    Local models sometimes emit tool calls as raw JSON like:
        {"name": "tool_name", "arguments": {...}}

    This finds such objects, validates them against *known_tool_names*,
    and returns synthesized tool-call dicts matching the OpenAI format
    plus the remaining text with JSON stripped out.

    Returns (tool_calls, remaining_text). tool_calls is empty if none found.
    """
    if not text or not known_tool_names:
        return [], text

    # Identify code-block regions to skip (avoid false positives from examples)
    skip_ranges: list[tuple[int, int]] = []
    for m in _CODE_BLOCK_RE.finditer(text):
        skip_ranges.append((m.start(), m.end()))

    def _in_code_block(start: int, end: int) -> bool:
        for sr_start, sr_end in skip_ranges:
            if start >= sr_start and end <= sr_end:
                return True
        return False

    candidates = _find_top_level_json_objects(text)

    tool_calls: list[dict] = []
    # Track regions to strip (in reverse order later)
    strip_ranges: list[tuple[int, int]] = []

    for start, end, obj in candidates:
        if _in_code_block(start, end):
            continue

        name = obj.get("name")
        if not isinstance(name, str) or name not in known_tool_names:
            continue

        arguments = obj.get("arguments")
        if arguments is None:
            continue

        # Normalize arguments to JSON string
        if isinstance(arguments, dict):
            args_str = json.dumps(arguments)
        elif isinstance(arguments, str):
            args_str = arguments
        else:
            args_str = json.dumps(arguments)

        tool_calls.append({
            "id": f"json-tc-{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": args_str,
            },
        })
        strip_ranges.append((start, end))

    if not tool_calls:
        return [], text

    # Strip extracted JSON from text (process in reverse to preserve indices)
    remaining = text
    for start, end in reversed(sorted(strip_ranges)):
        remaining = remaining[:start] + remaining[end:]

    # Clean up whitespace artifacts
    remaining = re.sub(r"\n{3,}", "\n\n", remaining).strip()

    return tool_calls, remaining


@dataclass
class FallbackInfo:
    """Metadata about a fallback that occurred during _llm_call."""
    original_model: str
    fallback_model: str
    reason: str  # e.g. "EmptyChoicesError" or "RateLimitError"
    original_error: str  # truncated error message


# Set by _llm_call when a fallback is used; cleared before each call.
# The loop reads this after _llm_call returns to emit trace events.
last_fallback_info: ContextVar[FallbackInfo | None] = ContextVar("last_fallback_info", default=None)


# ---------------------------------------------------------------------------
# Circuit breaker — skip models that recently failed and needed fallback
# ---------------------------------------------------------------------------
# model -> (expires_at, fallback_model, fallback_provider_id)
_model_cooldowns: dict[str, tuple[datetime, str, str | None]] = {}


def set_model_cooldown(model: str, fallback_model: str, provider_id: str | None = None) -> None:
    """Record that *model* failed and *fallback_model* should be used until cooldown expires."""
    cooldown_sec = settings.LLM_FALLBACK_COOLDOWN_SECONDS
    if cooldown_sec <= 0:
        return
    expires = datetime.now(timezone.utc) + timedelta(seconds=cooldown_sec)
    _model_cooldowns[model] = (expires, fallback_model, provider_id)
    logger.info("Circuit breaker: %s in cooldown until %s, using %s (provider=%s)",
                model, expires.isoformat(), fallback_model, provider_id)


def get_model_cooldown(model: str) -> tuple[str, str | None] | None:
    """Return (fallback_model, provider_id) if *model* is in cooldown, else None."""
    entry = _model_cooldowns.get(model)
    if entry is None:
        return None
    expires, fallback_model, fallback_provider = entry
    if datetime.now(timezone.utc) >= expires:
        del _model_cooldowns[model]
        return None
    return (fallback_model, fallback_provider)


def get_active_cooldowns() -> list[dict]:
    """Return all active cooldowns for the admin API."""
    now = datetime.now(timezone.utc)
    active = []
    expired_keys = []
    for model, (expires, fallback_model, fallback_provider) in _model_cooldowns.items():
        if now >= expires:
            expired_keys.append(model)
        else:
            active.append({
                "model": model,
                "fallback_model": fallback_model,
                "fallback_provider": fallback_provider,
                "expires_at": expires.isoformat(),
                "remaining_seconds": int((expires - now).total_seconds()),
            })
    for k in expired_keys:
        del _model_cooldowns[k]
    return active


def get_cooldown_expiry(model: str) -> datetime | None:
    """Return the cooldown expiry time for *model*, or None if not in cooldown."""
    entry = _model_cooldowns.get(model)
    if entry is None:
        return None
    expires, _, _ = entry
    if datetime.now(timezone.utc) >= expires:
        del _model_cooldowns[model]
        return None
    return expires


def clear_model_cooldown(model: str) -> bool:
    """Manually clear a model cooldown. Returns True if it was found."""
    return _model_cooldowns.pop(model, None) is not None


class EmptyChoicesError(Exception):
    """Raised when the LLM returns a response with an empty choices list."""
    pass


# All transient error types worth retrying.
_RETRYABLE_ERRORS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
    EmptyChoicesError,
)

# Errors that should trigger fallback chain.  Includes _RETRYABLE_ERRORS plus
# BadRequestError — the only way a BadRequestError escapes _retry_single_model
# is from a tools-not-supported retry failure, which should try fallbacks.
_FALLBACK_TRIGGER_ERRORS = (*_RETRYABLE_ERRORS, openai.BadRequestError)


# ---------------------------------------------------------------------------
# Shared retry engine
# ---------------------------------------------------------------------------

def _compute_backoff(base: float, attempt: int, cap: float = 300.0) -> float:
    """Truncated jitter exponential backoff with a floor at 50% of base.

    Prevents near-zero waits that would waste a retry attempt on rate limits.
    """
    upper = min(cap, base * (2 ** attempt))
    floor = base * 0.5
    return max(floor, random.uniform(0, upper))


@dataclass
class _ErrorClassification:
    """Result of classifying an LLM exception."""
    retryable: bool = False
    base_wait: float = 2.0
    skip_to_fallback: bool = False
    retry_without_tools: bool = False
    retry_without_images: bool = False


def _classify_error(exc: Exception, has_tools: bool) -> _ErrorClassification:
    """Centralized error classification for retry decisions."""
    if isinstance(exc, openai.BadRequestError):
        if _is_tools_not_supported_error(exc) and has_tools:
            return _ErrorClassification(retry_without_tools=True)
        if _is_vision_not_supported_error(exc):
            return _ErrorClassification(retry_without_images=True)
        return _ErrorClassification()  # not retryable, propagate

    if isinstance(exc, openai.RateLimitError):
        return _ErrorClassification(retryable=True, base_wait=settings.LLM_RATE_LIMIT_INITIAL_WAIT)

    if isinstance(exc, openai.InternalServerError) and _is_non_transient_500(exc):
        return _ErrorClassification(skip_to_fallback=True)

    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError,
                        openai.InternalServerError, EmptyChoicesError)):
        return _ErrorClassification(retryable=True, base_wait=settings.LLM_RETRY_INITIAL_WAIT)

    return _ErrorClassification()  # unknown error, not retryable


async def _retry_single_model(
    attempt_fn,
    model: str,
    has_tools: bool,
    max_retries: int,
    on_event=None,
    *,
    retry_without_tools_fn=None,
    retry_without_images_fn=None,
):
    """Retry loop for a single model.  Returns result on success, raises on exhaustion.

    Parameters
    ----------
    attempt_fn : async callable
        ``async () -> result`` — makes one API call.
    model : str
        Model name (for logging / events).
    has_tools : bool
        Whether tools are in the request (affects tools-not-supported handling).
    max_retries : int
        Max additional attempts after first failure.
    on_event : callable, optional
        ``(event_dict) -> None`` — called for retry/status events.
    retry_without_tools_fn : async callable, optional
        ``async () -> result`` — called when model doesn't support tools.
    retry_without_images_fn : async callable, optional
        ``async () -> result`` — called when model doesn't support vision/images.
    """
    for attempt in range(max_retries + 1):
        try:
            return await attempt_fn()
        except Exception as exc:
            cl = _classify_error(exc, has_tools)

            if cl.retry_without_tools and retry_without_tools_fn is not None:
                if on_event:
                    on_event({"type": "llm_retry", "attempt": 1, "max_retries": 1,
                              "wait_seconds": 0, "reason": "tools_not_supported", "model": model})
                try:
                    return await retry_without_tools_fn()
                except Exception as retry_exc:
                    logger.warning("Retry without tools also failed for %s: %s", model, retry_exc)
                    raise retry_exc from exc

            if cl.retry_without_images and retry_without_images_fn is not None:
                from app.services.providers import mark_model_no_vision
                asyncio.ensure_future(mark_model_no_vision(model))
                if on_event:
                    on_event({"type": "llm_retry", "attempt": 1, "max_retries": 1,
                              "wait_seconds": 0, "reason": "vision_not_supported", "model": model})
                try:
                    return await retry_without_images_fn()
                except Exception as retry_exc:
                    logger.warning("Retry without images also failed for %s: %s", model, retry_exc)
                    raise retry_exc from exc

            if cl.skip_to_fallback:
                logger.warning("Non-transient 500 from %s, skipping retries: %s", model, str(exc)[:200])
                raise

            if not cl.retryable:
                raise

            if attempt >= max_retries:
                raise

            wait = _compute_backoff(cl.base_wait, attempt)
            reason = "rate_limited" if isinstance(exc, openai.RateLimitError) else type(exc).__name__
            logger.warning("LLM call to %s failed with %s (attempt %d/%d), waiting %.1fs...",
                           model, reason, attempt + 1, max_retries, wait)
            if on_event:
                on_event({"type": "llm_retry", "attempt": attempt + 1, "max_retries": max_retries,
                          "wait_seconds": round(wait, 1), "reason": reason, "model": model})
            await asyncio.sleep(wait)


async def _run_with_fallback_chain(
    model: str,
    provider_id: str | None,
    model_params: dict | None,
    has_tools: bool,
    fallback_models: list[dict] | None,
    make_attempt_fn,
    make_no_tools_fn,
    max_retries: int,
    on_event=None,
    make_no_images_fn=None,
):
    """Orchestrate circuit breaker + primary model + fallback chain.

    Parameters
    ----------
    make_attempt_fn : callable
        ``(model, provider_id, model_params) -> async () -> result`` — factory for attempt callables.
    make_no_tools_fn : callable
        ``(model, provider_id, model_params) -> async () -> result`` — factory for no-tools attempt.
    make_no_images_fn : callable, optional
        ``(model, provider_id, model_params) -> async () -> result`` — factory for no-images attempt.
    on_event : callable, optional
        ``(event_dict) -> None`` — called for retry/fallback events.

    Returns the LLM result (stream or response).
    """
    last_fallback_info.set(None)

    # --- Circuit breaker: skip model if in cooldown ---
    cooldown_info = get_model_cooldown(model)
    cooldown_fb = cooldown_info[0] if cooldown_info else None
    cooldown_fb_provider = cooldown_info[1] if cooldown_info else None
    primary_exc = None

    if cooldown_fb is not None:
        # Use the stored fallback provider; fall back to caller's provider_id
        effective_cd_provider = cooldown_fb_provider or provider_id
        logger.info("Circuit breaker: skipping %s (in cooldown), using %s directly", model, cooldown_fb)
        if on_event:
            on_event({"type": "llm_cooldown_skip", "model": model, "using": cooldown_fb})
        try:
            _no_img = make_no_images_fn(cooldown_fb, effective_cd_provider, model_params) if make_no_images_fn else None
            result = await _retry_single_model(
                make_attempt_fn(cooldown_fb, effective_cd_provider, model_params),
                cooldown_fb, has_tools, max_retries, on_event,
                retry_without_tools_fn=make_no_tools_fn(cooldown_fb, effective_cd_provider, model_params),
                retry_without_images_fn=_no_img,
            )
            last_fallback_info.set(FallbackInfo(
                original_model=model, fallback_model=cooldown_fb,
                reason="cooldown_skip", original_error="model in cooldown",
            ))
            return result
        except _FALLBACK_TRIGGER_ERRORS as exc:
            logger.warning("Cooldown fallback %s also failed: %s, keeping cooldown active", cooldown_fb, exc)
            primary_exc = exc

    # --- Primary model ---
    if primary_exc is None:
        try:
            _no_img = make_no_images_fn(model, provider_id, model_params) if make_no_images_fn else None
            return await _retry_single_model(
                make_attempt_fn(model, provider_id, model_params),
                model, has_tools, max_retries, on_event,
                retry_without_tools_fn=make_no_tools_fn(model, provider_id, model_params),
                retry_without_images_fn=_no_img,
            )
        except _FALLBACK_TRIGGER_ERRORS as exc:
            primary_exc = exc

    # --- Fallback chain ---
    from app.services.server_config import get_global_fallback_models

    effective_fallbacks = list(fallback_models or [])
    for gfb in get_global_fallback_models():
        effective_fallbacks.append(gfb)

    tried = {model, cooldown_fb} if cooldown_fb else {model}
    last_exc = primary_exc

    for fb in effective_fallbacks:
        fb_model = fb.get("model", "")
        if not fb_model or fb_model in tried:
            continue
        tried.add(fb_model)
        fb_provider = fb.get("provider_id") or provider_id
        logger.warning("Model %s failed (%s: %s), attempting fallback %s",
                       model, type(last_exc).__name__, last_exc, fb_model)
        if on_event:
            on_event({"type": "llm_fallback", "from_model": model, "to_model": fb_model,
                       "reason": type(last_exc).__name__})
        try:
            _no_img = make_no_images_fn(fb_model, fb_provider, model_params) if make_no_images_fn else None
            result = await _retry_single_model(
                make_attempt_fn(fb_model, fb_provider, model_params),
                fb_model, has_tools, max_retries, on_event,
                retry_without_tools_fn=make_no_tools_fn(fb_model, fb_provider, model_params),
                retry_without_images_fn=_no_img,
            )
            last_fallback_info.set(FallbackInfo(
                original_model=model, fallback_model=fb_model,
                reason=type(primary_exc).__name__,
                original_error=str(primary_exc)[:500],
            ))
            set_model_cooldown(model, fb_model, fb_provider)
            return result
        except _FALLBACK_TRIGGER_ERRORS as fb_exc:
            last_exc = fb_exc
            continue

    raise last_exc


@dataclass
class AccumulatedMessage:
    """Fully accumulated message from a streaming LLM response."""
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[dict] | None = None
    thinking_content: str | None = None
    usage: Any = None  # openai Usage object or None
    cached_tokens: int | None = None
    response_cost: float | None = None

    def to_msg_dict(self) -> dict:
        """Produce the same dict as msg.model_dump(exclude_none=True)."""
        d: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d


class StreamAccumulator:
    """Accumulates streaming chat completion chunks into events + final message."""

    def __init__(self):
        self._content_parts: list[str] = []
        self._thinking_parts: list[str] = []
        self._think_parser = ThinkTagParser()
        self._xml_filter = ToolCallXmlFilter()
        # tool_calls indexed by delta.index
        self._tool_calls: dict[int, dict] = {}
        self._usage: Any = None
        self._finish_reason: str | None = None
        self._response_cost: float | None = None

    def feed(self, chunk) -> tuple[list[dict], bool]:
        """Process one chunk. Returns (events_to_emit, is_done)."""
        events: list[dict] = []
        if not chunk.choices:
            # Usage-only chunk (final chunk with stream_options)
            if chunk.usage:
                self._usage = chunk.usage
            # Usage-only chunks from LiteLLM may carry response_cost
            if self._response_cost is None:
                _hidden = getattr(chunk, '_hidden_params', None)
                if _hidden is None and hasattr(chunk, 'model_extra'):
                    _hidden = (chunk.model_extra or {}).get('_hidden_params')
                if isinstance(_hidden, dict) and 'response_cost' in _hidden:
                    self._response_cost = _hidden['response_cost']
            return events, False

        choice = chunk.choices[0]
        delta = choice.delta

        # Text content — route <think> blocks to thinking events,
        # then filter XML tool-call fragments from content.
        if delta.content:
            content_text, thinking_text = self._think_parser.feed(delta.content)
            if content_text:
                # Filter out XML tool-call fragments (e.g. MiniMax <invoke> tags)
                filtered = self._xml_filter.feed(content_text)
                if filtered:
                    self._content_parts.append(filtered)
                    events.append({"type": "text_delta", "delta": filtered})
            if thinking_text:
                self._thinking_parts.append(thinking_text)
                events.append({"type": "thinking", "delta": thinking_text})

        # Thinking/reasoning content (provider-dependent attribute)
        reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
        if reasoning:
            self._thinking_parts.append(reasoning)
            events.append({"type": "thinking", "delta": reasoning})

        # Tool call deltas
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in self._tool_calls:
                    self._tool_calls[idx] = {
                        "id": tc_delta.id or "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                tc = self._tool_calls[idx]
                if tc_delta.id:
                    tc["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tc["function"]["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        tc["function"]["arguments"] += tc_delta.function.arguments

        if chunk.usage:
            self._usage = chunk.usage

        # Try to grab response_cost from chunk (LiteLLM adds it to _hidden_params)
        if self._response_cost is None:
            _hidden = getattr(chunk, '_hidden_params', None)
            if _hidden is None and hasattr(chunk, 'model_extra'):
                _hidden = (chunk.model_extra or {}).get('_hidden_params')
            if isinstance(_hidden, dict) and 'response_cost' in _hidden:
                self._response_cost = _hidden['response_cost']

        is_done = choice.finish_reason is not None
        if is_done:
            self._finish_reason = choice.finish_reason
            # Flush any remaining buffered text from the think-tag parser
            flush_content, flush_thinking = self._think_parser.flush()
            if flush_content:
                # Route through XML filter before emitting
                filtered = self._xml_filter.feed(flush_content)
                if filtered:
                    self._content_parts.append(filtered)
                    events.append({"type": "text_delta", "delta": filtered})
            if flush_thinking:
                self._thinking_parts.append(flush_thinking)
                events.append({"type": "thinking", "delta": flush_thinking})
            # Flush the XML filter too
            xml_remaining = self._xml_filter.flush()
            if xml_remaining:
                self._content_parts.append(xml_remaining)
                events.append({"type": "text_delta", "delta": xml_remaining})
        return events, is_done

    def build(self) -> AccumulatedMessage:
        """Build the final accumulated message."""
        content = "".join(self._content_parts) if self._content_parts else None
        # Strip malformed tool-call fragments (XML/JSON) that some providers
        # (e.g. MiniMax) emit as text content alongside proper tool_use blocks.
        if content is not None:
            content = strip_malformed_tool_calls(content)
        # Normalize whitespace-only content to None (e.g. "\n\n" after stripped think tags)
        if content is not None and not content.strip():
            content = None
        elif content is not None:
            content = content.strip()
        thinking = "".join(self._thinking_parts) if self._thinking_parts else None
        tool_calls = (
            [self._tool_calls[i] for i in sorted(self._tool_calls)]
            if self._tool_calls else None
        )
        # Extract cached_tokens from usage details (provider-agnostic)
        cached_tokens = None
        if self._usage:
            details = getattr(self._usage, 'prompt_tokens_details', None)
            if details:
                cached_tokens = getattr(details, 'cached_tokens', None)
        return AccumulatedMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            thinking_content=thinking,
            usage=self._usage,
            cached_tokens=cached_tokens,
            response_cost=self._response_cost,
        )


def _is_tools_not_supported_error(exc: openai.BadRequestError) -> bool:
    """Detect 400 errors that indicate the model doesn't support function calling / tools."""
    msg = str(exc).lower()
    return any(k in msg for k in (
        "function calling",
        "tools are not supported",
        "does not support tools",
        "does not support function",
        "tool use is not supported",
    ))


def _is_vision_not_supported_error(exc: openai.BadRequestError) -> bool:
    """Detect 400 errors that indicate the model doesn't support image/vision content."""
    msg = str(exc).lower()
    return any(k in msg for k in (
        "unsupported content type 'image_url'",
        "image_url is not supported",
        "does not support image",
        "does not support vision",
        "image input is not supported",
    ))


def _is_non_transient_500(exc: openai.InternalServerError) -> bool:
    """Detect 500s that wrap non-transient upstream errors (e.g. LiteLLM wrapping a 400)."""
    msg = str(exc).lower()
    if any(k in msg for k in ("bad_request", "invalid params", "http_code\":\"400")):
        return True
    # Word-boundary match for "400" — avoids false positives on "14000ms", "port 24001", etc.
    return bool(re.search(r"\b400\b", msg))


@dataclass
class _CallParams:
    """Prepared parameters for an LLM API call."""
    client: Any
    model: str
    messages: list
    tools: list | None
    tool_choice: str | None
    extra: dict  # filtered model params
    provider_id: str | None = None  # resolved provider (for usage tracking)


def _prepare_call_params(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None,
    model_params: dict | None,
    *,
    force_no_tools: bool = False,
) -> _CallParams:
    """Shared model preparation: client, param filtering, message folding, tool stripping."""
    from app.agent.model_params import filter_model_params
    from app.services.providers import get_llm_client, model_supports_tools, model_supports_vision, requires_system_message_folding, resolve_provider_for_model

    # Auto-resolve provider when caller didn't specify one and the model is
    # registered under a specific provider.
    if provider_id is None:
        provider_id = resolve_provider_for_model(model)

    client = get_llm_client(provider_id)
    filtered = filter_model_params(model, model_params or {})

    eff_msgs = messages
    if requires_system_message_folding(model):
        eff_msgs = _fold_system_messages(messages)
    else:
        # Apply prompt cache breakpoints for Anthropic/Claude models.
        # Mutually exclusive with folding — folded models don't support
        # native system messages, so cache_control wouldn't apply.
        from app.agent.prompt_cache import should_apply_cache_control, apply_cache_breakpoints
        if should_apply_cache_control(model, provider_id):
            eff_msgs = apply_cache_breakpoints(eff_msgs)

    if not model_supports_vision(model):
        eff_msgs = _strip_images_from_messages(eff_msgs)

    eff_tools = tools_param
    eff_tool_choice = tool_choice
    if force_no_tools or not model_supports_tools(model):
        if tools_param:
            logger.warning("Stripping tools for model %s (supports_tools=false)", model)
        eff_tools = None
        eff_tool_choice = None

    return _CallParams(
        client=client, model=model, messages=eff_msgs,
        tools=eff_tools, tool_choice=eff_tool_choice, extra=filtered,
        provider_id=provider_id,
    )


_USAGE_DRAIN_TIMEOUT = 5.0  # seconds to wait for usage chunk after finish_reason


async def _consume_stream(stream) -> AsyncGenerator[dict | AccumulatedMessage, None]:
    """Consume a streaming response, yielding events then the final AccumulatedMessage.

    After finish_reason we read up to 5 more seconds to capture the usage-only
    chunk that providers send with stream_options.include_usage.  Without this,
    token_usage trace events are never recorded.  The timeout prevents slow
    providers (e.g. MiniMax) from hanging the stream after content is done.
    """
    accumulator = StreamAccumulator()
    finish_seen = False
    async for chunk in stream:
        events, is_done = accumulator.feed(chunk)
        for event in events:
            yield event
        if is_done:
            finish_seen = True
            break

    # After finish_reason, try to read remaining chunks (usage data) with a timeout.
    # Use __anext__ directly on the stream — avoids creating intermediate generator
    # wrappers that could break if the OpenAI SDK changes __aiter__ behavior.
    if finish_seen:
        try:
            while True:
                chunk = await asyncio.wait_for(stream.__anext__(), timeout=_USAGE_DRAIN_TIMEOUT)
                accumulator.feed(chunk)
        except (asyncio.TimeoutError, StopAsyncIteration):
            pass
        finally:
            # Close the stream to release the underlying HTTP connection promptly.
            if hasattr(stream, "aclose"):
                try:
                    await stream.aclose()
                except Exception:
                    pass

    yield accumulator.build()


async def _llm_call_stream(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None = None,
    model_params: dict | None = None,
    fallback_models: list[dict] | None = None,
) -> AsyncGenerator[dict | AccumulatedMessage, None]:
    """Streaming LLM call with retry + fallback. Yields events in real-time.

    Retry/fallback/cooldown events are pushed to a queue so the SSE consumer
    sees them immediately (important during long rate-limit waits).
    """
    event_queue: asyncio.Queue[dict] = asyncio.Queue()

    def _on_event(ev: dict):
        event_queue.put_nowait(ev)

    def _make_attempt(m, pid, mp):
        async def _attempt():
            p = _prepare_call_params(m, messages, tools_param, tool_choice, pid, mp)
            logger.info("LLM call: model=%s, provider_id=%s→%s, base_url=%s",
                        m, pid, p.provider_id, getattr(p.client, 'base_url', '?'))
            kwargs: dict = dict(
                model=p.model, messages=p.messages, stream=True,
                stream_options={"include_usage": True}, **p.extra,
            )
            if p.tools is not None:
                kwargs["tools"] = p.tools
            if p.tool_choice is not None:
                kwargs["tool_choice"] = p.tool_choice
            return await p.client.chat.completions.create(**kwargs)
        return _attempt

    def _make_no_tools(m, pid, mp):
        async def _attempt():
            p = _prepare_call_params(m, messages, tools_param, tool_choice, pid, mp, force_no_tools=True)
            kwargs: dict = dict(
                model=p.model, messages=p.messages, stream=True,
                stream_options={"include_usage": True}, **p.extra,
            )
            return await p.client.chat.completions.create(**kwargs)
        return _attempt

    def _make_no_images(m, pid, mp):
        async def _attempt():
            stripped = _strip_images_from_messages(messages)
            p = _prepare_call_params(m, stripped, tools_param, tool_choice, pid, mp)
            kwargs: dict = dict(
                model=p.model, messages=p.messages, stream=True,
                stream_options={"include_usage": True}, **p.extra,
            )
            if p.tools is not None:
                kwargs["tools"] = p.tools
            if p.tool_choice is not None:
                kwargs["tool_choice"] = p.tool_choice
            return await p.client.chat.completions.create(**kwargs)
        return _attempt

    # Run the retry/fallback chain in a background task so we can yield
    # events from the queue in real-time while retries are in progress.
    stream_result: list = []  # single-element list to hold the stream
    chain_error: list = []

    async def _run_chain():
        try:
            result = await _run_with_fallback_chain(
                model, provider_id, model_params,
                has_tools=bool(tools_param),
                fallback_models=fallback_models,
                make_attempt_fn=_make_attempt,
                make_no_tools_fn=_make_no_tools,
                max_retries=settings.LLM_MAX_RETRIES,
                on_event=_on_event,
                make_no_images_fn=_make_no_images,
            )
            stream_result.append(result)
        except Exception as exc:
            chain_error.append(exc)
        finally:
            # Sentinel so the consumer knows the chain is done
            event_queue.put_nowait(None)

    chain_task = asyncio.create_task(_run_chain())

    # Yield retry/fallback events in real-time as they arrive
    while True:
        ev = await event_queue.get()
        if ev is None:
            break
        yield ev

    # Wait for the task to finish (should already be done)
    await chain_task

    if chain_error:
        raise chain_error[0]

    async for ev in _consume_stream(stream_result[0]):
        yield ev


async def _llm_call(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None = None,
    model_params: dict | None = None,
    fallback_models: list[dict] | None = None,
):
    """Non-streaming LLM call with retry + fallback chain.

    Retry strategy:
    - Rate limits (429): longer backoff via LLM_RATE_LIMIT_INITIAL_WAIT (default 90s).
    - Timeouts, connection errors, 5xx: shorter backoff via LLM_RETRY_INITIAL_WAIT (default 2s).
    - After all retries exhausted on primary, try each fallback in order.
    - Global fallback list is appended after the caller's list.
    """
    from app.services.providers import record_usage

    def _make_attempt(m, pid, mp):
        async def _attempt():
            p = _prepare_call_params(m, messages, tools_param, tool_choice, pid, mp)
            kwargs: dict = dict(model=p.model, messages=p.messages, **p.extra)
            if p.tools is not None:
                kwargs["tools"] = p.tools
            if p.tool_choice is not None:
                kwargs["tool_choice"] = p.tool_choice
            resp = await p.client.chat.completions.create(**kwargs)
            if not resp.choices:
                raise EmptyChoicesError(
                    f"LLM returned empty choices list (model={m}, "
                    f"finish_reason=n/a, id={getattr(resp, 'id', '?')})"
                )
            if resp.usage:
                record_usage(p.provider_id, resp.usage.total_tokens)
            return resp
        return _attempt

    def _make_no_tools(m, pid, mp):
        async def _attempt():
            p = _prepare_call_params(m, messages, tools_param, tool_choice, pid, mp, force_no_tools=True)
            kwargs: dict = dict(model=p.model, messages=p.messages, **p.extra)
            resp = await p.client.chat.completions.create(**kwargs)
            if not resp.choices:
                raise EmptyChoicesError(
                    f"LLM returned empty choices list (model={m}, "
                    f"finish_reason=n/a, id={getattr(resp, 'id', '?')})"
                )
            if resp.usage:
                record_usage(p.provider_id, resp.usage.total_tokens)
            return resp
        return _attempt

    def _make_no_images(m, pid, mp):
        async def _attempt():
            stripped = _strip_images_from_messages(messages)
            p = _prepare_call_params(m, stripped, tools_param, tool_choice, pid, mp)
            kwargs: dict = dict(model=p.model, messages=p.messages, **p.extra)
            if p.tools is not None:
                kwargs["tools"] = p.tools
            if p.tool_choice is not None:
                kwargs["tool_choice"] = p.tool_choice
            resp = await p.client.chat.completions.create(**kwargs)
            if not resp.choices:
                raise EmptyChoicesError(
                    f"LLM returned empty choices list (model={m}, "
                    f"finish_reason=n/a, id={getattr(resp, 'id', '?')})"
                )
            if resp.usage:
                record_usage(p.provider_id, resp.usage.total_tokens)
            return resp
        return _attempt

    return await _run_with_fallback_chain(
        model, provider_id, model_params,
        has_tools=bool(tools_param),
        fallback_models=fallback_models,
        make_attempt_fn=_make_attempt,
        make_no_tools_fn=_make_no_tools,
        max_retries=settings.LLM_MAX_RETRIES,
        make_no_images_fn=_make_no_images,
    )


_IMAGE_STRIPPED_NOTE = (
    "[An image was attached but your model does not support viewing images directly. "
    "If you have the `describe_attachment` tool available, use it to get a text description. "
    "Otherwise, let the user know you cannot view images with your current model.]"
)


def _strip_images_from_messages(messages: list) -> list:
    """Return a copy of *messages* with image_url content blocks replaced by text notes."""
    out = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            out.append(msg)
            continue
        new_parts = []
        had_image = False
        for part in content:
            if part.get("type") == "image_url":
                had_image = True
            else:
                new_parts.append(part)
        if had_image:
            new_parts.append({"type": "text", "text": _IMAGE_STRIPPED_NOTE})
        out.append({**msg, "content": new_parts})
    return out


def _fold_system_messages(messages: list) -> list:
    """Fold all system messages into the conversation for providers that reject role:system.

    Strategy:
    - Collect all system message content and merge into a single user message
      placed at the start of the conversation.
    - Preserve non-system messages in order.
    - Ensure strict role alternation (no consecutive same-role messages) by
      merging adjacent same-role messages with a newline separator.
    """
    system_parts: list[str] = []
    non_system: list[dict] = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                system_parts.append(content)
            elif isinstance(content, list):
                # Multimodal/list content — flatten to string to preserve it
                text = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
                if text.strip():
                    system_parts.append(text)
            # Empty/None content is intentionally skipped (no useful data)
        else:
            non_system.append(msg)

    result: list[dict] = []
    if system_parts:
        result.append({"role": "user", "content": "\n\n---\n\n".join(system_parts)})
    result.extend(non_system)

    # Enforce role alternation: merge consecutive same-role messages
    merged: list[dict] = []
    for msg in result:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]
            prev_content = prev.get("content", "")
            cur_content = msg.get("content", "")

            # Never merge tool-result messages — each has a unique tool_call_id
            if msg.get("role") == "tool":
                merged.append(msg)
                continue

            # Only merge simple string content; skip complex (audio/multipart)
            if isinstance(prev_content, str) and isinstance(cur_content, str):
                combined = {**prev, "content": prev_content + "\n\n" + cur_content}
                # Preserve tool_calls from both assistant messages
                prev_tc = prev.get("tool_calls") or []
                cur_tc = msg.get("tool_calls") or []
                if prev_tc or cur_tc:
                    combined["tool_calls"] = list(prev_tc) + list(cur_tc)
                merged[-1] = combined
            else:
                merged.append(msg)
        else:
            merged.append(msg)
    return merged




async def _summarize_tool_result(
    tool_name: str, content: str, model: str, max_tokens: int, provider_id: str | None = None
) -> str:
    """Summarize a large tool result to reduce context window usage. Falls back to original on error."""
    from app.services.providers import get_llm_client
    cap = 12000
    head = 8000
    tail = 4000
    if len(content) > cap:
        input_content = (
            content[:head]
            + f"\n\n[... {len(content) - head - tail:,} chars omitted ...]\n\n"
            + content[-tail:]
        )
    else:
        input_content = content
    prompt = (
        "Summarize this tool output concisely. "
        "Preserve: exit codes, errors, warnings, key values, file names, IDs, counts, actionable info. "
        "Omit: progress bars, verbose package lists, redundant log lines. Be brief.\n\n"
        f"Tool: {tool_name}\n<output>\n{input_content}\n</output>"
    )
    try:
        client = get_llm_client(provider_id)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        summary = resp.choices[0].message.content or content
        return f"[summarized from {len(content):,} chars]\n{summary}"
    except Exception:
        logger.warning("Tool result summarization failed for %s, using original", tool_name)
        return content
