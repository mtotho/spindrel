"""Tool Surface composition.

Owns the "what tools does the LLM see this turn?" question: heartbeat
determinism, RAG retrieval, memory-flush mode selection, skill enrollment
loading, finalization (client-tools merge + budget application).

Sibling to `app/agent/context_assembly.py`, which delegates to this package
via `compose_stream(...)` and consumes the resulting `ToolSurfaceResult`.

A separate runtime guard exists at `app/agent/loop_helpers._resolve_loop_tools`
that filters tools per-iteration. That seam is intentionally kept distinct
from this package — folding it in would conflate assembly-time composition
with iteration-time filtering.
"""
from __future__ import annotations

from .types import ToolSurfaceResult, ToolSurfaceTraceEvent

__all__ = ["ToolSurfaceResult", "ToolSurfaceTraceEvent"]
