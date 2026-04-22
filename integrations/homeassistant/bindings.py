from __future__ import annotations

from integrations.homeassistant.widget_transforms import _TOGGLEABLE_DOMAINS, _parse_live_context


def live_context_options(raw_result: str, context: dict) -> list[dict]:
    """Normalize GetLiveContext output into picker options."""
    import json

    try:
        parsed = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return []

    result_text = parsed.get("result", "")
    if not isinstance(result_text, str):
        return []

    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    domains = {
        str(item).strip().lower()
        for item in (params.get("domains") or [])
        if str(item).strip()
    }
    toggle_only = bool(params.get("toggle_only"))

    out: list[dict] = []
    for entity in _parse_live_context(result_text):
        name = entity.get("name") or ""
        domain = (entity.get("domain") or "").strip().lower()
        area = (entity.get("area") or "").strip()
        if not name or not domain:
            continue
        if domains and domain not in domains:
            continue
        if toggle_only and domain not in _TOGGLEABLE_DOMAINS:
            continue
        entity_id = _entity_id_from_name(name, domain)
        out.append({
            "value": entity_id,
            "label": name,
            "description": entity_id,
            "group": area or domain.title(),
            "meta": {
                "domain": domain,
                "area": area,
            },
        })

    out.sort(key=lambda item: ((item.get("group") or "").lower(), item["label"].lower()))
    return out


def _entity_id_from_name(name: str, domain: str) -> str:
    slug = name.strip().lower()
    slug = "".join(ch if ch.isalnum() else "_" for ch in slug)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"{domain}.{slug.strip('_')}"
