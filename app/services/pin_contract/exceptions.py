"""Narrow exceptions for the pin contract resolver chain.

Replacing the bare ``except Exception: pass`` branches at
``widget_contracts.py:514`` and ``:618`` — when a preset / template / native
spec genuinely no longer exists (uninstalled integration), resolvers raise
one of these so the service can log + fall through cleanly. Any other
exception type propagates: that's a bug, not absent state.
"""
from __future__ import annotations


class PresetNotFound(LookupError):
    """The preset_id named on a pin's origin no longer resolves."""


class TemplateNotFound(LookupError):
    """A tool widget template named on a pin's origin no longer resolves."""


class NativeSpecNotFound(LookupError):
    """A native widget_ref named on a pin's origin no longer resolves."""
