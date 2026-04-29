"""Codex harness runtime.

Drives the OpenAI Codex CLI via its ``codex app-server`` JSON-RPC protocol
over stdio. Spawned per-turn — no long-lived process — while preserving the
Codex-native thread id for resume across Spindrel turns.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any

from integrations.codex import schema
from integrations.codex.app_server import (
    CodexAppServer,
    CodexAppServerError,
    CodexBinaryNotFound,
    Notification,
    ServerRequest,
)
from integrations.codex.approvals import (
    CodexServerRequestFatal,
    handle_server_request,
    mode_to_codex_policy,
    mode_to_codex_turn_policy,
)
from integrations.codex.events import normalize_token_usage, translate_notification
from integrations.sdk import (
    AuthStatus,
    ChannelEventEmitter,
    HarnessCompactResult,
    HarnessModelOption,
    HarnessRuntimeCommandResult,
    HarnessRuntimeCommandSpec,
    HarnessSlashCommandPolicy,
    HarnessToolSpec,
    RuntimeCapabilities,
    TurnContext,
    TurnResult,
    apply_tool_bridge,
    render_context_hints_for_prompt,
)

logger = logging.getLogger(__name__)


_CODEX_FALLBACK_MODELS: tuple[str, ...] = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
)
_CODEX_FALLBACK_EFFORTS: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh")


_CODEX_GENERIC_SLASH_ALLOWED: frozenset[str] = frozenset(
    {
        "help", "rename", "stop", "style", "theme", "clear",
        "sessions", "scratch", "split", "focus", "model", "effort",
        "compact", "context", "plan", "runtime", "new",
    }
)

_CODEX_NATIVE_COMMANDS: tuple[HarnessRuntimeCommandSpec, ...] = (
    HarnessRuntimeCommandSpec(
        id="config",
        label="config",
        description="Read Codex app-server configuration status.",
    ),
    HarnessRuntimeCommandSpec(
        id="mcp-status",
        label="mcp-status",
        description="List Codex-visible MCP server status.",
        aliases=("mcp",),
    ),
    HarnessRuntimeCommandSpec(
        id="plugins",
        label="plugins",
        description="List Codex plugins visible to the app-server.",
        aliases=("plugin",),
    ),
    HarnessRuntimeCommandSpec(
        id="skills",
        label="skills",
        description="List Codex skills visible to the app-server.",
    ),
    HarnessRuntimeCommandSpec(
        id="features",
        label="features",
        description="List Codex experimental feature flags.",
        aliases=("feature",),
    ),
    HarnessRuntimeCommandSpec(
        id="marketplace",
        label="marketplace",
        description="Manage Codex plugin marketplaces visible to the app-server.",
        aliases=("marketplaces",),
    ),
)


_AUTH_STATUS_CACHE: dict[str, tuple[float, AuthStatus]] = {}
_AUTH_STATUS_TTL = 30.0  # seconds
_CODEX_SKILL_TOKEN_RE = re.compile(r"(?<![\w$])\$([A-Za-z][\w.-]*)")


class CodexRuntime:
    """Drives the codex app-server against a workspace dir."""

    name = "codex"

    _READONLY: frozenset[str] = frozenset({"read", "list", "search"})
    _PLAN_AUTOAPPROVE: frozenset[str] = frozenset()

    def readonly_tools(self) -> frozenset[str]:
        return self._READONLY

    def prompts_in_accept_edits(self, tool_name: str) -> bool:
        return tool_name not in self._READONLY

    def autoapprove_in_plan(self, tool_name: str) -> bool:
        return tool_name in self._PLAN_AUTOAPPROVE

    def native_command_requires_approval(
        self,
        *,
        command_id: str,
        args: tuple[str, ...],
        args_text: str | None = None,
    ) -> bool:
        del args_text
        return _codex_native_command_is_mutating(command_id, args)

    def capabilities(self) -> RuntimeCapabilities:
        # The capabilities endpoint asks list_model_options() for live
        # per-model effort metadata. These fallback values keep the surface
        # usable when the binary is missing or model/list fails.
        return RuntimeCapabilities(
            display_name="Codex",
            supported_models=_CODEX_FALLBACK_MODELS,
            model_options=tuple(
                HarnessModelOption(
                    id=model,
                    label=model,
                    effort_values=_CODEX_FALLBACK_EFFORTS,
                    default_effort="medium",
                )
                for model in _CODEX_FALLBACK_MODELS
            ),
            model_is_freeform=True,
            effort_values=_CODEX_FALLBACK_EFFORTS,
            approval_modes=("bypassPermissions", "acceptEdits", "default", "plan"),
            slash_policy=HarnessSlashCommandPolicy(
                allowed_command_ids=_CODEX_GENERIC_SLASH_ALLOWED,
            ),
            native_compaction=True,
            context_window_tokens=None,
            native_commands=_CODEX_NATIVE_COMMANDS,
        )

    async def list_models(self) -> tuple[str, ...]:
        return tuple(option.id for option in await self.list_model_options())

    async def list_model_options(self) -> tuple[HarnessModelOption, ...]:
        try:
            async with CodexAppServer.spawn() as client:
                await client.initialize()
                result = await client.request(
                    schema.METHOD_MODEL_LIST,
                    {"includeHidden": False, "limit": 100},
                )
        except CodexBinaryNotFound:
            return self.capabilities().model_options
        except Exception:
            logger.warning("codex: model/list failed; using fallback list", exc_info=True)
            return self.capabilities().model_options
        return _parse_model_options(result) or self.capabilities().model_options

    async def start_turn(
        self,
        *,
        ctx: TurnContext,
        prompt: str,
        emit: ChannelEventEmitter,
    ) -> TurnResult:
        async with CodexAppServer.spawn(extra_env=dict(ctx.env)) as client:
            await client.initialize()

            params = _build_thread_start_params(ctx)
            if ctx.runtime_settings:
                # Opaque per-runtime overrides (caller-owned shape).
                params.update(dict(ctx.runtime_settings))

            dynamic_tools_signature: str | None = None

            async def _attach(specs: tuple[HarnessToolSpec, ...]) -> list[str]:
                nonlocal dynamic_tools_signature
                if not _server_supports_dynamic_tools(client):
                    return []
                entries = [_dynamic_tool_entry(spec) for spec in specs]
                params["dynamicTools"] = entries
                dynamic_tools_signature = _dynamic_tools_signature(entries)
                return [spec.name for spec in specs]

            exported, _ignored = await apply_tool_bridge(ctx, self, attach=_attach)
            allowed_tool_names = frozenset(exported)
            prior_dynamic_tools_signature = str(
                ctx.harness_metadata.get("codex_dynamic_tools_signature") or ""
            )
            dynamic_tools_changed = _dynamic_tools_changed(
                harness_session_id=ctx.harness_session_id,
                current_signature=dynamic_tools_signature,
                prior_signature=prior_dynamic_tools_signature,
            )

            if ctx.harness_session_id and not dynamic_tools_changed:
                resume_params = {"threadId": ctx.harness_session_id}
                if ctx.model:
                    resume_params["model"] = ctx.model
                resume = await client.request(schema.METHOD_THREAD_RESUME, resume_params)
                thread_id = _extract_thread_id(resume) or ctx.harness_session_id
            else:
                start = await client.request(schema.METHOD_THREAD_START, params)
                thread_id = _extract_thread_id(start) or ""

            turn_params = _build_turn_start_params(
                thread_id=thread_id,
                prompt=_prompt_with_bridge_guidance(prompt, exported),
                ctx=ctx,
                native_input_items=await _resolve_codex_native_input_items(client, prompt, ctx),
            )
            turn_resp = await client.request(schema.METHOD_TURN_START, turn_params)
            turn_id = _extract_turn_id(turn_resp) or ""

            tool_name_by_id: dict[str, str] = {}
            final_text_parts: list[str] = []
            result_meta: dict[str, Any] = {}

            async def _consume_notifications() -> None:
                async for note in client.notifications():
                    translate_notification(
                        note,
                        emit=emit,
                        tool_name_by_id=tool_name_by_id,
                        final_text_parts=final_text_parts,
                        result_meta=result_meta,
                    )
                    if result_meta.get("completed") or result_meta.get("is_error"):
                        return
                if not result_meta.get("completed") and not result_meta.get("is_error"):
                    result_meta["is_error"] = True
                    result_meta["error"] = "codex app-server stream closed before turn completed"

            async def _consume_server_requests() -> None:
                async for req in client.server_requests():
                    await handle_server_request(
                        ctx,
                        self,
                        req,
                        allowed_tool_names=allowed_tool_names,
                        emit=emit,
                    )
                    if result_meta.get("completed") or result_meta.get("is_error"):
                        return

            notifications_task = asyncio.create_task(_consume_notifications())
            requests_task = asyncio.create_task(_consume_server_requests())
            active_tasks: set[asyncio.Task[None]] = {notifications_task, requests_task}
            try:
                while active_tasks:
                    done, _pending = await asyncio.wait(
                        active_tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in done:
                        active_tasks.discard(task)
                        try:
                            await task
                        except asyncio.CancelledError:
                            raise
                        except CodexServerRequestFatal as exc:
                            result_meta["is_error"] = True
                            result_meta["error"] = str(exc)
                        except Exception as exc:
                            logger.exception("codex: turn stream consumer failed")
                            result_meta["is_error"] = True
                            result_meta["error"] = str(exc)
                    if result_meta.get("completed") or result_meta.get("is_error"):
                        break
            finally:
                for task in active_tasks:
                    task.cancel()
                for task in active_tasks:
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

            if result_meta.get("is_error"):
                if turn_id:
                    try:
                        await client.request(
                            schema.METHOD_TURN_INTERRUPT,
                            {"threadId": thread_id, "turnId": turn_id},
                        )
                    except Exception:
                        pass
                raise RuntimeError(
                    f"Codex turn ended with error: {result_meta.get('error')}"
                )

            return TurnResult(
                session_id=thread_id,
                final_text=result_meta.get("final_text") or "".join(final_text_parts),
                cost_usd=result_meta.get("total_cost_usd"),
                usage=result_meta.get("usage"),
                metadata={
                    "codex_dynamic_tools_signature": dynamic_tools_signature or "",
                    "codex_dynamic_tools": list(exported),
                    "codex_dynamic_tools_namespace": "spindrel",
                    "input_manifest": ctx.input_manifest.metadata(
                        runtime_items=tuple(turn_params.get("input") or ()),
                    ),
                    **_native_plan_metadata(result_meta),
                }
            )

    async def compact_session(
        self,
        *,
        ctx: TurnContext,
    ) -> HarnessCompactResult:
        if not ctx.harness_session_id:
            return HarnessCompactResult(
                ok=False,
                session_id=None,
                detail="No native Codex thread exists yet. Start a turn before compacting.",
                error="missing_harness_session_id",
            )
        try:
            async with CodexAppServer.spawn(extra_env=dict(ctx.env)) as client:
                await client.initialize()
                await client.request(
                    schema.METHOD_THREAD_RESUME,
                    {"threadId": ctx.harness_session_id},
                )
                await client.request(
                    schema.METHOD_THREAD_COMPACT_START,
                    {"threadId": ctx.harness_session_id},
                )
                result_meta: dict[str, Any] = {}
                async for note in client.notifications():
                    if note.method == schema.NOTIFICATION_TOKEN_USAGE_UPDATED:
                        result_meta["usage"] = normalize_token_usage(note.params)
                    if note.method == schema.NOTIFICATION_TURN_COMPLETED:
                        break
                    if note.method == schema.NOTIFICATION_ERROR:
                        err = note.params.get("error") if isinstance(note.params.get("error"), dict) else note.params
                        result_meta["is_error"] = True
                        result_meta["error"] = (err or {}).get("message") or "compact errored"
                        break
        except CodexBinaryNotFound as exc:
            return HarnessCompactResult(
                ok=False,
                session_id=ctx.harness_session_id,
                detail=str(exc),
                error="binary_not_found",
            )
        except Exception as exc:
            logger.exception("codex: native compact failed")
            return HarnessCompactResult(
                ok=False,
                session_id=ctx.harness_session_id,
                detail=f"Codex native compact failed: {exc}",
                error=str(exc),
            )

        if result_meta.get("is_error"):
            return HarnessCompactResult(
                ok=False,
                session_id=ctx.harness_session_id,
                detail=str(result_meta.get("error")),
                usage=result_meta.get("usage"),
                error=str(result_meta.get("error")),
            )
        return HarnessCompactResult(
            ok=True,
            session_id=ctx.harness_session_id,
            detail="Codex native compaction completed.",
            usage=result_meta.get("usage"),
        )

    async def execute_native_command(
        self,
        *,
        command_id: str,
        args: tuple[str, ...],
        ctx: TurnContext,
    ) -> HarnessRuntimeCommandResult:
        args = tuple(arg for arg in args if arg)
        resolved = _resolve_codex_native_app_server_call(command_id, args)
        if resolved is None:
            return HarnessRuntimeCommandResult(
                command_id=command_id,
                title="Unsupported Codex command",
                detail=f"Codex native command {command_id!r} is not whitelisted.",
                status="unsupported",
            )
        method, params = resolved
        if method is None:
            suggested_command = _codex_native_terminal_command(command_id, args)
            return HarnessRuntimeCommandResult(
                command_id=command_id,
                title="Open terminal for Codex command",
                detail=(
                    f"Codex /{command_id} with these arguments requires an interactive "
                    "or not-yet-bridged CLI flow. Use the in-app terminal to run it."
                ),
                status="terminal_handoff",
                payload={"args": list(args), "suggested_command": suggested_command},
            )
        try:
            async with CodexAppServer.spawn(extra_env=dict(ctx.env)) as client:
                await client.initialize()
                result = await client.request(method, params, timeout=20.0)
        except CodexBinaryNotFound as exc:
            return HarnessRuntimeCommandResult(
                command_id=command_id,
                title="Codex binary not found",
                detail=str(exc),
                status="error",
            )
        except Exception as exc:
            logger.exception("codex native command failed: %s", command_id)
            return HarnessRuntimeCommandResult(
                command_id=command_id,
                title="Codex native command failed",
                detail=str(exc),
                status="error",
            )
        return HarnessRuntimeCommandResult(
            command_id=command_id,
            title=f"Codex {command_id}",
            detail=_summarize_native_command_result(command_id, result),
            status="ok",
            payload=result if isinstance(result, dict) else {"result": result},
        )

    def auth_status(self) -> AuthStatus:
        cached = _AUTH_STATUS_CACHE.get(self.name)
        if cached and (time.monotonic() - cached[0]) < _AUTH_STATUS_TTL:
            return cached[1]
        try:
            status = asyncio.run(_check_auth_status())
        except RuntimeError:
            # Already inside a running loop — fall back to the optimistic
            # "needs login" hint rather than block the event loop.
            status = AuthStatus(
                ok=False,
                detail="Auth check skipped (running inside an event loop).",
                suggested_command="codex login --device-auth",
            )
        _AUTH_STATUS_CACHE[self.name] = (time.monotonic(), status)
        return status


def _codex_native_terminal_command(command_id: str, args: tuple[str, ...]) -> str:
    cli_command = {
        "mcp-status": "mcp",
        "plugins": "plugin",
        "features": "features",
        "marketplace": "marketplace",
    }.get(command_id, command_id)
    return " ".join(("codex", cli_command, *args))


def _codex_native_command_is_mutating(command_id: str, args: tuple[str, ...]) -> bool:
    cleaned = tuple(arg.strip() for arg in args if arg and arg.strip())
    first = cleaned[0].lower() if cleaned else ""
    if command_id == "plugins":
        return first in {"install", "i", "uninstall", "remove", "rm"}
    if command_id == "marketplace":
        return first in {"add", "remove", "rm", "upgrade", "update"}
    if command_id == "skills":
        return first in {"enable", "disable", "on", "off"}
    if command_id == "features":
        return first in {"enable", "disable", "on", "off", "set"}
    if command_id == "config":
        return first in {"set", "write", "upsert", "replace"}
    return False


def _resolve_codex_native_app_server_call(
    command_id: str,
    args: tuple[str, ...],
) -> tuple[str | None, dict[str, Any]] | None:
    cleaned = tuple(arg.strip() for arg in args if arg and arg.strip())
    lowered = tuple(arg.lower() for arg in cleaned)
    first = lowered[0] if lowered else ""
    if command_id == "config":
        if not cleaned or first in {"read", "list", "show"}:
            return schema.METHOD_CONFIG_READ, {}
        if first in {"set", "write", "upsert", "replace"} and len(cleaned) >= 3:
            key = cleaned[1]
            value = _parse_codex_config_value(" ".join(cleaned[2:]))
            strategy = "replace" if first == "replace" else "upsert"
            return schema.METHOD_CONFIG_VALUE_WRITE, {
                "keyPath": key,
                "value": value,
                "mergeStrategy": strategy,
            }
        return None, {}
    if command_id == "mcp-status":
        if not cleaned or first in {"list", "status"}:
            return schema.METHOD_MCP_SERVER_STATUS_LIST, {}
        if lowered[:2] == ("resource", "read") and len(cleaned) >= 4:
            return schema.METHOD_MCP_SERVER_RESOURCE_READ, {
                "server": cleaned[2],
                "uri": cleaned[3],
            }
        # OAuth and arbitrary tool calls have interactive/thread-bound flows.
        return None, {}
    if command_id == "plugins":
        if not cleaned or first == "list":
            return schema.METHOD_PLUGIN_LIST, {}
        if first == "read" and len(cleaned) >= 2:
            return schema.METHOD_PLUGIN_READ, {"pluginName": cleaned[1]}
        if first in {"install", "i"} and len(cleaned) >= 2:
            # The app-server plugin/install method installs from a marketplace
            # selector, not a bare CLI plugin name. Keep CLI-shaped installs as
            # terminal handoff so we do not fake success or send invalid params.
            return None, {}
        if first in {"uninstall", "remove", "rm"} and len(cleaned) >= 2:
            return schema.METHOD_PLUGIN_UNINSTALL, {"pluginId": cleaned[1]}
        return None, {}
    if command_id == "marketplace":
        if first == "add" and len(cleaned) >= 2:
            return schema.METHOD_MARKETPLACE_ADD, {"source": cleaned[1]}
        if first in {"remove", "rm"} and len(cleaned) >= 2:
            return schema.METHOD_MARKETPLACE_REMOVE, {"marketplaceName": cleaned[1]}
        if first in {"upgrade", "update"}:
            return schema.METHOD_MARKETPLACE_UPGRADE, {
                "marketplaceName": cleaned[1] if len(cleaned) >= 2 else None
            }
        return None, {}
    if command_id == "skills":
        if not cleaned or first == "list":
            return schema.METHOD_SKILLS_LIST, {}
        if first in {"enable", "disable", "on", "off"} and len(cleaned) >= 2:
            enabled = first in {"enable", "on"}
            selector = cleaned[1]
            return schema.METHOD_SKILLS_CONFIG_WRITE, {
                "enabled": enabled,
                "path": selector if selector.startswith("/") else None,
                "name": None if selector.startswith("/") else selector,
            }
        return None, {}
    if command_id == "features":
        if not cleaned or first == "list":
            return schema.METHOD_EXPERIMENTAL_FEATURE_LIST, {}
        if first in {"enable", "disable", "on", "off"} and len(cleaned) >= 2:
            return schema.METHOD_EXPERIMENTAL_FEATURE_ENABLEMENT_SET, {
                "enablement": {cleaned[1]: first in {"enable", "on"}},
            }
        if first == "set" and len(cleaned) >= 3:
            return schema.METHOD_EXPERIMENTAL_FEATURE_ENABLEMENT_SET, {
                "enablement": {cleaned[1]: cleaned[2].lower() in {"1", "true", "yes", "on", "enable", "enabled"}},
            }
        return None, {}
    return None


def _parse_codex_config_value(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _build_turn_input(
    prompt: str,
    ctx: TurnContext,
    *,
    native_input_items: tuple[dict[str, Any], ...] = (),
) -> list[dict[str, Any]]:
    """Compose the codex ``turn/start.input`` array.

    The protocol takes an array of typed content items. Text still carries
    host hints, while manifest inputs become native Codex items when possible.
    """
    items: list[dict[str, Any]] = [
        schema.text_input_item(render_context_hints_for_prompt(prompt, ctx.context_hints))
    ]
    for attachment in ctx.input_manifest.attachments:
        if attachment.kind != "image":
            continue
        if attachment.content_base64:
            items.append({
                "type": schema.INPUT_ITEM_IMAGE,
                "url": f"data:{attachment.mime_type};base64,{attachment.content_base64}",
            })
        elif attachment.path:
            items.append({
                "type": schema.INPUT_ITEM_LOCAL_IMAGE,
                "path": attachment.path,
            })
    items.extend(dict(item) for item in native_input_items)
    return items


async def _resolve_codex_native_input_items(
    client: CodexAppServer,
    prompt: str,
    ctx: TurnContext,
) -> tuple[dict[str, Any], ...]:
    """Resolve prompt-native Codex affordances into typed input items.

    Codex skills are invoked by ``$name`` in text; adding a sibling ``skill``
    item lets app-server inject the exact skill body without model-side lookup.
    If resolution fails, the text marker remains intact and Codex can still
    attempt its native fallback.
    """

    names = _extract_codex_skill_tokens(prompt)
    if not names:
        return ()
    try:
        result = await client.request(
            schema.METHOD_SKILLS_LIST,
            {"cwds": [ctx.workdir]},
            timeout=5.0,
        )
    except Exception:
        logger.info("codex: skills/list failed while resolving native skill input items", exc_info=True)
        return ()
    by_name = _codex_skill_paths_by_name(result)
    items: list[dict[str, Any]] = []
    for name in names:
        path = by_name.get(name)
        if not path:
            continue
        items.append({
            "type": schema.INPUT_ITEM_SKILL,
            "name": name,
            "path": path,
        })
    return tuple(items)


def _extract_codex_skill_tokens(prompt: str) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _CODEX_SKILL_TOKEN_RE.finditer(prompt or ""):
        name = match.group(1).strip().rstrip(".,;:!?")
        if name and name not in seen:
            seen.add(name)
            found.append(name)
    return tuple(found)


def _codex_skill_paths_by_name(result: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        return out
    for cwd_entry in data:
        if not isinstance(cwd_entry, dict):
            continue
        skills = cwd_entry.get("skills")
        if not isinstance(skills, list):
            continue
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            name = skill.get("name")
            path = (
                skill.get("path")
                or skill.get("skillPath")
                or skill.get("filePath")
            )
            if isinstance(name, str) and name and isinstance(path, str) and path:
                out.setdefault(name, path)
    return out


def _build_thread_start_params(ctx: TurnContext) -> dict[str, Any]:
    """Build ``thread/start`` params for a new Codex thread."""
    params: dict[str, Any] = {"cwd": ctx.workdir}
    if ctx.model:
        params["model"] = ctx.model
    params.update(mode_to_codex_policy(ctx.permission_mode))
    return params


def _dynamic_tool_entry(spec: HarnessToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "namespace": "spindrel",
        "description": spec.description or spec.name,
        "inputSchema": spec.parameters or {"type": "object", "properties": {}},
    }


def _dynamic_tools_signature(entries: list[dict[str, Any]]) -> str:
    """Stable signature for Codex thread-start-scoped dynamic tools."""
    ordered = sorted(entries, key=lambda item: str(item.get("name") or ""))
    payload = json.dumps(ordered, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dynamic_tools_changed(
    *,
    harness_session_id: str | None,
    current_signature: str | None,
    prior_signature: str | None,
) -> bool:
    if not harness_session_id:
        return False
    return (current_signature or "") != (prior_signature or "")


def _prompt_with_bridge_guidance(prompt: str, exported_tools: list[str]) -> str:
    exported = set(exported_tools)
    if not exported:
        return prompt
    tool_list = ", ".join(sorted(exported))
    preferred_tools = [
        name for name in (
            "get_tool_info",
            "read_conversation_history",
            "search_memory",
            "get_memory_file",
            "file",
            "manage_bot_skill",
        )
        if name in exported
    ]
    guidance_parts = [
        "<spindrel_tool_guidance>",
        (
            "Spindrel host tools are available through the spindrel dynamic-tool "
            "namespace. When asked to call one of these host tools, invoke the "
            "dynamic tool by its exact name. Do not emulate it with shell commands, "
            "MCP helper probes, or text-only JSON."
        ),
        "Callable Spindrel dynamic tools this turn: " + tool_list,
    ]
    if preferred_tools:
        guidance_parts.append(
            "Prefer these tools for host-tracked memory, conversation history, "
            "and durable state instead of reading or editing those records with "
            "shell commands."
        )
    guidance_parts.extend(["</spindrel_tool_guidance>", prompt])
    return "\n\n".join(guidance_parts)


def _native_plan_metadata(result_meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(result_meta.get("plan"), (dict, list)):
        out["codex_native_plan"] = result_meta["plan"]
    text = result_meta.get("native_plan_text")
    if isinstance(text, str) and text.strip():
        out["codex_native_plan_text"] = text.strip()
    parts = result_meta.get("native_plan_delta_parts")
    if isinstance(parts, list) and parts:
        out["codex_native_plan_delta"] = "".join(str(part) for part in parts)
    return out


def _build_turn_start_params(
    *,
    thread_id: str,
    prompt: str,
    ctx: TurnContext,
    native_input_items: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Build current-schema ``turn/start`` params for every Codex turn."""
    params: dict[str, Any] = {
        "threadId": thread_id,
        "input": _build_turn_input(prompt, ctx, native_input_items=native_input_items),
        "cwd": ctx.workdir,
    }
    if ctx.model:
        params["model"] = ctx.model
    if ctx.effort:
        params["effort"] = ctx.effort
    params.update(
        mode_to_codex_turn_policy(
            ctx.permission_mode,
            session_plan_mode=ctx.session_plan_mode,
        )
    )
    if ctx.session_plan_mode == "planning":
        params["collaborationMode"] = {
            "mode": schema.COLLABORATION_MODE_PLAN,
            "settings": {
                "model": ctx.model or _CODEX_FALLBACK_MODELS[0],
                "reasoning_effort": ctx.effort or "medium",
                "developer_instructions": None,
            },
        }
    return params


