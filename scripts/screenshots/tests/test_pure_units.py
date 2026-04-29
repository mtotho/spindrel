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
import json
import inspect
from unittest.mock import patch

import pytest

from scripts.screenshots import config
from scripts.screenshots import harness_live
from scripts.screenshots import playwright_runtime
from scripts.screenshots import spindrel_plan_live
from scripts.screenshots.capture.specs import (
    ATTACHMENT_CHECK_SPECS,
    CHANNEL_WIDGET_USEFULNESS_SPECS,
    FLAGSHIP_SPECS,
    PROJECT_WORKSPACE_SPECS,
    SPATIAL_CHECK_SPECS,
    STARBOARD_SPECS,
    resolve_specs,
)
from scripts.screenshots.stage import envelopes
from scripts.screenshots.stage.scenarios.harness import stage_harness


class _SyncChromium:
    def __init__(self, *, fail_connect: bool = False, fail_launch: bool = False) -> None:
        self.fail_connect = fail_connect
        self.fail_launch = fail_launch
        self.calls: list[tuple[str, dict]] = []

    def connect(self, endpoint: str):
        self.calls.append(("connect", {"endpoint": endpoint}))
        if self.fail_connect:
            raise RuntimeError("connect failed")
        return f"playwright:{endpoint}"

    def connect_over_cdp(self, endpoint: str):
        self.calls.append(("connect_over_cdp", {"endpoint": endpoint}))
        if self.fail_connect:
            raise RuntimeError("cdp failed")
        return f"cdp:{endpoint}"

    def launch(self, **kwargs):
        self.calls.append(("launch", kwargs))
        if self.fail_launch:
            raise RuntimeError("Executable doesn't exist at /tmp/chromium")
        return {"launch": kwargs}


class _SyncPlaywright:
    def __init__(self, chromium: _SyncChromium) -> None:
        self.chromium = chromium


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


def test_spatial_checks_have_assertions_and_artifacts():
    assert len(SPATIAL_CHECK_SPECS) >= 5
    for spec in SPATIAL_CHECK_SPECS:
        assert spec.output.startswith("spatial-check-")
        assert spec.assert_js or spec.name == "spatial-check-density-smoke"
    assert any("data-starboard-panel" in str(spec.assert_js) for spec in SPATIAL_CHECK_SPECS)
    assert any("canvas-view-controls" in str(spec.assert_js) for spec in SPATIAL_CHECK_SPECS)


def test_starboard_capture_is_object_inspector_only():
    assert {spec.name for spec in STARBOARD_SPECS} == {"starboard-object-inspector"}
    spec = STARBOARD_SPECS[0]
    assert spec.output == "starboard-object-inspector.png"
    assert "starboard-map-brief" in str(spec.assert_js)
    assert "Object inspector" in str(spec.assert_js)
    assert "Mission Control" in str(spec.assert_js)


def test_attachment_checks_have_assertions_and_artifacts():
    assert {spec.name for spec in ATTACHMENT_CHECK_SPECS} == {
        "chat-attachments-drop-overlay",
        "chat-attachments-routing-tray",
        "chat-attachments-sent-receipts",
        "chat-attachments-terminal-sent-receipts",
    }
    for spec in ATTACHMENT_CHECK_SPECS:
        assert spec.output.startswith("chat-attachments-")
        assert spec.output.endswith(".png")
        assert spec.assert_js
    assert any("dropSet" in str(spec.pre_capture_js) for spec in ATTACHMENT_CHECK_SPECS)
    assert any("installFakeChatSubmit" in str(spec.pre_capture_js) for spec in ATTACHMENT_CHECK_SPECS)
    assert any("chat_mode" in "".join(spec.extra_init_scripts) for spec in ATTACHMENT_CHECK_SPECS)


