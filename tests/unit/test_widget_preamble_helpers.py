"""Pin Phase A SDK helpers in the InteractiveHtmlRenderer bootstrap.

No Vitest/Jest is configured in `ui/`, so this presence-snapshot test is
the backstop against "someone ripped out `spindrel.bus`" regressions. It
reads the renderer source as text and asserts that each helper the skill
doc promises is defined and exported on ``window.spindrel``.

If a new helper lands or a name is renamed, update the asserts AND the
corresponding section in ``skills/widgets/`` (sub-files under the folder
skill — typically ``sdk.md`` or ``handlers.md``) in the same commit.

For behaviour-level coverage (bus round-trips, form submit paths, error
boundary), write a real UI test once vitest is wired — tracked in
``Track - Widget SDK`` Phase A follow-ups.
"""
from __future__ import annotations

from pathlib import Path

import pytest

RENDERER = Path(__file__).resolve().parents[2] / (
    "ui/src/components/chat/renderers/InteractiveHtmlRenderer.tsx"
)


@pytest.fixture(scope="module")
def source() -> str:
    assert RENDERER.exists(), f"renderer missing: {RENDERER}"
    return RENDERER.read_text()


# ── Helper *definitions* live inside the IIFE ─────────────────────────
HELPER_DEFINITIONS = [
    # Phase B.5 additions
    "function onReload",
    "function autoReload",
    "function __ensureReloadStream",
    # Phase B.2 additions
    "function callHandler",
    # Phase B.1 additions
    "function dbQuery",
    "function dbExec",
    "function dbTx",
    # Phase A additions
    "function busPublish",
    "function busSubscribe",
    "function stream",
    "function __streamNormalizeArgs",
    "function cacheGet",
    "function cacheSet",
    "function cacheClear",
    "function notify",
    "function uiStatus",
    "function uiTable",
    "function uiChart",
    "function stateLoad",
    "function stateSave",
    "function statePatch",
    "function form",
    # Pre-existing — listed so a careless refactor doesn't drop them silently
    "function callTool",
    "function dataLoad",
    "function dataPatch",
    "function renderMarkdown",
    "function loadAsset",
]


@pytest.mark.parametrize("needle", HELPER_DEFINITIONS)
def test_helper_function_defined(source: str, needle: str) -> None:
    assert needle in source, f"bootstrap missing helper definition: `{needle}`"


# ── window.spindrel exposure ──────────────────────────────────────────
# The assignment `window.spindrel = {...}` has each exposed helper. Match
# on the key name followed by a colon so we don't false-positive on a
# standalone identifier elsewhere.
SPINDREL_KEYS = [
    # Phase B.5
    "onReload:",
    "autoReload:",
    # Phase B.2
    "callHandler:",
    # Phase B.1
    "db:",
    # Phase A
    "bus:",
    "stream:",
    "cache:",
    "notify:",
    "log:",
    "ui:",
    "state:",
    "form:",
    # Pre-existing — regression guard
    "callTool:",
    "data:",
    "api:",
    "apiFetch:",
    "readWorkspaceFile:",
    "writeWorkspaceFile:",
    "loadAsset:",
    "renderMarkdown:",
    "onToolResult:",
    "onConfig:",
    "onTheme:",
]


@pytest.mark.parametrize("key", SPINDREL_KEYS)
def test_window_spindrel_exposes(source: str, key: str) -> None:
    # Grab the block between `window.spindrel = {` and the matching close
    # so we're only checking the public surface, not random colons inside
    # unrelated code.
    marker = "window.spindrel = {"
    start = source.index(marker)
    # Find the first `};` after the marker. Naive — works because the
    # object literal doesn't contain nested `};` at column-0 and the close
    # is `  };`.
    close = source.index("  };", start)
    block = source[start:close]
    assert key in block, f"window.spindrel missing key `{key}`"


# ── Error boundary: uncaught errors + rejections forwarded to host ────
def test_error_boundary_forwards_errors(source: str) -> None:
    assert 'window.addEventListener("error"' in source
    assert 'window.addEventListener("unhandledrejection"' in source
    # Both post to parent with __spindrel marker so the host listener can
    # filter by origin. If the marker name changes, the host receiver
    # below must change too.
    assert '__spindrel: true' in source
    assert 'type: "error"' in source


