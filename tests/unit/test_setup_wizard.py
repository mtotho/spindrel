"""Tests for the setup wizard's headless/provider bootstrap behavior."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


def _load_setup_module(monkeypatch):
    monkeypatch.setenv("SPINDREL_HEADLESS", "1")
    path = Path(__file__).resolve().parents[2] / "scripts" / "setup.py"
    spec = importlib.util.spec_from_file_location("spindrel_setup_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_headless_import_does_not_require_questionary(monkeypatch):
    mod = _load_setup_module(monkeypatch)
    assert mod.HEADLESS is True
    assert mod.STYLE is None


def test_provider_alias_resolves_openai_subscription(monkeypatch):
    mod = _load_setup_module(monkeypatch)
    provider = mod.get_provider("openai-subscription")
    assert provider["id"] == "chatgpt-subscription"
    assert provider["provider_type"] == "openai-subscription"


def test_headless_subscription_seed_omits_llm_fallback(monkeypatch, tmp_path):
    mod = _load_setup_module(monkeypatch)
    mod.ENV_FILE = tmp_path / ".env"
    mod.SEED_FILE = tmp_path / "provider-seed.yaml"

    monkeypatch.setenv("SPINDREL_OVERWRITE", "1")
    monkeypatch.setenv("SPINDREL_DEPLOY_MODE", "docker")
    monkeypatch.setenv("SPINDREL_PROVIDER", "openai-subscription")
    monkeypatch.setenv("SPINDREL_WEB_SEARCH", "ddgs")
    monkeypatch.setenv("SPINDREL_API_KEY", "ask_test")
    monkeypatch.delenv("SPINDREL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("SPINDREL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("SPINDREL_MODEL", raising=False)

    mod.main_headless()

    env_text = mod.ENV_FILE.read_text()
    assert "DEFAULT_MODEL=gpt-5.4" in env_text
    assert "LLM_BASE_URL=" not in env_text
    assert "LLM_API_KEY=" not in env_text

    seed = yaml.safe_load(mod.SEED_FILE.read_text())
    assert seed["id"] == "chatgpt-subscription"
    assert seed["provider_type"] == "openai-subscription"
    assert seed["billing_type"] == "plan"
    assert seed["plan_cost"] == 20
    assert seed["plan_period"] == "monthly"


def test_headless_searxng_bootstraps_shared_browser(monkeypatch, tmp_path):
    mod = _load_setup_module(monkeypatch)
    mod.ENV_FILE = tmp_path / ".env"
    mod.SEED_FILE = tmp_path / "provider-seed.yaml"

    monkeypatch.setenv("SPINDREL_OVERWRITE", "1")
    monkeypatch.setenv("SPINDREL_DEPLOY_MODE", "docker")
    monkeypatch.setenv("SPINDREL_PROVIDER", "skip")
    monkeypatch.setenv("SPINDREL_WEB_SEARCH", "searxng")
    monkeypatch.setenv("SPINDREL_API_KEY", "ask_test")

    mod.main_headless()

    env_text = mod.ENV_FILE.read_text()
    assert "WEB_SEARCH_MODE=searxng" in env_text
    assert "WEB_SEARCH_CONTAINERS=true" in env_text
    assert "HEADLESS_BROWSER_CONTAINERS=true" in env_text
    assert "SPINDREL_BOOTSTRAP_INTEGRATIONS=web_search,browser_automation" in env_text
