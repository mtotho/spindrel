"""Pure-unit coverage for the screenshot tool.

Run-on-the-e2e-server parts (SpindrelClient HTTP calls, docker-exec helpers,
Playwright capture) are deliberately out of scope — those need a live e2e
instance and are exercised end-to-end by the `stage`/`capture` CLI.

What we pin here:
- envelope helpers always produce the native content_type
- resolve_specs substitutes placeholders and fails loudly on missing keys
- config.load refuses anything that doesn't look like the e2e instance
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from scripts.screenshots import config
from scripts.screenshots.capture.specs import FLAGSHIP_SPECS, resolve_specs
from scripts.screenshots.stage import envelopes
from scripts.screenshots.stage.scenarios.harness import stage_harness


class _HarnessDryRunClient:
    def __init__(self) -> None:
        self.polled_channel = False

    def ensure_bot(self, *, bot_id, name, model, system_prompt=""):
        return {"id": bot_id, "name": name, "model": model}

    def update_bot(self, bot_id, **fields):
        return {"id": bot_id, **fields}

    def _get(self, path):
        class _Resp:
            def json(self):
                return {"runtimes": [{"name": "demo"}]}

        return _Resp()

    def ensure_channel(self, *, client_id, bot_id="default", name=None, private=False, category=None):
        return {"id": "dry-run-channel", "client_id": client_id}

    def get_active_session_id(self, channel_id):
        self.polled_channel = True
        raise AssertionError("dry-run should not poll channel state")


def test_native_content_type_on_every_helper():
    helpers = [
        envelopes.notes,
        envelopes.todos,
        envelopes.usage_forecast,
        envelopes.upcoming_activity,
        envelopes.standing_order_poll,
        envelopes.machine_control,
        envelopes.context_tracker,
    ]
    for fn in helpers:
        env = fn()
        assert env["content_type"] == envelopes.NATIVE_CT, f"{fn.__name__} drifted"
        body = env["body"]
        assert body["widget_ref"].startswith("core/"), f"{fn.__name__} widget_ref"
        assert isinstance(body["state"], dict), f"{fn.__name__} state"


def test_html_hero_envelope_marks_interactive_html():
    env = envelopes.html_hero_envelope("https://example.com/bundle")
    assert env["content_type"] == "application/vnd.spindrel.html+interactive"
    assert env["widget_ref"] == "https://example.com/bundle"


def test_resolve_specs_substitutes_placeholders():
    staged = {
        "chat_main": "abc-chat",
        "demo_dashboard": "abc-dash",
        "pipeline": "abc-pipe",
        "pipeline_live": "task-xyz",
    }
    resolved = resolve_specs(FLAGSHIP_SPECS, staged)
    names_to_routes = {s.name: s.route for s in resolved}
    assert names_to_routes["chat-main"] == "/channels/abc-chat"
    assert names_to_routes["widget-dashboard"] == "/widgets/channel/abc-dash"
    assert names_to_routes["chat-pipeline-live"] == "/channels/abc-pipe/runs/task-xyz"


def test_resolve_specs_raises_on_missing_placeholder():
    with pytest.raises(KeyError, match="chat_main"):
        resolve_specs(FLAGSHIP_SPECS, {})


def test_resolve_specs_preserves_wait_strategy():
    staged = {
        "chat_main": "c",
        "demo_dashboard": "d",
        "pipeline": "p",
        "pipeline_live": "t",
    }
    resolved = {s.name: s for s in resolve_specs(FLAGSHIP_SPECS, staged)}
    assert resolved["home"].wait_kind == "function"
    assert 'a[href^="/channels/"]' in str(resolved["home"].wait_arg)
    assert resolved["widget-dashboard"].wait_kind == "function"
    assert resolved["chat-pipeline-live"].wait_kind == "function"


def test_config_rejects_production_looking_url(tmp_path):
    bad_env = {
        "SPINDREL_URL": "https://spindrel.example.com",
        "SPINDREL_UI_URL": "https://spindrel.example.com",
        "SPINDREL_API_KEY": "x",
    }
    with patch.dict(os.environ, bad_env, clear=False):
        with pytest.raises(RuntimeError, match="does not look like the e2e instance"):
            config.load()


def test_config_accepts_e2e_url():
    good_env = {
        "SPINDREL_URL": "http://10.10.30.208:18000",
        "SPINDREL_UI_URL": "http://10.10.30.208:18081",
        "SPINDREL_API_KEY": "e2e-key",
    }
    with patch.dict(os.environ, good_env, clear=False):
        cfg = config.load()
        assert cfg.api_url.endswith(":18000")
        assert cfg.ssh_alias  # has a default


def test_harness_stage_dry_run_stops_before_polling_channel_state():
    client = _HarnessDryRunClient()

    state = stage_harness(
        client,
        ssh_alias="unused",
        ssh_container="unused",
        dry_run=True,
    )

    assert state.channels["harness_chat"] == "dry-run-channel"
    assert client.polled_channel is False
