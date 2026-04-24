"""Shared helpers for integration-level tool-output rendering.

Renderers that want to surface tool invocations in chat (as compact
"badges", full rich widgets, or nothing at all) pull their primitives
from here so the logic stays consistent across platforms. Platform-
specific presentation (Slack Block Kit, Discord embeds, iMessage text)
stays in each renderer — this module only produces the structured
inputs (`ToolBadge`) and normalizes the `tool_output_display` setting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

ToolOutputDisplayValue = Literal["compact", "full", "none"]
_VALID: tuple[ToolOutputDisplayValue, ...] = ("compact", "full", "none")


class ToolOutputDisplay:
    """Namespace for `tool_output_display` enum handling."""

    COMPACT: ToolOutputDisplayValue = "compact"
    FULL: ToolOutputDisplayValue = "full"
    NONE: ToolOutputDisplayValue = "none"

    @staticmethod
    def normalize(value: object, default: ToolOutputDisplayValue = "compact") -> ToolOutputDisplayValue:
        """Coerce arbitrary input to a valid display mode, falling back to default."""
        if isinstance(value, str) and value in _VALID:
            return value  # type: ignore[return-value]
        return default


@dataclass(frozen=True)
class ToolBadge:
    """A one-line summary of a tool invocation for compact chat rendering."""

    tool_name: str
    display_label: str | None = None


@dataclass(frozen=True)
class ToolResultRenderingSupport:
    """Declared rich tool-result support for one integration renderer."""

    modes: frozenset[ToolOutputDisplayValue] = frozenset({"compact", "full", "none"})
    content_types: frozenset[str] = frozenset()
    view_keys: frozenset[str] = frozenset()
    interactive: bool = False
    unsupported_fallback: Literal["badge", "plain_text", "none"] = "badge"
    placement: Literal["same_message", "thread", "separate_message"] = "same_message"
    limits: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_manifest(cls, value: dict[str, Any] | None) -> "ToolResultRenderingSupport":
        value = value or {}
        modes = {
            mode
            for mode in value.get("modes", ("compact", "full", "none"))
            if mode in _VALID
        }
        fallback = value.get("unsupported_fallback", "badge")
        if fallback not in {"badge", "plain_text", "none"}:
            fallback = "badge"
        placement = value.get("placement", "same_message")
        if placement not in {"same_message", "thread", "separate_message"}:
            placement = "same_message"
        raw_limits = value.get("limits", {})
        if not isinstance(raw_limits, dict):
            raw_limits = {}
        limits = {
            str(k): int(v)
            for k, v in raw_limits.items()
            if isinstance(k, str)
            and isinstance(v, int)
            and v > 0
        }
        return cls(
            modes=frozenset(modes or _VALID),
            content_types=frozenset(_clean_strs(value.get("content_types"))),
            view_keys=frozenset(_clean_strs(value.get("view_keys"))),
            interactive=bool(value.get("interactive", False)),
            unsupported_fallback=fallback,  # type: ignore[arg-type]
            placement=placement,  # type: ignore[arg-type]
            limits=limits,
        )

    def supports(self, envelope: dict[str, Any]) -> bool:
        content_type = str(envelope.get("content_type") or "").strip()
        view_key = str(envelope.get("view_key") or "").strip()
        return (
            bool(view_key and view_key in self.view_keys)
            or bool(content_type and content_type in self.content_types)
        )


@dataclass(frozen=True)
class ToolResultField:
    label: str
    value: str


@dataclass(frozen=True)
class ToolResultLink:
    title: str
    url: str
    subtitle: str | None = None


@dataclass(frozen=True)
class ToolResultTable:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    truncated: bool = False


@dataclass(frozen=True)
class ToolResultCode:
    content: str
    language: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class ToolResultImage:
    url: str
    alt: str = "image"


@dataclass(frozen=True)
class ToolResultCard:
    """Portable read-only result card used by integration renderers."""

    title: str | None = None
    summary: str | None = None
    fields: tuple[ToolResultField, ...] = ()
    links: tuple[ToolResultLink, ...] = ()
    table: ToolResultTable | None = None
    code: ToolResultCode | None = None
    image: ToolResultImage | None = None
    status: str | None = None
    source_tool: str | None = None
    display_label: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class ToolResultPresentation:
    """Renderer-facing presentation model for one message's tool results."""

    mode: ToolOutputDisplayValue
    cards: tuple[ToolResultCard, ...] = ()
    badges: tuple[ToolBadge, ...] = ()
    unsupported_badges: tuple[ToolBadge, ...] = ()

    @property
    def all_badges(self) -> tuple[ToolBadge, ...]:
        return (*self.badges, *self.unsupported_badges)


