"""Optional `@tool` decorator: infer OpenAI function schema from type hints + docstring."""

from __future__ import annotations

import inspect
import logging
import re
import types
from typing import Annotated, Any, Callable, Union, get_args, get_origin, get_type_hints

from app.tools.registry import register

logger = logging.getLogger(__name__)

_JSON_SCALAR = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _unwrap_optional(t: Any) -> Any:
    origin = get_origin(t)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(t) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return t


def _strip_annotated(t: Any) -> Any:
    if get_origin(t) is Annotated:
        return get_args(t)[0]
    return t


def _annotated_description(t: Any) -> str | None:
    if get_origin(t) is not Annotated:
        return None
    args = get_args(t)
    if len(args) > 1 and isinstance(args[1], str):
        return args[1]
    return None


def _to_json_schema(t: Any) -> dict[str, Any]:
    t = _strip_annotated(_unwrap_optional(t))
    origin = get_origin(t)
    if origin is list:
        inner = get_args(t)[0] if get_args(t) else str
        return {"type": "array", "items": _to_json_schema(inner)}
    if t in _JSON_SCALAR:
        return {"type": _JSON_SCALAR[t]}
    if t is dict or origin is dict:
        return {"type": "object"}
    return {"type": "string"}


def _first_line_description(doc: str | None) -> str:
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def _parse_google_arg_descriptions(doc: str | None) -> dict[str, str]:
    if not doc or "Args:" not in doc:
        return {}
    after = doc.split("Args:", 1)[1]
    if "\n\n" in after:
        after = after.split("\n\n", 1)[0]
    out: dict[str, str] = {}
    for line in after.splitlines():
        m = re.match(r"^\s*(\w+)\s*:\s*(.+)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _infer_schema(func: Callable[..., Any], name: str | None, description: str | None) -> dict[str, Any]:
    sig = inspect.signature(func)
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        hints = {}

    props: dict[str, Any] = {}
    required: list[str] = []
    doc = inspect.getdoc(func)
    arg_docs = _parse_google_arg_descriptions(doc)

    for param_name, p in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        ann = hints.get(param_name, p.annotation if p.annotation is not inspect.Parameter.empty else str)
        schema = _to_json_schema(ann)
        ann_desc = _annotated_description(hints.get(param_name, p.annotation))
        if ann_desc:
            schema = {**schema, "description": ann_desc}
        elif param_name in arg_docs:
            schema = {**schema, "description": arg_docs[param_name]}
        props[param_name] = schema
        if p.default is inspect.Parameter.empty:
            required.append(param_name)

    fn_name = name or func.__name__
    desc = (description or _first_line_description(doc) or f"Tool {fn_name}.").strip()

    return {
        "type": "function",
        "function": {
            "name": fn_name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


def tool(
    _fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    source_dir: str | None = None,
):
    """Register a function as a local tool using an inferred OpenAI schema."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        src = source_dir or fn.__globals__.get("__tool_source_dir__")
        schema = _infer_schema(fn, name, description)
        return register(schema, source_dir=src)(fn)

    if _fn is not None:
        return decorator(_fn)
    return decorator
