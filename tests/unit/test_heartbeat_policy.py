"""Heartbeat execution policy normalization tests."""

from app.services.heartbeat_policy import normalize_heartbeat_execution_policy


def test_null_policy_defaults_to_medium():
    policy = normalize_heartbeat_execution_policy(None)

    assert policy["preset"] == "medium"
    assert policy["soft_max_llm_calls"] == 12
    assert policy["hard_max_llm_calls"] == 30
    assert policy["soft_current_prompt_tokens"] == 150_000
    assert policy["target_seconds"] == 180


def test_known_presets_expand_to_expected_values():
    low = normalize_heartbeat_execution_policy({"preset": "low"})
    high = normalize_heartbeat_execution_policy({"preset": "high"})

    assert low["soft_max_llm_calls"] == 6
    assert low["hard_max_llm_calls"] == 12
    assert high["soft_max_llm_calls"] == 20
    assert high["hard_max_llm_calls"] == 50


def test_numeric_override_on_preset_becomes_custom():
    policy = normalize_heartbeat_execution_policy({
        "preset": "medium",
        "hard_max_llm_calls": 40,
    })

    assert policy["preset"] == "custom"
    assert policy["soft_max_llm_calls"] == 12
    assert policy["hard_max_llm_calls"] == 40


def test_numeric_override_without_preset_becomes_custom():
    policy = normalize_heartbeat_execution_policy({"hard_max_llm_calls": 40})

    assert policy["preset"] == "custom"
    assert policy["soft_max_llm_calls"] == 12
    assert policy["hard_max_llm_calls"] == 40


def test_hard_cap_is_never_below_soft_cap():
    policy = normalize_heartbeat_execution_policy({
        "preset": "custom",
        "soft_max_llm_calls": 25,
        "hard_max_llm_calls": 10,
    })

    assert policy["preset"] == "custom"
    assert policy["hard_max_llm_calls"] == 25


def test_provider_state_is_reserved_until_runtime_support_exists():
    policy = normalize_heartbeat_execution_policy({
        "continuation_mode": "provider_state",
    })

    assert policy["continuation_mode"] == "stateless"