_COMPONENT_CT = "application/vnd.spindrel.components+json"
_HTML_CT = "application/vnd.spindrel.html+interactive"
_NATIVE_CT = "application/vnd.spindrel.native-app+json"


def _clean_strs(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(v).strip() for v in value if isinstance(v, str) and v.strip()]


_SUPPORTED_DEFAULT = ToolResultRenderingSupport.from_manifest({
    "content_types": [
        "text/plain",
        "text/markdown",
        "application/json",
        "application/vnd.spindrel.components+json",
        "application/vnd.spindrel.diff+text",
        "application/vnd.spindrel.file-listing+json",
    ],
    "view_keys": [
        "core.search_results",
        "core.command_result",
        "core.machine_target_status",
    ],
})


def _parse_jsonish(value: object) -> Any | None:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return None


def _text(value: object, limit: int = 800) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if len(value) > limit:
        return value[: max(0, limit - 1)].rstrip() + "…"
    return value


def _title_for(env: dict[str, Any]) -> str | None:
    return _text(env.get("display_label") or env.get("tool_name") or "Tool result", 150)


def _badge_for(env: dict[str, Any]) -> ToolBadge:
    tool_name = _text(env.get("tool_name"), 80) or "tool"
    label = env.get("display_label")
    return ToolBadge(tool_name=tool_name, display_label=_text(label, 120) or None)


def extract_tool_badges(tool_results: list[dict]) -> list[ToolBadge]:
    """Pull compact badges from persisted `Message.metadata["tool_results"]`.

    Each envelope in ``tool_results`` is the output of
    ``ToolResultEnvelope.compact_dict``. We take `tool_name` and
    `display_label` from each envelope, skip entries without a tool
    name, and de-dup identical (tool_name, display_label) pairs while
    preserving order (so a turn that called get_weather once shows one
    badge, not two).
    """
    badges: list[ToolBadge] = []
    seen: set[tuple[str, str | None]] = set()
    for env in tool_results or []:
        if not isinstance(env, dict):
            continue
        tool_name = (env.get("tool_name") or "").strip()
        if not tool_name:
            # Envelopes from before tool_name was added — fall back to
            # the generic "tool" label so users still see *something*
            # rather than the envelope being silently skipped.
            tool_name = "tool"
        label = env.get("display_label")
        if label is not None and not isinstance(label, str):
            label = str(label)
        if label == "":
            label = None
        key = (tool_name, label)
        if key in seen:
            continue
        seen.add(key)
        badges.append(ToolBadge(tool_name=tool_name, display_label=label))
    return badges


def build_tool_result_presentation(
    tool_results: list[dict] | None,
    *,
    display_mode: ToolOutputDisplayValue = "compact",
    support: ToolResultRenderingSupport | None = None,
) -> ToolResultPresentation:
    """Normalize persisted tool envelopes into a platform-neutral presentation.

    This is the deep SDK boundary: callers choose a display mode and pass
    an integration's declared support. The function returns read-only cards
    for supported envelopes plus badge fallbacks for unsupported ones.
    """
    mode = ToolOutputDisplay.normalize(display_mode)
    envelopes = [env for env in (tool_results or []) if isinstance(env, dict)]
    if mode == ToolOutputDisplay.NONE or not envelopes:
        return ToolResultPresentation(mode=mode)
    if mode == ToolOutputDisplay.COMPACT:
        return ToolResultPresentation(mode=mode, badges=tuple(extract_tool_badges(envelopes)))

    support = support or _SUPPORTED_DEFAULT
    cards: list[ToolResultCard] = []
    unsupported: list[ToolBadge] = []
    for env in envelopes:
        if support.supports(env):
            card = _card_from_envelope(env, support)
            if card is not None:
                cards.append(card)
                continue
        if support.unsupported_fallback == "badge":
            unsupported.append(_badge_for(env))
    return ToolResultPresentation(
        mode=mode,
        cards=tuple(cards),
        unsupported_badges=tuple(_dedupe_badges(unsupported)),
    )


def _dedupe_badges(badges: list[ToolBadge]) -> list[ToolBadge]:
    out: list[ToolBadge] = []
    seen: set[tuple[str, str | None]] = set()
    for badge in badges:
        key = (badge.tool_name, badge.display_label)
        if key in seen:
            continue
        seen.add(key)
        out.append(badge)
    return out


