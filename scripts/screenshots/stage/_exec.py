"""SSH + docker exec escape hatch.

Used for the two narrow cases where the HTTP admin API deliberately does not
expose runtime state fields (by design — we don't want a scoped key to be able
to fake pipeline progress or mint usage events).

1. ``seed_pipeline_step_states`` — mutate ``tasks.step_states`` / status /
   current_step_index after a normal ``POST /tasks`` pipeline create.
2. ``seed_usage_events`` — insert cost-bearing rows so ``/admin/bots`` cost
   pills render without spending real LLM tokens.

Everything else goes through the HTTP API. If you're tempted to add a third
helper here, add an admin endpoint instead.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

HELPERS_DIR = Path(__file__).resolve().parent / "server_helpers"


def run_server_helper(
    *,
    ssh_alias: str,
    container: str,
    helper_name: str,
    args: list[str],
    dry_run: bool = False,
) -> str:
    """Copy-and-pipe a helper script into the container and execute it.

    The script text is read locally, piped through ssh -> docker exec -i, and
    run as ``python -``. This avoids any file-staging step on the server and
    keeps the helpers versioned in-repo next to their callers.
    """
    script_path = HELPERS_DIR / f"{helper_name}.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Helper script not found: {script_path}")

    script = script_path.read_text()

    remote = [
        "docker",
        "exec",
        "-i",
        container,
        "python",
        "-",
        *args,
    ]
    cmd = ["ssh", ssh_alias, " ".join(shlex.quote(x) for x in remote)]

    if dry_run:
        logger.info("DRY-RUN %s %s", " ".join(cmd), args)
        return ""

    logger.info("Running server helper %s %s", helper_name, args)
    proc = subprocess.run(
        cmd,
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Server helper {helper_name} failed (rc={proc.returncode}):\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout
