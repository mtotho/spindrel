"""Deterministic e2e transcription hook.

This lives under tests/e2e and is mounted through INTEGRATION_DIRS by the e2e
compose file. Production STT providers do not know about this path.
"""

from __future__ import annotations

from integrations.sdk import HookContext, register_hook


def _before_transcription(ctx: HookContext, **_kwargs) -> str | None:
    if (ctx.extra or {}).get("source") != "chat":
        return None
    return "Reply with only VOICE_OK."


register_hook("before_transcription", _before_transcription)
