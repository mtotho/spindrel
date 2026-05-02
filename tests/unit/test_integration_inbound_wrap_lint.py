"""AST lint: every ``submit_chat`` / ``inject_message`` caller in
``integrations/`` must tag a source recognized by
``EXTERNAL_UNTRUSTED_SOURCES``.

Companion to the R1 runtime wrap (``app/security/prompt_sanitize.py`` +
the ``_strip_metadata_keys`` history-replay path). The runtime is correct
for today's integrations but invisible at the source-tagging layer — a
typo (``"slak"``) or a new integration that forgets to set the source
silently bypasses the LLM-bound ``<untrusted-data>`` envelope.

The lint walks every ``.py`` under ``integrations/`` (excluding
infrastructure shims and ``__pycache__``/``tests``/``scripts``) and
flags any call that:

- ``inject_message(...)`` without a literal ``source="<x>"`` kwarg
  whose value is in ``EXTERNAL_UNTRUSTED_SOURCES``;
- ``submit_chat(...)`` without a literal
  ``msg_metadata={"source": "<x>", ...}`` (or a within-function
  ``msg_metadata = {"source": "<x>", ...}`` assignment) whose value
  is in ``EXTERNAL_UNTRUSTED_SOURCES``.

For ``submit_chat`` callers that pass ``msg_metadata`` as a variable,
the walker traces back through the enclosing function body looking for
either a literal-Dict assignment or a ``msg_metadata["source"] = "..."``
subscript assignment. If neither yields a literal, the call is flagged
as ``source_not_resolvable`` — forcing an explicit literal somewhere
inside the function body, which matches every current call site.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from app.security.prompt_sanitize import EXTERNAL_UNTRUSTED_SOURCES

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATIONS_ROOT = REPO_ROOT / "integrations"

_SKIP_DIR_PARTS = {"__pycache__", "tests", "node_modules", "scripts"}
# integrations/utils.py defines inject_message itself; sdk.py is shim/docs;
# tool_output.py / base.py / __init__.py are infra. None of these *call*
# submit_chat/inject_message in production paths.
_INFRASTRUCTURE_FILES = {
    "__init__.py",
    "sdk.py",
    "utils.py",
    "base.py",
    "tool_output.py",
}

_TARGET_NAMES = {"submit_chat", "inject_message"}

# (relpath_from_repo_root, lineno) -> reason. Empty at landing — every
# current call site resolves cleanly. Add an entry only when a new caller
# is genuinely-dynamic (e.g. fans out across configurable sources) and
# document why the runtime guarantees correctness anyway.
ALLOWED_VIOLATIONS: dict[tuple[str, int], str] = {}


# ---------------------------------------------------------------------------
# AST walker
# ---------------------------------------------------------------------------


def _is_target_call(node: ast.Call) -> str | None:
    """Return the target function name (``submit_chat``/``inject_message``)
    if ``node`` calls one of them, else None.

    Matches both ``Name`` (``submit_chat(...)``) and ``Attribute``
    (``utils.inject_message(...)``) call shapes.
    """
    func = node.func
    if isinstance(func, ast.Name) and func.id in _TARGET_NAMES:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in _TARGET_NAMES:
        return func.attr
    return None


def _kwarg(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _literal_str(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _source_from_dict(dict_node: ast.Dict) -> str | None:
    """Pull a literal ``"source": "<x>"`` entry out of a Dict literal."""
    for key, value in zip(dict_node.keys, dict_node.values):
        if isinstance(key, ast.Constant) and key.value == "source":
            literal = _literal_str(value)
            if literal is not None:
                return literal
    return None


def _trace_msg_metadata_var(
    func_body: list[ast.stmt], var_name: str, call_lineno: int
) -> str | None:
    """Walk a function body looking for the literal source assigned into
    a ``msg_metadata`` variable before ``call_lineno``.

    Two assignment shapes recognized:

    1. ``msg_metadata = {"source": "<x>", ...}`` — Dict literal RHS.
    2. ``msg_metadata["source"] = "<x>"`` — Subscript assignment.

    Returns the literal string or ``None`` if not statically resolvable.
    """
    last_dict_source: str | None = None
    last_subscript_source: str | None = None

    for stmt in ast.walk(ast.Module(body=func_body, type_ignores=[])):
        if not isinstance(stmt, ast.Assign):
            continue
        # Only consider assignments that occur before the call.
        if getattr(stmt, "lineno", 0) >= call_lineno:
            continue
        for target in stmt.targets:
            # msg_metadata = {...}
            if (
                isinstance(target, ast.Name)
                and target.id == var_name
                and isinstance(stmt.value, ast.Dict)
            ):
                got = _source_from_dict(stmt.value)
                if got is not None:
                    last_dict_source = got
            # msg_metadata["source"] = "..."
            elif (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == var_name
            ):
                key = target.slice
                if isinstance(key, ast.Constant) and key.value == "source":
                    literal = _literal_str(stmt.value)
                    if literal is not None:
                        last_subscript_source = literal

    # Subscript wins if it overrides the literal-Dict source after the dict
    # was assigned. Otherwise the dict source stands.
    return last_subscript_source or last_dict_source


def _resolve_source(
    call: ast.Call,
    target: str,
    enclosing_funcs: list[ast.FunctionDef | ast.AsyncFunctionDef],
) -> tuple[str, str | None]:
    """Resolve the source string for one call site.

    Returns ``(kind, value)`` where ``kind`` is one of
    ``"resolved"``, ``"missing_source"``, ``"source_not_resolvable"``.
    """
    if target == "inject_message":
        source_node = _kwarg(call, "source")
        if source_node is None:
            return ("missing_source", None)
        literal = _literal_str(source_node)
        if literal is None:
            return ("source_not_resolvable", None)
        return ("resolved", literal)

    # target == "submit_chat" — look at msg_metadata
    md_node = _kwarg(call, "msg_metadata")
    if md_node is None:
        return ("missing_source", None)
    if isinstance(md_node, ast.Dict):
        got = _source_from_dict(md_node)
        if got is None:
            return ("source_not_resolvable", None)
        return ("resolved", got)
    if isinstance(md_node, ast.Name):
        # Walk back through the innermost enclosing function.
        if not enclosing_funcs:
            return ("source_not_resolvable", None)
        innermost = enclosing_funcs[-1]
        traced = _trace_msg_metadata_var(
            innermost.body, md_node.id, call.lineno
        )
        if traced is None:
            return ("source_not_resolvable", None)
        return ("resolved", traced)
    return ("source_not_resolvable", None)


def scan_module(
    tree: ast.AST,
) -> list[tuple[int, str, str, str | None]]:
    """Return list of ``(lineno, target, kind, detail)`` for every
    ``submit_chat``/``inject_message`` call in the module.

    ``kind`` is ``"resolved"`` for OK call sites; the source string lands
    in ``detail``. For violations, ``kind`` is one of
    ``"unknown_source"`` / ``"missing_source"`` / ``"source_not_resolvable"``
    and ``detail`` is the bad value (or None).
    """
    findings: list[tuple[int, str, str, str | None]] = []
    enclosing: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit(node: ast.AST) -> None:
        pushed = False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            enclosing.append(node)
            pushed = True
        try:
            if isinstance(node, ast.Call):
                target = _is_target_call(node)
                if target is not None:
                    kind, value = _resolve_source(node, target, enclosing)
                    if kind == "resolved":
                        if value not in EXTERNAL_UNTRUSTED_SOURCES:
                            findings.append(
                                (node.lineno, target, "unknown_source", value)
                            )
                        else:
                            findings.append(
                                (node.lineno, target, "resolved", value)
                            )
                    else:
                        findings.append((node.lineno, target, kind, value))
            for child in ast.iter_child_nodes(node):
                visit(child)
        finally:
            if pushed:
                enclosing.pop()

    visit(tree)
    return findings


def _iter_integration_files() -> list[Path]:
    out: list[Path] = []
    for path in INTEGRATIONS_ROOT.rglob("*.py"):
        if any(part in _SKIP_DIR_PARTS for part in path.parts):
            continue
        if path.name in _INFRASTRUCTURE_FILES and path.parent == INTEGRATIONS_ROOT:
            # Top-level infra; integration-specific utils.py files (rare)
            # are still in scope.
            continue
        out.append(path)
    return out


# ---------------------------------------------------------------------------
# Production-tree assertion
# ---------------------------------------------------------------------------


def collect_violations(
    integrations_root: Path,
    repo_root: Path,
    allowlist: dict[tuple[str, int], str],
) -> list[tuple[str, int, str, str | None]]:
    """Walk integrations and return violations not covered by allowlist.

    Pure function — takes its inputs explicitly so tests can drive it
    against a synthetic tree without touching module globals.
    """
    skip_parts = _SKIP_DIR_PARTS
    infra_files = _INFRASTRUCTURE_FILES
    violations: list[tuple[str, int, str, str | None]] = []
    for path in integrations_root.rglob("*.py"):
        if any(part in skip_parts for part in path.parts):
            continue
        if path.name in infra_files and path.parent == integrations_root:
            continue
        rel = path.relative_to(repo_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, target, kind, detail in scan_module(tree):
            if kind == "resolved":
                continue
            if (rel, lineno) in allowlist:
                continue
            violations.append((rel, lineno, kind, detail))
    return violations


def test_every_call_site_resolves() -> None:
    """No untrusted-source violations across ``integrations/``."""
    violations = collect_violations(INTEGRATIONS_ROOT, REPO_ROOT, ALLOWED_VIOLATIONS)
    if violations:
        formatted = "\n".join(
            f"  {rel}:{ln} [{kind}] target source={detail!r}"
            for rel, ln, kind, detail in violations
        )
        allowed = sorted(EXTERNAL_UNTRUSTED_SOURCES)
        pytest.fail(
            "Integration submit_chat/inject_message call sites must tag "
            "a literal source in EXTERNAL_UNTRUSTED_SOURCES. Offenders:\n"
            f"{formatted}\n\n"
            f"Allowed sources: {allowed}"
        )


# ---------------------------------------------------------------------------
# Synthetic-AST self-tests — pin the walker so it can't degrade to a no-op.
# ---------------------------------------------------------------------------


def _scan_src(src: str) -> list[tuple[int, str, str, str | None]]:
    return scan_module(ast.parse(textwrap.dedent(src)))


class TestWalkerSelfTests:
    def test_inject_message_known_source_resolves(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                await inject_message(content="x", source="github")
            """
        )
        assert findings == [(3, "inject_message", "resolved", "github")]

    def test_inject_message_unknown_source_is_caught(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                await inject_message(content="x", source="slak")
            """
        )
        assert findings == [(3, "inject_message", "unknown_source", "slak")]

    def test_inject_message_missing_source_is_caught(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                await inject_message(content="x")
            """
        )
        assert findings == [(3, "inject_message", "missing_source", None)]

    def test_submit_chat_inline_dict_resolves(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                await submit_chat(
                    message="x",
                    msg_metadata={"source": "wyoming", "sender_type": "human"},
                )
            """
        )
        assert findings == [(3, "submit_chat", "resolved", "wyoming")]

    def test_submit_chat_var_traced_through_function(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                msg_metadata = {"source": "slack", "sender_type": "human"}
                await submit_chat(message="x", msg_metadata=msg_metadata)
            """
        )
        assert findings == [(4, "submit_chat", "resolved", "slack")]

    def test_submit_chat_var_subscript_assignment_traced(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                msg_metadata = {}
                msg_metadata["source"] = "discord"
                await submit_chat(message="x", msg_metadata=msg_metadata)
            """
        )
        assert findings == [(5, "submit_chat", "resolved", "discord")]

    def test_submit_chat_var_unresolvable_is_caught(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                msg_metadata = build_metadata()
                await submit_chat(message="x", msg_metadata=msg_metadata)
            """
        )
        assert findings == [(4, "submit_chat", "source_not_resolvable", None)]

    def test_submit_chat_unknown_source_in_dict_is_caught(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                msg_metadata = {"source": "slak"}
                await submit_chat(message="x", msg_metadata=msg_metadata)
            """
        )
        assert findings == [(4, "submit_chat", "unknown_source", "slak")]

    def test_submit_chat_missing_msg_metadata_is_caught(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                await submit_chat(message="x")
            """
        )
        assert findings == [(3, "submit_chat", "missing_source", None)]

    def test_attribute_inject_message_call_is_matched(self) -> None:
        findings = _scan_src(
            """
            async def handler():
                await utils.inject_message(content="x", source="frigate")
            """
        )
        assert findings == [(3, "inject_message", "resolved", "frigate")]


class TestAllowlistShortCircuit:
    """Confirm the collector respects the allowlist."""

    def test_allowlisted_violation_is_skipped(self, tmp_path: Path) -> None:
        # Synthesize a tiny "integration" that misuses submit_chat.
        fake_root = tmp_path / "integrations"
        (fake_root / "fakeint").mkdir(parents=True)
        bad = fake_root / "fakeint" / "router.py"
        bad.write_text(
            textwrap.dedent(
                """
                async def handler():
                    await inject_message(content="x", source="slak")
                """
            ).lstrip(),
            encoding="utf-8",
        )
        rel = bad.relative_to(tmp_path).as_posix()

        # Empty allowlist surfaces the violation.
        violations = collect_violations(fake_root, tmp_path, {})
        assert violations == [(rel, 2, "unknown_source", "slak")]

        # Allowlist entry suppresses the same violation.
        violations = collect_violations(
            fake_root, tmp_path, {(rel, 2): "synthetic test"}
        )
        assert violations == []
