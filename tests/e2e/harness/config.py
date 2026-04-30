"""E2E test configuration — all knobs, loaded from E2E_* env vars."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_SMOKE_MODELS = [
    {"model": "gemini-2.5-flash-lite"},
    {"model": "gemma4:e4b"},
]


@dataclass
class E2EConfig:
    """Configuration for the E2E test harness."""

    # Mode: "compose" (default) spins up Docker stack; "external" skips it
    mode: str = "compose"

    # Docker image
    image_name: str = "spindrel:e2e"
    build_if_missing: bool = True

    # LLM provider — external endpoint (Gemini by default).
    # Pointing at a local ollama? Set E2E_LLM_BASE_URL to its URL (e.g. http://mac-mini:11434/v1).
    llm_base_url: str = ""
    llm_api_key: str = ""
    default_model: str = "gemini-2.5-flash-lite"

    # Model smoke test targets (Tier 3)
    smoke_models: list[dict] = field(default_factory=lambda: list(_DEFAULT_SMOKE_MODELS))

    # Server connection
    host: str = ""  # auto-detected in __post_init__
    port: int = 18000
    api_key: str = "e2e-test-key-12345"

    # Timeouts (seconds)
    startup_timeout: int = 120
    request_timeout: int = 60

    # Default bot for tests (override for external servers without e2e bot)
    bot_id: str = "e2e"

    # Behavior
    keep_running: bool = False
    wipe_db_on_teardown: bool = False

    # Paths
    compose_file: Path = field(default_factory=lambda: Path(__file__).parent.parent / "docker-compose.e2e.yml")
    compose_overrides: list[Path] = field(default_factory=list)
    bot_config_file: Path = field(default_factory=lambda: Path(__file__).parent.parent / "bot.e2e.yaml")
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent.parent)

    def __post_init__(self) -> None:
        if not self.host:
            # Auto-detect Docker environment
            self.host = "host.docker.internal" if Path("/.dockerenv").exists() else "localhost"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_external(self) -> bool:
        return self.mode == "external"

    @classmethod
    def from_env(cls) -> E2EConfig:
        """Load configuration from E2E_* environment variables."""
        compose_overrides = [
            Path(p).expanduser()
            for p in os.environ.get("E2E_COMPOSE_OVERRIDES", "").split(":")
            if p.strip()
        ]
        return cls(
            mode=os.environ.get("E2E_MODE", "compose"),
            image_name=os.environ.get("E2E_IMAGE", "spindrel:e2e"),
            build_if_missing=os.environ.get("E2E_BUILD_IF_MISSING", "1") == "1",
            llm_base_url=os.environ.get("E2E_LLM_BASE_URL", ""),
            llm_api_key=os.environ.get("E2E_LLM_API_KEY", ""),
            default_model=os.environ.get("E2E_DEFAULT_MODEL", "gemini-2.5-flash-lite"),
            smoke_models=json.loads(os.environ.get("E2E_SMOKE_MODELS", "null")) or list(_DEFAULT_SMOKE_MODELS),
            host=os.environ.get("E2E_HOST", ""),
            port=int(os.environ.get("E2E_PORT", "18000")),
            api_key=os.environ.get("E2E_API_KEY", "e2e-test-key-12345"),
            startup_timeout=int(os.environ.get("E2E_STARTUP_TIMEOUT", "120")),
            request_timeout=int(os.environ.get("E2E_REQUEST_TIMEOUT", "60")),
            bot_id=os.environ.get("E2E_BOT_ID", "e2e"),
            keep_running=os.environ.get("E2E_KEEP_RUNNING", "") == "1",
            wipe_db_on_teardown=os.environ.get("E2E_WIPE_DB_ON_TEARDOWN", "") == "1",
            compose_overrides=compose_overrides,
        )