def test_project_workspace_specs_have_assertions_and_artifacts():
    resolved = resolve_specs(
        PROJECT_WORKSPACE_SPECS,
        {
            "project_workspace": "channel-1",
            "project_workspace_project": "project-1",
            "project_workspace_blueprint": "blueprint-1",
            "project_workspace_blueprint_project": "blueprint-project-1",
        },
    )

    assert {spec.output for spec in resolved} == {
        "project-workspace-list.png",
        "project-workspace-detail.png",
        "project-workspace-blueprints.png",
        "project-workspace-blueprint-editor.png",
        "project-workspace-settings-blueprint.png",
        "project-workspace-terminal.png",
        "project-workspace-channels.png",
        "project-workspace-channel-settings.png",
        "project-workspace-memory-tool.png",
    }
    assert all(spec.assert_js for spec in resolved)
    routes = {spec.name: spec.route for spec in resolved}
    assert routes["project-workspace-detail"] == "/admin/projects/project-1"
    assert routes["project-workspace-blueprints"] == "/admin/projects/blueprints"
    assert routes["project-workspace-blueprint-editor"] == "/admin/projects/blueprints/blueprint-1"
    assert routes["project-workspace-settings-blueprint"] == "/admin/projects/blueprint-project-1#Settings"
    assert routes["project-workspace-terminal"] == "/admin/projects/project-1#Terminal"
    assert routes["project-workspace-channels"] == "/admin/projects/project-1#Channels"
    assert routes["project-workspace-channel-settings"] == "/channels/channel-1/settings#agent"
    assert routes["project-workspace-memory-tool"] == "/channels/channel-1"


def test_channel_widget_usefulness_specs_have_assertions_and_artifacts():
    resolved = resolve_specs(
        CHANNEL_WIDGET_USEFULNESS_SPECS,
        {"channel_widget_usefulness": "channel-1"},
    )

    assert {spec.output for spec in resolved} == {
        "channel-widget-usefulness-dashboard.png",
        "channel-widget-usefulness-drawer.png",
        "channel-widget-usefulness-settings.png",
    }
    assert all(spec.assert_js for spec in resolved)
    routes = {spec.name: spec.route for spec in resolved}
    assert routes["channel-widget-usefulness-dashboard"] == "/widgets/channel/channel-1"
    assert routes["channel-widget-usefulness-settings"] == "/channels/channel-1/settings#dashboard"


def test_resolve_specs_preserves_assertions():
    resolved = {s.name: s for s in resolve_specs(SPATIAL_CHECK_SPECS, {})}
    original = {s.name: s for s in SPATIAL_CHECK_SPECS}
    for name, spec in resolved.items():
        assert spec.assert_js == original[name].assert_js


def test_resolve_specs_preserves_attachment_assertions():
    resolved = {s.name: s for s in resolve_specs(ATTACHMENT_CHECK_SPECS, {"attachments": "abc"})}
    original = {s.name: s for s in ATTACHMENT_CHECK_SPECS}
    for name, spec in resolved.items():
        assert spec.route == "/channels/abc"
        assert spec.assert_js == original[name].assert_js


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


def test_harness_live_question_specs_are_opt_in():
    with patch.dict(os.environ, {}, clear=True):
        assert harness_live._question_specs("http://ui", "channel-1") == []

    with patch.dict(os.environ, {"HARNESS_VISUAL_QUESTION_SESSION_ID": "session-1"}, clear=True):
        specs = harness_live._question_specs("http://ui", "channel-1")

    assert [spec.name for spec in specs] == [
        "harness-question-default-dark",
        "harness-question-default-light",
        "harness-question-terminal-dark",
    ]
    assert all(spec.route == "http://ui/channels/channel-1/session/session-1" for spec in specs)
    assert [spec.chat_mode for spec in specs] == ["default", "default", "terminal"]


def test_harness_live_style_command_specs_type_slash_query():
    specs = harness_live._style_command_specs("http://ui", "channel-1", "session-1")

    assert [spec.name for spec in specs] == [
        "harness-style-command-default-dark",
        "harness-style-command-terminal-dark",
    ]
    assert all(spec.route == "http://ui/channels/channel-1/session/session-1" for spec in specs)
    assert [spec.chat_mode for spec in specs] == ["default", "terminal"]
    assert all(spec.slash_query == "/style" for spec in specs)
    assert all("Switch chat style" in spec.contains for spec in specs)


