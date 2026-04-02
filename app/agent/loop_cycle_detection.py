"""Within-run tool loop cycle detection.

Detects when an LLM gets stuck repeating the same sequence of tool calls
with identical arguments.  Pure logic — no loop.py dependencies.
"""

from __future__ import annotations

import hashlib
from typing import NamedTuple


class ToolCallSignature(NamedTuple):
    """Hashable identity for a single tool call (name + args digest)."""
    name: str
    args_hash: str


def make_signature(name: str, args: str) -> ToolCallSignature:
    """Create a signature from a tool name and its JSON-serialized arguments."""
    return ToolCallSignature(
        name=name,
        args_hash=hashlib.md5(args.encode(), usedforsecurity=False).hexdigest(),
    )


def detect_cycle(
    trace: list[ToolCallSignature],
    min_reps: int = 2,
) -> int | None:
    """Check whether the tail of *trace* is a repeating cycle.

    Scans cycle lengths from 1 up to ``len(trace) // 2``.
    - **Cycle length 1** (same call repeated): requires ``min_reps + 1``
      consecutive occurrences to avoid false positives on legitimate retries.
    - **Cycle length >= 2**: requires ``min_reps`` full repetitions at the tail.

    Returns the cycle length if detected, or ``None``.
    """
    n = len(trace)
    if n < 2:
        return None

    max_cycle_len = n // 2

    for clen in range(1, max_cycle_len + 1):
        required = (min_reps + 1) if clen == 1 else min_reps
        needed = clen * required
        if needed > n:
            continue

        tail = trace[-needed:]
        pattern = tail[:clen]

        match = True
        for rep in range(1, required):
            segment = tail[rep * clen : (rep + 1) * clen]
            if segment != pattern:
                match = False
                break

        if match:
            return clen

    return None
