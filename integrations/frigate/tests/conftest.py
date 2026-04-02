"""Ensure env vars are set before app.config imports."""
import os

os.environ.setdefault("API_KEY", "test-key")
