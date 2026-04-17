"""Pure validator for widget template packages.

Used by the ``/validate``, ``/preview``, and save endpoints, and by the
seeder when ingesting YAML. No DB access, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class ValidationIssue:
    phase: str  # "yaml" | "python" | "schema"
    message: str
    line: int | None = None
    severity: str = "error"  # "error" | "warning"


@dataclass
class ValidationResult:
    ok: bool
    template: dict | None = None
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)


def validate_package(yaml_template: str, python_code: str | None = None) -> ValidationResult:
    """Parse + validate a package body; return a ValidationResult.

    Never raises — all problems are reported as issues. A WIP package that
    references ``self:foo`` with no matching function produces a warning,
    not an error, so users can save in-progress work.
    """
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    try:
        parsed = yaml.safe_load(yaml_template)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark else None
        errors.append(ValidationIssue("yaml", str(exc), line=line))
        return ValidationResult(ok=False, errors=errors)

    if not isinstance(parsed, dict):
        errors.append(ValidationIssue("yaml", "Package YAML must be a mapping"))
        return ValidationResult(ok=False, errors=errors)

    template = parsed.get("template")
    if not isinstance(template, dict):
        errors.append(ValidationIssue("schema", "Missing required 'template' mapping"))
    else:
        if template.get("v") != 1:
            errors.append(ValidationIssue(
                "schema", "template.v must be 1 (the only supported schema version)",
            ))
        components = template.get("components")
        if not isinstance(components, list):
            errors.append(ValidationIssue(
                "schema", "template.components must be a list",
            ))

    transform_ref = parsed.get("transform")
    if transform_ref is not None and not _is_valid_ref(transform_ref):
        errors.append(ValidationIssue(
            "schema",
            "transform must be a 'module:func' or 'self:func' string",
        ))

    state_poll = parsed.get("state_poll")
    if state_poll is not None:
        if not isinstance(state_poll, dict):
            errors.append(ValidationIssue("schema", "state_poll must be a mapping"))
        else:
            sp_template = state_poll.get("template")
            if not isinstance(sp_template, dict):
                errors.append(ValidationIssue(
                    "schema", "state_poll.template must be a mapping",
                ))
            elif sp_template.get("v") != 1:
                errors.append(ValidationIssue(
                    "schema", "state_poll.template.v must be 1",
                ))
            sp_transform = state_poll.get("transform")
            if sp_transform is not None and not _is_valid_ref(sp_transform):
                errors.append(ValidationIssue(
                    "schema",
                    "state_poll.transform must be a 'module:func' or 'self:func' string",
                ))
            interval = state_poll.get("refresh_interval_seconds")
            if interval is not None:
                if not isinstance(interval, int) or interval < 1:
                    errors.append(ValidationIssue(
                        "schema",
                        "state_poll.refresh_interval_seconds must be a positive integer",
                    ))

    if python_code is not None and python_code.strip():
        try:
            compile(python_code, "<widget_package>", "exec")
        except SyntaxError as exc:
            errors.append(ValidationIssue(
                "python",
                f"SyntaxError: {exc.msg}",
                line=exc.lineno,
            ))

    self_refs = _collect_self_refs(parsed)
    defined_names = _extract_top_level_names(python_code)
    for ref in self_refs:
        if ref not in defined_names:
            warnings.append(ValidationIssue(
                "python",
                f"YAML references 'self:{ref}' but Python code does not define '{ref}'",
                severity="warning",
            ))

    return ValidationResult(
        ok=not errors,
        template=parsed if not errors else None,
        errors=errors,
        warnings=warnings,
    )


def _is_valid_ref(ref: Any) -> bool:
    return isinstance(ref, str) and ":" in ref and not ref.startswith(":") and not ref.endswith(":")


def _collect_self_refs(parsed: dict) -> set[str]:
    refs: set[str] = set()
    for key in ("transform",):
        v = parsed.get(key)
        if isinstance(v, str) and v.startswith("self:"):
            refs.add(v.split(":", 1)[1])
    state_poll = parsed.get("state_poll")
    if isinstance(state_poll, dict):
        v = state_poll.get("transform")
        if isinstance(v, str) and v.startswith("self:"):
            refs.add(v.split(":", 1)[1])
    return refs


def _extract_top_level_names(code: str | None) -> set[str]:
    """AST-walk the module for top-level `def` / assignments.

    Tolerates compilation errors (already reported as a separate issue).
    """
    if not code or not code.strip():
        return set()
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names
