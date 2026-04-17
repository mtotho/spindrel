"""Admin tool: secret value management for the orchestrator bot."""
import json
import logging
import re

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import SecretValue
from app.services import secret_values
from app.tools.registry import register

logger = logging.getLogger(__name__)

# Secret names must be valid env var identifiers
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@register({
    "type": "function",
    "function": {
        "name": "manage_secret",
        "description": (
            "Manage encrypted secret values (API keys, tokens, credentials). "
            "Secrets are encrypted at rest, injected into containers as env vars, "
            "and automatically redacted from bot output. "
            "Actions: list, create, delete."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "delete"],
                    "description": "The action to perform.",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Secret name (UPPER_SNAKE_CASE, e.g. MY_API_KEY). "
                        "Required for create and delete."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "Secret value (required for create).",
                },
                "description": {
                    "type": "string",
                    "description": "Optional human-readable description of what this secret is for.",
                },
            },
            "required": ["action"],
        },
    },
}, safety_tier="control_plane")
async def manage_secret(
    action: str,
    name: str | None = None,
    value: str | None = None,
    description: str | None = None,
) -> str:
    if action == "list":
        async with async_session() as db:
            secrets = await secret_values.list_secrets(db)
        return json.dumps(secrets, ensure_ascii=False)

    if action == "create":
        if not name:
            return json.dumps({"error": "name is required for create"}, ensure_ascii=False)
        if not value:
            return json.dumps({"error": "value is required for create"}, ensure_ascii=False)
        if not _NAME_RE.match(name):
            return json.dumps({
                "error": f"Invalid secret name '{name}'. Must be UPPER_SNAKE_CASE "
                "(e.g. MY_API_KEY). Start with a letter, use only A-Z, 0-9, underscore."
            }, ensure_ascii=False)

        async with async_session() as db:
            # Check for duplicate name
            existing = (await db.execute(
                select(SecretValue).where(SecretValue.name == name)
            )).scalar_one_or_none()
            if existing:
                return json.dumps({"error": f"Secret '{name}' already exists. Delete it first to replace."}, ensure_ascii=False)

            result = await secret_values.create_secret(
                db, name=name, value=value,
                description=description or "", created_by="tool",
            )
        return json.dumps({"ok": True, "name": result["name"], "message": f"Secret '{name}' created"}, ensure_ascii=False)

    if action == "delete":
        if not name:
            return json.dumps({"error": "name is required for delete"}, ensure_ascii=False)

        async with async_session() as db:
            row = (await db.execute(
                select(SecretValue).where(SecretValue.name == name)
            )).scalar_one_or_none()
            if not row:
                return json.dumps({"error": f"Secret '{name}' not found"}, ensure_ascii=False)

            deleted = await secret_values.delete_secret(db, row.id)
            if not deleted:
                return json.dumps({"error": f"Failed to delete secret '{name}'"}, ensure_ascii=False)

        return json.dumps({"ok": True, "name": name, "message": f"Secret '{name}' deleted"}, ensure_ascii=False)

    return json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False)
