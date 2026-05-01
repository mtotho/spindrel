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
    "_ask_targets_for_channel": "discord/slack parallel ask-targets adapter",
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


# ---------------------------------------------------------------------------
# Structural-twin gate
#
# Catches the inverse smell that ``ALLOWED_DUPLICATES`` lets through: two
# integrations defining helpers with **different names** but **identical
# normalized AST bodies**. The 2026-05-01 audit found 32 baseline clusters
# at the time this gate was introduced. Those are recorded in
# ``ALLOWED_STRUCTURAL_TWINS`` keyed by AST-normalized hash. The hash uses
# anonymized arg/local names and elided constants, so it stays stable when
# the bodies are reformatted but flips the moment a body genuinely diverges
# (which would invalidate the rationale and force a re-review).
# ---------------------------------------------------------------------------


_MIN_TWIN_BODY_STMTS = 3


class _BodyNormalizer(ast.NodeTransformer):
    """Anonymize args/locals and elide constants for stable structural hashing."""

    def __init__(self) -> None:
        self._renames: dict[str, str] = {}
        self._counter = 0

    def _slot(self, name: str) -> str:
        if name not in self._renames:
            self._renames[name] = f"v{self._counter}"
            self._counter += 1
        return self._renames[name]

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = self._slot(node.arg)
        node.annotation = None
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self._renames:
            node.id = self._renames[node.id]
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        return ast.Constant(value="CONST")

    def visit_Assign(self, node: ast.Assign) -> ast.AST:
        for target in node.targets:
            self._register_targets(target)
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        node.annotation = ast.Constant(value="CONST")
        self._register_targets(node.target)
        return self.generic_visit(node)

    def _register_targets(self, target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            self._slot(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._register_targets(elt)


def _function_body_hash(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # strip docstring
    if len(body) < _MIN_TWIN_BODY_STMTS:
        return None
    fresh = ast.parse(ast.unparse(ast.Module(body=body, type_ignores=[])))
    _BodyNormalizer().visit(fresh)
    ast.fix_missing_locations(fresh)
    import hashlib  # local to keep top-of-file imports unchanged
    return hashlib.sha256(ast.dump(fresh).encode()).hexdigest()[:16]


def _collect_helpers_by_signature_hash() -> dict[str, list[tuple[str, Path, str]]]:
    """Returns ``{hash: [(integration_id, path, func_name), ...]}``."""
    out: dict[str, list[tuple[str, Path, str]]] = collections.defaultdict(list)
    for path in sorted(INTEGRATIONS_ROOT.rglob("*.py")):
        rel_parts = path.relative_to(INTEGRATIONS_ROOT).parts
        if not rel_parts:
            continue
        if len(rel_parts) == 1 and rel_parts[0] in _INFRASTRUCTURE_FILES:
            continue
        if any(part in _SKIP_DIR_PARTS for part in rel_parts):
            continue
        integration_id = rel_parts[0]
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            h = _function_body_hash(node)
            if h is None:
                continue
            out[h].append((integration_id, path, node.name))
    return out


# Baseline of cross-integration structural twins as of 2026-05-01. New
# entries should be rare; if a hash collision shows up that isn't on this
# list, lift the helper into ``integrations/sdk.py``. If it's a deliberate
# parallel-platform shape (Discord/Slack/BlueBubbles), add a new entry with
# the same terse-rationale style as ``ALLOWED_DUPLICATES``.
ALLOWED_STRUCTURAL_TWINS: dict[str, str] = {
    # discord/slack platform-adapter parallels — same shape by design.
    "01d148a4da26479b": "discord/slack parallel _resolve_dispatch_config",
    "03040e9fc326cd78": "discord/slack parallel get_channel_settings client",
    "04c2a3ccfdf46c59": "discord/slack parallel cancel_session client",
    "0c93ca4577b4fbb8": "discord/slack parallel format_thinking platform formatters",
    "0fec5293a010c918": "discord/slack parallel _emoji_for_tool",
    "1911e196123c8cd3": "discord/slack parallel fetch_session_context[_diagnostics] client",
    "2201d0155eb74574": "discord/slack parallel compact_session client",
    "2b8638a5f42d92d3": "discord/slack parallel submit_chat client",
    "30e65671e7d5ec92": "discord/slack parallel set_global_setting state",
    "3163b0ad3547e3ca": "discord/slack parallel _fetch_*_config_sync settings",
    "3ca385bcfb906bc8": "discord/slack parallel set_channel_state",
    "48e35b6d067a0bde": "discord/slack parallel _truncate (different char limits)",
    "5648760abb9d9868": "discord/slack parallel _load_state",
    "6f758435893443aa": "discord/slack parallel format_tool_status",
    "a0f5af014e242b5e": "discord/slack parallel post_chat client",
    "a5dffdc801a23d7a": "discord/slack parallel update_channel_settings client",
    "b6a75eceb12bd0de": "discord/slack parallel fetch_session_context_compressed",
    "c68272e4596b8190": "discord/slack parallel _get_audit_channel",
    "d10bbbc2c71c7b13": "discord/slack parallel _evict_stale_reactions",
    "e32329ca1ef14c18": "discord/slack parallel list_bots/list_models client",
    "e74bdf15ee7a5fd3": "discord/slack parallel _fetch_*_config_async settings",
    "e7efb60ec2d6902d": "discord/slack parallel fetch_session_context_contents",
    "ec1eafe9eefd3d17": "discord/slack parallel truncate_for_stream",
    # bluebubbles parallels — message-shape ingest variants.
    "9a8e91dc0a7f6f6d": "bluebubbles/github platform-specific text splitter (different char limits)",
    "ca769b81115aa106": "bluebubbles/discord parallel store_passive_message[_http]",
    # local_companion/ssh machine-control adapter pair.
    "a95ee7263e8d80cf": "local_companion/ssh parallel _trim",
    # truenas/unifi parallel network-equipment integrations.
    "d88ee6258daef763": "truenas/unifi parallel parse_*_bool config coercion",
}


def test_no_unallowlisted_structural_twins() -> None:
    """Same-shape helpers with different names across integrations.

    Catches drift that the exact-name gate misses. A hash collision under
    different names in 2+ integrations means the bodies are AST-equivalent
    after argument/local-name anonymization. Either lift the helper into
    ``integrations/sdk.py`` or add the hash to ``ALLOWED_STRUCTURAL_TWINS``
    with a one-line rationale.
    """
    by_hash = _collect_helpers_by_signature_hash()
    offenders: list[str] = []
    for h, members in by_hash.items():
        integrations = {m[0] for m in members}
        if len(integrations) < 2:
            continue
        if h in ALLOWED_STRUCTURAL_TWINS:
            continue
        offenders.append(
            f"  hash={h} integrations={sorted(integrations)} "
            f"members={[(m[0], str(m[1].relative_to(REPO_ROOT)), m[2]) for m in members]}"
        )

    assert not offenders, (
        "Found cross-integration structural twins (same body, possibly "
        "different name). Lift to integrations/sdk.py, OR add the hash to "
        "ALLOWED_STRUCTURAL_TWINS with a one-line rationale.\n"
        + "\n".join(offenders)
    )


def test_structural_twin_allowlist_does_not_rot() -> None:
    """Drop allowlist entries when the underlying twin is gone."""
    by_hash = _collect_helpers_by_signature_hash()
    actual = {h for h, members in by_hash.items() if len({m[0] for m in members}) >= 2}
    stale = sorted(set(ALLOWED_STRUCTURAL_TWINS) - actual)
    assert not stale, (
        "ALLOWED_STRUCTURAL_TWINS contains hashes no longer present in the "
        "codebase — remove them:\n  " + "\n  ".join(stale)
    )
