"""Plan board parser/serializer — shared between MC tools and MC router.

Parses/serializes the plans.md format:

    # Plans

    ## Deploy v2 API [draft]
    - **id**: plan-a1b2c3
    - **created**: 2026-03-31

    ### Steps
    1. [ ] Update configuration files
    2. [x] Run database migrations
    3. [~] Deploy to staging

    ### Notes
    Free-form notes here.

Status lifecycle: draft → approved → executing → complete | abandoned
Step markers: [ ] pending, [~] in_progress, [x] done, [-] skipped
"""
from __future__ import annotations

import logging
import re
import uuid

logger = logging.getLogger(__name__)

VALID_STATUSES = {"draft", "approved", "executing", "complete", "abandoned"}
STEP_MARKERS = {"[ ]": "pending", "[x]": "done", "[~]": "in_progress", "[-]": "skipped", "[!]": "failed"}
STEP_MARKERS_REV = {"pending": "[ ]", "done": "[x]", "in_progress": "[~]", "skipped": "[-]", "failed": "[!]"}


def generate_plan_id() -> str:
    """Generate a short plan ID like plan-a1b2c3."""
    return f"plan-{uuid.uuid4().hex[:6]}"


def parse_step_status(marker: str) -> str:
    """Convert a step marker to a status string."""
    return STEP_MARKERS.get(marker, "pending")


def _parse_steps(text: str) -> list[dict]:
    """Parse numbered step lines from a text block."""
    steps: list[dict] = []
    step_re = re.compile(r"^(\d+)\.\s+\[([ x~!-])\]\s+(.+)$")
    for line in text.splitlines():
        m = step_re.match(line.strip())
        if m:
            marker = f"[{m.group(2)}]"
            steps.append({
                "position": int(m.group(1)),
                "status": parse_step_status(marker),
                "content": m.group(3).strip(),
            })
    return steps


def parse_plans_md(content: str) -> list[dict]:
    """Parse plans.md into a list of plan dicts.

    Returns:
        [{"title": str, "status": str, "meta": dict, "steps": list, "notes": str}]
    """
    plans: list[dict] = []

    # Split by ## headers (plans)
    parts = re.split(r"(?m)^## ", content)

    for part in parts[1:]:  # skip preamble before first ##
        lines = part.split("\n", 1)
        header = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""

        # Parse title and status from header: "Title [status]"
        status_match = re.search(r"\[(\w+)\]\s*$", header)
        if status_match and status_match.group(1).lower() in VALID_STATUSES:
            status = status_match.group(1).lower()
            title = header[:status_match.start()].strip()
        else:
            status = "draft"
            title = header

        if not title:
            continue

        # Parse meta fields, steps section, and notes section
        meta: dict[str, str] = {}
        steps: list[dict] = []
        notes = ""

        # Split by ### subsections
        subsections = re.split(r"(?m)^### ", body)

        # First subsection (before any ###) contains meta fields
        preamble = subsections[0] if subsections else ""
        for line in preamble.splitlines():
            m = re.match(r"^- \*\*(\w+)\*\*:\s*(.*)$", line)
            if m:
                meta[m.group(1)] = m.group(2).strip()

        # Process ### subsections
        for sub in subsections[1:]:
            sub_lines = sub.split("\n", 1)
            sub_title = sub_lines[0].strip().lower()
            sub_body = sub_lines[1] if len(sub_lines) > 1 else ""

            if sub_title == "steps":
                steps = _parse_steps(sub_body)
            elif sub_title == "notes":
                notes = sub_body.strip()

        plans.append({
            "title": title,
            "status": status,
            "meta": meta,
            "steps": steps,
            "notes": notes,
        })

    return plans


def serialize_plans_md(plans: list[dict]) -> str:
    """Serialize plan dicts back to plans.md format."""
    lines = ["# Plans", ""]

    for plan in plans:
        status = plan.get("status", "draft")
        lines.append(f"## {plan['title']} [{status}]")

        # Meta fields
        for key, value in plan.get("meta", {}).items():
            lines.append(f"- **{key}**: {value}")

        # Steps section
        steps = plan.get("steps", [])
        if steps:
            lines.append("")
            lines.append("### Steps")
            for step in steps:
                marker = STEP_MARKERS_REV.get(step["status"], "[ ]")
                lines.append(f"{step['position']}. {marker} {step['content']}")

        # Notes section
        notes = plan.get("notes", "")
        if notes:
            lines.append("")
            lines.append("### Notes")
            lines.append(notes)

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
