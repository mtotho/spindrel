import asyncio
import json
import os

from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "git_pull",
        "description": (
            "Pull latest code from origin master on the live server. "
            "Always ask the user for confirmation before running this — "
            "it will cause the server to reload."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}, safety_tier="control_plane")
async def git_pull() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    proc = await asyncio.create_subprocess_exec(
        "git", "pull", "origin", "master",
        cwd=repo_root,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return json.dumps({
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "exit_code": proc.returncode,
    }, ensure_ascii=False)
