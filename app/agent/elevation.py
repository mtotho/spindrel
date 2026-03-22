"""Rule-based model elevation classifier.

Runs once per iteration inside the agent tool loop, before _llm_call().
Decides whether to elevate from the base model to a more capable model
based on heuristic signals derived from the conversation context.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signal weights (defaults — can be overridden via bot YAML in the future)
# ---------------------------------------------------------------------------
ELEVATION_DEFAULT_WEIGHTS: dict[str, float] = {
    "message_length": 0.10,
    "code_content": 0.20,
    "keyword_elevate": 0.20,
    "keyword_simple": -0.20,
    "tool_complexity": 0.15,
    "conversation_depth": 0.10,
    "iteration_depth": 0.10,
    "prior_errors": 0.15,
}

# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------
_ELEVATE_KEYWORDS = re.compile(
    r"\b(explain|design|plan|debug|why|architect|implement|refactor|analy[sz]e)\b",
    re.IGNORECASE,
)
_SIMPLE_KEYWORDS = re.compile(
    r"\b(what time|remind|turn on|turn off|weather|timer)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Tool classifications
# ---------------------------------------------------------------------------
_COMPLEX_TOOLS = {"delegate_to_harness", "delegate_to_agent", "delegate_to_exec"}
_RESEARCH_TOOLS = {"web_search", "browse_page"}
_SIMPLE_TOOLS = {"get_current_local_time", "get_time", "get_weather", "toggle_tts"}

# ---------------------------------------------------------------------------
# Error indicators in tool results
# ---------------------------------------------------------------------------
_ERROR_PATTERNS = re.compile(
    r"\b(error|failed|exception|traceback)\b", re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ElevationDecision:
    model: str
    was_elevated: bool
    score: float
    rules_fired: list[str]
    signal_breakdown: dict[str, float]


@dataclass
class Signal:
    id: str
    weight: float
    evaluate: Callable[..., float]


# ---------------------------------------------------------------------------
# Signal implementations
# ---------------------------------------------------------------------------

def _get_last_user_content(messages: list[dict]) -> str:
    """Return the text content of the last user message, or empty string."""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                return content
            # Handle list-of-parts (multimodal messages)
            if isinstance(content, list):
                return " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            return str(content)
    return ""


def _signal_message_length(messages: list[dict], **_kw) -> float:
    text = _get_last_user_content(messages)
    length = len(text)
    if length <= 500:
        return 0.0
    if length >= 1500:
        return 1.0
    # Linear interpolation between 500 and 1500
    return (length - 500) / 1000.0 * 1.0  # 0.0 at 500, 0.5 at 1000, 1.0 at 1500


def _signal_code_content(messages: list[dict], **_kw) -> float:
    text = _get_last_user_content(messages)
    blocks = text.count("```")
    if blocks >= 4:  # 2+ complete code blocks
        return 1.0
    if blocks >= 2:  # 1 complete code block
        return 0.7
    # Single backtick inline code
    if "`" in text:
        return 0.7
    return 0.0


def _signal_keyword_elevate(messages: list[dict], **_kw) -> float:
    text = _get_last_user_content(messages)
    matches = _ELEVATE_KEYWORDS.findall(text)
    if len(matches) >= 2:
        return 1.0
    if len(matches) == 1:
        return 0.8
    return 0.0


def _signal_keyword_simple(messages: list[dict], **_kw) -> float:
    text = _get_last_user_content(messages)
    matches = _SIMPLE_KEYWORDS.findall(text)
    if not matches:
        return 0.0
    if len(text) < 50 and matches:
        return 1.0
    return 0.8


def _signal_tool_complexity(
    messages: list[dict], tool_history: list | None = None, **_kw,
) -> float:
    tools_used: set[str] = set()
    if tool_history:
        for item in tool_history:
            if isinstance(item, str):
                tools_used.add(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("function", {}).get("name", "")
                if name:
                    tools_used.add(name)

    if tools_used & _COMPLEX_TOOLS:
        return 1.0
    if tools_used & _RESEARCH_TOOLS:
        return 0.7
    if tools_used and tools_used <= _SIMPLE_TOOLS:
        return 0.0
    return 0.0


def _signal_conversation_depth(messages: list[dict], **_kw) -> float:
    tool_msg_count = sum(1 for m in messages if m.get("role") == "tool")
    if tool_msg_count > 15:
        return 1.0
    if tool_msg_count > 10:
        return 0.8
    if tool_msg_count > 5:
        return 0.5
    return 0.0


def _signal_iteration_depth(
    messages: list[dict], tool_history: list | None = None, **_kw,
) -> float:
    iteration_count = len(tool_history) if tool_history else 0
    if iteration_count >= 8:
        return 1.0
    if iteration_count >= 5:
        return 0.8
    if iteration_count >= 3:
        return 0.5
    return 0.0


def _signal_prior_errors(messages: list[dict], **_kw) -> float:
    # Check last 10 tool results for error patterns
    error_count = 0
    recent_tool_msgs = [
        m for m in messages if m.get("role") == "tool"
    ][-10:]
    for m in recent_tool_msgs:
        content = m.get("content", "")
        if isinstance(content, str) and _ERROR_PATTERNS.search(content):
            error_count += 1
    if error_count >= 2:
        return 0.9
    if error_count == 1:
        return 0.5
    return 0.0


# ---------------------------------------------------------------------------
# Build default signal list
# ---------------------------------------------------------------------------
_DEFAULT_SIGNALS: list[Signal] = [
    Signal("message_length", ELEVATION_DEFAULT_WEIGHTS["message_length"], _signal_message_length),
    Signal("code_content", ELEVATION_DEFAULT_WEIGHTS["code_content"], _signal_code_content),
    Signal("keyword_elevate", ELEVATION_DEFAULT_WEIGHTS["keyword_elevate"], _signal_keyword_elevate),
    Signal("keyword_simple", ELEVATION_DEFAULT_WEIGHTS["keyword_simple"], _signal_keyword_simple),
    Signal("tool_complexity", ELEVATION_DEFAULT_WEIGHTS["tool_complexity"], _signal_tool_complexity),
    Signal("conversation_depth", ELEVATION_DEFAULT_WEIGHTS["conversation_depth"], _signal_conversation_depth),
    Signal("iteration_depth", ELEVATION_DEFAULT_WEIGHTS["iteration_depth"], _signal_iteration_depth),
    Signal("prior_errors", ELEVATION_DEFAULT_WEIGHTS["prior_errors"], _signal_prior_errors),
]


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------
def classify_turn(
    messages: list[dict],
    bot_model: str,
    elevated_model: str,
    threshold: float,
    tool_history: list | None = None,
) -> ElevationDecision:
    """Classify whether this turn should be elevated to a more capable model.

    Synchronous, deterministic, no I/O. Must be fast (<5ms).
    """
    signal_breakdown: dict[str, float] = {}
    rules_fired: list[str] = []

    try:
        raw_score = 0.0
        for signal in _DEFAULT_SIGNALS:
            raw_value = signal.evaluate(messages, tool_history=tool_history)
            contribution = signal.weight * raw_value
            signal_breakdown[signal.id] = round(contribution, 4)
            raw_score += contribution
            if raw_value > 0 and signal.weight > 0:
                rules_fired.append(signal.id)
            elif raw_value > 0 and signal.weight < 0:
                rules_fired.append(signal.id)

        score = max(0.0, min(1.0, raw_score))

        # If elevated_model is the same as bot_model, no point elevating
        if elevated_model == bot_model:
            return ElevationDecision(
                model=bot_model,
                was_elevated=False,
                score=score,
                rules_fired=rules_fired,
                signal_breakdown=signal_breakdown,
            )

        if score >= threshold:
            return ElevationDecision(
                model=elevated_model,
                was_elevated=True,
                score=score,
                rules_fired=rules_fired,
                signal_breakdown=signal_breakdown,
            )

        return ElevationDecision(
            model=bot_model,
            was_elevated=False,
            score=score,
            rules_fired=rules_fired,
            signal_breakdown=signal_breakdown,
        )

    except Exception:
        logger.exception("Elevation classifier error — falling through to base model")
        # Ensure all 8 signal keys are present even on error
        for signal in _DEFAULT_SIGNALS:
            signal_breakdown.setdefault(signal.id, 0.0)
        return ElevationDecision(
            model=bot_model,
            was_elevated=False,
            score=0.0,
            rules_fired=[],
            signal_breakdown=signal_breakdown,
        )
