"""Heartbeat execution policy defaults and normalization."""

from __future__ import annotations

from typing import Any


DEFAULT_HEARTBEAT_EXECUTION_POLICY: dict[str, Any] = {
    "tool_surface": "focused_escape",
    "continuation_mode": "stateless",
    "soft_max_llm_calls": 6,
    "hard_max_llm_calls": 12,
    "soft_current_prompt_tokens": 50_000,
    "target_seconds": 90,
}


def normalize_heartbeat_execution_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a bounded heartbeat execution policy with stable defaults."""
    policy = dict(DEFAULT_HEARTBEAT_EXECUTION_POLICY)
    if isinstance(raw, dict):
        policy.update({k: v for k, v in raw.items() if v is not None})

    if policy.get("tool_surface") not in {"focused_escape", "full", "strict"}:
        policy["tool_surface"] = DEFAULT_HEARTBEAT_EXECUTION_POLICY["tool_surface"]
    if policy.get("continuation_mode") not in {"stateless", "provider_state"}:
        policy["continuation_mode"] = DEFAULT_HEARTBEAT_EXECUTION_POLICY["continuation_mode"]

    for key, low, high in (
        ("soft_max_llm_calls", 1, 50),
        ("hard_max_llm_calls", 1, 100),
        ("soft_current_prompt_tokens", 0, 1_000_000),
        ("target_seconds", 1, 3_600),
    ):
        try:
            value = int(policy.get(key, DEFAULT_HEARTBEAT_EXECUTION_POLICY[key]))
        except (TypeError, ValueError):
            value = int(DEFAULT_HEARTBEAT_EXECUTION_POLICY[key])
        policy[key] = max(low, min(high, value))

    if policy["hard_max_llm_calls"] < policy["soft_max_llm_calls"]:
        policy["hard_max_llm_calls"] = policy["soft_max_llm_calls"]
    return policy
