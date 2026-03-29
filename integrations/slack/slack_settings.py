"""Environment and YAML config for the Slack integration."""
import os
import time
from pathlib import Path

import httpx
import yaml

_DIR = Path(__file__).resolve().parent

# Legacy YAML fallback
_yaml_cfg: dict = {}
_yaml_path = _DIR / "slack_config.yaml"
if _yaml_path.exists():
    try:
        with open(_yaml_path) as f:
            _yaml_cfg = yaml.safe_load(f) or {}
    except Exception:
        _yaml_cfg = {}

_yaml_channel_map: dict[str, str] = _yaml_cfg.get("channels", {})
_yaml_default_bot: str = _yaml_cfg.get("default_bot", "default")

BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]  # xoxb-...
APP_LEVEL_TOKEN = os.environ["SLACK_APP_TOKEN"]  # xapp-...

API_KEY = os.environ.get("AGENT_API_KEY") or os.environ.get("API_KEY")
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8000")
STATE_PATH = _DIR / "slack_state.json"

# ---------------------------------------------------------------------------
# Live config cache (TTL=60s) — reads from /api/slack/config on agent server
# ---------------------------------------------------------------------------
_config_cache: dict = {}
_config_cache_ts: float = 0.0
_CONFIG_TTL = 60.0


def _fetch_slack_config() -> dict:
    """Synchronously fetch Slack config from agent server API."""
    url = f"{AGENT_BASE_URL}/integrations/slack/config"
    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    try:
        r = httpx.get(url, headers=headers, timeout=5.0)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


def get_slack_config() -> dict:
    """Return cached Slack config, refreshing if TTL expired."""
    global _config_cache, _config_cache_ts
    now = time.monotonic()
    if now - _config_cache_ts > _CONFIG_TTL:
        fresh = _fetch_slack_config()
        if fresh:
            _config_cache = fresh
            _config_cache_ts = now
        elif not _config_cache:
            # First call failed — use YAML fallback
            _config_cache = {
                "default_bot": _yaml_default_bot,
                "channels": _yaml_channel_map,
            }
            _config_cache_ts = now
    return _config_cache


# Provide module-level channel_map / default_bot for backward compat
def _get_channel_map() -> dict[str, str]:
    cfg = get_slack_config()
    channels = cfg.get("channels", _yaml_channel_map)
    # channels may be dict[str, str] (legacy) or dict[str, dict] (new format)
    result: dict[str, str] = {}
    for k, v in channels.items():
        if isinstance(v, dict):
            result[k] = v.get("bot_id") or ""
        else:
            result[k] = v
    return result


def _get_default_bot() -> str:
    return get_slack_config().get("default_bot", _yaml_default_bot)


def get_channel_config(channel_id: str) -> dict:
    """Return full config for a channel: bot_id, require_mention, passive_memory."""
    cfg = get_slack_config()
    channels = cfg.get("channels", {})
    ch = channels.get(channel_id, {})
    default_bot = cfg.get("default_bot", _yaml_default_bot)
    if isinstance(ch, dict):
        return {
            "bot_id": ch.get("bot_id") or default_bot,
            "require_mention": ch.get("require_mention", True),
            "passive_memory": ch.get("passive_memory", True),
            "allow_bot_messages": ch.get("allow_bot_messages", False),
            "thinking_display": ch.get("thinking_display", "append"),
        }
    # Legacy: ch is a bot_id string
    bot_id = ch if ch else default_bot
    return {
        "bot_id": bot_id,
        "require_mention": True,
        "passive_memory": True,
        "allow_bot_messages": False,
        "thinking_display": "append",
    }


# For modules that import these at import time, give them live-refreshing proxies
class _ChannelMapProxy:
    def get(self, key, default=None):
        return _get_channel_map().get(key, default)

    def __contains__(self, key):
        return key in _get_channel_map()

    def items(self):
        return _get_channel_map().items()


channel_map: dict[str, str] = _ChannelMapProxy()  # type: ignore[assignment]
default_bot: str = _yaml_default_bot  # initial value; state.py calls _get_default_bot() dynamically


def get_bot_display_info(bot_id: str) -> dict:
    """Return display name and icon info for a bot from cached config."""
    bots = get_slack_config().get("bots", {})
    return bots.get(bot_id, {})