def _parse_model_options(result: dict[str, Any] | None) -> tuple[HarnessModelOption, ...]:
    """Parse Codex ``model/list`` into Spindrel runtime model options."""
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        return ()
    options: list[HarnessModelOption] = []
    for entry in data:
        if not isinstance(entry, dict) or entry.get("hidden"):
            continue
        ident = entry.get("id") or entry.get("model")
        if not isinstance(ident, str) or not ident:
            continue
        efforts: list[str] = []
        for effort in entry.get("supportedReasoningEfforts") or ():
            if isinstance(effort, dict):
                value = effort.get("reasoningEffort")
            else:
                value = effort
            if isinstance(value, str) and value:
                efforts.append(value)
        default_effort = entry.get("defaultReasoningEffort")
        options.append(
            HarnessModelOption(
                id=ident,
                label=entry.get("displayName") if isinstance(entry.get("displayName"), str) else ident,
                effort_values=tuple(efforts) or _CODEX_FALLBACK_EFFORTS,
                default_effort=default_effort if isinstance(default_effort, str) else None,
            )
        )
    return tuple(options)


def _summarize_native_command_result(command_id: str, result: Any) -> str:
    if not isinstance(result, dict):
        return "Runtime command completed."
    for key in ("servers", "plugins", "skills", "features", "data", "items"):
        value = result.get(key)
        if isinstance(value, list):
            return f"{command_id}: {len(value)} item(s)."
    if result:
        return f"{command_id}: returned {len(result)} top-level field(s)."
    return f"{command_id}: no data returned."


