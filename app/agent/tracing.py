"""Trace helpers for the agent loop.

Provides classification of system messages and a lightweight trace logger
controlled by the AGENT_TRACE setting.
"""

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_SYS_MSG_PREFIXES: list[tuple[str, str]] = [
    ("Current time:", "sys:datetime"),
    ("Tagged skill context", "sys:tagged_skills"),
    ("Tagged knowledge", "sys:tagged_knowledge"),
    ("Pinned skill context", "sys:skill_pinned"),
    ("Available skills (use get_skill", "sys:skill_index"),
    ("Relevant skill context:\n", "sys:skill_rag"),
    ("Relevant context:\n", "sys:skill_context"),
    ("Available sub-agents", "sys:delegate_index"),
    ("Relevant memories from past", "sys:memory"),
    ("Pinned knowledge", "sys:pinned_knowledge"),
    ("Relevant knowledge:\n", "sys:knowledge"),
    ("Relevant code/files", "sys:fs_context"),
    ("Available tools (not yet loaded", "sys:tool_index"),
    ("Active plans for this session:", "sys:plans"),
    ("You must respond to the user", "sys:forced_response"),
    ("You have used too many tool calls", "sys:max_iterations"),
    ("[TRANSCRIPT_INSTRUCTION]", "sys:audio"),
]


def _CLASSIFY_SYS_MSG(content: str) -> str:
    for prefix, label in _SYS_MSG_PREFIXES:
        if content.startswith(prefix):
            return label
    return "sys:system_prompt"


def _trace(msg: str, *args: Any) -> None:
    """Log a single-line agent trace when AGENT_TRACE is enabled (no JSON)."""
    if settings.AGENT_TRACE:
        logger.info("[agent] " + msg, *args)
