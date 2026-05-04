"""get_doc / list_docs — read-only access to internal reference docs under docs/.

Counterpart to ``get_skill`` / ``get_skill_list`` for the ``docs/`` tree.
Skills hold procedural knowledge; ``docs/reference/`` holds long-form reference
manuals that bots should not have to keep resident.
"""
import json
import logging

from app.agent.docs import list_docs as _list_docs, load_doc as _load_doc
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_doc",
        "description": (
            "Retrieve the full content of an internal reference doc by its ID. "
            "IDs are extension-less paths under docs/ — e.g. 'reference/widgets/sdk' "
            "for docs/reference/widgets/sdk.md. Use this when a procedural skill "
            "points you at a reference manual you don't have resident."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Extension-less doc ID, e.g. 'reference/widgets/sdk'.",
                },
            },
            "required": ["id"],
        },
    },
}, safety_tier="readonly", tool_metadata={
    "domains": ["doc_access"],
    "capabilities": ["doc.read"],
    "intent_tags": ["load doc", "reference manual", "doc body"],
    "exposure": "ambient",
    "auto_inject": ["chat_baseline"],
    "context_policy": {"retention": "sticky_reference"},
}, returns={
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "body": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["id"],
})
async def get_doc(id: str) -> str:
    doc = _load_doc(id)
    if doc is None:
        return json.dumps({"id": id, "error": f"Doc '{id}' not found."}, ensure_ascii=False)
    payload: dict = {"id": doc.id, "body": doc.body}
    if doc.title:
        payload["title"] = doc.title
    if doc.summary:
        payload["summary"] = doc.summary
    if doc.tags:
        payload["tags"] = doc.tags
    return json.dumps(payload, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "list_docs",
        "description": (
            "List internal reference docs by ID with their frontmatter summary. "
            "Optionally filter by top-level area such as 'reference', 'guides', "
            "or 'tracks'. Use this to discover what reference manuals exist before "
            "calling get_doc()."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "area": {
                    "type": "string",
                    "description": (
                        "Optional top-level area to filter by, e.g. 'reference' "
                        "to limit to docs/reference/**."
                    ),
                },
            },
        },
    },
}, safety_tier="readonly", tool_metadata={
    "domains": ["doc_access"],
    "capabilities": ["doc.read"],
    "intent_tags": ["list docs", "doc discovery"],
    "exposure": "ambient",
    "auto_inject": ["chat_baseline"],
    "context_policy": {"retention": "sticky_reference"},
}, returns={
    "type": "object",
    "properties": {
        "count": {"type": "integer"},
        "docs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id"],
            },
        },
    },
    "required": ["count", "docs"],
})
async def list_docs(area: str | None = None) -> str:
    summaries = _list_docs(area=area)
    docs = []
    for s in summaries:
        entry: dict = {"id": s.id}
        if s.title:
            entry["title"] = s.title
        if s.summary:
            entry["summary"] = s.summary
        if s.tags:
            entry["tags"] = s.tags
        docs.append(entry)
    return json.dumps({"count": len(docs), "docs": docs}, ensure_ascii=False)
