"""Cross-integration duplicate-helper guard.

Companion to ``test_integration_import_boundary.py``. That test catches
integrations reaching *down* into ``app.*`` instead of the SDK. This
test catches the inverse smell: integrations growing the *same private
helper* in two places instead of lifting it into ``integrations.sdk``.

If the same private function name is defined under two distinct
integration packages, either:

1. Lift it into ``integrations/sdk.py`` and import it from both, or
2. Add the name to ``ALLOWED_DUPLICATES`` with a one-line reason.

The allowlist below is the snapshot of duplicates that existed when
this guard was introduced (2026-04-27). All of them are platform
adapters with parallel Discord/Slack/BlueBubbles shapes, or paired
Linux/SSH machine-control adapters — same shape repeated by design,
not by drift. New entries should justify themselves; the goal is to
catch the *next* ``_find_chrome_path``-style copy-paste, not relitigate
existing intentional parallels.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATIONS_ROOT = REPO_ROOT / "integrations"

# Files at the integrations/ root are infrastructure shims, not integrations.
_INFRASTRUCTURE_FILES = {"__init__.py", "sdk.py", "utils.py", "base.py", "tool_output.py"}
_SKIP_DIR_PARTS = {"__pycache__", "tests", "node_modules", "scripts"}

# Names duplicated across integrations that are intentional, not drift.
# Keep the rationale terse; if a new entry doesn't have an obvious one,
# lift the helper to the SDK instead of adding it here.
ALLOWED_DUPLICATES: dict[str, str] = {
    # Platform adapters with parallel chat-platform shapes (Discord/Slack/BlueBubbles).
    "_apply_fresh_config": "discord/slack parallel adapter shape",
    "_claims_user_id": "discord/slack/bluebubbles parallel adapter shape",
    "_decide": "discord/slack parallel approval-policy shape",
    "_decide_with_rule": "discord/slack parallel approval-policy shape",
    "_emoji_for_tool": "discord/slack parallel adapter shape",
    "_evict_stale_reactions": "discord/slack parallel adapter shape",
    "_get_audit_channel": "discord/slack parallel audit-channel shape",
    "_get_channel_map": "discord/slack parallel channel-map shape",
    "_get_default_bot": "discord/slack/bluebubbles parallel default-bot shape",
    "_load_state": "discord/slack parallel state-file shape",
    "_on_after_response": "discord/slack parallel hook shape",
    "_on_after_tool_call": "discord/slack parallel hook shape",
    "_on_audit_tool_call": "discord/slack parallel hook shape",
    "_resolve_dispatch_config": "discord/slack/bluebubbles parallel adapter shape",
    "_resolve_display_names": "discord/slack parallel adapter shape",
    "_resolve_session_id": "discord/slack parallel adapter shape",
    "_save_state": "discord/slack parallel state-file shape",
    "_update_message": "discord/slack parallel adapter shape",
    "_user_attribution": "discord/slack parallel adapter shape",
    # HTTP-style integrations each owning their own client surface.
    "_base_url": "arr/frigate/gmail private API client URL",
    "_get": "arr/frigate private API client GET",
    "_post": "arr/slack private API client POST",
    "_headers": "per-integration HTTP header builder (different auth)",
    "_truncate": "discord/slack/github platform-specific char limits",
    # Misc parallel patterns.
    "_register": "per-integration tool/skill registry init",
    "_extract_text": "bluebubbles/ingestion message-shape extractors",
    "_error": "bluebubbles/frigate private error helpers",
    "_build_execution_config": "frigate/github task-execution config builders",
    # Machine-control adapter pairs (local_companion + ssh).
    "_dump_targets": "local_companion/ssh parallel target persistence",
    "_parse_targets": "local_companion/ssh parallel target parsing",
    "_save_targets": "local_companion/ssh parallel target persistence",
    "_trim": "local_companion/ssh string trim helpers",
    "_utc_now_iso": "local_companion/ssh time helpers",
    # Sidecar containerized integrations.
    "_in_docker": "web_search/wyoming containerized-runtime probe",
    "_instance_id": "web_search/wyoming containerized-runtime probe",
}


def _top_level_private_defs(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and not node.name.startswith("__"):
                names.add(node.name)
    return names


def _collect_helpers_by_integration() -> dict[str, dict[str, list[Path]]]:
    """Returns ``{name: {integration_id: [paths...]}}``."""
    by_name: dict[str, dict[str, list[Path]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for path in sorted(INTEGRATIONS_ROOT.rglob("*.py")):
        rel_parts = path.relative_to(INTEGRATIONS_ROOT).parts
        if not rel_parts:
            continue
        if len(rel_parts) == 1 and rel_parts[0] in _INFRASTRUCTURE_FILES:
            continue
        if rel_parts[0] in _SKIP_DIR_PARTS:
            continue
        if any(part in _SKIP_DIR_PARTS for part in rel_parts):
            continue
        integration_id = rel_parts[0]
        for name in _top_level_private_defs(path):
            by_name[name][integration_id].append(path)
    return by_name


def test_no_new_cross_integration_duplicate_helpers() -> None:
    by_name = _collect_helpers_by_integration()

    offenders: list[str] = []
    for name, integrations in by_name.items():
        if len(integrations) < 2:
            continue
        if name in ALLOWED_DUPLICATES:
            continue
        ids = sorted(integrations.keys())
        offenders.append(f"  {name!r} defined in {ids}")

    assert not offenders, (
        "Found private helper(s) duplicated across integrations. Lift to "
        "integrations/sdk.py and import from both, OR add to "
        "ALLOWED_DUPLICATES in this test with a one-line rationale.\n"
        + "\n".join(offenders)
    )


def test_allowlist_does_not_rot() -> None:
    """Drop allowlist entries when the underlying duplicate is gone.

    Prevents the allowlist from becoming a graveyard of stale names that
    silently widen the test's blast radius.
    """
    by_name = _collect_helpers_by_integration()
    actual_dupes = {n for n, ints in by_name.items() if len(ints) >= 2}
    stale = sorted(set(ALLOWED_DUPLICATES) - actual_dupes)
    assert not stale, (
        "ALLOWED_DUPLICATES contains names no longer duplicated in the "
        "codebase — remove them:\n  " + "\n  ".join(stale)
    )
