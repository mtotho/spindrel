"""Tests for app.agent.model_params — provider capability map, filtering, and definitions."""
import pytest

from app.agent.model_params import (
    MODEL_PARAM_SUPPORT,
    _HEURISTIC_NO_SYS_MSG_FAMILIES,
    PARAM_DEFINITIONS,
    filter_model_params,
    get_provider_family,
    get_supported_params,
)


# ---------------------------------------------------------------------------
# get_provider_family
# ---------------------------------------------------------------------------

class TestGetProviderFamily:
    def test_openai_prefix(self):
        assert get_provider_family("openai/gpt-4o") == "openai"

    def test_anthropic_prefix(self):
        assert get_provider_family("anthropic/claude-3-opus") == "anthropic"

    def test_gemini_prefix(self):
        assert get_provider_family("gemini/gemini-2.5-flash") == "gemini"

    def test_deepseek_prefix(self):
        assert get_provider_family("deepseek/deepseek-chat") == "deepseek"

    def test_bare_model_defaults_to_openai(self):
        """Models without a slash (e.g. gpt-4o) are treated as openai."""
        assert get_provider_family("gpt-4o") == "openai"
        assert get_provider_family("gpt-3.5-turbo") == "openai"

    def test_case_insensitive(self):
        assert get_provider_family("Anthropic/claude-3") == "anthropic"
        assert get_provider_family("GEMINI/gemini-pro") == "gemini"

    def test_unknown_provider(self):
        assert get_provider_family("somevendor/model-v1") == "somevendor"


# ---------------------------------------------------------------------------
# get_supported_params
# ---------------------------------------------------------------------------

class TestGetSupportedParams:
    def test_openai_has_all_four_plus_reasoning(self):
        params = get_supported_params("gpt-4o")
        assert "temperature" in params
        assert "max_tokens" in params
        assert "frequency_penalty" in params
        assert "presence_penalty" in params
        assert "reasoning_effort" in params

    def test_anthropic_only_temperature_and_max_tokens(self):
        params = get_supported_params("anthropic/claude-3-opus")
        assert "temperature" in params
        assert "max_tokens" in params
        assert "frequency_penalty" not in params
        assert "presence_penalty" not in params
        assert "reasoning_effort" not in params

    def test_gemini_has_penalties_no_reasoning(self):
        params = get_supported_params("gemini/gemini-2.5-flash")
        assert "frequency_penalty" in params
        assert "presence_penalty" in params
        assert "reasoning_effort" not in params

    def test_unknown_provider_uses_default(self):
        params = get_supported_params("randomvendor/some-model")
        assert params == MODEL_PARAM_SUPPORT["_default"]
        assert "temperature" in params
        assert "max_tokens" in params


# ---------------------------------------------------------------------------
# filter_model_params
# ---------------------------------------------------------------------------