def test_harness_live_native_slash_specs_use_clean_runtime_sessions():
    specs = harness_live._native_slash_specs(
        "http://ui",
        codex_channel_id="codex-channel",
        codex_session_id="codex-session",
        claude_channel_id="claude-channel",
        claude_session_id="claude-session",
    )

    assert [spec.name for spec in specs] == [
        "harness-native-slash-picker-dark",
        "harness-codex-native-plugins-result-dark",
        "harness-codex-native-plugin-install-handoff-dark",
        "harness-claude-native-skills-result-dark",
    ]
    assert specs[0].route == "http://ui/channels/codex-channel/session/codex-session"
    assert specs[1].route == "http://ui/channels/codex-channel/session/codex-session"
    assert specs[2].route == "http://ui/channels/codex-channel/session/codex-session"
    assert specs[3].route == "http://ui/channels/claude-channel/session/claude-session"
    assert specs[0].submit_slash is False
    assert specs[1].slash_query == "/plugins"
    assert specs[1].submit_slash is True
    assert specs[2].slash_query == "/plugins install spindrel-fixture-nonexistent"
    assert specs[2].submit_slash is True
    assert "codex plugin install spindrel-fixture-nonexistent" in specs[2].contains
    assert specs[3].slash_query == "/skills"
    assert specs[3].submit_slash is True
    assert specs[3].submit_ready_js
    assert "Claude Code" in specs[3].contains


def test_harness_live_claude_custom_skill_spec_targets_preseeded_session():
    specs = harness_live._claude_custom_skill_specs(
        "http://ui",
        "channel-1",
        "session-1",
        expected_phrase="NATIVE-SKILL-SCREENSHOT-test",
    )

    assert [spec.name for spec in specs] == ["harness-claude-native-custom-skill-result-dark"]
    assert specs[0].route == "http://ui/channels/channel-1/session/session-1"
    assert specs[0].slash_query is None
    assert specs[0].submit_slash is False
    assert "NATIVE-SKILL-SCREENSHOT-test" in specs[0].contains


def test_harness_live_project_terminal_specs_are_docs_fixtures():
    target = harness_live.RuntimeTarget(
        name="claude",
        channel_id="channel-1",
        bridge_label_fragment="Bridge parity diagnostic",
        write_label_fragment="Use the Spindrel host file bridge tool",
        project_label_fragment="Harness Project Parity",
    )

    specs = harness_live._project_terminal_specs("http://ui", target, "session-1")

    assert [spec.name for spec in specs] == ["harness-claude-project-terminal"]
    assert specs[0].route == "http://ui/channels/channel-1/session/session-1"
    assert specs[0].chat_mode == "terminal"
    assert "Harness Project Parity" in specs[0].contains
    assert "tool calls" in specs[0].not_contains


def test_harness_live_native_edit_terminal_spec_requires_diff_output():
    specs = harness_live._native_edit_terminal_specs("http://ui", "channel-1", "session-1")

    assert [spec.name for spec in specs] == ["harness-claude-native-edit-terminal"]
    assert specs[0].route == "http://ui/channels/channel-1/session/session-1"
    assert specs[0].chat_mode == "terminal"
    assert "Before native diff" in specs[0].wait_js
    assert "After native diff" in specs[0].contains


