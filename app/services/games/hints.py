"""Pure-function hint builders for the games framework.

These helpers compose into per-game ``localize(state, bot_id)`` callbacks
that the heartbeat block uses to give each bot bot-aware coaching instead
of dumping raw state. No DB access, no I/O — every function takes plain
state and returns plain text.

Used today by ``blockyard.py``; ``storybook.py`` reuses
``bot_pacing_nudge`` for stanza counts and ``recent_failures``.
"""
from __future__ import annotations

from typing import Any, Iterable


def neighborhood_snapshot(
    blocks: dict[str, dict[str, Any]],
    anchor: tuple[int, int, int],
    *,
    radius: int = 2,
) -> str:
    """Render a 3D ASCII view of the cells within ``radius`` of ``anchor``.

    Z-layer slices, lowest first. Empty cells render as ``.``; occupied
    cells render as the first letter of the block ``type`` (uppercase if
    placed by ``anchor`` block's owner, lowercase otherwise — but we keep
    it simple and just use lowercase first letter; ``X`` marks the anchor
    cell itself). Returns a compact multi-line string suitable for
    inlining into a heartbeat prompt.
    """
    ax, ay, az = anchor
    lines: list[str] = []
    for dz in range(-radius, radius + 1):
        z = az + dz
        if z < 0:
            continue
        layer_lines = [f"  z={z}:"]
        for dy in range(-radius, radius + 1):
            y = ay + dy
            row_chars: list[str] = []
            for dx in range(-radius, radius + 1):
                x = ax + dx
                if (x, y, z) == anchor:
                    row_chars.append("X")
                    continue
                key = f"{x},{y},{z}"
                cell = blocks.get(key)
                if cell is None:
                    row_chars.append(".")
                else:
                    btype = str(cell.get("type") or "?")
                    row_chars.append(btype[:1].lower() if btype else "?")
            layer_lines.append("    " + " ".join(row_chars))
        lines.extend(layer_lines)
    if not lines:
        return f"  (no cells within radius {radius} of {anchor})"
    legend = (
        f"  Centered on X=({ax},{ay},{az}); '.' = empty, "
        "letter = first char of block type."
    )
    return "\n".join([legend, *lines])


def bot_pacing_nudge(
    state: dict[str, Any],
    bot_id: str,
    *,
    self_count_field: str = "block_count",
    others_label: str = "block",
) -> str | None:
    """Compare this bot's contribution vs the others' average.

    Returns a one-line nudge when the bot is significantly behind or ahead,
    or None when participation is roughly even (or there's only one
    participant). Uses ``state["players"][bot_id][self_count_field]`` as
    the per-bot count.
    """
    players = state.get("players") or {}
    if bot_id not in players or len(players) < 2:
        return None
    self_count = int(players[bot_id].get(self_count_field) or 0)
    others = [
        int((players.get(other) or {}).get(self_count_field) or 0)
        for other in players
        if other != bot_id
    ]
    if not others:
        return None
    avg_others = sum(others) / len(others)
    if avg_others <= 0 and self_count == 0:
        return None
    if self_count == 0 and avg_others >= 1:
        return (
            f"You haven't placed a {others_label} yet; the others have "
            f"placed {int(avg_others)} on average. Jump in."
        )
    if avg_others > 0 and self_count < avg_others * 0.5:
        return (
            f"You're behind on {others_label} count "
            f"({self_count} vs {avg_others:.0f} avg). "
            "Place something visible this round."
        )
    if avg_others > 0 and self_count > avg_others * 2:
        return (
            f"You've placed a lot of {others_label}s "
            f"({self_count} vs {avg_others:.0f} avg). "
            "Consider giving the others room to build."
        )
    return None


def unused_block_types(
    state: dict[str, Any],
    bot_id: str,
    all_types: Iterable[str],
) -> list[str]:
    """Return block types this bot has never placed."""
    used: set[str] = set()
    for cell in (state.get("blocks") or {}).values():
        if cell.get("bot") != bot_id:
            continue
        btype = cell.get("type")
        if isinstance(btype, str) and btype:
            used.add(btype)
    return [t for t in all_types if t not in used]


def recent_failures(
    state: dict[str, Any],
    bot_id: str,
    *,
    limit: int = 3,
) -> list[str]:
    """Pull recent turn-log entries flagged as failures for this bot.

    Failures are entries with ``args.error`` set or ``summary`` starting
    with ``"failed:"``. The framework doesn't write these today — this is
    a forward-compatible probe for future error capture. Returns up to
    ``limit`` summaries, newest first.
    """
    log = list(state.get("turn_log") or [])
    out: list[str] = []
    for entry in reversed(log):
        if entry.get("actor") != bot_id:
            continue
        summary = str(entry.get("summary") or "")
        args = entry.get("args") or {}
        if args.get("error") or summary.startswith("failed:"):
            out.append(summary or "(failure with no summary)")
            if len(out) >= limit:
                break
    return out


def notable_labels(
    blocks: dict[str, dict[str, Any]],
    *,
    cap: int = 50,
) -> list[dict[str, Any]]:
    """Return up to ``cap`` blocks with non-empty labels, newest first.

    Each entry: ``{"x", "y", "z", "type", "label", "bot"}``. Used by
    Blockyard's summarizer so bots can build on each other's named
    pieces ("attach lantern next to Rolland's 'doorframe'").
    """
    out: list[dict[str, Any]] = []
    for key, cell in blocks.items():
        label = cell.get("label")
        if not label:
            continue
        try:
            x_str, y_str, z_str = key.split(",")
            x, y, z = int(x_str), int(y_str), int(z_str)
        except (ValueError, AttributeError):
            continue
        out.append(
            {
                "x": x,
                "y": y,
                "z": z,
                "type": cell.get("type"),
                "label": label,
                "bot": cell.get("bot"),
                "ts": cell.get("ts"),
            },
        )
    out.sort(key=lambda c: c.get("ts") or "", reverse=True)
    return out[:cap]
