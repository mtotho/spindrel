"""E2E test configuration — all knobs, loaded from E2E_* env vars."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class E2EConfig:
    """Configuration for the E2E test harness."""

    # Mode: "compose" (default) spins up Docker stack; "external" skips it
    mode: str = "compose"

    # Docker image
    image_name: str = "agent-server:e2e"
    build_if_missing: bool = True

    # LLM provider
    llm_provider: str = "ollama"  # "ollama" or "external"
    llm_base_url: str = ""  # resolved in __post_init__
    llm_api_key: str = ""
    default_model: str = "gemma3:1b"

    # Server connection
    host: str = ""  # auto-detected in __post_init__
    port: int = 18000
    api_key: str = "e2e-test-key-12345"

    # Timeouts (seconds)
    startup_timeout: int = 120
    request_timeout: int = 60
    model_pull_timeout: int = 300

    # Default bot for tests (override for external servers without e2e bot)
    bot_id: str = "e2e"

    # Behavior
    keep_running: bool = False

    # Paths
    compose_file: Path = field(default_factory=lambda: Path(__file__).parent.parent / "docker-compose.e2e.yml")
    bot_config_file: Path = field(default_factory=lambda: Path(__file__).parent.parent / "bot.e2e.yaml")
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent.parent)

    def __post_init__(self) -> None:
        if not self.host:
            # Auto-detect Docker environment
            self.host = "host.docker.internal" if Path("/.dockerenv").exists() else "localhost"
        if not self.llm_base_url:
            if self.llm_provider == "ollama":
                self.llm_base_url = "http://ollama:11434/v1"
            else:
                self.llm_base_url = "http://localhost:11434/v1"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def use_ollama(self) -> bool:
        return self.llm_provider == "ollama"

    @property
    def is_external(self) -> bool:
        return self.mode == "external"

    @classmethod
    def from_env(cls) -> E2EConfig:
        """Load configuration from E2E_* environment variables."""
        return cls(
            mode=os.environ.get("E2E_MODE", "compose"),
            image_name=os.environ.get("E2E_IMAGE", "agent-server:e2e"),
            build_if_missing=os.environ.get("E2E_BUILD_IF_MISSING", "1") == "1",
            llm_provider=os.environ.get("E2E_LLM_PROVIDER", "ollama"),
            llm_base_url=os.environ.get("E2E_LLM_BASE_URL", ""),
            llm_api_key=os.environ.get("E2E_LLM_API_KEY", ""),
            default_model=os.environ.get("E2E_DEFAULT_MODEL", "gemma3:1b"),
            host=os.environ.get("E2E_HOST", ""),
            port=int(os.environ.get("E2E_PORT", "18000")),
            api_key=os.environ.get("E2E_API_KEY", "e2e-test-key-12345"),
            startup_timeout=int(os.environ.get("E2E_STARTUP_TIMEOUT", "120")),
            request_timeout=int(os.environ.get("E2E_REQUEST_TIMEOUT", "60")),
            model_pull_timeout=int(os.environ.get("E2E_MODEL_PULL_TIMEOUT", "300")),
            bot_id=os.environ.get("E2E_BOT_ID", "e2e"),
            keep_running=os.environ.get("E2E_KEEP_RUNNING", "") == "1",
        )