def test_harness_live_filter_specs_accepts_exact_names_and_globs():
    specs = [
        harness_live.CaptureSpec(
            name="harness-codex-terminal-write",
            route="http://ui",
            wait_js="true",
            contains=(),
        ),
        harness_live.CaptureSpec(
            name="harness-claude-native-edit-terminal",
            route="http://ui",
            wait_js="true",
            contains=(),
        ),
        harness_live.CaptureSpec(
            name="harness-claude-mobile-context",
            route="http://ui",
            wait_js="true",
            contains=(),
        ),
    ]

    exact = harness_live._filter_specs(specs, "harness-claude-native-edit-terminal")
    globbed = harness_live._filter_specs(specs, "harness-*-terminal*")
    combined = harness_live._filter_specs(specs, "harness-codex-*,harness-claude-mobile-context")

    assert [spec.name for spec in exact] == ["harness-claude-native-edit-terminal"]
    assert [spec.name for spec in globbed] == [
        "harness-codex-terminal-write",
        "harness-claude-native-edit-terminal",
    ]
    assert [spec.name for spec in combined] == [
        "harness-codex-terminal-write",
        "harness-claude-mobile-context",
    ]


def test_harness_live_mobile_context_specs_are_docs_fixtures():
    target = harness_live.RuntimeTarget(
        name="codex",
        channel_id="channel-1",
        bridge_label_fragment="Bridge parity diagnostic",
        write_label_fragment="Use the Spindrel host file bridge tool",
        project_label_fragment="Harness Project Parity",
    )

    specs = harness_live._mobile_context_specs("http://ui", target, "session-1")

    assert [spec.name for spec in specs] == ["harness-codex-mobile-context"]
    assert specs[0].route == "http://ui/channels/channel-1/session/session-1"
    assert specs[0].chat_mode == "terminal"
    assert specs[0].viewport == (390, 844)
    assert specs[0].click_selector == harness_live.HARNESS_CONTEXT_CHIP_SELECTOR
    assert specs[0].after_click_selector == '[data-testid="harness-context-panel-mobile"], [data-testid="harness-context-panel"]'
    assert "harness-context-chip-mobile" in specs[0].wait_js
    assert "harness-context-panel-mobile" in specs[0].after_click_wait_js
    assert "getBoundingClientRect" in specs[0].after_click_wait_js
    assert "Harness context" in specs[0].contains


def test_harness_live_usage_log_specs_target_harness_channel():
    specs = harness_live._usage_log_specs("http://ui", "channel-1")

    assert [spec.name for spec in specs] == [
        "harness-usage-logs-dark",
        "harness-usage-logs-light",
    ]
    assert all(spec.route == "http://ui/admin/usage?channel_id=channel-1&after=30d#Logs" for spec in specs)
    assert all("harness sdk" in spec.wait_js for spec in specs)
    assert all("harness SDK" in spec.contains for spec in specs)


def test_harness_live_capture_sets_page_viewport_for_cdp_runtime():
    source = inspect.getsource(harness_live._capture_one)

    assert source.count("page.set_viewport_size") >= 2
    assert '"width": spec.viewport[0]' in source
    assert '"height": spec.viewport[1]' in source
    assert "viewport={" not in source


def test_harness_live_plan_mode_switcher_specs_are_docs_fixtures():
    target = harness_live.RuntimeTarget(
        name="claude",
        channel_id="channel-1",
        bridge_label_fragment="Bridge parity diagnostic",
        write_label_fragment="Use the Spindrel host file bridge tool",
        project_label_fragment="Harness Project Parity",
    )

    specs = harness_live._plan_mode_switcher_specs("http://ui", target, "session-1")

    assert [spec.name for spec in specs] == ["harness-claude-plan-mode-switcher"]
    assert specs[0].route == "http://ui/channels/channel-1/session/session-1"
    assert specs[0].chat_mode == "terminal"
    assert specs[0].click_selector == '[data-testid="composer-plan-mode-control"]'
    assert "Harness Project Parity" in specs[0].wait_js
    assert "Harness Project Parity" in specs[0].contains
    assert "plan mode" in specs[0].contains


