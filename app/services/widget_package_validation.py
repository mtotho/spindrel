"""Pure validator for widget template packages.

Used by the ``/validate``, ``/preview``, and save endpoints, and by the
seeder when ingesting YAML. No DB access, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import ValidationError

from app.schemas.widget_components import (
    COMPONENT_MODELS,
    KNOWN_COMPONENT_TYPES,
    EachBlock,
)


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
    try:
        parsed = yaml.safe_load(yaml_template)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark else None
        return ValidationResult(
            ok=False, errors=[ValidationIssue("yaml", str(exc), line=line)],
        )

    if not isinstance(parsed, dict):
        return ValidationResult(
            ok=False, errors=[ValidationIssue("yaml", "Package YAML must be a mapping")],
        )

    errors, warnings = _validate_parsed_definition(parsed)

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


def _validate_parsed_definition(
    parsed: dict,
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """Validate an already-parsed widget definition dict.

    Extracted so the widget-template loader can validate on boot without
    re-serializing to YAML. Covers the schema phase only — Python code
    compilation + self-ref checks live in ``validate_package``.
    """
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

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
        else:
            c_errs, c_warns = _validate_component_list(components, path="template.components")
            errors.extend(c_errs)
            warnings.extend(c_warns)

    # Fragments (P1-1) — validate each body as a component (or list of them)
    # so typos in a fragment surface at registration, not when it's inlined.
    fragments = parsed.get("fragments")
    if fragments is not None:
        if not isinstance(fragments, dict):
            errors.append(ValidationIssue(
                "schema", "fragments must be a mapping",
            ))
        else:
            for name, body in fragments.items():
                if isinstance(body, dict):
                    c_errs, c_warns = _validate_component_list(
                        [body], path=f"fragments.{name}",
                    )
                    errors.extend(c_errs)
                    warnings.extend(c_warns)
                elif isinstance(body, list):
                    c_errs, c_warns = _validate_component_list(
                        body, path=f"fragments.{name}",
                    )
                    errors.extend(c_errs)
                    warnings.extend(c_warns)
                else:
                    errors.append(ValidationIssue(
                        "schema",
                        f"fragments.{name} must be a mapping or a list of mappings",
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
            if sp_template is None:
                # P1-1: omitted state_poll.template defaults to template
                # at registration time.
                pass
            elif not isinstance(sp_template, dict):
                errors.append(ValidationIssue(
                    "schema", "state_poll.template must be a mapping",
                ))
            else:
                if sp_template.get("v") != 1:
                    errors.append(ValidationIssue(
                        "schema", "state_poll.template.v must be 1",
                    ))
                sp_components = sp_template.get("components")
                if not isinstance(sp_components, list):
                    errors.append(ValidationIssue(
                        "schema", "state_poll.template.components must be a list",
                    ))
                else:
                    c_errs, c_warns = _validate_component_list(
                        sp_components, path="state_poll.template.components",
                    )
                    errors.extend(c_errs)
                    warnings.extend(c_warns)
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

    return errors, warnings


def _validate_component_list(
    components: list, path: str,
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """Validate each node against its Pydantic model. Unknown types → warning."""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    for i, node in enumerate(components):
        node_path = f"{path}[{i}]"
        if not isinstance(node, dict):
            errors.append(ValidationIssue(
                "schema", f"{node_path} must be a mapping (got {type(node).__name__})",
            ))
            continue

        # Top-level each-block in components[] is not supported by the engine —
        # it can't flatten nested lists back into the components array.
        if "each" in node and "template" in node and "type" not in node:
            errors.append(ValidationIssue(
                "schema",
                f"{node_path}: each-blocks are not allowed at template.components[]; "
                "use them inside rows/items/children instead",
            ))
            continue

        ctype = node.get("type")
        if not isinstance(ctype, str):
            errors.append(ValidationIssue(
                "schema", f"{node_path} missing required 'type' string",
            ))
            continue

        if ctype not in KNOWN_COMPONENT_TYPES:
            warnings.append(ValidationIssue(
                "schema",
                f"{node_path} has unknown type {ctype!r} "
                "(will render as UnknownBlock at runtime)",
                severity="warning",
            ))
            continue

        model_cls = COMPONENT_MODELS[ctype]
        try:
            model_cls.model_validate(node)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err.get("loc", ()))
                errors.append(ValidationIssue(
                    "schema",
                    f"{node_path} ({ctype}): {err['msg']}"
                    + (f" at {loc}" if loc else ""),
                ))
            continue

        # Recurse into children for container nodes.
        if ctype in ("section", "form"):
            children = node.get("children")
            if isinstance(children, list):
                child_errs, child_warns = _validate_component_list(
                    children, path=f"{node_path}.children",
                )
                errors.extend(child_errs)
                warnings.extend(child_warns)
            elif isinstance(children, dict) and "each" in children:
                # each-block children — shape already validated by the model
                pass

    return errors, warnings


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
