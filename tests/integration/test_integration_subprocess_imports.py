"""Integration subprocess import smoke test.

Spawns a fresh Python interpreter for each integration's subprocess
entry script and asserts the import phase completes without
ImportError on a *local* symbol. Catches the class of bug where a
refactor deletes a symbol still imported by the subprocess side —
e.g., the session-12 Slack crash loop where ``slash_commands.py`` still
imported the deleted ``stream_chat`` from ``agent_client``.

Why subprocess instead of pytest's main process: each subprocess entry
sets up its own ``sys.path`` (e.g., inserts ``integrations/slack/``),
which doesn't match the test runner's import topology. Spawning a real
child process matches what production runs and ensures the entry
script's actual import graph is exercised.

This is an import-phase test, not a connect-and-authenticate test. We
stub any env vars that are read at module top level so module bodies
can finish executing, but we never reach ``main()`` (the
``if __name__ == '__main__'`` block doesn't fire because we load the
script under a different module name via importlib).

Optional third-party deps (e.g., ``discord.py``, ``aiomqtt``) live in
each integration's own ``requirements.txt`` and are NOT installed in
``Dockerfile.test``. When such a dep is missing the test SKIPS that
integration with a clear reason. Local intra-repo ImportError still
fails the test — that's the actual failure mode this test exists to
catch.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATIONS_DIR = REPO_ROOT / "integrations"

# Stub env vars for integrations whose subprocess entry scripts read
# os.environ at module top level. Real values are not needed — these
# are import-phase smoke tests, not authenticate-and-connect tests.
# Add a key here when a new integration adds a top-level os.environ
# read in its entry script (KeyError will tell you which one).
STUB_ENV: dict[str, str] = {
    "SLACK_BOT_TOKEN": "xoxb-test",
    "SLACK_APP_TOKEN": "xapp-test",
    "DISCORD_TOKEN": "discord-test",
    "FRIGATE_MQTT_BROKER": "localhost",
    "BLUEBUBBLES_SERVER_URL": "http://localhost",
    "BLUEBUBBLES_PASSWORD": "test",
    "GMAIL_EMAIL": "test@example.com",
    "GMAIL_APP_PASSWORD": "test",
    "AGENT_BASE_URL": "http://localhost:8000",
    "AGENT_API_KEY": "test-key",
}


def _discover_subprocess_entries() -> list[tuple[str, Path]]:
    """Find every (integration_name, script_path) declared by process.py CMD
    or by the YAML ``process.cmd`` section in integration.yaml.

    Reads each ``integrations/*/process.py``'s ``CMD`` attribute via
    importlib so new integrations are picked up automatically. Also reads
    ``integrations/*/integration.yaml`` for YAML-declared processes.
    Skips integrations that declare ``CMD = None`` (e.g., bluebubbles,
    which runs as a webhook only).
    """
    import yaml as _yaml

    entries: list[tuple[str, Path]] = []
    seen: set[str] = set()

    # 1. process.py (legacy)
    for process_py in sorted(INTEGRATIONS_DIR.glob("*/process.py")):
        integration = process_py.parent.name
        spec = importlib.util.spec_from_file_location(
            f"_smoke_process_{integration}", process_py
        )
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            continue
        cmd = getattr(module, "CMD", None)
        if not cmd or not isinstance(cmd, list) or len(cmd) < 2:
            continue
        script_rel = cmd[1]
        script_path = REPO_ROOT / script_rel
        if not script_path.exists() or script_path.suffix != ".py":
            continue
        entries.append((integration, script_path))
        seen.add(integration)

    # 2. integration.yaml process.cmd (modern)
    for yaml_path in sorted(INTEGRATIONS_DIR.glob("*/integration.yaml")):
        integration = yaml_path.parent.name
        if integration in seen:
            continue
        try:
            with open(yaml_path) as f:
                data = _yaml.safe_load(f)
            process = data.get("process") if isinstance(data, dict) else None
            if not process or not isinstance(process, dict):
                continue
            cmd = process.get("cmd")
            if not cmd or not isinstance(cmd, list) or len(cmd) < 2:
                continue
            script_rel = cmd[1]
            script_path = REPO_ROOT / script_rel
            if not script_path.exists() or script_path.suffix != ".py":
                continue
            entries.append((integration, script_path))
        except Exception:
            continue

    return entries


SUBPROCESS_ENTRIES = _discover_subprocess_entries()


# External top-level packages each integration's entry script imports.
# If any of these aren't installed in the test environment we skip the
# corresponding parametrize case — the dep lives in the integration's
# own requirements.txt, not in the main test image. A local ImportError
# (one of OUR modules / OUR symbols) is still a hard failure.
_EXTERNAL_DEP_HINTS: dict[str, tuple[str, ...]] = {
    "slack": ("slack_bolt",),
    "discord": ("discord",),
    "frigate": ("aiomqtt",),
    "gmail": ("imapclient",),
    "bluebubbles": ("socketio",),
}


def _missing_external_deps(integration: str) -> list[str]:
    """Return any external packages declared for ``integration`` that
    aren't importable in the current test environment."""
    hints = _EXTERNAL_DEP_HINTS.get(integration, ())
    missing: list[str] = []
    for pkg in hints:
        if importlib.util.find_spec(pkg) is None:
            missing.append(pkg)
    return missing


@pytest.mark.parametrize(
    "integration,script_path",
    SUBPROCESS_ENTRIES,
    ids=[name for name, _ in SUBPROCESS_ENTRIES] or ["_no_entries_discovered"],
)
def test_integration_subprocess_imports_clean(
    integration: str, script_path: Path
) -> None:
    """Spawn each integration's subprocess entry and verify it imports
    cleanly with no ImportError / ModuleNotFoundError / NameError.

    The script is loaded via ``importlib.util.spec_from_file_location``
    in a child process, which executes the module body but skips the
    ``if __name__ == '__main__'`` block — so we exercise every
    top-level import without ever calling ``main()``.
    """
    missing = _missing_external_deps(integration)
    if missing:
        pytest.skip(
            f"{integration}: external deps not installed in test "
            f"image: {missing}. These live in "
            f"integrations/{integration}/requirements.txt, not "
            f"pyproject.toml; the smoke test only catches local "
            f"ImportError when the deps are present."
        )

    env = os.environ.copy()
    env.update(STUB_ENV)

    # Use a tiny shim that loads the entry script under a synthetic
    # module name so its ``__name__ == '__main__'`` guard never fires.
    # Module-level code STILL executes — that's the entire point.
    import_stub = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location("
        f"'_smoke_{integration}_entry', r'{script_path}')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        f"sys.modules['_smoke_{integration}_entry'] = module\n"
        "spec.loader.exec_module(module)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", import_stub],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )

    if result.returncode != 0:
        pytest.fail(
            f"Importing {integration} subprocess entry "
            f"{script_path.relative_to(REPO_ROOT)} failed with exit "
            f"code {result.returncode}:\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )


def test_subprocess_entry_discovery_finds_known_integrations() -> None:
    """Sanity check the discovery loop — if a refactor renames or moves
    process.py files, this test fails loudly instead of the parametrize
    silently shrinking to zero cases.
    """
    discovered = {name for name, _ in SUBPROCESS_ENTRIES}
    expected_subset = {"slack", "discord"}
    missing = expected_subset - discovered
    assert not missing, (
        f"Expected subprocess entries for {expected_subset}, missing "
        f"{missing}. Discovered: {sorted(discovered)}"
    )
