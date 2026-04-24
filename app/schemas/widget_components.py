"""Pydantic schema for the widget component tree.

Canonical source of truth for what's valid under `template.components[]`
(and `state_poll.template.components[]`). Used by
``widget_package_validation`` at registration time so malformed widgets
fail fast with precise errors instead of surfacing as blank cards or
`Unknown: <type>` blocks at render time.

Permissive where templated, strict on structure:

  - Enum fields (``color``, ``variant``, ``icon``, ``layout``, ``style``)
    accept a known literal *or* any string containing ``{{`` — template
    expressions resolve at runtime.
  - Numeric / boolean fields accept their native type *or* a string (for
    template expressions).
  - Required fields must be present.
  - Unknown component ``type:`` values do NOT fail validation — the
    runtime renderer is forward-compatible, so the validator surfaces
    them as warnings via ``KNOWN_COMPONENT_TYPES`` and skips deep
    validation for that node.
  - Extra/unknown fields on known types are rejected (catches typos like
    ``defaultOpn``).

Frontend parity: component types mirror the discriminated union in
``ui/src/components/chat/renderers/ComponentRenderer.tsx``. When a new
primitive lands there, add it here and in
``KNOWN_COMPONENT_TYPES``.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


# ── Enum vocabularies (matched against ComponentRenderer.tsx) ──

SEMANTIC_COLORS = ("default", "muted", "accent", "success", "warning", "danger", "info")
LINK_ICONS = ("github", "web", "email", "file", "link")
BUTTON_VARIANTS = ("default", "primary", "danger")
TEXT_STYLES = ("default", "muted", "bold", "code")
LAYOUTS = ("vertical", "inline")
DISPATCH_TYPES = ("tool", "api", "widget_config")
HTTP_METHODS = ("POST", "PUT", "PATCH", "DELETE")
PRIORITIES = ("primary", "secondary", "metadata")
PROPERTY_VARIANTS = ("default", "metadata")
AUTH_MODES = ("none", "bearer")


def _is_templated(v: Any) -> bool:
    return isinstance(v, str) and "{{" in v and "}}" in v


def _enum_or_template(allowed: tuple[str, ...]):
    """Validator factory: accept a known enum literal or any templated string."""

    def check(v: Any) -> Any:
        if v is None:
            return v
        if isinstance(v, str) and (_is_templated(v) or v in allowed):
            return v
        raise ValueError(f"must be one of {list(allowed)} or a templated string")

    return check


SemanticColor = Annotated[Optional[str], BeforeValidator(_enum_or_template(SEMANTIC_COLORS))]
LinkIcon = Annotated[Optional[str], BeforeValidator(_enum_or_template(LINK_ICONS))]
ButtonVariant = Annotated[Optional[str], BeforeValidator(_enum_or_template(BUTTON_VARIANTS))]
TextStyle = Annotated[Optional[str], BeforeValidator(_enum_or_template(TEXT_STYLES))]
Layout = Annotated[Optional[str], BeforeValidator(_enum_or_template(LAYOUTS))]
Priority = Annotated[Optional[str], BeforeValidator(_enum_or_template(PRIORITIES))]
PropertyVariant = Annotated[Optional[str], BeforeValidator(_enum_or_template(PROPERTY_VARIANTS))]
AuthMode = Annotated[Optional[str], BeforeValidator(_enum_or_template(AUTH_MODES))]


# ── Supporting types ──

class WidgetAction(BaseModel):
    """Shape mirrors ``ui/src/types/api.ts`` ``WidgetAction``."""

    model_config = ConfigDict(extra="forbid")
    dispatch: Literal["tool", "api", "widget_config"]
    tool: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[Literal["POST", "PUT", "PATCH", "DELETE"]] = None
    args: Optional[dict[str, Any]] = None
    config: Optional[dict[str, Any]] = None
    value_key: Optional[str] = None
    optimistic: Optional[Union[bool, str]] = None


class EachBlock(BaseModel):
    """An ``each:`` iteration block; valid wherever a list is expected.

    Not valid at the top-level ``template.components[]`` position — the
    runtime engine doesn't flatten nested lists back into the components
    array. Use it for ``rows``, ``items``, ``children``.
    """

    model_config = ConfigDict(extra="forbid")
    each: str
    template: Any


def _must_be_templated_str(v: Any) -> Any:
    """Accept a string only if it looks like a templated expression.

    Used for list-position fields where the author may want the runtime
    template engine to *produce* the list via a pipe transform — e.g.
    ``items: "{{data.success | map: {label: type, value: name}}}"``.
    Plain strings (non-templated) are still rejected, so list fields
    don't silently accept scalars.
    """
    if isinstance(v, str) and "{{" in v and "}}" in v:
        return v
    raise ValueError("must be a list, an each-block, or a templated string")


TemplatedStr = Annotated[str, BeforeValidator(_must_be_templated_str)]


# ── Base for all components ──

class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: Optional[str] = None
    priority: Priority = None


# ── Display primitives ──

class HeadingNode(_Base):
    type: Literal["heading"]
    text: str
    level: Optional[Union[int, str]] = None


class TextNode(_Base):
    type: Literal["text"]
    content: str
    style: TextStyle = None
    markdown: Optional[Union[bool, str]] = None


class StatusNode(_Base):
    type: Literal["status"]
    text: str
    color: SemanticColor = None


class DividerNode(_Base):
    type: Literal["divider"]
    label: Optional[str] = None


class CodeNode(_Base):
    type: Literal["code"]
    content: str
    language: Optional[str] = None


class _ImageOverlay(BaseModel):
    """A normalized-coords rectangle drawn over an image.

    ``x`` / ``y`` are the top-left corner in the image's 0..1 space,
    ``w`` / ``h`` are width/height as fractions of the image dimensions.
    Normalized so overlays survive resolution / aspect-ratio changes
    without the author recomputing pixels.
    """

    model_config = ConfigDict(extra="forbid")
    x: Union[int, float, str]
    y: Union[int, float, str]
    w: Union[int, float, str]
    h: Union[int, float, str]
    label: Optional[str] = None
    color: SemanticColor = None
    when: Optional[str] = None


class ImageNode(_Base):
    type: Literal["image"]
    url: str
    alt: Optional[str] = None
    height: Optional[Union[int, str]] = None
    aspect_ratio: Optional[str] = None
    auth: AuthMode = None
    lightbox: Optional[Union[bool, str]] = None
    overlays: Optional[Union[list[_ImageOverlay], EachBlock, TemplatedStr]] = None


# ── Grouping ──

class _PropertyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    value: str
    color: SemanticColor = None
    when: Optional[str] = None


class PropertiesNode(_Base):
    type: Literal["properties"]
    items: Union[list[_PropertyItem], EachBlock, TemplatedStr]
    layout: Layout = None
    variant: PropertyVariant = None


class TableNode(_Base):
    type: Literal["table"]
    columns: Union[list[str], TemplatedStr]
    rows: Union[list[list[str]], EachBlock, TemplatedStr]
    compact: Optional[Union[bool, str]] = None


class _LinkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    title: str
    subtitle: Optional[str] = None
    icon: LinkIcon = None
    when: Optional[str] = None


class LinksNode(_Base):
    type: Literal["links"]
    items: Union[list[_LinkItem], EachBlock, TemplatedStr]


class _TileItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Optional[str] = None
    value: Optional[str] = None
    caption: Optional[str] = None
    when: Optional[str] = None


class TilesNode(_Base):
    type: Literal["tiles"]
    items: Union[list[_TileItem], EachBlock, TemplatedStr]
    min_width: Optional[Union[int, str]] = None
    gap: Optional[Union[int, str]] = None


class SectionNode(_Base):
    type: Literal["section"]
    label: Optional[str] = None
    collapsible: Optional[Union[bool, str]] = None
    defaultOpen: Optional[Union[bool, str]] = None
    children: Union[list["ComponentNodeAny"], EachBlock] = Field(default_factory=list)


# ── Interactive ──

class ButtonNode(_Base):
    type: Literal["button"]
    label: str
    action: WidgetAction
    variant: ButtonVariant = None
    disabled: Optional[Union[bool, str]] = None
    subtle: Optional[Union[bool, str]] = None


class ToggleNode(_Base):
    type: Literal["toggle"]
    label: str
    value: Union[bool, str]
    action: WidgetAction
    color: SemanticColor = None
    description: Optional[str] = None
    on_label: Optional[str] = None
    off_label: Optional[str] = None


class _SelectOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    label: str


class SelectNode(_Base):
    type: Literal["select"]
    value: str
    options: Union[list[_SelectOption], EachBlock, TemplatedStr]
    action: WidgetAction
    label: Optional[str] = None


class InputNode(_Base):
    type: Literal["input"]
    value: str
    action: WidgetAction
    label: Optional[str] = None
    placeholder: Optional[str] = None


class SliderNode(_Base):
    type: Literal["slider"]
    value: Union[int, float, str]
    action: WidgetAction
    label: Optional[str] = None
    min: Optional[Union[int, float, str]] = None
    max: Optional[Union[int, float, str]] = None
    step: Optional[Union[int, float, str]] = None
    unit: Optional[str] = None
    color: SemanticColor = None


class FormNode(_Base):
    type: Literal["form"]
    submit_action: WidgetAction
    children: Union[list["ComponentNodeAny"], EachBlock] = Field(default_factory=list)
    submit_label: Optional[str] = None


# ── Fragment (reserved for P1-1; resolver ships later) ──

class FragmentNode(_Base):
    """Reference to a named fragment declared at the widget's ``fragments:``
    top level. Resolver lands in P1-1; the schema reserves the ``type``
    today so authors can start using it without triggering ``unknown
    type`` warnings once the resolver arrives.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    type: Literal["fragment"]
    ref: str
    with_: Optional[dict[str, Any]] = Field(default=None, alias="with")


