"""E2E test environment — manages the Docker Compose stack lifecycle."""

from __future__ import annotations

import logging
import subprocess
import time
from typing import TYPE_CHECKING

import httpx

from .waiters import wait_for_condition

if TYPE_CHECKING:
    from .config import E2EConfig

logger = logging.getLogger(__name__)

COMPOSE_PROJECT = "spindrel-e2e"


class E2EEnvironment:
    """Manages the E2E Docker Compose stack (postgres + agent-server + optional ollama)."""

    def __init__(self, config: E2EConfig) -> None:
        self.config = config
        self._started = False

    async def setup(self) -> None:
        """Build image, start stack, optionally pull model, wait for healthy."""
        if self.config.is_external:
            logger.info("External mode — skipping compose, using %s", self.config.base_url)
            await self._wait_for_healthy()
            self._started = True
            return
        self._ensure_image()
        self._compose_up()
        if self.config.use_ollama:
            self._pull_ollama_model()
        await self._wait_for_healthy()
        self._started = True

    async def teardown(self) -> None:
        """Stop and remove the compose stack (unless keep_running is set)."""
        if self.config.is_external or self.config.keep_running:
            logger.info("Leaving stack as-is (external=%s, keep_running=%s)",
                        self.config.is_external, self.config.keep_running)
            return
        self._compose_down()
        self._started = False

    # -- Image management --

    def _ensure_image(self) -> None:
        """Check if the Docker image exists; build it if missing and allowed."""
        result = subprocess.run(
            ["docker", "image", "inspect", self.config.image_name],
            capture_output=True,
        )
        if result.returncode == 0:
            logger.info("Image %s already exists", self.config.image_name)
            return

        if not self.config.build_if_missing:
            raise RuntimeError(
                f"Image {self.config.image_name} not found and build_if_missing=False. "
                f"Build it with: docker build -t {self.config.image_name} "
                f"--build-arg BUILD_DASHBOARDS=false {self.config.project_root}"
            )

        logger.info("Building image %s ...", self.config.image_name)
        result = subprocess.run(
            [
                "docker", "build",
                "-t", self.config.image_name,
                "--build-arg", "BUILD_DASHBOARDS=false",
                str(self.config.project_root),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to build image {self.config.image_name}:\n{result.stderr[-2000:]}"
            )
        logger.info("Image %s built successfully", self.config.image_name)

    # -- Compose lifecycle --

    def _compose_cmd(self, *args: str) -> list[str]:
        """Build the base docker compose command."""
        cmd = [
            "docker", "compose",
            "-f", str(self.config.compose_file),
            "-p", COMPOSE_PROJECT,
        ]
        cmd.extend(args)
        return cmd

    def _compose_up(self) -> None:
        """Start the compose stack."""
        env = self._compose_env()
        profiles = ["--profile", "ollama"] if self.config.use_ollama else []

        cmd = self._compose_cmd("up", "-d", *profiles)
        logger.info("Starting E2E stack: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start E2E stack:\n{result.stderr[-2000:]}"
            )
        logger.info("E2E stack started")

    def _compose_down(self) -> None:
        """Stop and remove the compose stack."""
        env = self._compose_env()
        cmd = self._compose_cmd("down", "-v", "--remove-orphans")
        logger.info("Tearing down E2E stack")
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def _compose_env(self) -> dict[str, str]:
        """Build environment variables for the compose command."""
        import os
        env = os.environ.copy()
        env.update({
            "E2E_IMAGE": self.config.image_name,
            "E2E_PORT": str(self.config.port),
            "E2E_API_KEY": self.config.api_key,
            "E2E_LLM_BASE_URL": self.config.llm_base_url,
            "E2E_LLM_API_KEY": self.config.llm_api_key,
            "E2E_DEFAULT_MODEL": self.config.default_model,
            "E2E_BOT_CONFIG": str(self.config.bot_config_file),
        })
        return env

    # -- Model management --

    def _pull_ollama_model(self) -> None:
        """Pull the configured model into the ollama container."""
        logger.info("Pulling model %s in ollama container...", self.config.default_model)
        env = self._compose_env()
        result = subprocess.run(
            self._compose_cmd(
                "exec", "-T", "ollama",
                "ollama", "pull", self.config.default_model,
            ),
            capture_output=True,
            text=True,
            env=env,
            timeout=self.config.model_pull_timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to pull model {self.config.default_model}:\n{result.stderr[-2000:]}"
            )
        logger.info("Model %s ready", self.config.default_model)

    # -- Health polling --

    async def _wait_for_healthy(self) -> None:
        """Poll until health returns ok AND the configured bot is loadable.

        After a restart, /health can return 200 before the bot registry is
        populated.  Tests that hit /chat immediately would get 404 because
        get_bot() raises HTTPException(404) for unknown bot IDs.  So we
        also verify the E2E bot exists via /bots before proceeding.
        """
        url = f"{self.config.base_url}/health"
        bot_url = f"{self.config.base_url}/bots"
        bot_id = self.config.bot_id
        headers = {"Authorization": f"Bearer {self.config.api_key}"}

        async def check() -> bool:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    # Step 1: health endpoint must be up
                    resp = await client.get(url, headers=headers)
                    if resp.status_code != 200:
                        return False
                    body = resp.json()
                    healthy = (
                        body.get("healthy", False)
                        or body.get("database", False)
                        or body.get("status") == "ok"
                    )
                    if not healthy:
                        return False

                    # Step 2: the configured bot must be in the registry
                    resp = await client.get(bot_url, headers=headers)
                    if resp.status_code != 200:
                        return False
                    data = resp.json()
                    bots = data["bots"] if isinstance(data, dict) and "bots" in data else data
                    if not any(b.get("id") == bot_id for b in bots):
                        logger.debug("Bot %s not yet in registry (%d bots loaded)", bot_id, len(bots))
                        return False
                    return True
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
                pass
            return False

        logger.info("Waiting for E2E server at %s (bot=%s) ...", url, bot_id)
        start = time.monotonic()
        try:
            await wait_for_condition(
                check,
                timeout=self.config.startup_timeout,
                interval=2.0,
                description=f"server healthy at {url} with bot {bot_id}",
            )
        except Exception:
            # Dump logs on failure for debugging
            logs = self.get_logs("agent-server", tail=50)
            logger.error("Server failed to become healthy. Logs:\n%s", logs)
            raise

        elapsed = time.monotonic() - start
        logger.info("E2E server healthy in %.1fs (bot %s ready)", elapsed, bot_id)

    # -- Diagnostics --

    def get_logs(self, service: str = "agent-server", tail: int = 100) -> str:
        """Return recent container logs for debugging."""
        env = self._compose_env()
        result = subprocess.run(
            self._compose_cmd("logs", "--tail", str(tail), service),
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        return result.stdout + result.stderr
