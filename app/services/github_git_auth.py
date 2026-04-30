"""Helpers for non-interactive GitHub git/gh authentication."""
from __future__ import annotations

import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping


def prepare_github_git_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return env with a reusable askpass helper when a GitHub token is present."""
    env = dict(base_env or os.environ)
    token = (env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or "").strip()
    if not token:
        return env
    env["GITHUB_TOKEN"] = token
    env["GH_TOKEN"] = token
    env.setdefault("GITHUB_USERNAME", "x-access-token")
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    script = Path(tempfile.gettempdir()) / "spindrel-github-askpass.sh"
    if not script.exists():
        script.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "*Username*) printf '%s\\n' \"${GITHUB_USERNAME:-x-access-token}\" ;;\n"
            "*) printf '%s\\n' \"${GITHUB_TOKEN:-$GH_TOKEN}\" ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        script.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    env["GIT_ASKPASS"] = str(script)
    return env


@contextmanager
def github_git_env(base_env: Mapping[str, str] | None = None) -> Iterator[dict[str, str]]:
    """Return an env that lets git and gh consume GITHUB_TOKEN non-interactively.

    GitHub CLI reads GH_TOKEN/GITHUB_TOKEN directly, but plain git over HTTPS
    needs an askpass helper. The helper script references the env var at run
    time; it does not write the token into the filesystem.
    """
    env = prepare_github_git_env(base_env)
    token = (env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or "").strip()
    if not token:
        yield env
        return

    env["GITHUB_TOKEN"] = token
    env["GH_TOKEN"] = token
    env.setdefault("GITHUB_USERNAME", "x-access-token")
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"

    with tempfile.TemporaryDirectory(prefix="spindrel-git-askpass-") as tmp:
        script = Path(tmp) / "askpass.sh"
        script.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "*Username*) printf '%s\\n' \"${GITHUB_USERNAME:-x-access-token}\" ;;\n"
            "*) printf '%s\\n' \"${GITHUB_TOKEN:-$GH_TOKEN}\" ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        script.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        env["GIT_ASKPASS"] = str(script)
        yield env