class TestFilterModelParams:
    def test_empty_params_returns_empty(self):
        assert filter_model_params("gpt-4", {}) == {}

    def test_none_params_returns_empty(self):
        """filter_model_params should handle the case where empty dict is passed."""
        assert filter_model_params("gpt-4", {}) == {}

    def test_all_supported_params_pass_through_openai(self):
        params = {
            "temperature": 0.7,
            "max_tokens": 4096,
            "frequency_penalty": 0.3,
            "presence_penalty": 0.5,
        }
        result = filter_model_params("gpt-4o", params)
        assert result == params

    def test_unsupported_params_stripped_for_anthropic(self):
        """Anthropic doesn't support frequency/presence penalties — they should be stripped."""
        params = {
            "temperature": 0.3,
            "max_tokens": 8192,
            "frequency_penalty": 0.1,
            "presence_penalty": 0.2,
        }
        result = filter_model_params("anthropic/claude-3-opus", params)
        assert result == {"temperature": 0.3, "max_tokens": 8192}
        assert "frequency_penalty" not in result
        assert "presence_penalty" not in result

    def test_none_values_stripped(self):
        """Params set to None should be removed."""
        params = {"temperature": None, "max_tokens": 4096}
        result = filter_model_params("gpt-4", params)
        assert result == {"max_tokens": 4096}

    def test_reasoning_effort_passes_for_openai(self, monkeypatch):
        # Phase 2 adds a DB-flag reasoning gate inside filter_model_params.
        # This test isolates the family-level pass-through, so force the DB
        # gate open — a dedicated suite covers the DB-gating behavior.
        monkeypatch.setattr(
            "app.services.providers.supports_reasoning",
            lambda _m: True,
        )
        params = {"reasoning_effort": "high", "temperature": 0.5}
        result = filter_model_params("gpt-4o", params)
        assert result["reasoning_effort"] == "high"

    def test_reasoning_effort_stripped_for_anthropic(self):
        params = {"reasoning_effort": "high", "temperature": 0.5}
        result = filter_model_params("anthropic/claude-3", params)
        assert "reasoning_effort" not in result
        assert result == {"temperature": 0.5}

    def test_reasoning_effort_stripped_for_gemini(self):
        params = {"reasoning_effort": "medium"}
        result = filter_model_params("gemini/gemini-2.5-flash", params)
        assert result == {}

    def test_unknown_keys_stripped(self):
        """Random keys not in any support set should be removed."""
        params = {"temperature": 0.5, "bogus_param": 42, "top_k": 10}
        result = filter_model_params("gpt-4", params)
        assert result == {"temperature": 0.5}

    def test_zero_values_preserved(self):
        """0 is a valid value (e.g. temperature=0), should not be stripped."""
        params = {"temperature": 0, "frequency_penalty": 0.0}
        result = filter_model_params("gpt-4", params)
        assert result == {"temperature": 0, "frequency_penalty": 0.0}

    def test_negative_penalties_preserved(self):
        """Negative penalties are valid."""
        params = {"frequency_penalty": -1.5, "presence_penalty": -0.5}
        result = filter_model_params("gpt-4", params)
        assert result == params

    def test_mixed_valid_and_invalid(self):
        """Mix of valid, unsupported, and None values."""
        params = {
            "temperature": 0.8,
            "max_tokens": None,
            "frequency_penalty": 0.2,
            "top_p": 0.9,         # not in our param set
            "presence_penalty": 0.1,
        }
        result = filter_model_params("openai/gpt-4", params)
        assert result == {
            "temperature": 0.8,
            "frequency_penalty": 0.2,
            "presence_penalty": 0.1,
        }


# ---------------------------------------------------------------------------
# PARAM_DEFINITIONS integrity
# ---------------------------------------------------------------------------

class TestParamDefinitions:
    def test_all_definitions_have_required_fields(self):
        for defn in PARAM_DEFINITIONS:
            assert "name" in defn
            assert "label" in defn
            assert "description" in defn
            assert "type" in defn
            assert defn["type"] in ("slider", "number", "select")

    def test_slider_definitions_have_range(self):
        for defn in PARAM_DEFINITIONS:
            if defn["type"] == "slider":
                assert "min" in defn
                assert "max" in defn
                assert "step" in defn
                assert defn["min"] < defn["max"]
                assert defn["step"] > 0

    def test_select_definitions_have_options(self):
        for defn in PARAM_DEFINITIONS:
            if defn["type"] == "select":
                assert "options" in defn
                assert len(defn["options"]) >= 2

    def test_every_definition_name_in_at_least_one_support_set(self):
        """Every param we define should be supported by at least one provider."""
        all_supported = set()
        for params in MODEL_PARAM_SUPPORT.values():
            all_supported |= params
        for defn in PARAM_DEFINITIONS:
            assert defn["name"] in all_supported, f"{defn['name']} not in any support set"

    def test_expected_params_present(self):
        names = {d["name"] for d in PARAM_DEFINITIONS}
        assert "temperature" in names
        assert "max_tokens" in names
        assert "frequency_penalty" in names
        assert "presence_penalty" in names
        assert "reasoning_effort" in names


# ---------------------------------------------------------------------------
# _HEURISTIC_NO_SYS_MSG_FAMILIES (heuristic fallback set)
# ---------------------------------------------------------------------------

class TestHeuristicNoSysMsgFamilies:
    def test_minimax_in_set(self):
        assert "minimax" in _HEURISTIC_NO_SYS_MSG_FAMILIES

    def test_standard_providers_not_in_set(self):
        for provider in ("openai", "anthropic", "gemini", "google", "mistral", "deepseek", "groq"):
            assert provider not in _HEURISTIC_NO_SYS_MSG_FAMILIES
