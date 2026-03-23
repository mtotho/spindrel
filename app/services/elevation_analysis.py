"""Analyze elevation_log.jsonl and produce a summary report.

Called periodically (e.g. daily) from the heartbeat worker.
Reads the JSONL log, merges backfill records, computes simple stats,
writes data/elevation_analysis.json, and returns a Slack-formatted summary.
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
_LOG_PATH = os.path.join(_LOG_DIR, "elevation_log.jsonl")
_ANALYSIS_PATH = os.path.join(_LOG_DIR, "elevation_analysis.json")


def _read_and_merge_log() -> list[dict[str, Any]]:
    """Read elevation_log.jsonl, merge backfill records into their parent entries."""
    if not os.path.exists(_LOG_PATH):
        return []

    entries: dict[str, dict[str, Any]] = {}
    with open(_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_id = record.get("id")
            if not entry_id:
                continue
            if record.get("backfill"):
                # Merge backfill fields into existing entry
                if entry_id in entries:
                    for k, v in record.items():
                        if k not in ("id", "backfill") and v is not None:
                            entries[entry_id][k] = v
            else:
                # Primary entry — initialize or update
                if entry_id in entries:
                    entries[entry_id].update(record)
                else:
                    entries[entry_id] = record

    return list(entries.values())


def analyze_elevation_log() -> dict[str, Any]:
    """Compute elevation stats and return the analysis dict."""
    entries = _read_and_merge_log()

    total = len(entries)
    if total == 0:
        return {"total_turns": 0, "generated_at": datetime.now(timezone.utc).isoformat()}

    elevated = [e for e in entries if e.get("was_elevated")]
    not_elevated = [e for e in entries if not e.get("was_elevated")]

    def _outcome_counts(subset: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for e in subset:
            outcome = e.get("outcome", "unknown")
            counts[outcome] += 1
        return dict(counts)

    def _success_rate(subset: list[dict]) -> float | None:
        with_outcome = [e for e in subset if e.get("outcome")]
        if not with_outcome:
            return None
        successes = sum(1 for e in with_outcome if e["outcome"] == "success")
        return round(successes / len(with_outcome), 4)

    def _avg(subset: list[dict], key: str) -> float | None:
        vals = [e[key] for e in subset if e.get(key) is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 1)

    # Group by bot
    by_bot: dict[str, int] = defaultdict(int)
    for e in elevated:
        by_bot[e.get("bot_id", "unknown")] += 1

    # Group by channel
    by_channel: dict[str, int] = defaultdict(int)
    for e in elevated:
        ch = e.get("channel_id") or "unknown"
        by_channel[ch] += 1

    # Group by model
    by_model: dict[str, int] = defaultdict(int)
    for e in elevated:
        by_model[e.get("model_chosen", "unknown")] += 1

    analysis = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_turns": total,
        "elevated_turns": len(elevated),
        "not_elevated_turns": len(not_elevated),
        "elevation_rate": round(len(elevated) / total, 4) if total else 0,
        "elevated_outcomes": _outcome_counts(elevated),
        "not_elevated_outcomes": _outcome_counts(not_elevated),
        "elevated_success_rate": _success_rate(elevated),
        "not_elevated_success_rate": _success_rate(not_elevated),
        "elevated_avg_latency_ms": _avg(elevated, "latency_ms"),
        "not_elevated_avg_latency_ms": _avg(not_elevated, "latency_ms"),
        "elevated_avg_tool_calls": _avg(elevated, "tool_call_count"),
        "not_elevated_avg_tool_calls": _avg(not_elevated, "tool_call_count"),
        "top_bots": dict(sorted(by_bot.items(), key=lambda x: -x[1])[:10]),
        "top_channels": dict(sorted(by_channel.items(), key=lambda x: -x[1])[:10]),
        "top_models": dict(sorted(by_model.items(), key=lambda x: -x[1])[:10]),
    }

    # Write to file
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with open(_ANALYSIS_PATH, "w") as f:
            json.dump(analysis, f, indent=2)
    except Exception:
        logger.warning("Failed to write elevation analysis", exc_info=True)

    return analysis


def format_slack_summary(analysis: dict[str, Any]) -> str:
    """Format the analysis dict as a Slack-friendly text summary."""
    if analysis.get("total_turns", 0) == 0:
        return "*Elevation Analysis*: No elevation data yet."

    lines = [
        "*Elevation Analysis*",
        f"Total turns: {analysis['total_turns']}",
        f"Elevated: {analysis['elevated_turns']} ({analysis['elevation_rate']:.1%})",
        "",
        "*Success Rates*",
        f"  Elevated: {_fmt_rate(analysis.get('elevated_success_rate'))}",
        f"  Not elevated: {_fmt_rate(analysis.get('not_elevated_success_rate'))}",
        "",
        "*Outcomes (elevated)*",
    ]
    for outcome, count in (analysis.get("elevated_outcomes") or {}).items():
        lines.append(f"  {outcome}: {count}")

    lines.append("")
    lines.append("*Outcomes (not elevated)*")
    for outcome, count in (analysis.get("not_elevated_outcomes") or {}).items():
        lines.append(f"  {outcome}: {count}")

    if analysis.get("elevated_avg_latency_ms") is not None:
        lines.append("")
        lines.append("*Avg Latency (ms)*")
        lines.append(f"  Elevated: {analysis['elevated_avg_latency_ms']}")
        lines.append(f"  Not elevated: {analysis.get('not_elevated_avg_latency_ms', 'N/A')}")

    if analysis.get("elevated_avg_tool_calls") is not None:
        lines.append("")
        lines.append("*Avg Tool Calls*")
        lines.append(f"  Elevated: {analysis['elevated_avg_tool_calls']}")
        lines.append(f"  Not elevated: {analysis.get('not_elevated_avg_tool_calls', 'N/A')}")

    if analysis.get("top_models"):
        lines.append("")
        lines.append("*Top Elevated Models*")
        for model, count in analysis["top_models"].items():
            lines.append(f"  {model}: {count}")

    if analysis.get("top_bots"):
        lines.append("")
        lines.append("*Top Bots (elevated)*")
        for bot, count in analysis["top_bots"].items():
            lines.append(f"  {bot}: {count}")

    if analysis.get("top_channels"):
        lines.append("")
        lines.append("*Top Channels (elevated)*")
        for ch, count in analysis["top_channels"].items():
            lines.append(f"  {ch}: {count}")

    return "\n".join(lines)


def _fmt_rate(rate: float | None) -> str:
    if rate is None:
        return "N/A"
    return f"{rate:.1%}"