def test_harness_live_parse_allows_browser_visible_url():
    env = {
        "SPINDREL_API_KEY": "test-key",
        "SPINDREL_URL": "http://127.0.0.1:8000",
        "SPINDREL_UI_URL": "http://127.0.0.1:8000",
        "SPINDREL_BROWSER_URL": "http://172.18.0.1:8000",
    }

    with patch.dict(os.environ, env, clear=True):
        args = harness_live._parse([])

    assert args.api_url == "http://127.0.0.1:8000"
    assert args.ui_url == "http://127.0.0.1:8000"
    assert args.browser_url == "http://172.18.0.1:8000"
    assert args.browser_api_url == "http://172.18.0.1:8000"
    assert args.output_dir == "/tmp/spindrel-harness-live-screenshots"


def test_harness_live_terminal_write_rejects_compact_tool_tape():
    assert "tool calls" in harness_live.TERMINAL_WRITE_NOT_CONTAINS


def test_spindrel_plan_live_loads_session_artifact(tmp_path):
    path = tmp_path / "sessions.json"
    path.write_text(json.dumps({
        "channel_id": "channel-1",
        "question_session_id": "question-1",
        "plan_session_id": "plan-1",
        "answered_session_id": "answered-1",
        "progress_session_id": "progress-1",
        "replan_session_id": "replan-1",
        "pending_session_id": "pending-1",
        "updated_at": 123,
    }))

    data = spindrel_plan_live._load_session_artifact(path)

    assert data["channel_id"] == "channel-1"
    assert data["question_session_id"] == "question-1"
    assert data["plan_session_id"] == "plan-1"
    assert data["answered_session_id"] == "answered-1"
    assert data["progress_session_id"] == "progress-1"
    assert data["replan_session_id"] == "replan-1"
    assert data["pending_session_id"] == "pending-1"
    assert data["updated_at"] == "123"


def test_spindrel_plan_live_builds_expected_specs():
    specs = spindrel_plan_live._build_specs(
        "http://ui",
        channel_id="channel-1",
        question_session_id="question-1",
        plan_session_id="plan-1",
        answered_session_id="answered-1",
        progress_session_id="progress-1",
        replan_session_id="replan-1",
        pending_session_id="pending-1",
    )

    assert [spec.name for spec in specs] == [
        "spindrel-plan-question-card-dark",
        "spindrel-plan-card-default-dark",
        "spindrel-plan-card-mobile-dark",
        "spindrel-plan-card-terminal-dark",
        "spindrel-plan-answered-questions-dark",
        "spindrel-plan-answered-questions-terminal-dark",
        "spindrel-plan-progress-executing-mobile-dark",
        "spindrel-plan-progress-executing-terminal-dark",
        "spindrel-plan-replan-pending-default-dark",
        "spindrel-plan-replan-pending-terminal-dark",
        "spindrel-plan-pending-outcome-default-dark",
        "spindrel-plan-pending-outcome-terminal-dark",
    ]
    assert specs[0].route == "http://ui/channels/channel-1/session/question-1"
    assert specs[1].route == "http://ui/channels/channel-1/session/plan-1"
    assert specs[2].viewport == (390, 844)
    assert specs[3].chat_mode == "terminal"
    assert specs[4].route == "http://ui/channels/channel-1/session/answered-1"
    assert specs[5].chat_mode == "terminal"
    assert specs[6].route == "http://ui/channels/channel-1/session/progress-1"
    assert specs[6].viewport == (390, 844)
    assert specs[7].chat_mode == "terminal"
    assert specs[8].route == "http://ui/channels/channel-1/session/replan-1"
    assert specs[9].chat_mode == "terminal"
    assert specs[10].route == "http://ui/channels/channel-1/session/pending-1"
    assert specs[11].chat_mode == "terminal"
    assert specs[1].scroll_text == "Native Spindrel Plan Parity"
    assert all("harness sdk" in spec.not_contains for spec in specs)
    assert [spec.chat_mode for spec in specs] == [
        "default",
        "default",
        "default",
        "terminal",
        "default",
        "terminal",
        "default",
        "terminal",
        "default",
        "terminal",
        "default",
        "terminal",
    ]


