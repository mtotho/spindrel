"""Heartbeat execution policy defaults and normalization."""

from __future__ import annotations

from typing import Any


HEARTBEAT_EXECUTION_PRESETS: dict[str, dict[str, int]] = {
    "low": {
        "soft_max_llm_calls": 6,
        "hard_max_llm_calls": 12,
        "soft_current_prompt_tokens": 50_000,
        "target_seconds": 90,
    },
    "medium": {
        "soft_max_llm_calls": 12,
        "hard_max_llm_calls": 30,
        "soft_current_prompt_tokens": 150_000,
        "target_seconds": 180,
    },
    "high": {
        "soft_max_llm_calls": 20,
        "hard_max_llm_calls": 50,
        "soft_current_prompt_tokens": 300_000,
        "target_seconds": 300,
    },
}

DEFAULT_HEARTBEAT_EXECUTION_PRESET = "medium"

DEFAULT_HEARTBEAT_EXECUTION_POLICY: dict[str, Any] = {
    "preset": DEFAULT_HEARTBEAT_EXECUTION_PRESET,
    "tool_surface": "focused_escape",
    "continuation_mode": "stateless",
    **HEARTBEAT_EXECUTION_PRESETS[DEFAULT_HEARTBEAT_EXECUTION_PRESET],
}


def normalize_heartbeat_execution_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Return a bounded heartbeat execution policy with stable defaults."""
    raw_dict = raw if isinstance(raw, dict) else {}
    raw_preset = raw_dict.get("preset")
    preset = raw_preset if raw_preset in HEARTBEAT_EXECUTION_PRESETS else DEFAULT_HEARTBEAT_EXECUTION_PRESET
    policy = {
        **DEFAULT_HEARTBEAT_EXECUTION_POLICY,
        "preset": preset,
        **HEARTBEAT_EXECUTION_PRESETS[preset],
    }
    policy.update({
        k: v for k, v in raw_dict.items()
        if v is not None and k in {
            "tool_surface",
            "continuation_mode",
            "soft_max_llm_calls",
            "hard_max_llm_calls",
            "soft_current_prompt_tokens",
            "target_seconds",
        }
    })

    if policy.get("tool_surface") not in {"focused_escape", "full", "strict"}:
        policy["tool_surface"] = DEFAULT_HEARTBEAT_EXECUTION_POLICY["tool_surface"]
    # Provider-state continuation is intentionally reserved until the loop owns
    # response-id retention, expiry, and replay semantics end to end.
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

    preset_values = HEARTBEAT_EXECUTION_PRESETS.get(policy["preset"])
    if raw_preset in HEARTBEAT_EXECUTION_PRESETS:
        if any(policy[key] != preset_values[key] for key in preset_values):
            policy["preset"] = "custom"
    elif raw_preset == "custom":
        policy["preset"] = "custom"
    elif any(key in raw_dict for key in HEARTBEAT_EXECUTION_PRESETS[DEFAULT_HEARTBEAT_EXECUTION_PRESET]):
        if any(policy[key] != preset_values[key] for key in preset_values):
            policy["preset"] = "custom"
    else:
        policy["preset"] = DEFAULT_HEARTBEAT_EXECUTION_PRESET
    return policy