def _extract_thread_id(result: dict[str, Any] | None) -> str | None:
    """Pull ``thread.id`` from a ``thread/start`` or ``thread/resume`` result."""
    if not isinstance(result, dict):
        return None
    thread = result.get("thread")
    if isinstance(thread, dict) and thread.get("id"):
        return str(thread["id"])
    return None


def _extract_turn_id(result: dict[str, Any] | None) -> str | None:
    """Pull ``turn.id`` from a ``turn/start`` result."""
    if not isinstance(result, dict):
        return None
    turn = result.get("turn")
    if isinstance(turn, dict) and turn.get("id"):
        return str(turn["id"])
    return None


def _server_supports_dynamic_tools(client: CodexAppServer) -> bool:
    """Schema-first check for dynamicTools support.

    Falls back to ``True`` (let attach try) when the capabilities response
    is silent. ``apply_tool_bridge`` translates an empty exported list into
    ``unsupported`` bridge status.
    """
    caps = client.server_capabilities or {}
    if isinstance(caps, dict):
        explicit = caps.get("dynamicTools")
        if explicit is False:
            return False
        if explicit is True:
            return True
    return True


async def _check_auth_status() -> AuthStatus:
    try:
        async with CodexAppServer.spawn() as client:
            await client.initialize()
            try:
                result = await client.request(
                    schema.METHOD_ACCOUNT_READ, {"refreshToken": False}
                )
            except CodexAppServerError as exc:
                code = str(getattr(exc, "code", "")).lower()
                if "auth" in code or "unauth" in code or "login" in code:
                    return AuthStatus(
                        ok=False,
                        detail="Run `codex login` to authenticate.",
                        suggested_command="codex login --device-auth",
                    )
                return AuthStatus(
                    ok=False,
                    detail=f"codex account/read failed: {exc.message}",
                    suggested_command="codex login --device-auth",
                )
    except CodexBinaryNotFound as exc:
        return AuthStatus(
            ok=False,
            detail=str(exc) or "Codex CLI not installed on this server. Install the codex binary and ensure it's on PATH.",
            suggested_command=None,
        )
    except Exception as exc:
        return AuthStatus(
            ok=False,
            detail=f"codex auth probe failed: {exc}",
            suggested_command="codex login --device-auth",
        )
    if isinstance(result, dict):
        if not result.get("account") and result.get("requiresOpenaiAuth"):
            return AuthStatus(
                ok=False,
                detail="Run `codex login` to authenticate.",
                suggested_command="codex login --device-auth",
            )
        account = result.get("account") or {}
    else:
        account = {}
    label = (
        account.get("email")
        or account.get("planType")
        or account.get("type")
        or "Codex account"
    )
    return AuthStatus(ok=True, detail=f"Logged in as {label}")


def _register() -> None:
    from integrations.sdk import register_runtime

    register_runtime(CodexRuntime.name, CodexRuntime())


_register()
