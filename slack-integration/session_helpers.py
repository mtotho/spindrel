"""Slack↔agent session identity helpers."""


def slack_client_id(channel_id: str) -> str:
    return f"slack:{channel_id}"


def fuzzy_find_session(sessions: list[dict], query: str) -> dict | None:
    """Match by UUID prefix or title (single match), or None."""
    if not query or not sessions:
        return None
    query = query.strip().lower()
    by_id = [s for s in sessions if (s.get("id") or "").lower().startswith(query)]
    if len(by_id) == 1:
        return by_id[0]
    by_title = [s for s in sessions if query in (s.get("title") or "").lower()]
    if len(by_title) == 1:
        return by_title[0]
    if by_id or by_title:
        return (by_id + [m for m in by_title if m not in by_id])[0]
    return None
