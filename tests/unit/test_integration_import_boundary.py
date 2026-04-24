"""Integration boundary guard.

Integrations should consume app-owned behavior through ``integrations.sdk``.
The allowlist below records existing debt so this test blocks new direct
``app.*`` imports without pretending the current tree is already clean.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATIONS_ROOT = REPO_ROOT / "integrations"

_ALLOWLIST = {
    "__init__.py",
    "bluebubbles/echo_tracker.py",
    "bluebubbles/hooks.py",
    "bluebubbles/renderer.py",
    "bluebubbles/router.py",
    "bluebubbles/tools/bluebubbles.py",
    "browser_live/router.py",
    "claude_code/executor.py",
    "claude_code/runner.py",
    "claude_code/tools/run_claude_code.py",
    "discord/approval_suggestions_helper.py",
    "discord/client.py",
    "discord/hooks.py",
    "discord/renderer.py",
    "discord/router.py",
    "excalidraw/tools/excalidraw.py",
    "frigate/router.py",
    "frigate/tools/frigate.py",
    "frigate/widget_transforms.py",
    "github/renderer.py",
    "google_workspace/router.py",
    "google_workspace/tools/gws.py",
    "local_companion/machine_control.py",
    "local_companion/router.py",
    "slack/client.py",
    "slack/hooks.py",
    "slack/message_handlers.py",
    "slack/renderer.py",
    "slack/router.py",
    "slack/uploads.py",
    "slack/web_api.py",
    "ssh/machine_control.py",
    "utils.py",
    "web_search/config.py",
    "web_search/tools/web_search.py",
    "wyoming/config.py",
    "wyoming/router.py",
}


def _direct_app_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "app" or node.module.startswith("app."):
                imports.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app" or alias.name.startswith("app."):
                    imports.append(alias.name)
    return imports


def test_no_new_direct_app_imports_under_integrations() -> None:
    offenders: list[str] = []
    for path in sorted(INTEGRATIONS_ROOT.rglob("*.py")):
        rel = path.relative_to(INTEGRATIONS_ROOT).as_posix()
        if rel == "sdk.py" or "/tests/" in f"/{rel}":
            continue
        imports = _direct_app_imports(path)
        if imports and rel not in _ALLOWLIST:
            offenders.append(f"{rel}: {sorted(set(imports))}")

    assert not offenders, (
        "New direct app.* imports under integrations must go through "
        "integrations.sdk or be added to the tracked allowlist:\n"
        + "\n".join(offenders)
    )
