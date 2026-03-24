"""Tool registration shim for integrations.

When running inside the agent server, this re-exports the real register
decorator from app.tools.registry. When running standalone (e.g. an
external integration developing/testing outside the server), it provides
a compatible stub that just attaches the schema to the function.
"""

try:
    from app.tools.registry import register  # noqa: F401
except ImportError:

    def register(schema, *, source_dir=None):
        """Stub register — attaches schema for later discovery."""

        def decorator(func):
            func._tool_schema = schema
            return func

        return decorator
