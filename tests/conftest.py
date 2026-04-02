import os

# Set required env vars before any app imports trigger Settings() instantiation.
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
# Disable tool policy engine in tests — the SQLite test DB doesn't reliably
# have all tables, and most unit tests don't need policy evaluation.
os.environ.setdefault("TOOL_POLICY_ENABLED", "false")
