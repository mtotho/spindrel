"""Pytest fixtures for E2E tests.

Session-scoped environment (compose stack starts once per pytest session).
Function-scoped client (fresh per test, with unique channel IDs for isolation).
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

import pytest
import pytest_asyncio

from .harness.config import E2EConfig
from .harness.environment import E2EEnvironment
from .harness.client import E2EClient

logger = logging.getLogger(__name__)


def pytest_configure(config: pytest.Config) -> None:
    """Override the default '-m not e2e' when targeting e2e tests directly."""
    # If any of the specified paths are under tests/e2e/, remove the marker filter
    args = config.invocation_params.args
    if any("tests/e2e" in str(a) or "e2e/" in str(a) for a in args):
        # Clear the marker expression that was set by addopts
        config.option.markexpr = ""


@pytest.fixture(scope="session")
def e2e_config() -> E2EConfig:
    """Load E2E configuration from environment variables."""
    return E2EConfig.from_env()


@pytest_asyncio.fixture(scope="session")
async def e2e_env(e2e_config: E2EConfig) -> AsyncGenerator[E2EEnvironment, None]:
    """Start the E2E compose stack once for the entire test session."""
    env = E2EEnvironment(e2e_config)
    await env.setup()
    yield env
    await env.teardown()


@pytest_asyncio.fixture
async def client(
    e2e_config: E2EConfig,
    e2e_env: E2EEnvironment,  # noqa: ARG001 — ensures stack is up
) -> AsyncGenerator[E2EClient, None]:
    """Fresh E2E client per test. Auto-closes on teardown."""
    c = E2EClient(e2e_config)
    yield c
    await c.close()