# ── Host-side postMessage receiver ────────────────────────────────────
# The receiver in the React component demultiplexes notify / log / error
# into toasts, the widget log ring, and the error banner respectively.
def test_host_receiver_wired(source: str) -> None:
    # message listener registered + scoped to iframe.contentWindow
    assert 'window.addEventListener("message"' in source
    assert "event.source !== iframe.contentWindow" in source
    # Three branches the iframe emits
    assert 'data.type === "notify"' in source
    assert 'data.type === "error"' in source
    assert 'data.type === "log"' in source
    # Reload affordance for the error banner — remounts the iframe via key
    assert "setReloadNonce" in source
    assert "widget-iframe-${reloadNonce}" in source
    # Log branch feeds the Dev Panel Widget log subtab via the store.
    # Route: iframe postMessage → pushWidgetLog({ts, level, message, pinId, …}).
    assert "pushWidgetLog" in source
    assert 'from "../../../stores/widgetLog"' in source


# ── Phase B.5: widget_reload auto-subscription wiring ────────────────
def test_widget_reload_kind_whitelisted(source: str) -> None:
    """`spindrel.stream("widget_reload", ...)` must not throw on unknown kind."""
    # The stream kind whitelist is a JS Set literal; a missing entry would
    # cause the `throw new Error("spindrel.stream: unknown event kind ...")`
    # path to fire. Pin the presence.
    assert '"widget_reload"' in source, "stream kind whitelist missing widget_reload"


def test_reload_stream_filters_by_pin_id(source: str) -> None:
    """The auto-subscription filter MUST compare payload.pin_id to dashboardPinId.

    Without the filter every pin of a bundle would reload whenever any peer
    called ctx.notify_reload() — a noisy multi-pin footgun. If this assertion
    fires, someone relaxed the filter; check that peer-pin sync still works
    via spindrel.bus instead.
    """
    assert "payload.pin_id === dashboardPinId" in source


def test_autoreload_runs_initial_render(source: str) -> None:
    """autoReload runs renderFn() once at registration — mount + reload share path.

    Concretely: autoReload's body calls `renderFn()` synchronously, handles a
    returned Promise, then delegates to onReload. Pin the outer call so a
    refactor that drops the initial render (making autoReload a plain alias
    for onReload) fails the snapshot.
    """
    # Find the autoReload function body and confirm it invokes renderFn()
    # before returning the onReload subscription.
    marker = "function autoReload("
    start = source.index(marker)
    end = source.index("\n  }\n", start)
    body = source[start:end]
    assert "renderFn()" in body, "autoReload no longer runs renderFn() on registration"
    assert "return onReload(" in body, "autoReload must delegate subscription to onReload"


# ── ui.chart is exposed on the nested ui: object, not the top level ──
def test_ui_chart_exposed_on_ui_namespace(source: str) -> None:
    # Find the `ui: {` block inside window.spindrel and assert `chart:` is
    # present. Narrow window so we don't pick up a `chart:` in some other
    # object literal by accident.
    marker = "ui: {"
    start = source.rindex(marker)
    close = source.index("}", start)
    block = source[start:close]
    assert "chart:" in block, "window.spindrel.ui missing `chart:` export"
    assert "status:" in block and "table:" in block, "ui namespace regressed"


# ── Skill doc must mention the new helpers so bots know they exist ────
# The skill was split from a single file (`skills/html_widgets.md`) into a
# folder (`skills/widgets/`) with per-topic sub-skills — each helper is
# documented somewhere under the folder, so the check reads every .md in
# the folder and asserts presence in the union.
_WIDGETS_SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "widgets"


def _skill_doc_text() -> str:
    assert _WIDGETS_SKILL_DIR.is_dir(), f"widgets skill folder missing: {_WIDGETS_SKILL_DIR}"
    parts = [p.read_text() for p in sorted(_WIDGETS_SKILL_DIR.rglob("*.md"))]
    return "\n\n".join(parts)


def test_skill_doc_documents_phase_a_helpers() -> None:
    text = _skill_doc_text()
    for needle in [
        "window.spindrel.db",
        "window.spindrel.bus",
        "window.spindrel.cache",
        "window.spindrel.notify",
        "window.spindrel.ui.table",
        "window.spindrel.ui.status",
        "window.spindrel.ui.chart",
        "window.spindrel.state",
        "window.spindrel.form",
        "window.spindrel.callHandler",
    ]:
        assert needle in text, f"skills/widgets/ missing docs for `{needle}`"