# ── Discriminated union ──

ComponentNode = Annotated[
    Union[
        HeadingNode, TextNode, StatusNode, DividerNode, CodeNode, ImageNode,
        PropertiesNode, TableNode, LinksNode, TilesNode, SectionNode,
        ButtonNode, ToggleNode, SelectNode, InputNode, SliderNode, FormNode,
        FragmentNode,
    ],
    Field(discriminator="type"),
]

# Alias used by forward references (SectionNode.children, FormNode.children).
ComponentNodeAny = ComponentNode

KNOWN_COMPONENT_TYPES: frozenset[str] = frozenset({
    "heading", "text", "status", "divider", "code", "image",
    "properties", "table", "links", "tiles", "section",
    "button", "toggle", "select", "input", "slider", "form",
    "fragment",
})

COMPONENT_MODELS: dict[str, type[BaseModel]] = {
    "heading": HeadingNode,
    "text": TextNode,
    "status": StatusNode,
    "divider": DividerNode,
    "code": CodeNode,
    "image": ImageNode,
    "properties": PropertiesNode,
    "table": TableNode,
    "links": LinksNode,
    "tiles": TilesNode,
    "section": SectionNode,
    "button": ButtonNode,
    "toggle": ToggleNode,
    "select": SelectNode,
    "input": InputNode,
    "slider": SliderNode,
    "form": FormNode,
    "fragment": FragmentNode,
}


class ComponentBody(BaseModel):
    """Root template body — what sits under ``template:`` and ``state_poll.template:``."""

    model_config = ConfigDict(extra="forbid")
    v: Literal[1]
    components: list[ComponentNode] = Field(default_factory=list)


SectionNode.model_rebuild()
FormNode.model_rebuild()
ComponentBody.model_rebuild()
