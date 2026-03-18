"""Client-side tool execution (e.g. shell_exec)."""
import json
import subprocess


def execute_client_tool(tool_name: str, arguments: dict) -> str:
    """Execute a client-side tool and return the result as a string."""
    if tool_name == "shell_exec":
        command = arguments.get("command", "")
        print(f"  [shell] $ {command}")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = proc.stdout
            if proc.stderr:
                output += ("\n" if output else "") + proc.stderr
            if proc.returncode != 0:
                output += f"\n[exit code {proc.returncode}]"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "[error: command timed out after 30s]"
        except Exception as e:
            return f"[error: {e}]"

    return json.dumps({"error": f"Unknown client tool: {tool_name}"})
