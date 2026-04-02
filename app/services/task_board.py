"""Task board parser/serializer — shared between integration tools and MC router.

Parses/serializes the kanban-style tasks.md format:

    # Tasks

    ## Column Name

    ### Card Title
    - **id**: mc-a1b2c3
    - **priority**: medium
    - **created**: 2024-01-01

    Description text here.
"""
from __future__ import annotations

import logging
import re
import uuid

logger = logging.getLogger(__name__)


def generate_card_id() -> str:
    """Generate a short card ID like mc-a1b2c3."""
    return f"mc-{uuid.uuid4().hex[:6]}"


def parse_card(raw: str) -> dict:
    """Parse a single card block (everything after ### Title).

    Returns: {"title": str, "meta": dict[str, str], "description": str}
    """
    lines = raw.strip().splitlines()
    if not lines:
        return {"title": "", "meta": {}, "description": ""}

    title = lines[0].strip()
    meta: dict[str, str] = {}
    desc_lines: list[str] = []
    in_desc = False

    for line in lines[1:]:
        m = re.match(r"^- \*\*(\w+)\*\*:\s*(.*)$", line)
        if m and not in_desc:
            meta[m.group(1)] = m.group(2).strip()
        else:
            in_desc = True
            desc_lines.append(line)

    return {
        "title": title,
        "meta": meta,
        "description": "\n".join(desc_lines).strip(),
    }


def serialize_card(card: dict) -> str:
    """Serialize a card dict back to markdown."""
    lines = [f"### {card['title']}"]
    for key, value in card["meta"].items():
        lines.append(f"- **{key}**: {value}")
    if card.get("description"):
        lines.append("")
        lines.append(card["description"])
    return "\n".join(lines)


def parse_tasks_md(content: str) -> list[dict]:
    """Parse tasks.md into a list of columns with cards.

    Returns: [{"name": "Backlog", "cards": [{"title": ..., "meta": {...}, "description": ...}, ...]}, ...]
    """
    columns: list[dict] = []

    # Split by ## headers (columns)
    parts = re.split(r"(?m)^## ", content)

    for part in parts[1:]:  # skip preamble before first ##
        lines = part.split("\n", 1)
        col_name = lines[0].strip()
        col_body = lines[1] if len(lines) > 1 else ""

        cards: list[dict] = []
        card_parts = re.split(r"(?m)^### ", col_body)

        for card_raw in card_parts[1:]:  # skip text before first ###
            card = parse_card(card_raw)
            if card["title"]:
                cards.append(card)

        columns.append({"name": col_name, "cards": cards})

    return columns


def serialize_tasks_md(columns: list[dict]) -> str:
    """Serialize columns back to tasks.md format."""
    lines = ["# Tasks", ""]

    for col in columns:
        lines.append(f"## {col['name']}")
        lines.append("")
        for card in col.get("cards", []):
            lines.append(serialize_card(card))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def default_columns() -> list[dict]:
    """Default kanban columns for a new tasks.md."""
    return [
        {"name": "Backlog", "cards": []},
        {"name": "In Progress", "cards": []},
        {"name": "Review", "cards": []},
        {"name": "Done", "cards": []},
    ]
