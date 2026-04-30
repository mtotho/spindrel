from __future__ import annotations

import argparse
from pathlib import Path
import urllib.error

import pytest

from scripts import agent_e2e_dev


def test_write_env_redacts_nothing_but_writes_gitignored_local_env(monkeypatch, tmp_path):
    env_path = tmp_path / ".env.agent-e2e"
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)

    args = argparse.Namespace(
        host="localhost",
        port="19000",
        api_key="test-key",
        base_url="",
        llm_base_url="https://example.invalid/v1",
        llm_api_key="secret-key",
        model="gpt-test",
        provider="openai-compatible",
        force=False,
        allow_production=False,
    )

    assert agent_e2e_dev.cmd_write_env(args) == 0
    body = env_path.read_text()
    assert "E2E_PORT=19000" in body
    assert "E2E_LLM_API_KEY=secret-key" in body
    assert env_path.stat().st_mode & 0o777 == 0o600


def test_write_env_refuses_production_like_base_url(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", tmp_path / ".env.agent-e2e")
    args = argparse.Namespace(
        host="localhost",
        port="18000",
        api_key="test-key",
        base_url="http://127.0.0.1:8000",
        llm_base_url="",
        llm_api_key="",
        model="gpt-test",
        provider="openai-compatible",
        force=False,
        allow_production=False,
    )

    with pytest.raises(SystemExit, match="refusing production-like target"):
        agent_e2e_dev.cmd_write_env(args)


def test_write_auth_override_mounts_existing_auth_dirs(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    scratch = repo / "scratch" / "agent-e2e"
    override = scratch / "compose.auth.override.yml"
    codex_home = tmp_path / ".codex"
    claude_home = tmp_path / ".claude"
    codex_home.mkdir()
    claude_home.mkdir()
    monkeypatch.setattr(agent_e2e_dev, "REPO_ROOT", repo)
    monkeypatch.setattr(agent_e2e_dev, "SCRATCH_DIR", scratch)
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", override)

    args = argparse.Namespace(
        codex_home=str(codex_home),
        claude_home=str(claude_home),
        force=False,
    )

    assert agent_e2e_dev.cmd_write_auth_override(args) == 0
    body = override.read_text()
    assert f"{codex_home}:/home/spindrel/.codex:rw" in body
    assert f"{claude_home}:/home/spindrel/.claude:rw" in body


def test_write_env_subscription_mode_uses_placeholder_until_oauth(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)

    args = argparse.Namespace(
        host="localhost",
        port="18000",
        api_key="test-key",
        base_url="",
        llm_base_url="",
        llm_api_key="ignored-key",
        model="",
        provider="subscription",
        force=False,
        allow_production=False,
    )

    assert agent_e2e_dev.cmd_write_env(args) == 0
    body = env_path.read_text()
    assert f"E2E_LLM_BASE_URL={agent_e2e_dev.SUBSCRIPTION_DUMMY_BASE_URL}" in body
    assert "E2E_LLM_API_KEY=" in body
    assert f"E2E_DEFAULT_MODEL={agent_e2e_dev.SUBSCRIPTION_DEFAULT_MODEL}" in body
    assert "SPINDREL_AGENT_E2E_PROVIDER=subscription" in body
    assert "SPINDREL_PROVIDER=chatgpt-subscription" in body
    assert "subscription mode" in capsys.readouterr().out


def test_doctor_redacts_api_keys(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text(
        "\n".join([
            "SPINDREL_E2E_URL=http://localhost:18000",
            "E2E_API_KEY=abcdef123456",
            "E2E_LLM_API_KEY=llmsecret123456",
        ])
    )
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "SCREENSHOT_ENV", tmp_path / "missing")
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", tmp_path / "missing-override.yml")
    monkeypatch.setattr(agent_e2e_dev, "_check_url", lambda url, key: (True, "{}"))

    args = argparse.Namespace(allow_production=False)

    assert agent_e2e_dev.cmd_doctor(args) == 0
    out = capsys.readouterr().out
    assert "abcdef123456" not in out
    assert "llmsecret123456" not in out
    assert "abcd...3456" in out
    assert "llms...3456" in out


def test_doctor_reports_subscription_bootstrap_pending(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text(
        "\n".join([
            "SPINDREL_E2E_URL=http://localhost:18000",
            "E2E_API_KEY=abcdef123456",
            "SPINDREL_AGENT_E2E_PROVIDER=subscription",
            f"E2E_LLM_BASE_URL={agent_e2e_dev.SUBSCRIPTION_DUMMY_BASE_URL}",
        ])
    )
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "SCREENSHOT_ENV", tmp_path / "missing")
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", tmp_path / "missing-override.yml")
    monkeypatch.setattr(agent_e2e_dev, "_check_url", lambda url, key: (True, "{}"))

    assert agent_e2e_dev.cmd_doctor(argparse.Namespace(allow_production=False)) == 0
    out = capsys.readouterr().out
    assert "provider mode: subscription" in out
    assert "subscription bootstrap: pending" in out


def test_commands_prints_subscription_handoff_when_configured(monkeypatch, tmp_path, capsys):
    env_path = tmp_path / ".env.agent-e2e"
    env_path.write_text("SPINDREL_AGENT_E2E_PROVIDER=subscription\n")
    monkeypatch.setattr(agent_e2e_dev, "LOCAL_ENV", env_path)
    monkeypatch.setattr(agent_e2e_dev, "AUTH_OVERRIDE", tmp_path / "missing-override.yml")

    assert agent_e2e_dev.cmd_commands(argparse.Namespace(env_file=".env.agent-e2e")) == 0
    out = capsys.readouterr().out
    assert "subscription handoff:" in out
    assert "bootstrap-subscription" in out


def test_bootstrap_subscription_sequences_provider_oauth_and_bot_patch(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method: str, url: str, *, api_key: str = "", body: dict | None = None, timeout: int = 20):
        calls.append((method, url, body))
        if url.endswith("/api/v1/admin/providers/chatgpt-subscription") and method == "GET":
            return {"id": "chatgpt-subscription"}
        if url.endswith("/start/chatgpt-subscription"):
            return {
                "verification_uri": "https://example.invalid/device",
                "user_code": "ABCD",
                "interval": 1,
                "expires_in": 20,
            }
        if url.endswith("/poll/chatgpt-subscription"):
            return {"status": "success", "email": "user@example.invalid", "plan": "Plus"}
        return {}

    monkeypatch.setattr(agent_e2e_dev, "_request_json", fake_request)
    monkeypatch.setattr(agent_e2e_dev.time, "sleep", lambda _: None)
    args = argparse.Namespace(
        api_url="http://localhost:18000",
        api_key="key",
        provider_id="chatgpt-subscription",
        model="gpt-5.4-mini",
        bot=["e2e"],
        allow_production=False,
    )

    assert agent_e2e_dev.cmd_bootstrap_subscription(args) == 0
    assert (
        "PATCH",
        "http://localhost:18000/api/v1/admin/bots/e2e",
        {"model_provider_id": "chatgpt-subscription", "model": "gpt-5.4-mini"},
    ) in calls


def test_request_json_includes_http_error_body(monkeypatch):
    class FakeHTTPError(urllib.error.HTTPError):
        def read(self):
            return b'{"detail":"bad payload"}'

    def fake_urlopen(req, timeout):
        raise FakeHTTPError(req.full_url, 422, "Unprocessable Entity", {}, None)

    monkeypatch.setattr(agent_e2e_dev.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match='HTTP 422: {"detail":"bad payload"}'):
        agent_e2e_dev._request_json("POST", "http://localhost:18000/test")


def test_bootstrap_subscription_explains_stale_image_for_missing_provider_type(monkeypatch):
    def fake_ensure_provider(api_url, api_key, provider_id):
        raise RuntimeError(
            "POST /providers returned HTTP 422: "
            "{\"detail\":\"Invalid provider_type. Must be one of: ['openai-compatible']\"}"
        )

    monkeypatch.setattr(agent_e2e_dev, "_ensure_provider", fake_ensure_provider)
    args = argparse.Namespace(
        api_url="http://localhost:18000",
        api_key="key",
        provider_id="chatgpt-subscription",
        model="gpt-5.4-mini",
        bot=["e2e"],
        allow_production=False,
    )

    with pytest.raises(SystemExit, match="Rebuild the local e2e image"):
        agent_e2e_dev.cmd_bootstrap_subscription(args)