def _card_from_envelope(
    env: dict[str, Any],
    support: ToolResultRenderingSupport,
) -> ToolResultCard | None:
    view_key = str(env.get("view_key") or "")
    if view_key == "core.search_results":
        return _search_results_card(env, support)
    if view_key in {"core.command_result", "core.machine_target_status"}:
        return _generic_data_card(env, support)

    ct = str(env.get("content_type") or "text/plain")
    if ct == _COMPONENT_CT:
        return _components_card(env, support)
    if ct in {"text/plain", "text/markdown"}:
        return _text_card(env)
    if ct == "application/json":
        return _json_card(env, support)
    if ct == "application/vnd.spindrel.diff+text":
        return _code_card(env, language="diff", support=support)
    if ct == "application/vnd.spindrel.file-listing+json":
        return _file_listing_card(env, support)
    if ct in {_HTML_CT, _NATIVE_CT}:
        return None
    return _text_card(env)


def _base_card(env: dict[str, Any], **kwargs: Any) -> ToolResultCard:
    return ToolResultCard(
        title=kwargs.pop("title", _title_for(env)),
        source_tool=_text(env.get("tool_name"), 80) or None,
        display_label=_text(env.get("display_label"), 120) or None,
        truncated=bool(env.get("truncated")) or bool(kwargs.pop("truncated", False)),
        **kwargs,
    )


def _text_card(env: dict[str, Any]) -> ToolResultCard | None:
    summary = _text(env.get("plain_body") or env.get("body"), 1500)
    if not summary and not env.get("truncated"):
        return None
    if env.get("truncated"):
        summary = (summary + "\n\n[truncated]").strip()
    return _base_card(env, summary=summary)


def _json_card(env: dict[str, Any], support: ToolResultRenderingSupport) -> ToolResultCard | None:
    parsed = _parse_jsonish(env.get("body"))
    if parsed is None:
        return _text_card(env)
    content = json.dumps(parsed, indent=2, ensure_ascii=False)
    return _base_card(
        env,
        code=_limited_code(content, "json", support),
    )


def _code_card(
    env: dict[str, Any],
    *,
    language: str,
    support: ToolResultRenderingSupport,
) -> ToolResultCard | None:
    content = _text(env.get("body") or env.get("plain_body"), 100000)
    if not content and not env.get("truncated"):
        return None
    return _base_card(env, code=_limited_code(content, language, support))


def _limited_code(
    content: str,
    language: str | None,
    support: ToolResultRenderingSupport,
) -> ToolResultCode:
    limit = support.limits.get("max_code_chars", 2900)
    truncated = len(content) > limit
    if truncated:
        content = content[: max(0, limit - 20)].rstrip() + "\n... [truncated]"
    return ToolResultCode(content=content, language=language, truncated=truncated)


def _file_listing_card(
    env: dict[str, Any],
    support: ToolResultRenderingSupport,
) -> ToolResultCard | None:
    parsed = _parse_jsonish(env.get("body") or env.get("data"))
    if not isinstance(parsed, (dict, list)):
        return _text_card(env)
    rows_src = parsed.get("entries") if isinstance(parsed, dict) else parsed
    if not isinstance(rows_src, list):
        return _json_card(env, support)
    max_rows = support.limits.get("max_table_rows", 20)
    rows: list[tuple[str, ...]] = []
    for item in rows_src[:max_rows]:
        if isinstance(item, dict):
            rows.append((
                _text(item.get("path") or item.get("name"), 120),
                _text(item.get("type"), 40),
                _text(item.get("size") or item.get("size_bytes"), 40),
            ))
        else:
            rows.append((_text(item, 160), "", ""))
    return _base_card(
        env,
        table=ToolResultTable(
            columns=("Path", "Type", "Size"),
            rows=tuple(rows),
            truncated=len(rows_src) > max_rows,
        ),
    )


def _search_results_card(
    env: dict[str, Any],
    support: ToolResultRenderingSupport,
) -> ToolResultCard | None:
    data = env.get("data")
    parsed = data if isinstance(data, dict) else _parse_jsonish(env.get("body"))
    if not isinstance(parsed, dict):
        return _components_card(env, support) or _text_card(env)
    results = parsed.get("results")
    links: list[ToolResultLink] = []
    if isinstance(results, list):
        for item in results[: support.limits.get("max_links", 10)]:
            if not isinstance(item, dict):
                continue
            url = _text(item.get("url"), 500)
            if not url:
                continue
            links.append(ToolResultLink(
                title=_text(item.get("title") or url, 180),
                url=url,
                subtitle=_text(item.get("content") or item.get("subtitle"), 180) or None,
            ))
    title = _text(parsed.get("query"), 160)
    title = f"Search: {title}" if title else _title_for(env)
    count = parsed.get("count")
    status = f"{count} result(s)" if count is not None else None
    return _base_card(env, title=title, status=status, links=tuple(links))