def test_spindrel_plan_live_parse_allows_browser_visible_url():
    env = {
        "SPINDREL_API_KEY": "test-key",
        "SPINDREL_URL": "http://127.0.0.1:8000",
        "SPINDREL_UI_URL": "http://127.0.0.1:8000",
        "SPINDREL_BROWSER_URL": "http://172.18.0.1:8000",
        "SPINDREL_PLAN_CHANNEL_ID": "channel-1",
        "SPINDREL_PLAN_SESSIONS_JSON": "/tmp/sessions.json",
    }

    with patch.dict(os.environ, env, clear=True):
        args = spindrel_plan_live._parse([])

    assert args.api_url == "http://127.0.0.1:8000"
    assert args.browser_url == "http://172.18.0.1:8000"
    assert args.browser_api_url == "http://172.18.0.1:8000"
    assert args.channel_id == "channel-1"
    assert args.sessions_json == "/tmp/sessions.json"


def test_playwright_runtime_candidates_prefer_remote_then_runtime_then_executable(monkeypatch):
    runtime_candidate = playwright_runtime.BrowserLaunchCandidate(
        kind="remote",
        source="runtime-service:browser.playwright",
        endpoint="ws://playwright-local:3000",
        protocol="cdp",
    )
    monkeypatch.setattr(playwright_runtime, "_runtime_service_candidate", lambda: runtime_candidate)
    env = {
        "PLAYWRIGHT_WS_URL": "ws://explicit:3000",
        "PLAYWRIGHT_CONNECT_PROTOCOL": "playwright",
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE": "/snap/bin/chromium",
    }

    with patch.dict(os.environ, env, clear=True):
        candidates = playwright_runtime.launch_candidates()

    assert [(c.source, c.endpoint, c.executable_path) for c in candidates] == [
        ("PLAYWRIGHT_WS_URL", "ws://explicit:3000", None),
        ("runtime-service:browser.playwright", "ws://playwright-local:3000", None),
        ("PLAYWRIGHT_CHROMIUM_EXECUTABLE", None, "/snap/bin/chromium"),
        ("playwright-managed", None, None),
    ]


def test_playwright_runtime_uses_explicit_remote_before_local_executable(monkeypatch):
    monkeypatch.setattr(playwright_runtime, "_runtime_service_candidate", lambda: None)
    chromium = _SyncChromium()
    pw = _SyncPlaywright(chromium)

    with patch.dict(
        os.environ,
        {
            "PLAYWRIGHT_WS_URL": "ws://explicit:3000",
            "PLAYWRIGHT_CONNECT_PROTOCOL": "cdp",
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE": "/snap/bin/chromium",
        },
        clear=True,
    ):
        browser = playwright_runtime.launch_sync_browser(pw)

    assert browser == "cdp:ws://explicit:3000"
    assert chromium.calls == [("connect_over_cdp", {"endpoint": "ws://explicit:3000"})]


def test_playwright_runtime_falls_back_to_explicit_executable(monkeypatch):
    monkeypatch.setattr(playwright_runtime, "_runtime_service_candidate", lambda: None)
    chromium = _SyncChromium(fail_connect=True)
    pw = _SyncPlaywright(chromium)

    with patch.dict(
        os.environ,
        {
            "PLAYWRIGHT_WS_URL": "ws://down:3000",
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE": "/snap/bin/chromium",
        },
        clear=True,
    ):
        browser = playwright_runtime.launch_sync_browser(pw)

    assert browser == {"launch": {"headless": True, "executable_path": "/snap/bin/chromium"}}
    assert [call[0] for call in chromium.calls] == ["connect", "connect_over_cdp", "launch"]


def test_playwright_runtime_missing_managed_browser_error_is_actionable(monkeypatch):
    monkeypatch.setattr(playwright_runtime, "_runtime_service_candidate", lambda: None)
    chromium = _SyncChromium(fail_launch=True)
    pw = _SyncPlaywright(chromium)

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match="python -m playwright install chromium"):
            playwright_runtime.launch_sync_browser(pw)
