"""Make the slack integration directory importable for tests."""
import os
import sys
from pathlib import Path

# slack_settings.py reads these at import time and raises KeyError if
# missing. We only need placeholders — tests that touch real Slack APIs
# mock them out.
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
os.environ.setdefault("AGENT_API_KEY", "test-key")

_slack_dir = str(Path(__file__).resolve().parent.parent)
if _slack_dir not in sys.path:
    sys.path.insert(0, _slack_dir)