def _generic_data_card(
    env: dict[str, Any],
    support: ToolResultRenderingSupport,
) -> ToolResultCard | None:
    parsed = env.get("data")
    if not isinstance(parsed, dict):
        parsed = _parse_jsonish(env.get("body"))
    if not isinstance(parsed, dict):
        return _components_card(env, support) or _text_card(env)
    fields = [
        ToolResultField(_text(k, 80), _text(v, 180))
        for k, v in parsed.items()
        if not isinstance(v, (dict, list))
    ][:10]
    return _base_card(
        env,
        summary=_text(env.get("plain_body"), 1000) or None,
        fields=tuple(fields),
        code=None if fields else _limited_code(json.dumps(parsed, indent=2), "json", support),
    )


def _components_card(
    env: dict[str, Any],
    support: ToolResultRenderingSupport,
) -> ToolResultCard | None:
    parsed = _parse_jsonish(env.get("body"))
    if not isinstance(parsed, dict) or parsed.get("v") != 1:
        return _text_card(env)
    card = _MutableCard(title=_title_for(env), source_env=env, support=support)
    for node in parsed.get("components", []):
        if isinstance(node, dict):
            _apply_component(card, node)
    return card.freeze()


@dataclass
class _MutableCard:
    title: str | None
    source_env: dict[str, Any]
    support: ToolResultRenderingSupport
    summary: str | None = None
    fields: list[ToolResultField] = field(default_factory=list)
    links: list[ToolResultLink] = field(default_factory=list)
    table: ToolResultTable | None = None
    code: ToolResultCode | None = None
    image: ToolResultImage | None = None
    status: str | None = None

    def freeze(self) -> ToolResultCard:
        if not any((self.title, self.summary, self.fields, self.links, self.table, self.code, self.image, self.status)):
            return _base_card(self.source_env)
        return _base_card(
            self.source_env,
            title=self.title,
            summary=self.summary,
            fields=tuple(self.fields[:10]),
            links=tuple(self.links[: self.support.limits.get("max_links", 10)]),
            table=self.table,
            code=self.code,
            image=self.image,
            status=self.status,
        )


def _apply_component(card: _MutableCard, node: dict[str, Any]) -> None:
    ntype = node.get("type")
    if ntype == "heading":
        text = _text(node.get("text"), 150)
        if text:
            card.title = text
    elif ntype == "text":
        content = _text(node.get("content"), 1500)
        if content and card.summary:
            card.summary = f"{card.summary}\n\n{content}"
        elif content:
            card.summary = content
    elif ntype == "properties":
        items = node.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    card.fields.append(ToolResultField(
                        _text(item.get("label"), 80),
                        _text(item.get("value"), 180),
                    ))
    elif ntype == "links":
        items = node.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("url"):
                    card.links.append(ToolResultLink(
                        title=_text(item.get("title") or item.get("url"), 180),
                        url=_text(item.get("url"), 500),
                        subtitle=_text(item.get("subtitle"), 180) or None,
                    ))
    elif ntype == "table":
        columns = tuple(_text(c, 60) for c in node.get("columns", []) if _text(c, 60))
        raw_rows = node.get("rows", [])
        if columns and isinstance(raw_rows, list):
            max_rows = card.support.limits.get("max_table_rows", 20)
            rows = tuple(
                tuple(_text(cell, 120) for cell in row)
                for row in raw_rows[:max_rows]
                if isinstance(row, list)
            )
            card.table = ToolResultTable(columns=columns, rows=rows, truncated=len(raw_rows) > max_rows)
    elif ntype == "code":
        card.code = _limited_code(
            _text(node.get("content"), 100000),
            _text(node.get("language"), 30) or None,
            card.support,
        )
    elif ntype == "image" and node.get("url"):
        card.image = ToolResultImage(url=_text(node.get("url"), 500), alt=_text(node.get("alt"), 120) or "image")
    elif ntype == "status":
        card.status = _text(node.get("text"), 160)
    elif ntype == "section":
        children = node.get("children", [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    _apply_component(card, child)


__all__ = [
    "ToolBadge",
    "ToolOutputDisplay",
    "ToolOutputDisplayValue",
    "ToolResultCard",
    "ToolResultCode",
    "ToolResultField",
    "ToolResultImage",
    "ToolResultLink",
    "ToolResultPresentation",
    "ToolResultRenderingSupport",
    "ToolResultTable",
    "build_tool_result_presentation",
    "extract_tool_badges",
]
