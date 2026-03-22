import os

# Set required env vars before any app imports trigger Settings() instantiation.
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
