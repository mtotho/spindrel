import asyncio
import json
import os

from app.tools.registry import register

DEVELOPMENT_BRANCH = "development"
STABLE_CHANNEL = "stable"
DEVELOPMENT_CHANNEL = "development"


@register({
    "type": "function",
    "function": {
        "name": "git_pull",
        "description": (
            "Update the live server to the latest stable release tag by default, "
            "or to origin development when channel='development'. "
            "Always ask the user for confirmation before running this — "
            "it will cause the server to reload."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "enum": [STABLE_CHANNEL, DEVELOPMENT_CHANNEL],
                    "default": STABLE_CHANNEL,
                },
            },
        },
    },
}, safety_tier="control_plane", returns={
    "type": "object",
    "properties": {
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "exit_code": {"type": "integer"},
    },
    "required": ["stdout", "stderr", "exit_code"],
})
async def git_pull(channel: str = STABLE_CHANNEL) -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = await _update_repo(repo_root, channel)
    return json.dumps(result, ensure_ascii=False)


async def _run_git(repo_root: str, *args: str) -> dict[str, object]:
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", repo_root, *args,
        cwd=repo_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "exit_code": proc.returncode,
    }


async def _update_repo(repo_root: str, channel: str) -> dict[str, object]:
    if channel == DEVELOPMENT_CHANNEL:
        return await _update_development(repo_root)
    if channel != STABLE_CHANNEL:
        return {"stdout": "", "stderr": f"unsupported channel: {channel}", "exit_code": 2}
    return await _update_stable(repo_root)


async def _update_stable(repo_root: str) -> dict[str, object]:
    fetch = await _run_git(repo_root, "fetch", "origin", "--tags", "--prune")
    if fetch["exit_code"] != 0:
        return fetch

    tags = await _run_git(repo_root, "tag", "--sort=-v:refname")
    if tags["exit_code"] != 0:
        return tags
    tag = next((line.strip() for line in str(tags["stdout"]).splitlines() if line.strip()), "")
    if not tag:
        return {"stdout": fetch["stdout"], "stderr": "No release tags found after fetching origin.", "exit_code": 1}

    checkout = await _run_git(repo_root, "checkout", "--detach", f"refs/tags/{tag}")
    checkout["stdout"] = f"{fetch['stdout']}{checkout['stdout']}"
    checkout["stderr"] = f"{fetch['stderr']}{checkout['stderr']}"
    return checkout


async def _update_development(repo_root: str) -> dict[str, object]:
    fetch = await _run_git(repo_root, "fetch", "origin", DEVELOPMENT_BRANCH)
    if fetch["exit_code"] != 0:
        return fetch

    switch = await _run_git(repo_root, "switch", DEVELOPMENT_BRANCH)
    if switch["exit_code"] != 0:
        switch = await _run_git(repo_root, "switch", "-c", DEVELOPMENT_BRANCH, "--track", f"origin/{DEVELOPMENT_BRANCH}")
    if switch["exit_code"] != 0:
        switch["stdout"] = f"{fetch['stdout']}{switch['stdout']}"
        switch["stderr"] = f"{fetch['stderr']}{switch['stderr']}"
        return switch

    pull = await _run_git(repo_root, "pull", "--rebase", "origin", DEVELOPMENT_BRANCH)
    pull["stdout"] = f"{fetch['stdout']}{switch['stdout']}{pull['stdout']}"
    pull["stderr"] = f"{fetch['stderr']}{switch['stderr']}{pull['stderr']}"
    return pull
