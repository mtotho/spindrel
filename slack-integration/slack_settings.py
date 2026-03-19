"""Environment and YAML config for the Slack integration."""
import os
from pathlib import Path

import yaml

_DIR = Path(__file__).resolve().parent

with open(_DIR / "slack_config.yaml") as f:
    _cfg = yaml.safe_load(f) or {}

channel_map: dict[str, str] = _cfg.get("channels", {})
default_bot: str = _cfg.get("default_bot", "default")

BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]  # xoxb-...
APP_LEVEL_TOKEN = os.environ["SLACK_APP_TOKEN"]  # xapp-...
API_KEY = os.environ.get("AGENT_API_KEY") or os.environ.get("API_KEY")
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8000")
STATE_PATH = _DIR / "slack_state.json"
