"""Google Workspace CLI wrapper tool."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
import tempfile
import time

import httpx

from integrations import _register as reg
from integrations.google_workspace.config import SERVICE_ALIASES

logger = logging.getLogger(__name__)

setting = reg.get_settings()

# Max output size to return (50 KB)
_MAX_OUTPUT = 50_000

# Refresh the access token if it expires within this many seconds
_REFRESH_BUFFER_SECONDS = 120


def _extract_service(command: str) -> str | None:
    """Extract the service name from a GWS CLI command string.

    The first token is the service (e.g., 'drive' from 'drive files list').
    """
    parts = command.strip().split()
    if not parts:
        return None
    return parts[0].lower()


def _normalize_service(raw: str) -> str:
    """Normalize a service name, resolving known aliases."""
    return SERVICE_ALIASES.get(raw, raw)


async def _refresh_access_token() -> str | None:
    """Refresh the access token using the stored refresh token.

    Returns the new access token, or None if refresh failed.
    Updates stored tokens in DB on success.
    """
    client_id = setting("GWS_CLIENT_ID")
    client_secret = setting("GWS_CLIENT_SECRET")
    refresh_token = setting("GWS_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )

        if resp.status_code != 200:
            logger.error("Token refresh failed: %s %s", resp.status_code, resp.text[:500])
            return None

        data = resp.json()
        new_access_token = data.get("access_token", "")
        expires_in = data.get("expires_in")
        expires_at = str(int(time.time() + expires_in)) if expires_in else ""

        if not new_access_token:
            return None

        # Persist the refreshed token
        try:
            from app.db.engine import async_session
            from app.services.integration_settings import update_settings

            setup_vars = [
                {"key": "GWS_ACCESS_TOKEN", "secret": True},
                {"key": "GWS_TOKEN_EXPIRES_AT", "secret": False},
            ]
            async with async_session() as db:
                await update_settings(
                    "google_workspace",
                    {"GWS_ACCESS_TOKEN": new_access_token, "GWS_TOKEN_EXPIRES_AT": expires_at},
                    setup_vars,
                    db,
                )
        except Exception:
            logger.debug("Failed to persist refreshed token to DB", exc_info=True)

        logger.info("Google Workspace access token refreshed (expires in %ss)", expires_in)
        return new_access_token
    except Exception:
        logger.error("Token refresh request failed", exc_info=True)
        return None


def _token_needs_refresh() -> bool:
    """Check if the access token is expired or expiring soon."""
    expires_at = setting("GWS_TOKEN_EXPIRES_AT")
    if not expires_at:
        # No expiry tracked — assume expired to be safe
        return True
    try:
        return time.time() >= (int(expires_at) - _REFRESH_BUFFER_SECONDS)
    except (ValueError, TypeError):
        return True


async def _get_channel_allowed_services(channel_id) -> list[str] | None:
    """Get allowed services for the current channel from its ChannelIntegration config.

    Returns list of allowed service names, or None if integration not activated.
    """
    if not channel_id:
        return None

    try:
        from app.db.engine import async_session
        from app.db.models import ChannelIntegration
        from sqlalchemy import select

        async with async_session() as db:
            stmt = select(ChannelIntegration).where(
                ChannelIntegration.channel_id == channel_id,
                ChannelIntegration.integration_type == "google_workspace",
                ChannelIntegration.activated.is_(True),
            )
            result = await db.execute(stmt)
            ci = result.scalar_one_or_none()
            if not ci:
                return None

            config = ci.activation_config or {}
            return config.get("allowed_services", ["drive", "gmail", "calendar"])
    except Exception:
        logger.debug("Failed to check channel integration config", exc_info=True)
        return None


def _build_credentials_json() -> dict | None:
    """Build a credentials dict from stored OAuth tokens."""
    client_id = setting("GWS_CLIENT_ID")
    client_secret = setting("GWS_CLIENT_SECRET")
    refresh_token = setting("GWS_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        return None

    return {
        "type": "authorized_user",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }


@reg.register({
    "type": "function",
    "function": {
        "name": "gws",
        "description": "Execute Google Workspace CLI commands for Drive, Gmail, Calendar, Sheets, Docs, and more. The command should NOT include the 'gws' prefix.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "GWS CLI command (without 'gws' prefix). Examples: 'drive files list', 'gmail +triage', 'calendar +agenda'",
                },
            },
            "required": ["command"],
        },
    },
})
async def gws(command: str) -> str:
    """Execute a Google Workspace CLI command with channel-scoped service access."""
    # Check binary exists (also check ~/.local/bin where user-prefix npm installs go)
    _gws_bin = shutil.which("gws") or shutil.which("gws", path=os.path.expanduser("~/.local/bin"))
    if not _gws_bin:
        return (
            "Error: GWS CLI binary not found. "
            "Install via Admin > Integrations > Google Workspace > Install npm Packages."
        )

    # Check credentials
    creds = _build_credentials_json()
    if not creds:
        return (
            "Error: Google account not connected. "
            "Configure OAuth in Admin > Integrations > Google Workspace."
        )

    # Proactively refresh the access token if expired or expiring soon
    if _token_needs_refresh():
        refreshed = await _refresh_access_token()
        if not refreshed:
            return (
                "Error: Google access token expired and refresh failed. "
                "The account owner needs to reconnect at Admin > Integrations > Google Workspace."
            )

    # Extract and validate service
    raw_service = _extract_service(command)
    if not raw_service:
        return "Error: Empty command. Provide a GWS CLI command like 'drive files list'."

    service = _normalize_service(raw_service)

    # Check channel-level service scoping
    from app.agent.context import current_channel_id
    channel_id = current_channel_id.get()
    allowed = await _get_channel_allowed_services(channel_id)

    if allowed is None:
        return (
            "Error: Google Workspace integration is not activated on this channel. "
            "Activate it in the channel's Integrations tab."
        )

    if service not in allowed:
        return (
            f"Error: Service '{service}' is not enabled on this channel. "
            f"Enabled services: {', '.join(allowed)}. "
            "Change this in the channel's Integrations tab."
        )

    # Write temporary credentials file
    tmp_cred = None
    try:
        tmp_cred = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="gws_creds_", delete=False
        )
        json.dump(creds, tmp_cred)
        tmp_cred.close()

        # Build environment with credentials
        env = os.environ.copy()
        env["GOOGLE_APPLICATION_CREDENTIALS"] = tmp_cred.name

        timeout = 60
        try:
            timeout = int(setting("GWS_TIMEOUT", "60"))
        except (ValueError, TypeError):
            pass

        try:
            args = [_gws_bin] + shlex.split(command)
        except ValueError as exc:
            return f"Error: Invalid command syntax: {exc}"

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )

        output = stdout.decode(errors="replace")
        err_output = stderr.decode(errors="replace")

        if proc.returncode != 0:
            combined = (err_output or output).strip()
            combined_lower = combined.lower()
            # Detect auth failures from the CLI and surface a clear message
            if any(hint in combined_lower for hint in [
                "invalid_grant", "token has been expired or revoked",
                "token has been revoked", "unauthorized", "401",
                "refresh token", "invalid credentials",
            ]):
                return (
                    "Error: Google authentication failed — the account connection "
                    "may have expired or been revoked. "
                    "Reconnect at Admin > Integrations > Google Workspace."
                )
            if len(combined) > _MAX_OUTPUT:
                combined = combined[:_MAX_OUTPUT] + "\n... (output truncated)"
            return f"GWS CLI error (exit {proc.returncode}):\n{combined}"

        result = output.strip()
        if err_output.strip():
            result += f"\n\n(stderr: {err_output.strip()[:1000]})"

        if len(result) > _MAX_OUTPUT:
            result = result[:_MAX_OUTPUT] + "\n... (output truncated)"

        return result if result else "(no output)"

    except asyncio.TimeoutError:
        return f"Error: Command timed out after {timeout}s. Try a more specific query or increase GWS_TIMEOUT."
    except Exception as exc:
        logger.error("GWS CLI execution failed: %s", exc, exc_info=True)
        return f"Error executing GWS CLI: {exc}"
    finally:
        if tmp_cred and os.path.exists(tmp_cred.name):
            try:
                os.unlink(tmp_cred.name)
            except OSError:
                pass
