"""Declarative YAML scenario format — dataclasses and loader."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# -- Dataclasses --


@dataclass
class StepAssertion:
    """A single assertion to check after a scenario step executes."""

    key: str        # e.g. "tool_called", "response_not_empty"
    value: Any      # e.g. ["get_current_time"], True, {"min": 5}


@dataclass
class ScenarioStep:
    """One send-and-verify step within a scenario."""

    message: str
    stream: bool = True
    assertions: list[StepAssertion] = field(default_factory=list)


@dataclass
class InlineBotConfig:
    """Bot config declared inline in a scenario (created via API, deleted after)."""

    id: str
    name: str
    system_prompt: str = "You are a test bot. Be concise."
    model: str | None = None  # None = resolved from E2E config at runtime
    local_tools: list[str] = field(default_factory=list)
    tool_retrieval: bool = True
    tool_similarity_threshold: float | None = None


@dataclass
class Scenario:
    """A complete test scenario loaded from YAML."""

    name: str
    description: str = ""
    bot_id: str | None = None         # pre-mounted bot ID
    bot: InlineBotConfig | None = None  # inline bot (created/deleted)
    tags: list[str] = field(default_factory=list)
    timeout: int = 60
    channel: str = "shared"  # "shared" (one channel for all steps) or "per_step"
    steps: list[ScenarioStep] = field(default_factory=list)
    source_file: str = ""  # path of the YAML file this came from

    def effective_bot_id(self, default: str = "e2e") -> str:
        """Return the bot ID to use for chat requests."""
        if self.bot:
            return self.bot.id
        return self.bot_id or default

    @property
    def test_id(self) -> str:
        """Return a pytest-friendly test ID."""
        return self.name.replace(" ", "_").replace("-", "_")


@dataclass
class StepResult:
    """Result of executing a single scenario step."""

    step_index: int
    passed: bool
    failures: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    response_text: str = ""


@dataclass
class ScenarioResult:
    """Result of executing a complete scenario."""

    scenario: Scenario
    passed: bool
    step_results: list[StepResult] = field(default_factory=list)
    error: str | None = None  # fatal error (e.g. bot creation failed)


# -- YAML Parsing --


def _parse_assertions(raw: list[dict[str, Any]]) -> list[StepAssertion]:
    """Parse assertion dicts from YAML into StepAssertion objects."""
    assertions = []
    for item in raw:
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict assertion: %r", item)
            continue
        for key, value in item.items():
            assertions.append(StepAssertion(key=key, value=value))
    return assertions


def _parse_step(raw: dict[str, Any]) -> ScenarioStep:
    """Parse a single step from YAML."""
    return ScenarioStep(
        message=raw["message"],
        stream=raw.get("stream", True),
        assertions=_parse_assertions(raw.get("assertions", [])),
    )


def _parse_inline_bot(raw: dict[str, Any]) -> InlineBotConfig:
    """Parse an inline bot config from YAML."""
    return InlineBotConfig(
        id=raw["id"],
        name=raw.get("name", raw["id"]),
        system_prompt=raw.get("system_prompt", "You are a test bot. Be concise."),
        model=raw.get("model"),
        local_tools=raw.get("local_tools", []),
        tool_retrieval=raw.get("tool_retrieval", True),
        tool_similarity_threshold=raw.get("tool_similarity_threshold"),
    )


def _parse_scenario(raw: dict[str, Any], source_file: str = "") -> Scenario:
    """Parse a single scenario from YAML."""
    bot = None
    bot_id = None
    if "bot" in raw and isinstance(raw["bot"], dict):
        bot = _parse_inline_bot(raw["bot"])
    elif "bot_id" in raw:
        bot_id = raw["bot_id"]

    return Scenario(
        name=raw["name"],
        description=raw.get("description", ""),
        bot_id=bot_id,
        bot=bot,
        tags=raw.get("tags", []),
        timeout=raw.get("timeout", 60),
        channel=raw.get("channel", "shared"),
        steps=[_parse_step(s) for s in raw.get("steps", [])],
        source_file=source_file,
    )


# -- Public API --


def parse_scenario_from_dict(raw: dict[str, Any], source: str = "<ad-hoc>") -> Scenario:
    """Parse a single scenario from a raw dict (e.g. from yaml.safe_load).

    Public wrapper around _parse_scenario for ad-hoc / programmatic use.
    """
    return _parse_scenario(raw, source_file=source)


# -- Loaders --


def load_scenarios_from_file(path: Path) -> list[Scenario]:
    """Load all scenarios from a single YAML file."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error("Failed to load scenario file %s: %s", path, e)
        return []

    if not data or "scenarios" not in data:
        logger.warning("No 'scenarios' key in %s", path)
        return []

    scenarios = []
    for raw in data["scenarios"]:
        try:
            scenario = _parse_scenario(raw, source_file=str(path))
            scenarios.append(scenario)
        except Exception as e:
            logger.error("Failed to parse scenario in %s: %s", path, e)

    return scenarios


def load_scenarios_from_directory(directory: Path) -> list[Scenario]:
    """Load all scenarios from all YAML files in a directory."""
    if not directory.is_dir():
        logger.debug("Scenario directory %s does not exist", directory)
        return []

    scenarios = []
    for yaml_file in sorted(directory.glob("*.yaml")):
        scenarios.extend(load_scenarios_from_file(yaml_file))
    for yml_file in sorted(directory.glob("*.yml")):
        scenarios.extend(load_scenarios_from_file(yml_file))

    return scenarios
